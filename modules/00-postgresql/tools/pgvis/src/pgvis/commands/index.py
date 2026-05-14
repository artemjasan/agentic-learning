"""Visualize B-tree and Hash index internals.

Traces lookups and range scans through the index structure,
showing each page visited, the key comparisons, heap fetch,
and MVCC visibility check.

Navigate with ← → arrow keys, q to quit.
"""

import struct

import click
from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pgvis.commands.join import _present, _read_key  # reuse navigation
from pgvis.core import connect, console


@click.group()
@click.pass_context
def index(ctx):
    """Visualize index internals."""
    pass


# ── B-tree page view ──────────────────────────────────────────────────────


@index.command(name="page")
@click.argument("index_name")
@click.argument("page_ref", default="root")
@click.pass_context
def index_page(ctx, index_name, page_ref):
    """Show the physical layout of a B-tree index page.

    PAGE_REF can be: root, leaf, internal, or a page number.
    """
    dsn = ctx.obj["dsn"]
    with connect(dsn, autocommit=True) as conn:
        meta = _get_metapage(conn, index_name)
        if page_ref == "root":
            page_num = meta["root"]
        elif page_ref == "leaf":
            page_num = _find_first_leaf(conn, index_name, meta["root"], meta["level"])
        elif page_ref == "internal" and meta["level"] >= 2:
            items = _get_page_items(conn, index_name, meta["root"])
            page_num = _ctid_to_page(items[0]["ctid"])
        else:
            try:
                page_num = int(page_ref)
            except ValueError:
                console.print(f"[red]Unknown page reference: {page_ref}. Use root, leaf, internal, or a number.[/red]")
                return
        _render_index_page(conn, index_name, page_num)


