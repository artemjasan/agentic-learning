import click
import psycopg
from psycopg.pq import TransactionStatus
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pgvis.core import connect, console
from pgvis.format import fmt_cell

PROMPT_PAD = "  "


@click.command()
@click.argument("query", required=False)
@click.option("-i", "--interactive", is_flag=True, help="Interactive REPL mode.")
@click.pass_context
def sql(ctx, query: str | None, interactive: bool) -> None:
    """Run SQL with pretty output. Pass a query or use -i for interactive mode."""
    dsn = ctx.obj["dsn"]

    if query:
        with connect(dsn, autocommit=True) as conn:
            _execute_and_render(conn, query)
    elif interactive:
        _repl(dsn)
    else:
        console.print("[dim]Usage: pgvis sql \"SELECT 1\" or pgvis sql -i[/dim]")


def _execute_and_render(
    conn: psycopg.Connection, query: str, *, show_tx: bool = False,
) -> None:
    try:
        cur = conn.execute(query)
        if cur.description:
            rows = cur.fetchall()
            table = _build_results_table(cur.description, rows)
            console.print(Padding(table, (0, 0, 0, 4)))

            if show_tx and conn.info.transaction_status == TransactionStatus.INTRANS:
                sub = _build_tx_subtitle(conn)
                console.print(Padding(sub, (0, 0, 0, 4)))
        else:
            status = Text(cur.statusmessage or "OK", style="green")
            tx_sub = None
            if show_tx and conn.info.transaction_status == TransactionStatus.INTRANS:
                tx_sub = _build_tx_subtitle(conn)
            _print_panel(status, subtitle=tx_sub)
    except psycopg.Error as e:
        error = Text()
        error.append(f"ERROR: {e}", style="red")
        if conn.info.transaction_status == TransactionStatus.INERROR:
            error.append("\nTransaction aborted. ROLLBACK to reset.", style="dim")
        _print_panel(error)


def _repl(dsn: str) -> None:
    try:
        import readline  # noqa: F401
    except ImportError:
        pass

    with connect(dsn, autocommit=True) as conn:
        pid = conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        dbname = conn.execute("SELECT current_database() AS db").fetchone()["db"]
        console.print(f"\n{PROMPT_PAD}[bold]pgvis sql[/bold] — {dbname} (pid={pid})")
        console.print(f"{PROMPT_PAD}[dim]Type SQL. \\q to quit.[/dim]\n")

        buf: list[str] = []
        while True:
            status = conn.info.transaction_status
            if status == TransactionStatus.INTRANS:
                prompt = f"{PROMPT_PAD}[dim]{dbname}[/dim] [bold yellow]tx>[/bold yellow] "
            elif status == TransactionStatus.INERROR:
                prompt = f"{PROMPT_PAD}[dim]{dbname}[/dim] [bold red]err>[/bold red] "
            else:
                prompt = f"{PROMPT_PAD}[dim]{dbname}[/dim] [bold cyan]>[/bold cyan] "

            if buf:
                prompt = f"{PROMPT_PAD}[dim]{dbname}[/dim] [dim]..>[/dim] "

            try:
                line = console.input(prompt)
            except (EOFError, KeyboardInterrupt):
                console.print()
                break

            stripped = line.strip()
            if stripped.lower() in ("\\q", "quit", "exit"):
                break
            if not stripped and not buf:
                continue

            buf.append(line)
            full = " ".join(b.strip() for b in buf).strip()

            immediate = full.upper() in ("BEGIN", "COMMIT", "ROLLBACK", "END")
            if not full.endswith(";") and not immediate:
                continue

            sql_text = full.rstrip(";").strip() if full.endswith(";") else full
            buf.clear()

            if not sql_text:
                continue

            _execute_and_render(conn, sql_text, show_tx=True)
            console.print()
            console.print()


# ── Queries ──────────────────────────────────────────────────────────────────


def _fetch_tx_state(conn: psycopg.Connection) -> dict:
    row = conn.execute("""
        SELECT pg_backend_pid() AS pid,
               current_setting('transaction_isolation') AS isolation,
               txid_current_snapshot()::text AS snapshot
    """).fetchone()

    locks = conn.execute("""
        SELECT locktype, virtualxid, transactionid
        FROM pg_locks
        WHERE pid = pg_backend_pid()
          AND locktype IN ('virtualxid', 'transactionid')
    """).fetchall()

    row["virtualxid"] = None
    row["xid"] = None
    for lock in locks:
        if lock["locktype"] == "virtualxid":
            row["virtualxid"] = lock["virtualxid"]
        elif lock["locktype"] == "transactionid":
            row["xid"] = lock["transactionid"]

    return row


# ── Rendering ────────────────────────────────────────────────────────────────


def _build_results_table(description, rows: list[dict]) -> Table | Text:
    if not rows:
        return Text("(0 rows)", style="dim")

    table = Table(border_style="cyan", show_edge=True, pad_edge=True, padding=(0, 1))
    for col in description:
        table.add_column(col.name, header_style="bold cyan", style="white")

    for row in rows:
        table.add_row(*[fmt_cell(v) for v in row.values()])

    return table


def _build_tx_subtitle(conn: psycopg.Connection) -> Text:
    state = _fetch_tx_state(conn)

    line = Text()
    line.append(f"pid={state['pid']}", style="cyan")

    if state.get("virtualxid"):
        line.append(f"  vxid={state['virtualxid']}", style="dim")

    xid = state.get("xid")
    if xid:
        line.append(f"  xid={xid}", style="green bold")
    else:
        line.append("  xid=∅", style="dim")

    line.append(f"  [{state['isolation']}]", style="dim")

    snap = state.get("snapshot")
    if snap:
        line.append(f"  snap={snap}", style="yellow")

    return line


def _print_panel(content, *, subtitle: Text | None = None) -> None:
    panel = Panel(
        content,
        subtitle=subtitle,
        subtitle_align="left",
        border_style="dim",
        padding=(1, 2) if not isinstance(content, Text) else (0, 2),
    )
    console.print(Padding(panel, (0, 0, 0, 2)))
