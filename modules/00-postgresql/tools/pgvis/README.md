# pgvis — PostgreSQL Internals Visualizer

CLI tool for visualizing PostgreSQL internal data structures. Built for the [PostgreSQL deep dive](../../STUDY.md) study module.

## Setup

```bash
uv sync
```

## Usage

```bash
# Heap page layout (header, item pointers, tuples)
uv run pgvis page <table> <page_number>
uv run pgvis page <table> <page_number> --all      # show all tuples
uv run pgvis page <table> <page_number> --no-data   # skip row data decoding

# Free Space Map
uv run pgvis fsm <table>          # bar chart per page
uv run pgvis fsm <table> --tree   # binary search tree view

# Visibility Map
uv run pgvis vm <table>

# Custom connection
uv run pgvis --dsn "postgresql://user:pass@host:port/db" page users 0
```

## Requires

PostgreSQL extensions: `pageinspect`, `pg_visibility`, `pg_buffercache`, `pg_freespacemap`.

Default connection: `postgresql://study:study@localhost:5433/study`.
