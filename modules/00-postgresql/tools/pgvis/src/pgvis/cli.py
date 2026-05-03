import click

from pgvis.db import (
    connect,
    fetch_freespace,
    fetch_heap_items,
    fetch_page_header,
    fetch_relation_info,
    fetch_tuple_data,
    fetch_visibility_map,
)
from pgvis.render import console, render_fsm, render_fsm_tree, render_page, render_vm

DEFAULT_DSN = "postgresql://study:study@localhost:5433/study"


@click.group()
@click.option("--dsn", default=DEFAULT_DSN, envvar="PGVIS_DSN", help="PostgreSQL connection string.")
@click.pass_context
def cli(ctx, dsn: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["dsn"] = dsn


@cli.command()
@click.argument("table")
@click.argument("page_num", type=int)
@click.option("--no-data", is_flag=True, help="Skip fetching decoded row data.")
@click.option("--all", "show_all", is_flag=True, help="Show all tuples instead of preview.")
@click.pass_context
def page(ctx, table: str, page_num: int, no_data: bool, show_all: bool) -> None:
    """Visualize a heap page: header, item pointers, tuples."""
    dsn = ctx.obj["dsn"]

    with connect(dsn) as conn:
        info = fetch_relation_info(conn, table)
        if page_num >= info["num_pages"]:
            console.print(
                f"[red]Page {page_num} out of range. "
                f"Table '{table}' has {info['num_pages']} pages (0-{info['num_pages'] - 1}).[/red]"
            )
            raise SystemExit(1)

        console.print(
            f"\n[bold]{table}[/bold] — "
            f"{info['size_bytes']} bytes, {info['num_pages']} pages "
            f"({info['filepath']})\n"
        )

        header = fetch_page_header(conn, table, page_num)
        items = fetch_heap_items(conn, table, page_num)

        tuple_data = {}
        if not no_data:
            tuple_data = fetch_tuple_data(conn, table, page_num, items)

        render_page(header, items, tuple_data, show_all=show_all)


@cli.command()
@click.argument("table")
@click.option("--tree", is_flag=True, help="Show the FSM as a binary search tree.")
@click.pass_context
def fsm(ctx, table: str, tree: bool) -> None:
    """Visualize the Free Space Map: free bytes per page."""
    with connect(ctx.obj["dsn"]) as conn:
        info = fetch_relation_info(conn, table)
        console.print(
            f"\n[bold]{table}[/bold] — "
            f"{info['size_bytes']} bytes, {info['num_pages']} pages\n"
        )
        freespace = fetch_freespace(conn, table)
        if tree:
            render_fsm_tree(table, freespace)
        else:
            render_fsm(table, freespace, info)


@cli.command()
@click.argument("table")
@click.pass_context
def vm(ctx, table: str) -> None:
    """Visualize the Visibility Map: all-visible and all-frozen flags."""
    with connect(ctx.obj["dsn"]) as conn:
        info = fetch_relation_info(conn, table)
        console.print(
            f"\n[bold]{table}[/bold] — "
            f"{info['size_bytes']} bytes, {info['num_pages']} pages\n"
        )
        visibility = fetch_visibility_map(conn, table)
        render_vm(table, visibility)
