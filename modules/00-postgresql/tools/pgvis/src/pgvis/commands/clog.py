import click
from rich.text import Text

from pgvis.core import connect
from pgvis.format import PanelBuilder


@click.command()
@click.argument("start", type=int, required=False)
@click.argument("end", type=int, required=False)
@click.option("--last", type=int, default=None, help="Show the last N transaction IDs.")
@click.pass_context
def clog(ctx, start: int | None, end: int | None, last: int | None) -> None:
    """Visualize the CLOG: transaction commit status."""
    with connect(ctx.obj["dsn"]) as conn:
        current = conn.execute("SELECT txid_current_snapshot()").fetchone()
        snap = current["txid_current_snapshot"]
        snap_parts = str(snap).split(":")
        snap_xmax = int(snap_parts[1])

        if start is not None and end is not None:
            end = min(end, snap_xmax - 1)
        elif last is not None:
            end = snap_xmax - 1
            start = max(3, end - last)
        else:
            end = snap_xmax - 1
            start = max(3, end - 30)

        entries = conn.execute(
            """
            SELECT x::bigint AS xid, txid_status(x::bigint) AS status
            FROM generate_series(%s::bigint, %s::bigint) AS x
            """,
            (start, end),
        ).fetchall()

        xip_list = snap_parts[2] if len(snap_parts) > 2 else ""
        in_progress = set()
        if xip_list:
            in_progress = {int(x) for x in xip_list.split(",") if x}

        _render(entries, in_progress, snap_xmax)


def _render(entries: list[dict], in_progress: set[int], snap_xmax: int) -> None:
    p = PanelBuilder()

    status_style = {
        "committed": "green",
        "aborted": "red",
        "in progress": "yellow bold",
    }

    for entry in entries:
        xid = entry["xid"]
        status = entry["status"] or "not yet assigned"

        line = Text()
        line.append(f"  xid {xid:>6}", style="cyan")
        line.append("  │  ", style="dim")

        style = status_style.get(status, "dim")

        if status == "committed":
            line.append("██", style=style)
            line.append(f"  {status}", style=style)
        elif status == "aborted":
            line.append("░░", style=style)
            line.append(f"  {status}", style=style)
        elif status == "in progress":
            line.append("▓▓", style=style)
            line.append(f"  {status}", style=style)
        else:
            line.append("  ", style="dim")
            line.append(f"  {status}", style="dim")

        if xid in in_progress:
            line.append("  ← in current snapshot xip_list", style="yellow")

        p.add(line)

    p.blank()

    committed = sum(1 for e in entries if e["status"] == "committed")
    aborted = sum(1 for e in entries if e["status"] == "aborted")
    in_prog = sum(1 for e in entries if e["status"] == "in progress")
    total = len(entries)

    summary = Text()
    summary.append("  ", style="dim")
    summary.append(f"{committed}", style="green bold")
    summary.append(" committed  ", style="dim")
    summary.append(f"{aborted}", style="red bold")
    summary.append(" aborted  ", style="dim")
    if in_prog:
        summary.append(f"{in_prog}", style="yellow bold")
        summary.append(" in progress  ", style="dim")
    summary.append(f"({total} total)", style="dim")
    p.add(summary)

    p.print(title="[bold]CLOG — Transaction Status[/bold]", border_style="cyan")
