import psycopg
from psycopg.rows import dict_row


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row)


def fetch_page_header(conn: psycopg.Connection, table: str, page: int) -> dict:
    return conn.execute(
        "SELECT * FROM page_header(get_raw_page(%s, %s))", (table, page)
    ).fetchone()


def fetch_heap_items(conn: psycopg.Connection, table: str, page: int) -> list[dict]:
    return conn.execute(
        "SELECT * FROM heap_page_items(get_raw_page(%s, %s))", (table, page)
    ).fetchall()


def fetch_tuple_data(
    conn: psycopg.Connection, table: str, page: int, items: list[dict]
) -> dict[int, dict]:
    """Fetch decoded row values for tuples on a page via ctid."""
    active_lps = [item["lp"] for item in items if item["lp_off"] > 0]
    if not active_lps:
        return {}

    ctid_array = ", ".join(f"'({page},{lp})'::tid" for lp in active_lps)
    rows = conn.execute(
        f"SELECT ctid, * FROM {table} WHERE ctid = ANY(ARRAY[{ctid_array}])"  # noqa: S608
    ).fetchall()

    results = {}
    for row in rows:
        ctid_str = str(row.pop("ctid"))
        # ctid comes as "(page,item)" string
        item_num = int(ctid_str.strip("()").split(",")[1])
        results[item_num] = row
    return results


def fetch_relation_info(conn: psycopg.Connection, table: str) -> dict:
    return conn.execute(
        """
        SELECT pg_relation_filepath(%s) AS filepath,
               pg_relation_size(%s) AS size_bytes,
               pg_relation_size(%s) / 8192 AS num_pages
        """,
        (table, table, table),
    ).fetchone()


def fetch_freespace(conn: psycopg.Connection, table: str) -> list[dict]:
    conn.execute("CREATE EXTENSION IF NOT EXISTS pg_freespacemap")
    return conn.execute(
        "SELECT blkno, avail FROM pg_freespace(%s) ORDER BY blkno",
        (table,),
    ).fetchall()


def fetch_fsm_page(conn: psycopg.Connection, table: str, fsm_page: int) -> list[tuple[int, int]]:
    """Read raw FSM page and return (slot, value) pairs."""
    row = conn.execute(
        "SELECT fsm_page_contents(get_raw_page(%s, 'fsm', %s))",
        (table, fsm_page),
    ).fetchone()
    contents = row["fsm_page_contents"]
    entries = []
    for line in contents.strip().split("\n"):
        line = line.strip()
        if line.startswith("fp_next_slot") or not line:
            continue
        slot_str, val_str = line.split(":")
        entries.append((int(slot_str.strip()), int(val_str.strip())))
    return entries


def fetch_visibility_map(conn: psycopg.Connection, table: str) -> list[dict]:
    return conn.execute(
        """
        SELECT blkno, all_visible, all_frozen
        FROM pg_visibility(%s)
        ORDER BY blkno
        """,
        (table,),
    ).fetchall()