def _render_index_page(conn, index_name, page_num):
    from pgvis.format import PanelBuilder, section_bar

    stats = _get_page_stats(conn, index_name, page_num)
    items = _get_page_items(conn, index_name, page_num)
    header = conn.execute(
        "SELECT * FROM page_header(get_raw_page(%s, %s))", [index_name, page_num],
    ).fetchone()

    page_type = stats["type"]
    btpo_level = int(stats.get("btpo_level", stats.get("btpo", 0)))
    type_label = {"l": "leaf", "i": "internal", "r": "root"}.get(page_type, page_type)
    is_leaf = btpo_level == 0
    right_sibling = int(stats.get("btpo_next", 0))

    lower = header["lower"]
    upper = header["upper"]
    special = header["special"]
    free_bytes = upper - lower
    pointer_bytes = lower - 24
    item_bytes = special - upper
    special_bytes = 8192 - special

    p = PanelBuilder()

    # ── Page header ──
    p.add(section_bar(0x0, "PAGE HEADER", "24 bytes", "cyan"))
    p.blank()

    _kv(p, "LSN", str(header["lsn"]),
         "Log Sequence Number — position in WAL when this page was last modified.")
    _kv(p, "Lower", f"{lower}",
         "Where item pointers end. Pointers grow downward from byte 24.")
    _kv(p, "Upper", f"{upper}",
         "Where index tuples start. Tuples grow upward from the bottom.")
    _kv(p, "Special", f"{special}",
         "Start of B-tree specific data (right-sibling link, level).")
    _kv(p, "Page type", f"{type_label}, level {btpo_level}",
         "Level 0 = leaf (has key→TID entries). Higher = internal (has key→child page).")
    p.blank()

    note = Text()
    note.append(f"  {'':>6}    ", style="dim")
    note.append("  Same 8KB page layout as heap: header → pointers → free → data → special", style="dim italic")
    p.add(note)
    p.blank()

    # ── Item pointers ──
    p.add(section_bar(24, "ITEM POINTERS ↓", f"{pointer_bytes} bytes, {len(items)} items", "yellow"))
    p.blank()

    note = Text()
    note.append(f"  {'':>6}    ", style="dim")
    note.append("  Each pointer is 4 bytes: (offset, length, flags)", style="dim italic")
    p.add(note)
    note2 = Text()
    note2.append(f"  {'':>6}    ", style="dim")
    note2.append("  It tells where the actual index tuple is on this page.", style="dim italic")
    p.add(note2)
    p.blank()

    show_items = items[:10] if len(items) > 15 else items
    for item in show_items:
        line = Text()
        line.append(f"  {'':>6}    ", style="dim")
        line.append(f"LP {item['itemoffset']:>4}", style="yellow bold")
        line.append(f"  → tuple of {item['itemlen']} bytes in the tuples area below", style="white")
        p.add(line)

    if len(items) > 15:
        remaining = len(items) - 10
        line = Text()
        line.append(f"  {'':>6}    ", style="dim")
        line.append(f"    ... {remaining} more pointers", style="dim italic")
        p.add(line)
    p.blank()

    # ── Free space ──
    p.add(section_bar(lower, "FREE SPACE", f"{free_bytes} bytes", "dim"))

    note = Text()
    note.append(f"  {'':>6}    ", style="dim")
    note.append("  Pointers grow ↓ from top, tuples grow ↑ from bottom. They share this gap.", style="dim italic")
    p.add(note)
    p.blank()

    # ── Index tuples ──
    p.add(section_bar(upper, "INDEX TUPLES ↑", f"{item_bytes} bytes", "green" if is_leaf else "yellow"))
    p.blank()

    note = Text()
    note.append(f"  {'':>6}    ", style="dim")
    if is_leaf:
        note.append(f"  {len(items)} sorted entries. Each ~16 bytes: key + heap TID.", style="dim italic")
        p.add(note)
        note2 = Text()
        note2.append(f"  {'':>6}    ", style="dim")
        note2.append("  Sorted by key — enables binary search within the page.", style="dim italic")
        p.add(note2)
        note3 = Text()
        note3.append(f"  {'':>6}    ", style="dim")
        note3.append("  This is where the actual data lives (item pointers just point here).", style="dim italic")
        p.add(note3)
    else:
        note.append(f"  {len(items)} pivot entries. Each has a key boundary + child page number.", style="dim italic")
        p.add(note)
        note2 = Text()
        note2.append(f"  {'':>6}    ", style="dim")
        note2.append("  This is where the actual data lives (item pointers just point here).", style="dim italic")
        p.add(note2)
    p.blank()

    # Show sample tuples with structure
    # Separate high key from data entries
    has_high_key = not is_leaf and right_sibling or (is_leaf and right_sibling)
    data_start = 1 if has_high_key else 0

    if has_high_key and items:
        hk = items[0]
        hk_val = _parse_int4_key(hk["data"])
        hk_hex = (hk["data"] or "").strip()
        line = Text()
        line.append(f"  {'':>6}    ", style="dim")
        line.append(f"  LP {hk['itemoffset']:>3}  ", style="dim")
        if hk_val is not None:
            line.append(f"[{hk_hex}] → ", style="dim")
            line.append(f"HIGH KEY = {hk_val:,}", style="magenta bold")
            line.append("  (upper bound for all keys on this page)", style="dim italic")
        else:
            line.append("HIGH KEY (no data)", style="magenta")
        p.add(line)

        sep = Text()
        sep.append(f"  {'':>6}    ", style="dim")
        sep.append("  ─── navigation entries below ───", style="dim")
        p.add(sep)

    sample_items = items[data_start:data_start + 5]
    for item in sample_items:
        key_val = _parse_int4_key(item["data"])
        htid = item.get("htid") or item["ctid"]
        raw_hex = (item["data"] or "").strip()

        line = Text()
        line.append(f"  {'':>6}    ", style="dim")
        line.append(f"  LP {item['itemoffset']:>3}  ", style="dim")

        if key_val is not None:
            line.append(f"[{raw_hex}]", style="dim")
            line.append(" → key=", style="dim")
            line.append(f"{key_val:,}", style="green" if is_leaf else "yellow")
            if is_leaf:
                line.append(f"  TID={htid}", style="white")
            else:
                child = _ctid_to_page(item["ctid"])
                line.append(f"  child=page {child}", style="white")
        else:
            child = _ctid_to_page(item["ctid"])
            line.append("[no key]", style="dim")
            line.append(f" → leftmost child=page {child}", style="white")

        line.append(f"  ({item['itemlen']} bytes)", style="dim")
        p.add(line)

    remaining = len(items) - data_start - len(sample_items)
    if remaining > 0:
        extra = Text()
        extra.append(f"  {'':>6}    ", style="dim")
        extra.append(f"  ... {remaining} more entries", style="dim italic")
        p.add(extra)

    # Explain the hex encoding
    keyed = [it for it in sample_items if _parse_int4_key(it["data"]) is not None]
    if keyed:
        note3 = Text()
        note3.append(f"  {'':>6}    ", style="dim")
        hex_parts = keyed[0]["data"].strip().split()
        if len(hex_parts) >= 4:
            note3.append(f"  key bytes: {' '.join(hex_parts[:4])} → int4 little-endian → {_parse_int4_key(keyed[0]['data'])}", style="dim italic")
        p.add(note3)
    p.blank()

    # ── Special area ──
    p.add(section_bar(special, "SPECIAL (B-tree)", f"{special_bytes} bytes", "magenta"))
    p.blank()

    note = Text()
    note.append(f"  {'':>6}    ", style="dim")
    note.append("  B-tree pages have extra metadata that heap pages don't:", style="dim italic")
    p.add(note)
    p.blank()

    _kv(p, "Right sibling",
         f"page {right_sibling}" if right_sibling else "(none — rightmost page)",
         "Leaf pages form a linked list → enables range scans without going back up the tree." if is_leaf
         else "Internal pages also link right for tree traversal during splits.")
    _kv(p, "Level", str(btpo_level),
         "0 = leaf (bottom). Higher = closer to root. The root's level = tree depth.")
    _kv(p, "Flags", str(stats.get("btpo_flags", "?")),
         "1 = leaf, 2 = root, 4 = deleted, 8 = meta, 16 = half-dead.")
    p.blank()

    # ── Space bar ──
    total = 8192
    p_pct = pointer_bytes / total * 100
    f_pct = free_bytes / total * 100
    t_pct = item_bytes / total * 100
    s_pct = special_bytes / total * 100
    bar = Text()
    bar.append(f"  {'':>6}    ", style="dim")
    bar.append("▓" * max(1, int(p_pct / 2)), style="yellow")
    bar.append("░" * max(1, int(f_pct / 2)), style="dim")
    bar.append("▓" * max(1, int(t_pct / 2)), style="green" if is_leaf else "yellow")
    bar.append("▓" * max(1, int(s_pct / 2)), style="magenta")
    bar.append(f"  ptrs {p_pct:.0f}%  free {f_pct:.0f}%  tuples {t_pct:.0f}%  special {s_pct:.0f}%", style="dim")
    p.add(bar)

    p.print(title=f"Index Page {page_num} ({type_label})", border_style="blue")


