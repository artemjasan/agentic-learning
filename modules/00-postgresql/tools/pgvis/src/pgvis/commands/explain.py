"""EXPLAIN ANALYZE with step-by-step annotations."""

import json

import click
from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from pgvis.core import connect, console


NODE_DESCRIPTIONS = {
    "Seq Scan": "Reads every page of the table sequentially, checks each tuple against the filter condition.",
    "Index Scan": "Walks a B-tree index to find matching entries, then fetches each heap tuple by its physical address (random I/O per tuple).",
    "Index Only Scan": "Answers entirely from the index without touching the heap. Only works when all needed columns are in the index and pages are marked all-visible.",
    "Bitmap Heap Scan": "Reads heap pages in physical order using a pre-built bitmap. Converts random I/O into sequential.",
    "Bitmap Index Scan": "Scans the index to collect page numbers of matching entries. Builds a bitmap — doesn't read the heap yet.",
    "BitmapAnd": "Combines multiple bitmaps with AND — only pages in all bitmaps survive.",
    "BitmapOr": "Combines multiple bitmaps with OR — pages from any bitmap are included.",
    "Nested Loop": "For each row from the outer side, runs the inner side once to find matches. Best when outer is small and inner has an index.",
    "Hash Join": "Builds a hash table from the smaller side (build), then probes it with each row from the larger side (probe). Needs equality condition.",
    "Merge Join": "Sorts both sides by the join key, then merges in a single pass. Efficient when inputs are pre-sorted or very large.",
    "Sort": "Sorts rows. Uses quicksort in memory if it fits in work_mem, external merge sort on disk if not.",
    "Incremental Sort": "Sorts on additional keys when input is already sorted on leading keys.",
    "Aggregate": "Computes aggregate functions (count, sum, avg, etc.) over all input rows.",
    "HashAggregate": "Groups rows by hashing the GROUP BY keys. Each group is a hash table entry.",
    "GroupAggregate": "Groups pre-sorted rows and computes aggregates per group.",
    "Limit": "Stops returning rows after reaching the specified count.",
    "Result": "Returns a constant or evaluates an expression without scanning a table.",
    "Materialize": "Stores results in memory so they can be re-scanned by a parent node.",
    "Memoize": "Caches inner-side results keyed by outer-side values. Avoids re-executing for repeated keys.",
    "Gather": "Collects rows from parallel worker processes.",
    "Gather Merge": "Merge-sorts pre-sorted rows from parallel workers.",
    "Append": "Concatenates results from multiple sub-plans (UNION ALL, partitioned tables).",
    "Unique": "Removes consecutive duplicate rows from sorted input.",
    "Subquery Scan": "Wraps a subquery result as a scan source.",
    "CTE Scan": "Scans a materialized Common Table Expression (WITH clause).",
    "Hash": "Builds a hash table for use by a Hash Join parent node.",
    "WindowAgg": "Computes window functions (ROW_NUMBER, RANK, etc.) over partitioned/ordered input.",
    "SetOp": "Implements set operations (INTERSECT, EXCEPT) on sorted inputs.",
}

CONDITION_EXPLANATIONS = {
    "Filter": "applied to every tuple after reading — rows that don't match are discarded",
    "Index Cond": "pushed into the index — navigates the B-tree directly to matching entries",
    "Recheck Cond": "rechecked on each heap tuple because the bitmap only tracks page numbers, not rows",
    "Join Filter": "checked on each joined pair — non-matching pairs discarded",
    "Hash Cond": "equality condition used to build and probe the hash table",
    "Merge Cond": "condition used to match rows during the merge pass",
    "One-Time Filter": "evaluated once — if false, the entire subtree is skipped",
}

OUTER_DESCRIPTIONS = {
    "Nested Loop": "drives the loop — scanned first, one row at a time",
    "Hash Join": "probe side — each row looks up the hash table",
    "Merge Join": "first sorted input to the merge",
}

INNER_DESCRIPTIONS = {
    "Nested Loop": "runs once per outer row to find matches",
    "Hash Join": "build side — loaded entirely into a hash table first",
    "Merge Join": "second sorted input to the merge",
}


