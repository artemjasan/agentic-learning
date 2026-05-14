"""Step-by-step visualization of join algorithms.

Uses hardcoded sample data — no database connection needed.
Navigate with ← → arrow keys, q to quit.
"""

import sys
import termios
import tty

import click
from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pgvis.core import console

USERS = [
    {"id": 42, "name": "alice"},
    {"id": 77, "name": "bob"},
    {"id": 103, "name": "carol"},
    {"id": 150, "name": "dave"},
    {"id": 200, "name": "eve"},
]

ORDERS = [
    {"id": 1, "user_id": 99, "amount": 50},
    {"id": 2, "user_id": 42, "amount": 75},
    {"id": 3, "user_id": 55, "amount": 30},
    {"id": 4, "user_id": 42, "amount": 20},
    {"id": 5, "user_id": 77, "amount": 15},
    {"id": 6, "user_id": 88, "amount": 90},
    {"id": 7, "user_id": 103, "amount": 45},
    {"id": 8, "user_id": 42, "amount": 60},
]


# ── Keyboard input ──────────────────────────────────────────────────────────


def _read_key():
    """Read a single keypress. Returns 'left', 'right', or 'quit'."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            ch3 = sys.stdin.read(1)
            if ch2 == "[":
                if ch3 == "D":
                    return "left"
                if ch3 == "C":
                    return "right"
        if ch in ("q", "\x03"):
            return "quit"
        return "right"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _present(frames):
    """Navigate through frames with arrow keys."""
    idx = 0
    while True:
        console.clear()
        console.print(frames[idx])

        nav = Text()
        if idx > 0:
            nav.append("  ← ", style="bold")
        else:
            nav.append("    ", style="dim")
        nav.append(f" {idx + 1}/{len(frames)} ", style="bold white")
        if idx < len(frames) - 1:
            nav.append(" →  ", style="bold")
        else:
            nav.append("    ", style="dim")
        nav.append("   q to quit", style="dim")
        console.print(nav)

        key = _read_key()
        if key == "quit":
            break
        elif key == "right" and idx < len(frames) - 1:
            idx += 1
        elif key == "left" and idx > 0:
            idx -= 1


# ── Column builders ─────────────────────────────────────────────────────────


def _outer_column(current_idx):
    col = Text()
    for i, u in enumerate(USERS):
        label = f"{u['name']:<8} id={u['id']}"
        if i == current_idx:
            col.append(f"  ► {label}\n", style="bold yellow")
        elif i < current_idx:
            col.append(f"  ✓ {label}\n", style="green dim")
        else:
            col.append(f"    {label}\n", style="dim")
    return col


def _inner_column(inner_idx, current_outer_match_ids, is_match=False):
    col = Text()
    for i, o in enumerate(ORDERS):
        label = f"uid={o['user_id']:<4} ${o['amount']:>3}"
        if i == inner_idx:
            if is_match:
                col.append(f"  ► {label}  ✓ MATCH\n", style="bold green")
            else:
                col.append(f"  ► {label}  ✗\n", style="cyan")
        elif i < inner_idx:
            if o["id"] in current_outer_match_ids:
                col.append(f"  ✓ {label}\n", style="green dim")
            else:
                col.append(f"    {label}\n", style="dim")
        else:
            col.append(f"    {label}\n", style="white dim")
    return col


def _match_column(matches, highlight_last=False):
    col = Text()
    if not matches:
        col.append("  (none yet)\n", style="dim")
        return col
    for i, (m_user, m_order) in enumerate(matches):
        is_last = highlight_last and i == len(matches) - 1
        style = "bold green" if is_last else "green"
        col.append(f"  {m_user['name']} + ${m_order['amount']}\n", style=style)
    return col


def _three_col_layout(headers, columns):
    layout = Table(show_header=True, box=box.SIMPLE, padding=(0, 2), expand=False)
    for header, style in headers:
        layout.add_column(header, header_style=style, min_width=22)
    layout.add_row(*columns)
    return layout


def _data_intro_frame(join_type="inner"):
    """First frame: show both tables and explain what a join does."""
    users_table = Table(
        title="users", title_style="bold yellow",
        box=box.ROUNDED, border_style="yellow", padding=(0, 1),
    )
    users_table.add_column("id", style="bold")
    users_table.add_column("name")
    for u in USERS:
        users_table.add_row(str(u["id"]), u["name"])

    orders_table = Table(
        title="orders", title_style="bold cyan",
        box=box.ROUNDED, border_style="cyan", padding=(0, 1),
    )
    orders_table.add_column("id", style="dim")
    orders_table.add_column("user_id", style="bold")
    orders_table.add_column("amount")
    for o in ORDERS:
        orders_table.add_row(str(o["id"]), str(o["user_id"]), f"${o['amount']}")

    tables = Table(show_header=False, box=None, padding=(0, 3))
    tables.add_column(min_width=20)
    tables.add_column(min_width=30)
    tables.add_row(users_table, orders_table)

    join_keyword = {
        "inner": "JOIN",
        "left": "LEFT JOIN",
        "right": "RIGHT JOIN",
        "full": "FULL OUTER JOIN",
    }.get(join_type, "JOIN")

    query = Text()
    query.append("\n  SELECT ", style="bold cyan")
    query.append("u.name, o.amount\n", style="cyan")
    query.append("  FROM ", style="bold cyan")
    query.append("users u\n", style="cyan")
    query.append(f"  {join_keyword} ", style="bold cyan")
    query.append("orders o ", style="cyan")
    query.append("ON ", style="bold cyan")
    query.append("u.id = o.user_id\n", style="cyan")

    explanation = Text()
    explanation.append("\n  alice has 3 orders, bob and carol have 1 each.\n", style="dim")
    explanation.append("  dave and eve have ", style="dim")
    explanation.append("no orders", style="bold")
    explanation.append(".\n", style="dim")
    explanation.append("  Orders uid=99, 55, 88 have ", style="dim")
    explanation.append("no matching user", style="bold")
    explanation.append(".\n\n", style="dim")

    if join_type == "inner":
        explanation.append("  INNER JOIN: only matched pairs.\n", style="white")
        explanation.append("  dave, eve → excluded. uid=99,55,88 → excluded.\n", style="dim")
        explanation.append("  Expected: 5 matched rows.\n", style="dim")
    elif join_type == "left":
        explanation.append("  LEFT JOIN: all users kept, even without orders.\n", style="white")
        explanation.append("  dave, eve → kept with NULL order.\n", style="yellow")
        explanation.append("  uid=99,55,88 → excluded (not on the LEFT side).\n", style="dim")
        explanation.append("  Expected: 5 matched + 2 with NULLs = 7 rows.\n", style="dim")
    elif join_type == "right":
        explanation.append("  RIGHT JOIN: all orders kept, even without a user.\n", style="white")
        explanation.append("  uid=99,55,88 → kept with NULL user.\n", style="yellow")
        explanation.append("  dave, eve → excluded (not on the RIGHT side).\n", style="dim")
        explanation.append("  Expected: 5 matched + 3 with NULLs = 8 rows.\n", style="dim")
    elif join_type == "full":
        explanation.append("  FULL OUTER JOIN: all rows from both sides.\n", style="white")
        explanation.append("  dave, eve → kept with NULL order.\n", style="yellow")
        explanation.append("  uid=99,55,88 → kept with NULL user.\n", style="yellow")
        explanation.append("  Expected: 5 matched + 2 + 3 = 10 rows.\n", style="dim")

    return Panel(
        Group(query, tables, explanation),
        title="[bold]The Data[/bold]",
        border_style="white",
        padding=(1, 2),
    )


def _strategy_intro_frame(title, description):
    """Second frame: explain the algorithm strategy."""
    return Panel(
        Text.from_markup(description),
        title=f"[bold]{title}[/bold]",
        border_style="cyan",
        padding=(1, 2),
    )


# ── Join type handling ──────────────────────────────────────────────────────

JOIN_TYPES = ["inner", "left", "right", "full"]

_join_type_option = click.option(
    "--type", "join_type", type=click.Choice(JOIN_TYPES),
    default="inner", help="Join type: inner, left, right, full.",
)


def _add_unmatched_frames(matches, join_type):
    """Build frames showing unmatched rows added for outer join types."""
    matched_user_ids = {m[0]["id"] for m in matches}
    matched_order_ids = {m[1]["id"] for m in matches}
    unmatched_users = [u for u in USERS if u["id"] not in matched_user_ids]
    unmatched_orders = [o for o in ORDERS if o["id"] not in matched_order_ids]

    extra_rows = []
    frames = []

    if join_type in ("left", "full") and unmatched_users:
        for user in unmatched_users:
            extra_rows.append((user, None))

    if join_type in ("right", "full") and unmatched_orders:
        for order in unmatched_orders:
            extra_rows.append((None, order))

    if not extra_rows:
        return frames, []

    text = Text()
    type_label = join_type.upper() + " JOIN"
    text.append(f"\n  {type_label}", style="bold yellow")
    text.append(" — adding unmatched rows:\n\n", style="white")

    for user, order in extra_rows:
        if user and not order:
            text.append(f"    {user['name']} (id={user['id']})", style="yellow")
            text.append("  +  NULL\n", style="dim")
        elif order and not user:
            text.append("    NULL  +  ", style="dim")
            text.append(f"order #{order['id']} ${order['amount']} (uid={order['user_id']})\n", style="yellow")

    text.append(
        f"\n  INNER JOIN would return {len(matches)} rows.\n",
        style="dim",
    )
    text.append(
        f"  {type_label} returns {len(matches) + len(extra_rows)} rows"
        f" ({len(extra_rows)} extra with NULLs).\n",
        style="white",
    )

    frames.append(Panel(
        text,
        title=f"[bold yellow]{type_label} — Unmatched Rows[/bold yellow]",
        border_style="yellow",
        padding=(1, 2),
    ))

    return frames, extra_rows


def _build_summary_matches(matches, extra_rows):
    """Build the matches section for the summary, including NULLs."""
    text = Text()
    text.append("\n  Matches:\n", style="bold")
    for user, order in matches:
        text.append(f"    {user['name']} (id={user['id']}) + order #{order['id']} ${order['amount']}\n", style="green")
    for user, order in extra_rows:
        if user and not order:
            text.append(f"    {user['name']} (id={user['id']}) + NULL\n", style="yellow")
        elif order and not user:
            text.append(f"    NULL + order #{order['id']} ${order['amount']}\n", style="yellow")
    return text


# ── Nested Loop ─────────────────────────────────────────────────────────────


@click.group()
def join():
    """Visualize join algorithms step by step."""
    pass


@join.command()
@_join_type_option
def nested(join_type):
    """Nested loop join: for each outer row, scan all inner rows."""
    frames = _build_nested_frames(join_type)
    _present(frames)


def _build_nested_frames(join_type="inner"):
    frames = []
    total = len(USERS) * len(ORDERS)

    # Show the data first
    frames.append(_data_intro_frame(join_type))

    # Explain the strategy
    frames.append(_strategy_intro_frame("Nested Loop Join",
        "\n  [bold]Strategy:[/bold] for each row in the outer table,\n"
        "  scan [bold]every[/bold] row in the inner table.\n\n"
        "  [dim]Think of it as a double for-loop:[/dim]\n"
        "  [cyan]for user in users:\n"
        "      for order in orders:\n"
        "          if user.id == order.user_id:\n"
        "              emit(user, order)[/cyan]\n\n"
        f"  Outer: {len(USERS)} users    Inner: {len(ORDERS)} orders\n"
        f"  Total comparisons: {len(USERS)} × {len(ORDERS)} = {total}\n"
        "\n"
        "  [bold yellow]When does the planner pick this?[/bold yellow]\n"
        "  When the outer side is [bold]small[/bold] (1-50 rows) and the inner side\n"
        "  has an [bold]index[/bold] on the join column. Each inner lookup\n"
        "  becomes O(log N) instead of O(N).\n\n"
        "  [dim]Typical query:[/dim]\n"
        "  [cyan]SELECT * FROM orders o\n"
        "  JOIN users u ON u.id = o.user_id\n"
        "  WHERE u.id = 42[/cyan]\n"
        "  [dim]→ 1 user drives the loop, index lookup on orders[/dim]\n"
    ))

    matches = []
    comparisons = 0

    for outer_idx, user in enumerate(USERS):
        current_match_ids = set()
        for inner_idx, order in enumerate(ORDERS):
            comparisons += 1
            is_match = user["id"] == order["user_id"]
            if is_match:
                matches.append((user, order))
                current_match_ids.add(order["id"])

            outer_col = _outer_column(outer_idx)
            inner_col = _inner_column(inner_idx, current_match_ids, is_match)
            match_col = _match_column(matches, highlight_last=is_match)

            layout = _three_col_layout(
                [("Outer (users)", "bold yellow"),
                 ("Inner (orders)", "bold cyan"),
                 ("Matches", "bold green")],
                [outer_col, inner_col, match_col],
            )

            status = Text()
            status.append(f"\n  {user['name']}.id ({user['id']})", style="white")
            if is_match:
                status.append(f" = order.uid ({order['user_id']}) → ", style="white")
                status.append("MATCH! ✓", style="bold green")
            else:
                status.append(f" ≠ order.uid ({order['user_id']})", style="dim")

            progress = comparisons / total
            filled = int(40 * progress)
            bar = "█" * filled + "░" * (40 - filled)
            status.append(f"\n\n  [{bar}] {comparisons}/{total}", style="dim")
            status.append(f"   matches: {len(matches)}", style="green")

            frames.append(Panel(
                Group(layout, status),
                title="[bold]Nested Loop Join[/bold]",
                subtitle=f"[dim]outer row {outer_idx + 1}/{len(USERS)}[/dim]",
                border_style="cyan",
                padding=(1, 1),
            ))

    # Join type: add unmatched rows
    unmatched_frames, extra_rows = _add_unmatched_frames(matches, join_type)
    frames.extend(unmatched_frames)

    # Summary frame
    type_label = join_type.upper()
    summary = Text()
    summary.append("\n  Done!\n\n", style="bold green")
    summary.append(f"  Join type:         {type_label} JOIN\n", style="white")
    summary.append(f"  Total comparisons: {comparisons}\n", style="white")
    summary.append(f"  Total matches:     {len(matches)}\n", style="green")
    if extra_rows:
        summary.append(f"  Unmatched rows:    {len(extra_rows)} (with NULLs)\n", style="yellow")
        summary.append(f"  Total result:      {len(matches) + len(extra_rows)} rows\n", style="bold white")
    summary.append(f"\n  Complexity: O(N × M) = O({len(USERS)} × {len(ORDERS)}) = {total}\n", style="dim")
    summary.append(
        "\n  Every outer row scanned ALL inner rows.\n"
        "  With an index on the inner side, each lookup\n"
        "  would be O(log M) instead of O(M).\n",
        style="dim italic",
    )
    summary.append_text(_build_summary_matches(matches, extra_rows))

    frames.append(Panel(summary, title="[bold]Nested Loop — Summary[/bold]", border_style="green", padding=(1, 2)))
    return frames


# ── Hash Join ───────────────────────────────────────────────────────────────


@join.command()
@_join_type_option
def hash(join_type):
    """Hash join: build hash table from smaller side, probe with larger."""
    frames = _build_hash_frames(join_type)
    _present(frames)


def _build_hash_frames(join_type="inner"):
    frames = []
    num_buckets = 8

    # Show the data first
    frames.append(_data_intro_frame(join_type))

    # Explain the strategy
    frames.append(_strategy_intro_frame("Hash Join",
        "\n  [bold]Strategy:[/bold] two phases.\n\n"
        "  [bold yellow]Phase 1 — Build:[/bold yellow]\n"
        "  Load the smaller side (users) into a hash table\n"
        "  keyed by the join column (id).\n\n"
        "  [bold cyan]Phase 2 — Probe:[/bold cyan]\n"
        "  Scan the larger side (orders). For each order,\n"
        "  hash its user_id, look up the hash table.\n"
        "  Match → O(1). No match → O(1). No scanning.\n\n"
        f"  Hash function: id % {num_buckets}  (8 buckets)\n"
        "\n"
        "  [bold yellow]When does the planner pick this?[/bold yellow]\n"
        "  When both sides are [bold]medium to large[/bold] and the join\n"
        "  condition is [bold]equality[/bold] (=). The smaller side must fit\n"
        "  in work_mem. Can't be used for range conditions (<, >).\n\n"
        "  [dim]Typical query:[/dim]\n"
        "  [cyan]SELECT * FROM users u\n"
        "  JOIN orders o ON o.user_id = u.id\n"
        "  WHERE u.score = 42[/cyan]\n"
        "  [dim]→ 5,000 users × 1M orders, hash table from users (320kB)[/dim]\n"
    ))

    # Build phase
    hash_table: dict[int, list] = {i: [] for i in range(num_buckets)}

    for user_idx, user in enumerate(USERS):
        bucket = user["id"] % num_buckets
        hash_table[bucket].append(user)

        users_col = Text()
        for i, u in enumerate(USERS):
            label = f"{u['name']:<8} id={u['id']}"
            if i == user_idx:
                users_col.append(f"  ► {label}\n", style="bold yellow")
            elif i < user_idx:
                users_col.append(f"  ✓ {label}\n", style="green dim")
            else:
                users_col.append(f"    {label}\n", style="dim")

        ht_col = _hash_table_column(hash_table, num_buckets, highlight_bucket=bucket, phase="build")

        layout = Table(show_header=True, box=box.SIMPLE, padding=(0, 3), expand=False)
        layout.add_column("Build Side (users)", header_style="bold yellow", min_width=22)
        layout.add_column("Hash Table", header_style="bold white", min_width=40)
        layout.add_row(users_col, ht_col)

        status = Text()
        status.append(f"\n  hash({user['id']}) % {num_buckets} = {bucket}", style="white")
        status.append(f"  →  insert {user['name']} into bucket {bucket}\n", style="yellow")
        status.append(f"\n  Built: {user_idx + 1}/{len(USERS)}", style="dim")

        frames.append(Panel(
            Group(layout, status),
            title="[bold yellow]Hash Join — Build Phase[/bold yellow]",
            border_style="yellow",
            padding=(1, 1),
        ))

    # Probe phase
    matches = []

    for order_idx, order in enumerate(ORDERS):
        bucket = order["user_id"] % num_buckets
        entries = hash_table[bucket]
        match = None
        for entry in entries:
            if entry["id"] == order["user_id"]:
                match = entry
                break

        is_match = match is not None
        if is_match:
            matches.append((match, order))

        orders_col = Text()
        for i, o in enumerate(ORDERS):
            label = f"uid={o['user_id']:<4} ${o['amount']:>3}"
            if i == order_idx:
                if is_match:
                    orders_col.append(f"  ► {label}  ✓\n", style="bold green")
                else:
                    orders_col.append(f"  ► {label}  ✗\n", style="cyan")
            elif i < order_idx:
                was_matched = any(m[1]["id"] == o["id"] for m in matches)
                if was_matched:
                    orders_col.append(f"  ✓ {label}\n", style="green dim")
                else:
                    orders_col.append(f"    {label}\n", style="dim")
            else:
                orders_col.append(f"    {label}\n", style="white dim")

        ht_col = _hash_table_column(hash_table, num_buckets, highlight_bucket=bucket, phase="probe")
        match_col = _match_column(matches, highlight_last=is_match)

        layout = _three_col_layout(
            [("Probe Side (orders)", "bold cyan"),
             ("Hash Table", "bold white"),
             ("Matches", "bold green")],
            [orders_col, ht_col, match_col],
        )

        status = Text()
        status.append(f"\n  hash({order['user_id']}) % {num_buckets} = {bucket}", style="white")
        if not entries:
            status.append(f"  →  bucket {bucket} empty → ", style="white")
            status.append("skip", style="red")
        elif is_match:
            status.append(f"  →  bucket {bucket}: id={match['id']} = uid={order['user_id']} → ", style="white")
            status.append("MATCH! ✓", style="bold green")
        else:
            checked = ", ".join(f"id={e['id']}" for e in entries)
            status.append(f"  →  bucket {bucket}: {checked} ≠ uid={order['user_id']} → ", style="white")
            status.append("no match", style="dim")

        progress = (order_idx + 1) / len(ORDERS)
        filled = int(40 * progress)
        bar = "█" * filled + "░" * (40 - filled)
        status.append(f"\n\n  [{bar}] {order_idx + 1}/{len(ORDERS)}", style="dim")
        status.append(f"   matches: {len(matches)}", style="green")

        frames.append(Panel(
            Group(layout, status),
            title="[bold cyan]Hash Join — Probe Phase[/bold cyan]",
            border_style="cyan",
            padding=(1, 1),
        ))

    # Join type: add unmatched rows
    unmatched_frames, extra_rows = _add_unmatched_frames(matches, join_type)
    frames.extend(unmatched_frames)

    # Summary
    type_label = join_type.upper()
    summary = Text()
    summary.append("\n  Done!\n\n", style="bold green")
    summary.append(f"  Join type:         {type_label} JOIN\n", style="white")
    summary.append(f"  Build phase:  {len(USERS)} rows → hash table ({num_buckets} buckets)\n", style="white")
    summary.append(f"  Probe phase:  {len(ORDERS)} rows × O(1) lookup each\n", style="white")
    summary.append(f"  Total matches: {len(matches)}\n", style="green")
    if extra_rows:
        summary.append(f"  Unmatched rows:    {len(extra_rows)} (with NULLs)\n", style="yellow")
        summary.append(f"  Total result:      {len(matches) + len(extra_rows)} rows\n", style="bold white")
    summary.append(f"\n  Complexity: O(N + M) = O({len(USERS)} + {len(ORDERS)}) = {len(USERS) + len(ORDERS)}\n", style="dim")
    summary.append(f"  vs Nested Loop: O(N × M) = {len(USERS) * len(ORDERS)}\n", style="dim")
    summary.append(
        "\n  Each probe is a hash lookup — O(1) on average.\n"
        "  The hash table must fit in memory (work_mem).\n"
        "  If it doesn't → multi-batch: spill to disk.\n",
        style="dim italic",
    )
    summary.append_text(_build_summary_matches(matches, extra_rows))

    frames.append(Panel(summary, title="[bold]Hash Join — Summary[/bold]", border_style="green", padding=(1, 2)))
    return frames


def _hash_table_column(hash_table, num_buckets, highlight_bucket, phase):
    col = Text()
    for b in range(num_buckets):
        entries = hash_table[b]
        is_target = b == highlight_bucket
        label = f"  [{b}] "

        if is_target:
            style = "bold yellow" if phase == "build" else "bold cyan"
            col.append(label, style=style)
        else:
            col.append(label, style="dim")

        if entries:
            parts = [f"{{{e['name']}, id={e['id']}}}" for e in entries]
            chain = " → ".join(parts)
            if is_target:
                col.append(chain, style=style)
                arrow = " ← inserting" if phase == "build" else " ← probe"
                col.append(arrow, style=style)
            else:
                col.append(chain, style="white dim")
        elif is_target:
            if phase == "probe":
                col.append("(empty)", style="bold red")
            else:
                col.append("(empty → inserting)", style="bold yellow")

        col.append("\n")
    return col


# ── Merge Join ──────────────────────────────────────────────────────────────


@join.command()
@_join_type_option
def merge(join_type):
    """Merge join: sort both sides, merge with two cursors."""
    frames = _build_merge_frames(join_type)
    _present(frames)


def _build_merge_frames(join_type="inner"):
    frames = []
    left = sorted(USERS, key=lambda u: u["id"])
    right = sorted(ORDERS, key=lambda o: o["user_id"])

    # Show the data first
    frames.append(_data_intro_frame(join_type))

    # Explain the strategy
    frames.append(_strategy_intro_frame("Merge Join",
        "\n  [bold]Strategy:[/bold] sort both sides by the join key,\n"
        "  then merge with two cursors in a single pass.\n\n"
        "  Rules:\n"
        "  • left.id [bold]<[/bold] right.uid  →  advance left cursor\n"
        "  • left.id [bold]>[/bold] right.uid  →  advance right cursor\n"
        "  • left.id [bold]=[/bold] right.uid  →  MATCH! emit the pair\n\n"
        "  [dim]Both inputs must be sorted first.\n"
        "  If they're already sorted (e.g., from an index),\n"
        "  the sort step is free.[/dim]\n"
        "\n"
        "  [bold yellow]When does the planner pick this?[/bold yellow]\n"
        "  When both sides are [bold]very large[/bold] and the data is\n"
        "  already [bold]sorted[/bold] (e.g., from an index scan), or when\n"
        "  the hash table would overflow work_mem. Also works\n"
        "  with [bold]range conditions[/bold] (<, >, ≤, ≥), unlike Hash Join.\n\n"
        "  [dim]Typical query:[/dim]\n"
        "  [cyan]SELECT * FROM users u\n"
        "  JOIN orders o ON o.user_id = u.id\n"
        "  ORDER BY u.id[/cyan]\n"
        "  [dim]→ both sides sorted by id, merge is a single pass[/dim]\n"
    ))

    matches = []
    comparisons = 0
    left_idx = 0
    right_idx = 0

    while left_idx < len(left) and right_idx < len(right):
        left_val: int = left[left_idx]["id"]
        right_val: int = right[right_idx]["user_id"]
        comparisons += 1

        if left_val < right_val:
            frame = _merge_frame(left, right, left_idx, right_idx, "advance_left", matches, comparisons)
            frames.append(frame)
            left_idx += 1
        elif left_val > right_val:
            frame = _merge_frame(left, right, left_idx, right_idx, "advance_right", matches, comparisons)
            frames.append(frame)
            right_idx += 1
        else:
            while right_idx < len(right) and right[right_idx]["user_id"] == left_val:
                matches.append((left[left_idx], right[right_idx]))
                comparisons += 1
                frame = _merge_frame(left, right, left_idx, right_idx, "match", matches, comparisons)
                frames.append(frame)
                right_idx += 1
            left_idx += 1

    # Join type: add unmatched rows
    unmatched_frames, extra_rows = _add_unmatched_frames(matches, join_type)
    frames.extend(unmatched_frames)

    # Summary
    type_label = join_type.upper()
    summary = Text()
    summary.append("\n  Done!\n\n", style="bold green")
    summary.append(f"  Join type:         {type_label} JOIN\n", style="white")
    summary.append(f"  Total comparisons: {comparisons}\n", style="white")
    summary.append(f"  Total matches:     {len(matches)}\n", style="green")
    if extra_rows:
        summary.append(f"  Unmatched rows:    {len(extra_rows)} (with NULLs)\n", style="yellow")
        summary.append(f"  Total result:      {len(matches) + len(extra_rows)} rows\n", style="bold white")
    summary.append(
        f"\n  Complexity: O(N log N + M log M + N + M)\n"
        f"    sort left:  {len(USERS)} rows\n"
        f"    sort right: {len(ORDERS)} rows\n"
        f"    merge pass: {comparisons} comparisons (single forward pass)\n",
        style="dim",
    )
    summary.append(
        "\n  Cursors only move forward — no backtracking.\n"
        "  Pre-sorted inputs skip the sort step entirely.\n"
        "  Efficient when both sides are very large.\n",
        style="dim italic",
    )
    summary.append_text(_build_summary_matches(matches, extra_rows))

    frames.append(Panel(summary, title="[bold]Merge Join — Summary[/bold]", border_style="green", padding=(1, 2)))
    return frames


def _merge_frame(left, right, left_idx, right_idx, action, matches, comparisons):
    left_val = left[left_idx]["id"]
    right_val = right[right_idx]["user_id"]

    # Left column
    left_col = Text()
    for i, u in enumerate(left):
        label = f"id={u['id']:<4} {u['name']}"
        if i == left_idx:
            left_col.append(f"  ► {label}\n", style="bold yellow")
        elif i < left_idx:
            left_col.append(f"    {label}\n", style="dim")
        else:
            left_col.append(f"    {label}\n", style="white dim")

    # Right column
    right_col = Text()
    matched_order_ids = {m[1]["id"] for m in matches}
    for i, o in enumerate(right):
        label = f"uid={o['user_id']:<4} ${o['amount']:>3}"
        if i == right_idx:
            if action == "match":
                right_col.append(f"  ► {label}  ✓\n", style="bold green")
            else:
                right_col.append(f"  ► {label}\n", style="bold cyan")
        elif i < right_idx:
            if o["id"] in matched_order_ids:
                right_col.append(f"  ✓ {label}\n", style="green dim")
            else:
                right_col.append(f"    {label}\n", style="dim")
        else:
            right_col.append(f"    {label}\n", style="white dim")

    match_col = _match_column(matches, highlight_last=(action == "match"))

    layout = _three_col_layout(
        [("Left — sorted", "bold yellow"),
         ("Right — sorted", "bold cyan"),
         ("Matches", "bold green")],
        [left_col, right_col, match_col],
    )

    status = Text()
    if action == "match":
        status.append(f"\n  left.id ({left_val}) = right.uid ({right_val}) → ", style="white")
        status.append("MATCH! ✓", style="bold green")
    elif action == "advance_left":
        status.append(f"\n  left.id ({left_val}) < right.uid ({right_val}) → ", style="white")
        status.append("advance left cursor ↓", style="yellow")
    elif action == "advance_right":
        status.append(f"\n  left.id ({left_val}) > right.uid ({right_val}) → ", style="white")
        status.append("advance right cursor ↓", style="cyan")

    status.append(f"\n\n  Comparisons: {comparisons}   Matches: {len(matches)}", style="dim")

    return Panel(
        Group(layout, status),
        title="[bold]Merge Join[/bold]",
        border_style="cyan",
        padding=(1, 1),
    )