def _kv(p, key, val, explanation):
    """Add a key-value line with an explanation underneath."""
    line = Text()
    line.append(f"  {'':>6}    ", style="dim")
    line.append(f"{key:>14}", style="cyan")
    line.append("  │  ", style="dim")
    line.append(val, style="white")
    p.add(line)
    if explanation:
        exp = Text()
        exp.append(f"  {'':>6}    ", style="dim")
        exp.append(f"{'':>14}  ", style="dim")
        exp.append(f"  {explanation}", style="dim italic")
        p.add(exp)


# ── B-tree tree overview ───────────────────────────────────────────────────


@index.command()
@click.argument("index_name")
@click.pass_context
def tree(ctx, index_name):
    """Show B-tree structure: depth, pages per level, sample entries."""
    dsn = ctx.obj["dsn"]
    with connect(dsn, autocommit=True) as conn:
        frames = _build_tree_frames(conn, index_name)
    _present(frames)


def _build_tree_frames(conn, index_name):
    frames = []
    meta = _get_metapage(conn, index_name)
    root_page = meta["root"]
    depth = meta["level"]

    index_size = conn.execute(
        "SELECT relpages, pg_relation_size(oid) AS bytes "
        "FROM pg_class WHERE relname = %s", [index_name],
    ).fetchone()

    index_col = _get_index_column(conn, index_name)
    table_name = _get_index_table(conn, index_name)
    table_size = conn.execute(
        "SELECT relpages, pg_relation_size(oid) AS bytes "
        "FROM pg_class WHERE relname = %s", [table_name],
    ).fetchone()

    # Frame 1: overview
    overview = Text()
    overview.append(f"\n  B-tree index: ", style="dim")
    overview.append(f"{index_name}", style="bold cyan")
    overview.append(f"  on {table_name}.{index_col}\n\n", style="dim")
    overview.append(f"  Tree depth:    {depth + 1} levels\n", style="white")
    overview.append(f"  Root page:     {root_page}\n", style="white")
    overview.append(f"  Total pages:   {index_size['relpages']:,}\n", style="white")
    overview.append(f"  Index size:    {index_size['bytes'] / 1024 / 1024:.1f} MB\n", style="white")
    overview.append(f"  Table size:    {table_size['bytes'] / 1024 / 1024:.1f} MB", style="white")
    overview.append(f"  ({table_size['relpages']:,} pages)\n", style="dim")
    overview.append(f"\n  A point lookup reads {depth + 2} pages:\n", style="dim")
    overview.append(f"    {depth + 1} index pages (root → leaf) + 1 heap page\n", style="dim")

    frames.append(Panel(overview, title="[bold]B-tree Overview[/bold]", border_style="cyan", padding=(1, 2)))

    # Frame 2: what's inside an index page
    structure = Text()
    structure.append("\n  An index is a separate file of 8KB pages (same as heap).\n", style="white")
    structure.append("  But instead of full rows, each page stores:\n\n", style="white")

    structure.append("  Internal page entry:\n", style="bold yellow")
    structure.append("    ┌──────────────────────────────────┐\n", style="dim")
    structure.append("    │  key boundary  │  child page ptr │\n", style="yellow")
    structure.append("    │  ≤ 103,945     │  → page 289     │\n", style="dim")
    structure.append("    └──────────────────────────────────┘\n", style="dim")
    structure.append("    \"keys up to 103,945 are in the subtree at page 289\"\n\n", style="dim italic")

    structure.append("  Leaf page entry:\n", style="bold green")
    structure.append("    ┌──────────────────────────────────┐\n", style="dim")
    structure.append(f"    │  {index_col} value    │  heap TID       │\n", style="green")
    structure.append("    │  42            │  → (page 0, #42) │\n", style="dim")
    structure.append("    └──────────────────────────────────┘\n", style="dim")
    structure.append(f"    \"{index_col}=42 is at heap page 0, offset 42\"\n\n", style="dim italic")

    structure.append(f"  The index stores only the {index_col} column + pointer.\n", style="dim")
    structure.append(f"  That's why it's {index_size['bytes'] / 1024 / 1024:.1f} MB vs {table_size['bytes'] / 1024 / 1024:.1f} MB for the full table.\n", style="dim")

    frames.append(Panel(structure, title="[bold]What's Inside an Index Page[/bold]", border_style="white", padding=(1, 2)))

    # Frame 2: root page entries
    root_stats = _get_page_stats(conn, index_name, root_page)
    root_items = _get_page_items(conn, index_name, root_page)

    root_text = Text()
    root_text.append(f"\n  Root page [{root_page}]", style="bold yellow")
    root_text.append(f"  —  {root_stats['live_items']} entries\n", style="dim")
    root_text.append(f"  Level {depth} ({'internal' if depth > 0 else 'leaf'})\n\n", style="dim")

    for item in root_items[:20]:
        key_val = _parse_int4_key(item["data"])
        child_page = _ctid_to_page(item["ctid"])

        if key_val is not None:
            root_text.append(f"    → page {child_page:<6}", style="cyan")
            root_text.append(f"  keys ≤ {key_val:,}\n", style="white")
        else:
            root_text.append(f"    → page {child_page:<6}", style="cyan")
            root_text.append("  (leftmost child)\n", style="dim")

    if len(root_items) > 20:
        root_text.append(f"\n    ... {len(root_items) - 20} more entries\n", style="dim")

    root_text.append(
        f"\n  Each entry points to a child page that handles\n"
        f"  a range of key values.\n",
        style="dim italic",
    )

    frames.append(Panel(root_text, title="[bold]Root Page[/bold]", border_style="yellow", padding=(1, 2)))

    # Frame 3: sample leaf page (first leaf)
    first_leaf = _find_first_leaf(conn, index_name, root_page, depth)
    leaf_stats = _get_page_stats(conn, index_name, first_leaf)
    leaf_items = _get_page_items(conn, index_name, first_leaf)

    leaf_text = Text()
    leaf_text.append(f"\n  Leaf page [{first_leaf}]", style="bold green")
    leaf_text.append(f"  —  {leaf_stats['live_items']} entries\n", style="dim")
    right_link = leaf_stats.get("btpo_next", 0)
    leaf_text.append(f"  Next leaf: page {right_link}", style="dim")
    leaf_text.append("  (linked list for range scans)\n\n", style="dim")

    shown = 0
    for item in leaf_items[:15]:
        key_val = _parse_int4_key(item["data"])
        htid = item.get("htid") or item["ctid"]
        if key_val is not None:
            leaf_text.append(f"    id={key_val:<8}", style="white")
            leaf_text.append(f"  → heap {htid}\n", style="green")
            shown += 1

    if len(leaf_items) > 15:
        leaf_text.append(f"\n    ... {len(leaf_items) - 15} more entries\n", style="dim")

    leaf_text.append(
        f"\n  Leaf entries: sorted key values + heap TIDs.\n"
        f"  Leaves link to each other for range scans.\n",
        style="dim italic",
    )

    frames.append(Panel(leaf_text, title="[bold]Leaf Page (sample)[/bold]", border_style="green", padding=(1, 2)))

    return frames


