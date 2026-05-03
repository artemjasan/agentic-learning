# 00 — PostgreSQL Deep Dive

Comprehensive PostgreSQL study: from physical storage to writing extensions. Seventeen chapters building from fundamentals to expert-level internals.

## Prerequisites

- Docker and Docker Compose
- Python 3.12+ and `uv` (for the pgvis visualization tool)

## Infrastructure

```bash
docker compose up -d
```

Spins up PostgreSQL 18 with `pageinspect`, `pg_visibility`, `pg_stat_statements`, `pg_buffercache`, and `pg_freespacemap` extensions.

## Visualization Tool

```bash
cd tools/pgvis
uv run pgvis page users 0        # heap page layout
uv run pgvis fsm users            # free space map
uv run pgvis fsm users --tree     # FSM as binary search tree
uv run pgvis vm users             # visibility map
```

## Structure

Each chapter adds findings to STUDY.md. The tool grows alongside the study — new visualization commands are added as topics demand.

See [STUDY.md](STUDY.md) for the full learning plan, findings, and retrospectives.
