from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

PAGE_SIZE = 8192
PREVIEW_COUNT = 3


def render_page(
    header: dict, items: list[dict], tuple_data: dict[int, dict], *, show_all: bool = False
) -> None:
    lower = header["lower"]
    upper = header["upper"]
    special = header["special"]
    free_bytes = upper - lower
    pointer_bytes = lower - 24
    tuple_bytes = special - upper
    active = [i for i in items if i["lp_off"] > 0 and i["t_xmin"] is not None]

    lines: list[Text | str] = []

    _add_header_section(lines, header)
    _add_pointer_section(lines, items, pointer_bytes, show_all)
    _add_free_section(lines, lower, free_bytes)
    _add_tuple_section(lines, upper, active, tuple_data, tuple_bytes, show_all)
    _add_end(lines)
    _add_space_bar(lines, pointer_bytes, free_bytes, tuple_bytes)

    content = Text()
    for line in lines:
        if isinstance(line, Text):
            content.append_text(line)
        else:
            content.append(str(line))
        content.append("\n")

    console.print(Panel(
        content,
        border_style="blue",
        padding=(1, 2),
    ))


# ── Sections ──────────────────────────────────────────────────────────────────


def _add_header_section(lines: list, header: dict) -> None:
    lines.append(_section_bar(0x0, "PAGE HEADER", "24 bytes", "cyan"))
    lines.append("")

    pairs = [
        ("LSN", str(header["lsn"])),
        ("Checksum", str(header["checksum"])),
        ("Flags", str(header["flags"])),
        ("Page Size", str(header["pagesize"])),
        ("Lower", f"{header['lower']}  (end of item pointers)"),
        ("Upper", f"{header['upper']}  (start of tuples)"),
        ("Special", str(header["special"])),
    ]
    for key, val in pairs:
        line = Text()
        line.append(f"  {'':>6}    ", style="dim")
        line.append(f"{key:>12}", style="cyan")
        line.append("  │  ", style="dim")
        line.append(val, style="white")
        lines.append(line)

    lines.append("")


def _add_pointer_section(lines: list, items: list[dict], pointer_bytes: int, show_all: bool = False) -> None:
    num = len(items)
    lines.append(_section_bar(24, "ITEM POINTERS  ↓", f"{pointer_bytes} bytes, {num} items", "yellow"))
    lines.append("")

    flags_map = {0: "unused", 1: "normal", 2: "redirect", 3: "dead"}
    show = items if show_all else _pick_preview(items)

    for entry in show:
        if entry is None:
            lines.append(_ellipsis(len(items) - PREVIEW_COUNT * 2))
            continue

        flags = flags_map.get(entry["lp_flags"], str(entry["lp_flags"]))
        flag_style = {
            "normal": "green",
            "dead": "red bold",
            "redirect": "magenta",
            "unused": "dim",
        }.get(flags, "dim")

        line = Text()
        line.append(f"  {'':>6}    ", style="dim")
        line.append(f"LP {entry['lp']:>4}", style="yellow bold")
        line.append("  →  ", style="dim")
        line.append(f"offset {entry['lp_off']:>5}", style="white")
        line.append("  │  ", style="dim")
        line.append(f"len {entry['lp_len']:>3}", style="white")
        line.append("  │  ", style="dim")
        line.append(flags, style=flag_style)
        lines.append(line)

    lines.append("")


def _add_free_section(lines: list, lower: int, free_bytes: int) -> None:
    pct = free_bytes * 100 / PAGE_SIZE
    lines.append(_section_bar(lower, "FREE SPACE", f"{free_bytes} bytes, {pct:.1f}%", "dim"))
    lines.append("")