# ── B-tree point lookup ────────────────────────────────────────────────────


@index.command()
@click.argument("index_name")
@click.argument("value", type=int)
@click.option("--table", "table_name", default=None, help="Heap table name (auto-detected if omitted).")
@click.pass_context
def lookup(ctx, index_name, value, table_name):
    """Trace a point lookup through the B-tree to the heap tuple."""
    dsn = ctx.obj["dsn"]
    with connect(dsn, autocommit=True) as conn:
        if not table_name:
            table_name = _get_index_table(conn, index_name)
        frames = _build_lookup_frames(conn, index_name, value, table_name)
    _present(frames)


def _build_lookup_frames(conn, index_name, lookup_value, table_name):
    frames = []
    meta = _get_metapage(conn, index_name)
    root_page = meta["root"]
    depth = meta["level"]
    index_col = _get_index_column(conn, index_name)

    # Frame 1: the query and what we're doing
    intro = Text()
    intro.append("\n  ", style="")
    intro.append("SELECT ", style="bold cyan")
    intro.append("* ", style="cyan")
    intro.append("FROM ", style="bold cyan")
    intro.append(f"{table_name} ", style="cyan")
    intro.append("WHERE ", style="bold cyan")
    intro.append(f"{index_col} = {lookup_value}\n\n", style="cyan")

    intro.append(f"  Index:   {index_name}", style="white")
    intro.append(f"  (B-tree on {table_name}.{index_col})\n", style="dim")
    intro.append(f"  Tree depth: {depth + 1} levels", style="dim")
    intro.append(f"  (from bt_metap: root=page {root_page}, level={depth})\n", style="dim")

    level_names = []
    for lvl in range(depth, -1, -1):
        if lvl == depth:
            level_names.append("root")
        elif lvl == 0:
            level_names.append("leaf")
        else:
            level_names.append("internal")
    intro.append(f"  Levels: {' → '.join(level_names)}\n\n", style="dim")

    intro.append(f"  A lookup reads {depth + 2} pages: ", style="white")
    intro.append(f"{depth + 1} index + 1 heap\n", style="dim")
    intro.append(
        "\n  Path: root → internal → leaf → heap → MVCC check → result\n",
        style="dim italic",
    )

    frames.append(Panel(intro, title="[bold]B-tree Lookup[/bold]", border_style="cyan", padding=(1, 2)))

    # Walk the tree
    current_page = root_page
    pages_read = []
    target_tid = None

    for level in range(depth, -1, -1):
        page_items = _get_page_items(conn, index_name, current_page)
        page_stats = _get_page_stats(conn, index_name, current_page)
        is_leaf = level == 0
        is_rightmost = int(page_stats.get("btpo_next", 0)) == 0
        level_name = "root" if level == depth else "leaf" if is_leaf else "internal"

        text = Text()
        target_child = None
        right_sibling = int(page_stats.get("btpo_next", 0))

        if is_leaf:
            target_child, target_tid = _render_leaf_page(
                text, page_items, current_page, level_name,
                page_stats, lookup_value, right_sibling,
            )
        else:
            target_child = _render_internal_page(
                text, page_items, current_page, level_name,
                page_stats, lookup_value, is_rightmost,
            )

        pages_read.append(current_page)
        page_label = f"Page {current_page} ({level_name})"
        frames.append(Panel(text, title=f"[bold]{page_label}[/bold]", border_style="yellow", padding=(1, 2)))

        if is_leaf:
            break
        if target_child is not None:
            current_page = target_child

    # Heap fetch + MVCC
    if target_tid:
        heap_page, heap_offset = _parse_tid(target_tid)
        pages_read.append(f"heap:{heap_page}")

        heap_frame = _build_heap_mvcc_frame(conn, table_name, heap_page, heap_offset, lookup_value, pages_read)
        frames.append(heap_frame)

    return frames


