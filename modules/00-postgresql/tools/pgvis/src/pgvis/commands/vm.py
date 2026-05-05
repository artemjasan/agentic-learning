import click
import psycopg
from rich.text import Text

from pgvis.core import connect, console
from pgvis.format import PanelBuilder


@click.command()
@click.argument("table")
@click.pass_context
def vm(ctx, table: str) -> None:
    """Visualize the Visibility Map: all-visible and all-frozen flags."""
    with connect(ctx.obj["dsn"]) as conn:
        info = _fetch_relation_info(conn, table)
        console.print(
            f"\n[bold]{table}[/bold] — "
            f"{info['size_bytes']} bytes, {info['num_pages']} pages\n"
        )
        visibility = _fetch_visibility_map(conn, table)
        _render(table, visibility)


# ── Queries ──────────────────────────────────────────────────────────────────


def _fetch_relation_info(conn: psycopg.Connection, table: str) -> dict:
    return conn.execute(
        """
        SELECT pg_relation_filepath(%s) AS filepath,
               pg_relation_size(%s) AS size_bytes,
               pg_relation_size(%s) / 8192 AS num_pages
        """,
        (table, table, table),
    ).fetchone()


def _fetch_visibility_map(conn: psycopg.Connection, table: str) -> list[dict]:
    return conn.execute(
        """
        SELECT blkno, all_visible, all_frozen
        FROM pg_visibility(%s)
        ORDER BY blkno
        """,
        (table,),
    ).fetchall()


# ── Rendering ────────────────────────────────────────────────────────────────


def _render(table: str, visibility: list[dict]) -> None:
    p = PanelBuilder()

    all_visible_count = sum(1 for r in visibility if r["all_visible"])
    all_frozen_count = sum(1 for r in visibility if r["all_frozen"])

    for row in visibility:
        blkno = row["blkno"]
        visible = row["all_visible"]
        frozen = row["all_frozen"]

        line = Text()
        line.append(f"  Page {blkno:>4}", style="yellow")
        line.append("  │  ", style="dim")

        if frozen:
            line.append("██ FROZEN  ", style="cyan bold")
        elif visible:
            line.append("██ VISIBLE ", style="green bold")
        else:
            line.append("░░ DIRTY   ", style="red")

        line.append("  all_visible=", style="dim")
        line.append(str(visible), style="green" if visible else "red")
        line.append("  all_frozen=", style="dim")
        line.append(str(frozen), style="cyan" if frozen else "dim")
        p.add(line)

    p.blank()

    total = len(visibility)
    if total > 0:
        bar_width = 40
        v_w = round(all_visible_count / total * bar_width)
        f_w = round(all_frozen_count / total * bar_width)
        d_w = bar_width - v_w

        summary = Text()
        summary.append("  [", style="dim")
        summary.append("█" * f_w, style="cyan")
        summary.append("█" * max(0, v_w - f_w), style="green")
        summary.append("░" * d_w, style="red")
        summary.append("]", style="dim")
        summary.append(f"  {all_visible_count}/{total} visible", style="green")
        summary.append(f"  {all_frozen_count}/{total} frozen", style="cyan")
        p.add(summary)

    p.print(title=f"[bold]Visibility Map — {table}[/bold]", border_style="green")