@click.command()
@click.argument("query")
@click.pass_context
def explain(ctx, query):
    """Run EXPLAIN ANALYZE on a query and annotate each node step by step."""
    dsn = ctx.obj["dsn"]

    with connect(dsn, autocommit=True) as conn:
        text_plan = _run_text_explain(conn, query)
        plan_json = _run_json_explain(conn, query)
        cost_consts = _fetch_cost_constants(conn)

        relations = _collect_relations(plan_json["Plan"])
        table_stats = _fetch_table_stats(conn, relations)

    # Full plan
    console.print()
    console.print(Panel(
        Text(text_plan),
        title="[bold cyan]Full Query Plan[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))

    # Parse text into per-node segments (pre-order)
    segments = _parse_text_segments(text_plan)
    preorder = _collect_preorder(plan_json["Plan"])

    seg_map = {}
    for i, node in enumerate(preorder):
        if i < len(segments):
            seg_map[id(node)] = segments[i]

    # Execution order (post-order) with group labels
    exec_order = _collect_execution_order(plan_json["Plan"])
    total_steps = len(exec_order)

    # Show execution order rationale for joins
    _show_execution_intro(plan_json["Plan"])

    current_group = None
    for step, node in enumerate(exec_order, 1):
        group = node.get("_group")
        join_type = node.get("_join_type", "")

        if group != current_group:
            current_group = group
            _show_group_header(group, join_type, node)

        segment = seg_map.get(id(node), "")
        _show_step(node, step, total_steps, segment, cost_consts, table_stats)

        if step < total_steps:
            _show_connector(node, exec_order, step)

    # Summary
    _show_summary(plan_json)


# ── Data fetching ───────────────────────────────────────────────────────────


def _run_text_explain(conn, query):
    rows = conn.execute(f"EXPLAIN (ANALYZE, BUFFERS) {query}").fetchall()
    return "\n".join(r["QUERY PLAN"] for r in rows)


def _run_json_explain(conn, query):
    rows = conn.execute(
        f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
    ).fetchall()
    data = rows[0]["QUERY PLAN"]
    if isinstance(data, str):
        data = json.loads(data)
    return data[0]


def _fetch_cost_constants(conn):
    names = [
        "seq_page_cost", "random_page_cost", "cpu_tuple_cost",
        "cpu_operator_cost", "cpu_index_tuple_cost",
    ]
    result = {}
    for name in names:
        row = conn.execute(f"SHOW {name}").fetchone()
        result[name] = float(list(row.values())[0])
    return result


def _collect_relations(node):
    rels = set()
    if node.get("Relation Name"):
        rels.add(node["Relation Name"])
    for child in node.get("Plans", []):
        rels.update(_collect_relations(child))
    return rels


def _fetch_table_stats(conn, relations):
    stats = {}
    for rel in relations:
        row = conn.execute(
            "SELECT relpages, reltuples FROM pg_class WHERE relname = %s", [rel],
        ).fetchone()
        if row:
            stats[rel] = row
    return stats


# ── Text parsing ────────────────────────────────────────────────────────────


def _parse_text_segments(text_plan):
    """Split the text plan into one segment per node, in pre-order."""
    lines = text_plan.split("\n")
    segments = []
    current = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith(("Planning Time:", "Planning:", "Execution Time:")):
            break

        is_new_node = stripped.startswith("->")
        if not segments and not current:
            is_new_node = True

        if is_new_node and current:
            segments.append("\n".join(current))
            current = []

        current.append(line)

    if current:
        segments.append("\n".join(current))

    return segments


# ── Tree traversal ──────────────────────────────────────────────────────────


def _collect_preorder(node):
    result = [node]
    for child in node.get("Plans", []):
        result.extend(_collect_preorder(child))
    return result


def _collect_execution_order(node, group=None, join_type=None):
    """Post-order traversal with group/join metadata on each node.

    For Hash Join, the inner (build) side runs before the outer (probe) side,
    so we process children in that order.
    """
    result = []
    node_type = node.get("Node Type", "")
    is_join = node_type in ("Nested Loop", "Hash Join", "Merge Join")

    children = list(node.get("Plans", []))

    # Hash Join: build side (Inner) must finish before probe side (Outer)
    if node_type == "Hash Join":
        inner_first = [c for c in children if c.get("Parent Relationship") == "Inner"]
        outer_second = [c for c in children if c.get("Parent Relationship") == "Outer"]
        rest = [c for c in children if c.get("Parent Relationship") not in ("Inner", "Outer")]
        children = inner_first + outer_second + rest

    for child in children:
        rel = child.get("Parent Relationship", "")
        if is_join:
            child_group = (
                "OUTER" if rel == "Outer"
                else "INNER" if rel == "Inner"
                else group
            )
            child_join = node_type
        else:
            child_group = group
            child_join = join_type
        result.extend(_collect_execution_order(child, child_group, child_join))

    node["_group"] = "JOIN" if is_join else group
    node["_join_type"] = node_type if is_join else join_type
    result.append(node)
    return result


def _find_join_type(node):
    """Find the primary join node type in the plan tree."""
    node_type = node.get("Node Type", "")
    if node_type in ("Nested Loop", "Hash Join", "Merge Join"):
        return node_type
    for child in node.get("Plans", []):
        found = _find_join_type(child)
        if found:
            return found
    return None


def _show_execution_intro(plan_root):
    join_type = _find_join_type(plan_root)
    if not join_type:
        console.print()
        return

    intro = Text()

    if join_type == "Hash Join":
        intro.append("\n  Execution order: ", style="bold")
        intro.append("inner (build) → outer (probe) → join\n", style="white")
        intro.append(
            "  The hash table must be fully built before probing can begin,\n"
            "  so the inner side runs first.\n",
            style="dim",
        )
    elif join_type == "Nested Loop":
        intro.append("\n  Execution order: ", style="bold")
        intro.append("outer → inner (per row) → join\n", style="white")
        intro.append(
            "  The outer side produces one row, then the inner side runs\n"
            "  to find matches for that row. Repeats for each outer row.\n",
            style="dim",
        )
    elif join_type == "Merge Join":
        intro.append("\n  Execution order: ", style="bold")
        intro.append("sort both sides → merge\n", style="white")
        intro.append(
            "  Both sides are sorted, then merged in a single pass.\n",
            style="dim",
        )

    console.print(Panel(
        intro,
        border_style="yellow",
        padding=(0, 2),
    ))


# ── Rendering ───────────────────────────────────────────────────────────────


def _show_group_header(group, join_type, first_node):
    if not group:
        return

    if group == "OUTER":
        desc = OUTER_DESCRIPTIONS.get(join_type, "")
    elif group == "INNER":
        desc = INNER_DESCRIPTIONS.get(join_type, "")
        loops = first_node.get("Actual Loops", 1)
        if loops > 1:
            desc += f" — ×{loops} loops"
    elif group == "JOIN":
        desc = "combining results"
    else:
        return

    label = f" {group} "
    if desc:
        label += f"— {desc} "

    console.print()
    console.print(Rule(label, style="bold yellow"))


def _show_step(node, step, total, segment, cost_consts, table_stats):
    node_type = node.get("Node Type", "")
    desc = NODE_DESCRIPTIONS.get(node_type, "")
    relation = node.get("Relation Name", "")
    alias = node.get("Alias", "")
    index_name = node.get("Index Name", "")

    # Title
    parts = [f"Step {step}/{total}", node_type]
    if relation:
        r = relation
        if alias and alias != relation:
            r += f" ({alias})"
        parts.append(f"on {r}")
    if index_name:
        parts.append(f"using {index_name}")
    title = "  ".join(parts)

    # Explain text block
    explain_block = Text()
    if segment:
        for line in segment.split("\n"):
            cleaned = line.strip()
            if cleaned.startswith("->"):
                cleaned = cleaned[2:].strip()
            explain_block.append("  ┃ ", style="cyan")
            explain_block.append(cleaned + "\n")

    # Description
    desc_block = Text()
    if desc:
        desc_block.append(f"\n  {desc}\n", style="italic dim")

    # Details table
    details = _build_details_table(node, cost_consts, table_stats)

    # Why this strategy?
    strategy = _explain_strategy(node, cost_consts, table_stats)

    # Output line
    output = _build_output_line(node, step, total)

    renderables = [explain_block, desc_block, Text(), details]
    if strategy:
        renderables.append(Text())
        renderables.append(strategy)
    if output:
        renderables.append(Text())
        renderables.append(output)

    console.print(Panel(
        Group(*renderables),
        title=f"[bold cyan]{title}[/bold cyan]",
        border_style="blue",
        padding=(1, 2),
    ))


def _build_details_table(node, cost_consts, table_stats):
    table = Table(
        show_header=False, box=box.SIMPLE_HEAVY,
        padding=(0, 1), pad_edge=True, expand=True,
    )
    table.add_column("key", style="bold", width=16, no_wrap=True)
    table.add_column("value")

    node_type = node.get("Node Type", "")

    # Conditions
    for cond_key, cond_desc in CONDITION_EXPLANATIONS.items():
        cond_val = node.get(cond_key)
        if cond_val:
            val = Text()
            val.append(str(cond_val) + "\n", style="white")
            val.append(cond_desc, style="dim italic")
            table.add_row(cond_key, val)

    # Rows
    est = node.get("Plan Rows", 0)
    act = node.get("Actual Rows", 0)
    loops = node.get("Actual Loops", 1)

    row_val = Text()
    row_val.append(f"estimated {est:,}", style="white")
    row_val.append(" → ", style="dim")
    row_val.append(f"actual {act:,.0f}", style="bold white")
    if loops > 1:
        row_val.append(f" × {loops} loops = {act * loops:,.0f} total", style="dim")
    if est > 0 and act > 0:
        ratio = act / est
        if ratio > 2 or ratio < 0.5:
            row_val.append(
                f"\n⚠ estimate is {abs(ratio - 1) * 100:.0f}% off!", style="bold red",
            )
    removed = node.get("Rows Removed by Filter", 0)
    if removed:
        row_val.append(f"\n{removed:,.0f} rows read but discarded by filter", style="dim")
    table.add_row("Rows", row_val)

    # Width
    width = node.get("Plan Width", 0)
    width_val = Text()
    if width > 0:
        width_val.append(f"{width} bytes per row", style="white")
    elif node_type == "Bitmap Index Scan":
        width_val.append("0 bytes", style="white")
        width_val.append(" — produces page numbers, not row data", style="dim")
    else:
        width_val.append(f"{width} bytes", style="white")
    table.add_row("Width", width_val)

    # Cost
    startup = node.get("Startup Cost", 0)
    total_cost = node.get("Total Cost", 0)

    cost_val = Text()
    cost_val.append(f"{startup:.2f}", style="white")
    cost_val.append(" startup → ", style="dim")
    cost_val.append(f"{total_cost:.2f}", style="bold white")
    cost_val.append(" total", style="dim")

    cost_lines = _explain_cost(node, cost_consts, table_stats)
    if cost_lines:
        cost_val.append("\n")
        for cl in cost_lines:
            cost_val.append(cl + "\n", style="dim")

    table.add_row("Cost", cost_val)

    # Time
    act_start = node.get("Actual Startup Time")
    act_total = node.get("Actual Total Time")
    if act_start is not None:
        time_val = Text()
        time_val.append(f"{act_start:.3f}ms", style="white")
        time_val.append(" to first row → ", style="dim")
        time_val.append(f"{act_total:.3f}ms", style="bold white")
        time_val.append(" total", style="dim")
        if loops > 1:
            time_val.append(
                f"\n{act_total * loops:.3f}ms across all {loops} loops", style="dim",
            )
        table.add_row("Time", time_val)

    # Buffers
    hit = node.get("Shared Hit Blocks", 0)
    read = node.get("Shared Read Blocks", 0)
    if hit or read:
        buf_val = Text()
        parts = []
        if hit:
            parts.append(f"{hit:,} from cache")
        if read:
            parts.append(f"{read:,} from disk")
        buf_val.append(" + ".join(parts), style="white")
        total_pages = hit + read
        buf_val.append(f"  = {total_pages:,} pages", style="dim")
        if total_pages >= 128:
            buf_val.append(f" ({total_pages * 8 / 1024:.1f} MB)", style="dim")
        table.add_row("Buffers", buf_val)

    # Heap Blocks (bitmap scan)
    exact_blocks = node.get("Exact Heap Blocks")
    lossy_blocks = node.get("Lossy Heap Blocks")
    if exact_blocks or lossy_blocks:
        hb_val = Text()
        if exact_blocks:
            hb_val.append(f"{exact_blocks:,} exact", style="white")
            hb_val.append(
                " — bitmap tracked individual pages", style="dim",
            )
        if lossy_blocks:
            if exact_blocks:
                hb_val.append(" + ")
            hb_val.append(f"{lossy_blocks:,} lossy", style="yellow")
            hb_val.append(
                " — not enough memory, tracking page ranges only", style="dim",
            )
        table.add_row("Heap Blocks", hb_val)

    # Sort info
    sort_method = node.get("Sort Method")
    if sort_method:
        sort_val = Text()
        sort_val.append(sort_method, style="bold white")
        space = node.get("Sort Space Used", 0)
        space_type = node.get("Sort Space Type", "")
        if space:
            sort_val.append(f"  {space}kB {space_type}", style="white")
        if "disk" in sort_method.lower() or space_type.lower() == "disk":
            sort_val.append(
                "\n⚠ overflowed work_mem — spilled to disk!", style="bold red",
            )
        table.add_row("Sort", sort_val)

    # Hash info
    batches = node.get("Hash Batches")
    if batches is not None:
        hash_val = Text()
        buckets = node.get("Hash Buckets", 0)
        peak = node.get("Peak Memory Usage", 0)
        hash_val.append(f"{buckets:,} buckets, {batches} batch(es)", style="white")
        if peak:
            hash_val.append(f", {peak}kB peak memory", style="white")
        if batches > 1:
            hash_val.append(
                "\n⚠ multiple batches — overflowed work_mem!", style="bold red",
            )
        table.add_row("Hash", hash_val)

    # Loops
    loop_val = Text()
    loop_val.append(f"{loops}", style="white")
    if loops > 1:
        loop_val.append(" — this node ran multiple times", style="dim")
    else:
        loop_val.append(" — ran once", style="dim")
    table.add_row("Loops", loop_val)

    return table


def _explain_cost(node, cost_consts, table_stats):
    node_type = node.get("Node Type", "")
    relation = node.get("Relation Name", "")
    lines = []

    spc = cost_consts["seq_page_cost"]
    rpc = cost_consts["random_page_cost"]
    ctc = cost_consts["cpu_tuple_cost"]
    coc = cost_consts["cpu_operator_cost"]

    if node_type == "Seq Scan" and relation in table_stats:
        stats = table_stats[relation]
        rp = int(stats["relpages"])
        rt = stats["reltuples"]

        page_cost = spc * rp
        tuple_cost = ctc * rt

        lines.append("")
        lines.append(f"  seq_page_cost × pages     = {spc} × {rp} = {page_cost:.2f}")
        lines.append(f"  cpu_tuple_cost × tuples   = {ctc} × {rt:.0f} = {tuple_cost:.2f}")

        has_filter = node.get("Filter") is not None
        if has_filter:
            op_cost = coc * rt
            lines.append(
                f"  cpu_operator_cost × tuples = {coc} × {rt:.0f} = {op_cost:.2f}",
            )
            total = page_cost + tuple_cost + op_cost
        else:
            total = page_cost + tuple_cost

        lines.append(f"  {'─' * 42}")
        lines.append(f"  = {total:.2f}")

    elif node_type == "Index Scan":
        est_rows = node.get("Plan Rows", 0)
        lines.append("")
        lines.append(f"  B-tree traversal + random heap page fetches")
        lines.append(f"  random_page_cost = {rpc} per heap page")
        if est_rows <= 10:
            lines.append(f"  ~{est_rows} rows × {rpc} random fetch + index + CPU")

    elif node_type == "Index Only Scan":
        lines.append("")
        lines.append("  B-tree traversal only (no heap when pages all-visible)")

    elif node_type == "Bitmap Index Scan":
        lines.append("")
        lines.append("  index traversal to build page bitmap")

    elif node_type == "Bitmap Heap Scan":
        lines.append("")
        lines.append("  startup ≈ child's total cost (wait for bitmap)")
        lines.append("  + sequential heap page reads + recheck per tuple")

    elif node_type == "Nested Loop":
        lines.append("")
        lines.append("  = outer cost + (inner cost × outer rows)")

    elif node_type == "Hash Join":
        lines.append("")
        lines.append("  = hash table build cost + probe cost per outer row")

    elif node_type == "Merge Join":
        lines.append("")
        lines.append("  = sort both sides (if needed) + single merge pass")

    elif node_type == "Sort":
        lines.append("")
        lines.append("  comparison cost ∝ N × log₂(N)")

    elif node_type == "Hash":
        lines.append("")
        lines.append("  hash table construction from input rows")

    elif node_type == "Limit":
        est = node.get("Plan Rows", 0)
        lines.append("")
        lines.append(f"  stops after {est:,} rows — avoids producing entire result")

    elif node_type == "Aggregate":
        lines.append("")
        lines.append("  CPU cost to process each input row through aggregate functions")

    elif node_type == "HashAggregate":
        lines.append("")
        lines.append("  build hash table keyed on GROUP BY columns")

    elif node_type == "GroupAggregate":
        lines.append("")
        lines.append("  stream through sorted groups, aggregate each")

    return lines


def _explain_strategy(node, cost_consts, table_stats):
    """Explain why the planner chose this strategy over alternatives."""
    node_type = node.get("Node Type", "")
    relation = node.get("Relation Name", "")
    est_rows = node.get("Plan Rows", 0)
    rpc = cost_consts["random_page_cost"]

    text = Text()

    if node_type == "Seq Scan" and relation in table_stats:
        stats = table_stats[relation]
        reltuples = stats["reltuples"]
        relpages = int(stats["relpages"])

        if reltuples > 0:
            selectivity = est_rows / reltuples
        else:
            selectivity = 1.0

        text.append("  Why Seq Scan? ", style="bold yellow")
        if relpages <= 10:
            text.append(
                f"Table is small ({relpages} pages). "
                "Index overhead isn't worth it for a tiny table.",
                style="dim",
            )
        elif selectivity > 0.15:
            pct = selectivity * 100
            text.append(
                f"~{pct:.0f}% of rows match. Reading all {relpages:,} pages "
                f"sequentially (cost {relpages:,}) is cheaper than "
                f"~{est_rows:,} random fetches (cost ~{est_rows * rpc:,.0f}).",
                style="dim",
            )
        else:
            text.append(
                f"No usable index on the filtered column, "
                f"or planner estimated seq scan as cheapest.",
                style="dim",
            )

    elif node_type == "Index Scan" and relation in table_stats:
        stats = table_stats[relation]
        reltuples = stats["reltuples"]

        if reltuples > 0:
            selectivity = est_rows / reltuples
        else:
            selectivity = 0

        text.append("  Why Index Scan? ", style="bold yellow")
        if est_rows <= 1:
            text.append(
                "Looking for 1 row. B-tree navigates directly — "
                "a few pages instead of the whole table.",
                style="dim",
            )
        else:
            pct = selectivity * 100
            text.append(
                f"Only ~{pct:.1f}% of rows match ({est_rows:,} rows). "
                f"Few enough that {est_rows:,} random fetches "
                f"beat scanning all {int(stats['relpages']):,} pages.",
                style="dim",
            )

    elif node_type == "Bitmap Heap Scan" and relation in table_stats:
        stats = table_stats[relation]
        reltuples = stats["reltuples"]
        relpages = int(stats["relpages"])

        if reltuples > 0:
            selectivity = est_rows / reltuples
        else:
            selectivity = 0

        pct = selectivity * 100
        text.append("  Why Bitmap Scan? ", style="bold yellow")
        text.append(
            f"~{pct:.1f}% of rows match ({est_rows:,} rows). "
            f"Too many for Index Scan ({est_rows:,} random fetches × "
            f"{rpc} = ~{est_rows * rpc:,.0f} cost), "
            f"too few for Seq Scan (would read all {relpages:,} pages). "
            f"Bitmap reads only the matching pages, in physical order.",
            style="dim",
        )

    elif node_type == "Index Only Scan":
        text.append("  Why Index Only Scan? ", style="bold yellow")
        text.append(
            "All columns the query needs are in the index. "
            "Skips the heap entirely when pages are all-visible.",
            style="dim",
        )

    elif node_type == "Nested Loop":
        children = node.get("Plans", [])
        outer_rows = 0
        for child in children:
            if child.get("Parent Relationship") == "Outer":
                outer_rows = child.get("Plan Rows", 0)

        text.append("  Why Nested Loop? ", style="bold yellow")
        if outer_rows <= 1:
            text.append(
                f"Outer side returns ~{outer_rows} row. "
                "One row means one inner lookup — simplest and fastest.",
                style="dim",
            )
        else:
            text.append(
                f"Outer side returns ~{outer_rows:,} rows. "
                "With an index on the inner side, each lookup is fast.",
                style="dim",
            )

    elif node_type == "Hash Join":
        children = node.get("Plans", [])
        build_rows = probe_rows = 0
        for child in children:
            if child.get("Parent Relationship") == "Inner":
                build_rows = child.get("Plan Rows", 0)
            elif child.get("Parent Relationship") == "Outer":
                probe_rows = child.get("Plan Rows", 0)

        text.append("  Why Hash Join? ", style="bold yellow")
        text.append(
            f"Build side: ~{build_rows:,} rows (fits in a hash table). "
            f"Probe side: ~{probe_rows:,} rows. "
            f"One pass through each side beats "
            f"{probe_rows:,} nested index lookups.",
            style="dim",
        )

    elif node_type == "Merge Join":
        text.append("  Why Merge Join? ", style="bold yellow")
        text.append(
            "Both sides are large or pre-sorted. "
            "Sort + merge is efficient when neither side is small "
            "enough for a hash table.",
            style="dim",
        )

    else:
        return None

    return text


def _build_output_line(node, step, total):
    node_type = node.get("Node Type", "")
    act_rows = node.get("Actual Rows", 0)
    group = node.get("_group")

    output = Text()

    if step == total:
        output.append(f"  ➜ {act_rows:,.0f} result row(s) returned to client", style="green bold")
        return output

    if node_type == "Bitmap Index Scan":
        output.append("  ➜ bitmap of page numbers → next step reads those pages", style="yellow")
    elif node_type == "Hash":
        output.append("  ➜ hash table ready for probing", style="yellow")
    elif group == "OUTER":
        output.append(f"  ➜ {act_rows:,.0f} row(s) drive the join", style="yellow")
    elif group == "INNER":
        output.append(f"  ➜ {act_rows:,.0f} row(s) matched → combined with outer side", style="yellow")
    elif group == "JOIN":
        output.append(f"  ➜ {act_rows:,.0f} joined row(s) → next step", style="yellow")
    else:
        output.append(f"  ➜ {act_rows:,.0f} row(s) → next step", style="yellow")

    return output


def _show_connector(_node, _exec_order, _step_idx):
    """Show arrow between steps."""
    console.print(Text("                          │", style="dim"))
    console.print(Text("                          ▼", style="dim"))
    console.print()


def _show_summary(plan_json):
    planning_time = plan_json.get("Planning Time", 0)
    execution_time = plan_json.get("Execution Time", 0)

    planning = plan_json.get("Planning", {})
    plan_hit = planning.get("Shared Hit Blocks", 0)
    plan_read = planning.get("Shared Read Blocks", 0)

    plan = plan_json.get("Plan", {})
    total_hit = plan.get("Shared Hit Blocks", 0)
    total_read = plan.get("Shared Read Blocks", 0)
    act_rows = plan.get("Actual Rows", 0)
    width = plan.get("Plan Width", 0)

    summary = Text()
    summary.append("  Planning     ", style="dim")
    summary.append(f"{planning_time:.3f}ms", style="white")
    if plan_hit or plan_read:
        summary.append(f"  ({plan_hit} cache + {plan_read} disk)", style="dim")
    summary.append("\n")
    summary.append("  Execution    ", style="dim")
    summary.append(f"{execution_time:.3f}ms", style="bold white")
    summary.append("\n")
    total_pages = total_hit + total_read
    summary.append("  Pages        ", style="dim")
    summary.append(f"{total_pages:,} total", style="white")
    if total_hit and total_read:
        summary.append(f"  ({total_hit:,} cache + {total_read:,} disk)", style="dim")
    elif total_hit:
        summary.append("  (all from cache)", style="dim")
    elif total_read:
        summary.append("  (all from disk)", style="dim")
    summary.append("\n")
    summary.append("  Result       ", style="dim")
    summary.append(f"{act_rows:,.0f} rows, {width} bytes each", style="white")

    console.print()
    console.print(Panel(
        summary,
        title="[bold green]Summary[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))