def _render_internal_page(text, page_items, current_page, level_name, page_stats, lookup_value, is_rightmost):
    """Render an internal B-tree page with a visual diagram."""
    data_items = page_items[0 if is_rightmost else 1:]
    target_child = _find_child_for_key(data_items, lookup_value)

    # Collect entries for the diagram
    entries = []
    for item in data_items:
        key_val = _parse_int4_key(item["data"])
        child_page = _ctid_to_page(item["ctid"])
        entries.append((key_val, child_page))

    # Page header
    text.append(f"\n  Page {current_page} ({level_name})", style="bold yellow")
    text.append(f"  —  {page_stats['live_items']} entries\n\n", style="dim")

    # Explanation
    text.append("  Each boundary key splits the range: keys below → left child, keys at or above → right child.\n", style="dim italic")
    text.append("  We compare our key to find which range it falls in.\n\n", style="dim italic")

    # Visual diagram — show up to 6 entries as boxes
    show_entries = []
    target_idx = None
    for i, (key_val, child_page) in enumerate(entries):
        if child_page == target_child:
            target_idx = len(show_entries)
        if len(show_entries) < 5 or child_page == target_child:
            show_entries.append((key_val, child_page))

    # Draw boxes with correct range labels
    top_line = "  ┌"
    mid_line = "  │"
    ptr_line = "  │"
    bot_line = "  └"
    for i, (key_val, child_page) in enumerate(show_entries):
        if key_val is None:
            next_key = None
            for k, _ in entries[1:]:
                if k is not None:
                    next_key = k
                    break
            label = f" < {next_key:,} " if next_key else " (all) "
        else:
            label = f" >= {key_val:,} "
        width = max(len(label), 10)
        label = label.center(width)
        ptr = f"  p.{child_page}  ".center(width)

        sep = "┬" if i < len(show_entries) - 1 else "┐"
        bsep = "┴" if i < len(show_entries) - 1 else "┘"

        top_line += "─" * width + sep
        mid_line += label + "│"
        ptr_line += ptr + "│"
        bot_line += "─" * width + bsep

    if len(entries) > len(show_entries):
        top_line += "───┐"
        mid_line += "...│"
        ptr_line += "   │"
        bot_line += "───┘"

    text.append(top_line + "\n", style="dim")
    text.append(mid_line + "\n", style="white")
    text.append(ptr_line + "\n", style="cyan")
    text.append(bot_line + "\n", style="dim")

    # Arrow showing which box we follow
    if target_idx is not None:
        text.append("\n")
        text.append(f"  key {lookup_value:,}", style="white")
        if entries[0][0] is None and target_child == entries[0][1]:
            bound = entries[1][0] if len(entries) > 1 and entries[1][0] else "?"
            text.append(f" < {bound:,}", style="white")
        else:
            for key_val, child_page in entries:
                if child_page == target_child and key_val is not None:
                    text.append(f" >= {key_val:,}", style="white")
                    break
        text.append(f" → follow ", style="white")
        text.append(f"page {target_child}\n", style="bold yellow")

    return target_child


