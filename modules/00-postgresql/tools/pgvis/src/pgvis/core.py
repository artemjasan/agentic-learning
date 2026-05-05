import psycopg
from psycopg.rows import dict_row
from rich.console import Console

console = Console()

PAGE_SIZE = 8192

DEFAULT_DSN = "postgresql://study:study@localhost:5433/study"


def connect(dsn: str, *, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=autocommit)
