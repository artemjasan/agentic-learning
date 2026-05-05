import click
import psycopg
from rich.text import Text

from pgvis.core import PAGE_SIZE, connect, console
from pgvis.format import PanelBuilder


@click.command()
@click.argument("table")
@click.option("--tree", is_flag=True, help="Show the FSM as a binary search tree.")
@click.pass_context
def fsm(ctx, table: str, tree: bool) -> None:
    """Visualize the Free Space Map: free bytes per page."""
    with connect(ctx.obj["dsn"]) as conn:
        info = _fetch_relation_info(conn, table)
        console.print(
            f"\n[bold]{table}[/bold] — "
            f"{info['size_bytes']} bytes, {info['num_pages']} pages\n"
        )
        freespace = _fetch_freespace(conn, table)
        if tree:
            _render_tree(table, freespace)
        else:
            _render_flat(table, freespace)


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


def _fetch_freespace(conn: psycopg.Connection, table: str) -> list[dict]:
    conn.execute("CREATE EXTENSION IF NOT EXISTS pg_freespacemap")
    return conn.execute(
        "SELECT blkno, avail FROM pg_freespace(%s) ORDER BY blkno",
        (table,),
    ).fetchall()


# ── Rendering ────────────────────────────────────────────────────────────────


def _render_flat(table: str, freespace: list[dict]) -> None:
    bar_width = 40
    p = PanelBuilder()

    for row in freespace:
        blkno = row["blkno"]
        avail = row["avail"]
        used = PAGE_SIZE - avail
        fill_pct = used / PAGE_SIZE
        avail_pct = avail / PAGE_SIZE

        filled_w = round(fill_pct * bar_width)
        empty_w = bar_width - filled_w

        line = Text()
        line.append(f"  Page {blkno:>4}", style="yellow")
        line.append("  │", style="dim")
        line.append("█" * filled_w, style="green")
        line.append("░" * empty_w, style="dim")
        line.append("│", style="dim")
        line.append(f"  {used:>5}/{PAGE_SIZE}B used", style="dim")
        line.append(f"  ({avail:>5}B free", style="cyan")
        line.append(f", {avail_pct * 100:.0f}%)", style="cyan")
        p.add(line)

    total_avail = sum(r["avail"] for r in freespace)
    total_capacity = len(freespace) * PAGE_SIZE
    p.blank()

    summary = Text()
    summary.append("  Total: ", style="dim")
    summary.append(f"{total_capacity - total_avail:,}", style="green bold")
    summary.append(f" / {total_capacity:,} bytes used", style="dim")
    summary.append(f"  ({total_avail:,} bytes free across {len(freespace)} pages)", style="cyan")
    p.add(summary)

    p.print(title=f"[bold]Free Space Map — {table}[/bold]", border_style="yellow")


def _render_tree(table: str, freespace: list[dict]) -> None:
    if not freespace:
        console.print("[dim]No pages[/dim]")
        return

    leaves = []
    for row in freespace:
        avail = row["avail"]
        blkno = row["blkno"]
        fsm_val = avail // 32
        leaves.append((blkno, avail, fsm_val))

    n = len(leaves)
    size = 1
    while size < n:
        size *= 2

    tree_size = size * 2
    tree = [0] * tree_size
    leaf_info = [None] * tree_size

    for i, (blkno, avail, fsm_val) in enumerate(leaves):
        idx = size + i
        tree[idx] = fsm_val
        leaf_info[idx] = (blkno, avail)

    for i in range(size - 1, 0, -1):
        tree[i] = max(tree[2 * i], tree[2 * i + 1])

    p = PanelBuilder()

    depth = 0
    level_start = 1
    while level_start < tree_size:
        level_end = min(level_start * 2, tree_size)
        is_leaf = level_start >= size

        level_nodes = []
        for idx in range(level_start, level_end):
            if tree[idx] > 0 or leaf_info[idx] is not None:
                level_nodes.append(idx)

        if not level_nodes:
            break

        if is_leaf:
            p.blank()
            label = Text()
            label.append(f"  Level {depth}", style="bold yellow")
            label.append("  (leaves = heap pages)", style="dim")
            p.add(label)
        elif depth == 0:
            label = Text()
            label.append("  Level 0", style="bold cyan")
            label.append("  (root)", style="dim")
            p.add(label)
        else:
            label = Text()
            label.append(f"  Level {depth}", style="bold cyan")
            p.add(label)

        p.blank()

        for idx in level_nodes:
            val = tree[idx]
            avail_bytes = val * 32

            line = Text()
            if is_leaf and leaf_info[idx] is not None:
                blkno, actual_avail = leaf_info[idx]
                bar_w = 20
                free_w = round(actual_avail / PAGE_SIZE * bar_w) if PAGE_SIZE > 0 else 0
                used_w = bar_w - free_w

                line.append("    ", style="dim")
                line.append(f"Page {blkno:>3}", style="yellow bold")
                line.append("  │", style="dim")
                line.append("█" * used_w, style="green")
                line.append("░" * free_w, style="dim")
                line.append("│", style="dim")
                line.append(f"  val={val:>3}", style="white")
                line.append(f"  (~{actual_avail}B free)", style="cyan")
            else:
                left_val = tree[2 * idx] if 2 * idx < tree_size else 0
                right_val = tree[2 * idx + 1] if 2 * idx + 1 < tree_size else 0

                line.append("    ", style="dim")
                line.append(f"[{idx:>3}]", style="cyan bold")
                line.append(f"  max={val:>3}", style="white")
                line.append(f"  (~{avail_bytes}B)", style="dim")
                line.append("  ← max(", style="dim")
                line.append(f"{left_val}", style="white")
                line.append(", ", style="dim")
                line.append(f"{right_val}", style="white")
                line.append(")", style="dim")

            p.add(line)

        depth += 1
        level_start *= 2

    p.blank()
    max_free = tree[1] * 32 if tree[1] > 0 else 0
    note = Text()
    note.append("  Search: ", style="bold")
    note.append(f"\"I need N bytes\" → start at root (max={max_free}B), follow the branch ", style="dim")
    note.append("where child ≥ N", style="white")
    p.add(note)

    p.print(title=f"[bold]FSM Tree — {table}[/bold]", border_style="yellow")