def _render_leaf_page(text, page_items, current_page, level_name, page_stats, lookup_value, right_sibling):
    """Render a leaf B-tree page with a visual diagram."""
    all_entries = []
    found_idx = None
    target_tid = None

    for item in page_items:
        key_val = _parse_int4_key(item["data"])
        htid = item.get("htid") or item["ctid"]
        if key_val is not None:
            all_entries.append((key_val, htid))
            if key_val == lookup_value:
                found_idx = len(all_entries) - 1
                target_tid = htid

    # Page header
    text.append(f"\n  Page {current_page} ({level_name})", style="bold green")
    text.append(f"  —  {len(all_entries)} entries\n", style="dim")
    if right_sibling:
        text.append(f"  ← prev | next → page {right_sibling}", style="dim")
        text.append("  (leaf linked list)\n", style="dim italic")
    text.append("\n", style="")

    # Explanation
    text.append("  Each entry: sorted key → heap TID (page, offset)\n", style="dim italic")
    text.append("  Binary search finds the key, TID points to the heap tuple.\n\n", style="dim italic")

    # Visual diagram — show a few boxes around the target
    if found_idx is not None:
        start = max(0, found_idx - 2)
        end = min(len(all_entries), found_idx + 3)
    else:
        start, end = 0, min(5, len(all_entries))

    # Draw boxes
    top_line = "  ┌"
    key_line = "  │"
    tid_line = "  │"
    bot_line = "  └"

    if start > 0:
        top_line = "   " + top_line
        key_line = "...│"
        tid_line = "   │"
        bot_line = "   " + bot_line

    for i in range(start, end):
        key_val, htid = all_entries[i]
        is_found = i == found_idx
        k_label = f" id={key_val} "
        t_label = f" →{htid} "
        width = max(len(k_label), len(t_label), 10)
        k_label = k_label.center(width)
        t_label = t_label.center(width)

        sep = "┬" if i < end - 1 else "┐"
        bsep = "┴" if i < end - 1 else "┘"

        top_line += "─" * width + sep
        key_line += k_label + "│"
        tid_line += t_label + "│"
        bot_line += "─" * width + bsep

    if end < len(all_entries):
        top_line += "───┐"
        key_line += "...│"
        tid_line += "   │"
        bot_line += "───┘"

    text.append(top_line + "\n", style="dim")
    if found_idx is not None:
        text.append(key_line + "\n", style="bold green")
    else:
        text.append(key_line + "\n", style="white")
    text.append(tid_line + "\n", style="cyan")
    text.append(bot_line + "\n", style="dim")

    # Arrow pointing to the found key
    if found_idx is not None:
        text.append("\n")
        text.append(f"  FOUND: id={lookup_value}", style="bold green")
        text.append(f" → TID {target_tid}", style="green")
        text.append("  → next: fetch from heap\n", style="dim")
    else:
        text.append(f"\n  Key {lookup_value} not found on this page.\n", style="red")

    return None, target_tid