def _add_tuple_section(
    lines: list, upper: int, active: list[dict], tuple_data: dict[int, dict], tuple_bytes: int,
    show_all: bool = False,
) -> None:
    lines.append(_section_bar(upper, "TUPLES  ↑", f"{tuple_bytes} bytes, {len(active)} tuples", "green"))
    lines.append("")

    if not active:
        lines.append(_centered_dim("(empty)"))
        lines.append("")
        return

    sorted_by_offset = sorted(active, key=lambda i: i["lp_off"])
    show = sorted_by_offset if show_all else _pick_preview(sorted_by_offset)

    for i, entry in enumerate(show):
        if entry is None:
            lines.append(_ellipsis(len(active) - PREVIEW_COUNT * 2))
            continue

        lp = entry["lp"]
        xmax = entry["t_xmax"] or 0

        # Tuple header line
        hdr = Text()
        hdr.append(f"  {'':>6}    ", style="dim")
        hdr.append("┌─ ", style="dim")
        hdr.append(f"LP {lp}", style="yellow bold")
        hdr.append(f"  │  ", style="dim")
        hdr.append(f"offset {entry['lp_off']}", style="dim")
        hdr.append(f"  │  ", style="dim")
        hdr.append(f"{entry['lp_len']} bytes", style="dim")
        lines.append(hdr)

        # xmin / xmax / ctid line
        meta = Text()
        meta.append(f"  {'':>6}    ", style="dim")
        meta.append("│  ", style="dim")
        meta.append("xmin=", style="dim")
        meta.append(f"{entry['t_xmin']}", style="cyan bold")
        meta.append("   xmax=", style="dim")
        meta.append(f"{xmax}", style="red bold" if xmax != 0 else "dim")
        meta.append("   ctid=", style="dim")
        meta.append(f"{entry['t_ctid']}", style="white")
        meta.append("   hoff=", style="dim")
        meta.append(f"{entry['t_hoff']}", style="white")
        lines.append(meta)

        # Data line
        if lp in tuple_data:
            row = tuple_data[lp]
            data = Text()
            data.append(f"  {'':>6}    ", style="dim")
            data.append("│  ", style="dim")
            first = True
            for k, v in row.items():
                if not first:
                    data.append("  │  ", style="dim")
                data.append(f"{k}", style="dim")
                data.append("=", style="dim")
                data.append(f"{v}", style="white bold")
                first = False
            lines.append(data)

        # Bottom border
        bot = Text()
        bot.append(f"  {'':>6}    ", style="dim")
        bot.append("└─────", style="dim")
        lines.append(bot)

        if i < len(show) - 1:
            lines.append("")

    lines.append("")


def _add_end(lines: list) -> None:
    lines.append(_section_bar(PAGE_SIZE, "END OF PAGE", "8192", "dim"))


def _add_space_bar(lines: list, pointer_bytes: int, free_bytes: int, tuple_bytes: int) -> None:
    lines.append("")

    bar_width = 64
    total = PAGE_SIZE

    h_w = max(1, round(24 / total * bar_width))
    p_w = max(1, round(pointer_bytes / total * bar_width))
    f_w = max(1, round(free_bytes / total * bar_width)) if free_bytes > 0 else 0
    t_w = max(1, round(tuple_bytes / total * bar_width))

    used = h_w + p_w + f_w + t_w
    t_w += bar_width - used

    bar = Text()
    bar.append("  [", style="dim")
    bar.append("█" * h_w, style="cyan")
    bar.append("█" * p_w, style="yellow")
    bar.append("░" * f_w, style="dim")
    bar.append("█" * t_w, style="green")
    bar.append("]", style="dim")
    lines.append(bar)

    legend = Text()
    legend.append("   ", style="dim")
    legend.append("█", style="cyan")
    legend.append(f" hdr ({24}B)  ", style="dim")
    legend.append("█", style="yellow")
    legend.append(f" ptrs ({pointer_bytes}B)  ", style="dim")
    legend.append("░", style="dim")
    legend.append(f" free ({free_bytes}B)  ", style="dim")
    legend.append("█", style="green")
    legend.append(f" tuples ({tuple_bytes}B)", style="dim")
    lines.append(legend)


def render_fsm(table: str, freespace: list[dict], info: dict) -> None:
    bar_width = 40
    lines: list[Text | str] = []

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
        lines.append(line)

    total_avail = sum(r["avail"] for r in freespace)
    total_capacity = len(freespace) * PAGE_SIZE
    lines.append("")

    summary = Text()
    summary.append(f"  Total: ", style="dim")
    summary.append(f"{total_capacity - total_avail:,}", style="green bold")
    summary.append(f" / {total_capacity:,} bytes used", style="dim")
    summary.append(f"  ({total_avail:,} bytes free across {len(freespace)} pages)", style="cyan")
    lines.append(summary)

    content = Text()
    for line in lines:
        if isinstance(line, Text):
            content.append_text(line)
        else:
            content.append(str(line))
        content.append("\n")

    console.print(Panel(
        content,
        title=f"[bold]Free Space Map — {table}[/bold]",
        border_style="yellow",
        padding=(1, 2),
    ))


