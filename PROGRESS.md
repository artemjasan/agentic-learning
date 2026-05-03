# Progress

## Current Focus

**PostgreSQL Deep Dive** (`modules/00-postgresql/`) — Chapter 1 complete. Ready for Chapter 2 (Shared buffers & OS page cache).

## Completed

### Chapter 1: Physical Storage ✅ (2026-05-03)
Deep dive into how Postgres stores data on disk. Covered page layout (8KB pages, item pointers growing down, tuples growing up), tuple structure (23B header + varlena data), MVCC fields (xmin/xmax/ctid), relation forks (FSM, VM, main), filenode vs OID, VACUUM vs VACUUM FULL at the physical level, page pruning, alignment, segment files, and page size tradeoffs. Brief TOAST intro (moved to its own chapter). Built the `pgvis` visualization tool with page, FSM (flat + tree), and VM views.

## Next Up

- Chapter 2: Shared buffers, OS page cache & the read/write path (split into 4 sessions: pg_buffercache, read path, write path, tuning)