def _build_heap_mvcc_frame(conn, table_name, heap_page, heap_offset, lookup_value, pages_read):
    """Show the heap tuple and MVCC visibility check."""
    try:
        tuple_info = conn.execute(
            "SELECT lp, lp_off, t_xmin, t_xmax, "
            "t_infomask::text, t_infomask2::text, t_ctid "
            "FROM heap_page_items(get_raw_page(%s, %s)) "
            "WHERE lp = %s",
            [table_name, heap_page, heap_offset],
        ).fetchone()
    except Exception:
        tuple_info = None

    try:
        row_data = conn.execute(
            f"SELECT * FROM {table_name} WHERE ctid = '({heap_page},{heap_offset})'",
        ).fetchone()
    except Exception:
        row_data = None

    text = Text()
    text.append(f"\n  Heap page {heap_page}, offset {heap_offset}\n\n", style="bold")

    if tuple_info:
        xmin = tuple_info["t_xmin"]
        xmax = tuple_info["t_xmax"]

        text.append("  Tuple header:\n", style="bold")
        text.append(f"    xmin = {xmin}", style="white")

        xmin_status = _check_xact_status(conn, xmin)
        if xmin_status == "committed":
            text.append("  (committed ✓)\n", style="green")
        elif xmin_status == "aborted":
            text.append("  (aborted ✗)\n", style="red")
        else:
            text.append(f"  ({xmin_status})\n", style="yellow")

        text.append(f"    xmax = {xmax}", style="white")
        if xmax == 0:
            text.append("  (not deleted — tuple is alive)\n", style="green")
        else:
            xmax_status = _check_xact_status(conn, xmax)
            if xmax_status == "committed":
                text.append("  (deleted ✗)\n", style="red")
            else:
                text.append(f"  ({xmax_status})\n", style="yellow")

        # Visibility check
        text.append("\n  MVCC visibility check:\n", style="bold")
        visible = xmin_status == "committed" and (xmax == 0 or _check_xact_status(conn, xmax) != "committed")
        if visible:
            text.append("    xmin committed ✓  AND  xmax=0 (alive) ✓\n", style="green")
            text.append("    → tuple is ", style="white")
            text.append("VISIBLE\n", style="bold green")
        else:
            text.append("    → tuple is ", style="white")
            text.append("NOT VISIBLE\n", style="bold red")

    if row_data:
        text.append("\n  Row data:\n", style="bold")
        for col, val in row_data.items():
            text.append(f"    {col}: ", style="dim")
            text.append(f"{val}\n", style="white")

    # Summary
    index_pages = len([p for p in pages_read if not str(p).startswith("heap")])
    text.append(f"\n  Total pages read: {len(pages_read)}", style="dim")
    text.append(f" ({index_pages} index + 1 heap)\n", style="dim")

    return Panel(text, title="[bold green]Heap Fetch + MVCC Check[/bold green]", border_style="green", padding=(1, 2))


# ── B-tree range scan ──────────────────────────────────────────────────────


@index.command(name="range")
@click.argument("index_name")
@click.argument("lo", type=int)
@click.argument("hi", type=int)
@click.option("--table", "table_name", default=None, help="Heap table name.")
@click.pass_context
def range_scan(ctx, index_name, lo, hi, table_name):
    """Trace a range scan through B-tree leaf pages."""
    dsn = ctx.obj["dsn"]
    with connect(dsn, autocommit=True) as conn:
        if not table_name:
            table_name = _get_index_table(conn, index_name)
        frames = _build_range_frames(conn, index_name, lo, hi, table_name)
    _present(frames)


def _build_range_frames(conn, index_name, lo, hi, table_name):
    frames = []
    meta = _get_metapage(conn, index_name)
    root_page = meta["root"]
    depth = meta["level"]

    # Intro
    intro = Text()
    intro.append("\n  Tracing B-tree range scan\n\n", style="bold")
    intro.append(f"  Index:   {index_name}\n", style="white")
    intro.append(f"  Range:   ", style="white")
    intro.append(f"key BETWEEN {lo} AND {hi}\n\n", style="bold cyan")
    intro.append("  Steps:\n", style="dim")
    intro.append("    1. Descend tree to find leaf containing first key\n", style="dim")
    intro.append("    2. Scan leaf entries in range\n", style="dim")
    intro.append("    3. Follow right-sibling links to next leaf if needed\n", style="dim")
    intro.append("    4. Stop when key > upper bound\n", style="dim")

    frames.append(Panel(intro, title="[bold]B-tree Range Scan[/bold]", border_style="cyan", padding=(1, 2)))

    # Find the starting leaf
    current_page = root_page
    for level in range(depth, 0, -1):
        page_items = _get_page_items(conn, index_name, current_page)
        child = _find_child_for_key(page_items, lo)
        if child is not None:
            current_page = child

    # Scan leaf pages
    matches = []
    leaf_pages_visited = 0
    done = False

    while not done and current_page != 0:
        leaf_pages_visited += 1
        leaf_stats = _get_page_stats(conn, index_name, current_page)
        leaf_items = _get_page_items(conn, index_name, current_page)
        right_link = leaf_stats.get("btpo_next", 0)

        page_matches = []
        past_range = False

        text = Text()
        text.append(f"\n  Leaf page [{current_page}]", style="bold green")
        text.append(f"  —  {leaf_stats['live_items']} entries", style="dim")
        if right_link and right_link != 0:
            text.append(f"  →  next: page {right_link}\n\n", style="dim")
        else:
            text.append("  (last leaf)\n\n", style="dim")

        for item in leaf_items:
            key_val = _parse_int4_key(item["data"])
            htid = item.get("htid") or item["ctid"]

            if key_val is None:
                continue

            if key_val < lo:
                text.append(f"    id={key_val:<8}  → skip (below range)\n", style="dim")
            elif key_val > hi:
                text.append(f"    id={key_val:<8}  → stop (above range)\n", style="dim")
                past_range = True
                done = True
                break
            else:
                text.append(f"  ► id={key_val:<8}  → heap {htid}", style="bold green")
                text.append("  ✓ in range\n", style="green")
                page_matches.append((key_val, htid))
                matches.append((key_val, str(htid)))

        if not past_range and right_link and right_link != 0:
            text.append(f"\n  End of page → follow right link to page {right_link}\n", style="yellow")

        text.append(f"\n  Matches on this page: {len(page_matches)}", style="dim")
        text.append(f"  Total so far: {len(matches)}\n", style="dim")

        frames.append(Panel(text, title=f"[bold]Leaf Page {current_page}[/bold]", border_style="green", padding=(1, 2)))

        if not done:
            current_page = right_link if right_link else 0

    # Summary
    summary = Text()
    summary.append("\n  Range scan complete!\n\n", style="bold green")
    summary.append(f"  Range:          {lo} to {hi}\n", style="white")
    summary.append(f"  Leaf pages:     {leaf_pages_visited}\n", style="white")
    summary.append(f"  Matching keys:  {len(matches)}\n", style="green")
    summary.append(
        f"\n  The scan followed the leaf linked list — no need to\n"
        "  go back up the tree. Each leaf points to the next.\n",
        style="dim italic",
    )
    if matches:
        summary.append(f"\n  Keys found: ", style="dim")
        keys_str = ", ".join(str(k) for k, _ in matches[:20])
        summary.append(keys_str, style="white")
        if len(matches) > 20:
            summary.append(f" ... ({len(matches) - 20} more)", style="dim")
        summary.append("\n", style="")

    frames.append(Panel(summary, title="[bold]Range Scan — Summary[/bold]", border_style="green", padding=(1, 2)))

    return frames