def render_vm(table: str, visibility: list[dict]) -> None:
    lines: list[Text | str] = []

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
        lines.append(line)

    lines.append("")

    # Summary bar
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
        lines.append(summary)

    content = Text()
    for line in lines:
        if isinstance(line, Text):
            content.append_text(line)
        else:
            content.append(str(line))
        content.append("\n")

    console.print(Panel(
        content,
        title=f"[bold]Visibility Map — {table}[/bold]",
        border_style="green",
        padding=(1, 2),
    ))


def render_fsm_tree(table: str, freespace: list[dict]) -> None:
    if not freespace:
        console.print("[dim]No pages[/dim]")
        return

    # Build leaf values (free space in FSM units: 1 unit = 32 bytes)
    leaves = []
    for row in freespace:
        avail = row["avail"]
        blkno = row["blkno"]
        fsm_val = avail // 32  # FSM stores in BLCKSZ/256 = 32-byte units
        leaves.append((blkno, avail, fsm_val))

    # Build complete binary tree bottom-up
    # Pad leaves to next power of 2
    n = len(leaves)
    size = 1
    while size < n:
        size *= 2

    # Tree array: index 1 = root, 2i = left child, 2i+1 = right child
    tree_size = size * 2
    tree = [0] * tree_size
    leaf_info = [None] * tree_size  # (blkno, avail) for leaf nodes

    # Fill leaves
    for i, (blkno, avail, fsm_val) in enumerate(leaves):
        idx = size + i
        tree[idx] = fsm_val
        leaf_info[idx] = (blkno, avail)

    # Build parents (max of children)
    for i in range(size - 1, 0, -1):
        tree[i] = max(tree[2 * i], tree[2 * i + 1])

    lines: list[Text | str] = []

    # Render tree level by level
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
            lines.append("")
            label = Text()
            label.append(f"  Level {depth}", style="bold yellow")
            label.append("  (leaves = heap pages)", style="dim")
            lines.append(label)
        elif depth == 0:
            label = Text()
            label.append("  Level 0", style="bold cyan")
            label.append("  (root)", style="dim")
            lines.append(label)
        else:
            label = Text()
            label.append(f"  Level {depth}", style="bold cyan")
            lines.append(label)

        lines.append("")

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
                # Internal node
                left_val = tree[2 * idx] if 2 * idx < tree_size else 0
                right_val = tree[2 * idx + 1] if 2 * idx + 1 < tree_size else 0

                line.append("    ", style="dim")
                line.append(f"[{idx:>3}]", style="cyan bold")
                line.append(f"  max={val:>3}", style="white")
                line.append(f"  (~{avail_bytes}B)", style="dim")
                line.append(f"  ← max(", style="dim")
                line.append(f"{left_val}", style="white")
                line.append(f", ", style="dim")
                line.append(f"{right_val}", style="white")
                line.append(f")", style="dim")

            lines.append(line)

        depth += 1
        level_start *= 2

    # How search works
    lines.append("")
    max_free = tree[1] * 32 if tree[1] > 0 else 0
    note = Text()
    note.append("  Search: ", style="bold")
    note.append(f"\"I need N bytes\" → start at root (max={max_free}B), follow the branch ", style="dim")
    note.append("where child ≥ N", style="white")
    lines.append(note)

    content = Text()
    for line in lines:
        if isinstance(line, Text):
            content.append_text(line)
        else:
            content.append(str(line))
        content.append("\n")

    console.print(Panel(
        content,
        title=f"[bold]FSM Tree — {table}[/bold]",
        border_style="yellow",
        padding=(1, 2),
    ))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _section_bar(offset: int, label: str, info: str, style: str) -> Text:
    line = Text()
    line.append(f"  0x{offset:04X}", style="dim italic")
    line.append("  ┃ ", style=f"bold {style}")
    line.append(f" {label} ", style=f"bold {style}")
    line.append(f" ({info})", style="dim")
    pad = max(0, 55 - len(label) - len(info))
    line.append(" " + "─" * pad, style="dim")
    return line


def _ellipsis(count: int) -> Text:
    line = Text()
    line.append(f"  {'':>6}    ", style="dim")
    line.append(f"    ⋮  ({count} more)", style="dim italic")
    return line


def _centered_dim(text: str) -> Text:
    return Text(f"  {'':>6}    {text}", style="dim")


def _pick_preview(items: list) -> list:
    if len(items) <= PREVIEW_COUNT * 2 + 1:
        return items
    return items[:PREVIEW_COUNT] + [None] + items[-PREVIEW_COUNT:]
