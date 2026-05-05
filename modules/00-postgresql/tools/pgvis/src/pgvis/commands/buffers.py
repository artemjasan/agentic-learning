import click
import psycopg
from rich.text import Text

from pgvis.core import connect
from pgvis.format import PanelBuilder


@click.command()
@click.pass_context
def buffers(ctx) -> None:
    """Visualize shared_buffers: utilization, clock-sweep usage, cached relations."""
    with connect(ctx.obj["dsn"]) as conn:
        summary = _fetch_summary(conn)
        relations = _fetch_relations(conn)
        usage_dist = _fetch_usage_distribution(conn)
        _render(summary, relations, usage_dist)


# ── Queries ──────────────────────────────────────────────────────────────────


def _fetch_summary(conn: psycopg.Connection) -> dict:
    row = conn.execute(
        """
        SELECT count(*) AS total,
               sum(CASE WHEN reldatabase IS NOT NULL THEN 1 ELSE 0 END) AS used,
               sum(CASE WHEN reldatabase IS NULL THEN 1 ELSE 0 END) AS empty
        FROM pg_buffercache
        """
    ).fetchone()

    setting = conn.execute("SHOW shared_buffers").fetchone()
    return {**row, "shared_buffers": setting["shared_buffers"]}


def _fetch_relations(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """
        SELECT c.relname,
               count(*) AS pages,
               sum(CASE WHEN b.isdirty THEN 1 ELSE 0 END) AS dirty,
               round(avg(b.usagecount), 1) AS avg_usage,
               max(b.usagecount) AS max_usage,
               count(*) * 8192 AS bytes
        FROM pg_buffercache b
        JOIN pg_class c ON c.relfilenode = b.relfilenode
        WHERE b.reldatabase = (SELECT oid FROM pg_database WHERE datname = current_database())
        GROUP BY c.relname
        ORDER BY pages DESC
        """
    ).fetchall()


def _fetch_usage_distribution(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """
        SELECT usagecount, count(*) AS slots
        FROM pg_buffercache
        WHERE reldatabase IS NOT NULL
        GROUP BY usagecount
        ORDER BY usagecount
        """
    ).fetchall()


# ── Rendering ────────────────────────────────────────────────────────────────


def _render(summary: dict, relations: list[dict], usage_dist: list[dict]) -> None:
    _render_utilization(summary)
    if usage_dist:
        _render_clock_sweep(usage_dist)
    if relations:
        _render_relations(relations)


def _render_utilization(summary: dict) -> None:
    total = summary["total"]
    used = summary["used"]
    empty = summary["empty"]
    total_mb = total * 8192 / (1024 * 1024)
    used_mb = used * 8192 / (1024 * 1024)
    pct = used / total * 100 if total > 0 else 0

    bar_width = 50
    used_w = round(pct / 100 * bar_width)
    empty_w = bar_width - used_w

    p = PanelBuilder()

    bar = Text()
    bar.append("  [", style="dim")
    bar.append("█" * used_w, style="green")
    bar.append("░" * empty_w, style="dim")
    bar.append("]", style="dim")
    bar.append(f"  {used_mb:.1f} / {total_mb:.1f} MB ({pct:.1f}%)", style="white")
    p.add(bar)

    info = Text()
    info.append(f"  shared_buffers = {summary['shared_buffers']}", style="dim")
    info.append(f"  │  {total:,} slots", style="dim")
    info.append(f"  │  {used:,} used", style="green")
    info.append(f"  │  {empty:,} empty", style="dim")
    p.add(info)

    p.print(title="[bold]Shared Buffers — Utilization[/bold]", border_style="cyan", padding=(1, 1))


def _render_clock_sweep(usage_dist: list[dict]) -> None:
    p = PanelBuilder()
    max_count = max(r["slots"] for r in usage_dist)

    for row in usage_dist:
        uc = row["usagecount"]
        slots = row["slots"]
        bar_w = round(slots / max_count * 35) if max_count > 0 else 0

        line = Text()
        line.append(f"  usage={uc}  ", style="yellow" if uc == 0 else "cyan")
        line.append("█" * bar_w, style="yellow" if uc == 0 else "cyan")
        line.append(f"  {slots:,} slots", style="dim")
        if uc == 0:
            line.append("  ← next eviction victims", style="yellow")
        elif uc >= 5:
            line.append("  ← hot (max)", style="red bold")
        p.add(line)

    p.print(
        title="[bold]Clock-Sweep Usage Counts[/bold]",
        subtitle="Higher count = survives more sweeps before eviction",
        border_style="cyan",
        padding=(1, 1),
    )


def _render_relations(relations: list[dict]) -> None:
    p = PanelBuilder()
    max_pages = relations[0]["pages"]

    for row in relations:
        name = row["relname"]
        pages = row["pages"]
        dirty = row["dirty"]
        avg_usage = row["avg_usage"]
        kb = pages * 8

        bar_w = round(pages / max_pages * 30) if max_pages > 0 else 0

        line = Text()
        line.append(f"  {name:<30}", style="white bold")
        line.append("│", style="dim")
        line.append("█" * bar_w, style="green")
        line.append(f"  {kb:>7} KB", style="dim")
        line.append(f"  ({pages:>5} pages)", style="dim")

        if dirty and dirty > 0:
            line.append(f"  dirty={dirty}", style="red bold")

        line.append(f"  avg_usage={avg_usage}", style="cyan")
        p.add(line)

    p.print(title="[bold]Cached Relations[/bold]", border_style="green", padding=(1, 1))