# ── Helpers ─────────────────────────────────────────────────────────────────


def _get_metapage(conn, index_name):
    row = conn.execute(
        "SELECT * FROM bt_metap(%s)", [index_name],
    ).fetchone()
    row["root"] = int(row["root"])
    row["level"] = int(row["level"])
    return row


def _get_page_stats(conn, index_name, page_num):
    return conn.execute(
        "SELECT * FROM bt_page_stats(%s, %s)", [index_name, page_num],
    ).fetchone()


def _get_page_items(conn, index_name, page_num):
    return conn.execute(
        "SELECT * FROM bt_page_items(%s, %s)", [index_name, page_num],
    ).fetchall()


def _get_index_column(conn, index_name):
    row = conn.execute(
        "SELECT a.attname "
        "FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid "
        "JOIN pg_attribute a ON a.attrelid = i.indrelid "
        "  AND a.attnum = i.indkey[0] "
        "WHERE c.relname = %s",
        [index_name],
    ).fetchone()
    return row["attname"] if row else "key"


def _get_index_table(conn, index_name):
    row = conn.execute(
        "SELECT c2.relname AS table_name "
        "FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid "
        "JOIN pg_class c2 ON c2.oid = i.indrelid "
        "WHERE c.relname = %s",
        [index_name],
    ).fetchone()
    return row["table_name"] if row else None


def _parse_int4_key(hex_data):
    """Parse int4 from pageinspect hex format like '2a 00 00 00'."""
    if not hex_data or not hex_data.strip():
        return None
    parts = hex_data.strip().split()
    if len(parts) < 4:
        return None
    try:
        raw = bytes(int(b, 16) for b in parts[:4])
        return struct.unpack("<i", raw)[0]
    except (ValueError, struct.error):
        return None


def _ctid_to_page(ctid_str):
    """Extract page number from ctid string like '(123,1)'."""
    try:
        clean = ctid_str.strip("()")
        page = int(clean.split(",")[0])
        return page
    except (ValueError, IndexError):
        return 0


def _parse_tid(tid_str):
    """Parse '(page,offset)' into (page, offset) integers."""
    try:
        clean = tid_str.strip("()")
        parts = clean.split(",")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return 0, 0


def _find_child_for_key(page_items, key):
    """On an internal page, find which child page handles the given key."""
    prev_page = None
    for item in page_items:
        child_page = _ctid_to_page(item["ctid"])
        key_val = _parse_int4_key(item["data"])

        if key_val is None:
            prev_page = child_page
            continue

        if key < key_val:
            return prev_page if prev_page is not None else child_page

        prev_page = child_page

    return prev_page


def _check_xact_status(conn, xid):
    """Check if a transaction is committed, aborted, or in-progress."""
    if xid == 0:
        return "none"
    if xid == 1:
        return "committed"  # bootstrap
    if xid == 2:
        return "committed"  # frozen
    try:
        row = conn.execute(
            "SELECT pg_xact_status(%s::text::xid8) AS status", [xid],
        ).fetchone()
        return row["status"] if row else "unknown"
    except Exception:
        return "committed"  # assume committed for old/frozen xids


def _find_first_leaf(conn, index_name, root_page, depth):
    """Navigate to the leftmost leaf page."""
    current = root_page
    for _ in range(depth):
        items = _get_page_items(conn, index_name, current)
        if items:
            current = _ctid_to_page(items[0]["ctid"])
    return current
