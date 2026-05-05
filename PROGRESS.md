# Progress

## Current Focus

**PostgreSQL Deep Dive** (`modules/00-postgresql/`) — Chapters 1, 2, 2b, 3 complete. Next: Chapter 4 (Query execution & EXPLAIN).

## Completed

### Chapter 1: Physical Storage ✅ (2026-05-03)
Page layout, tuple structure, MVCC fields, relation forks (FSM, VM), filenode vs OID, VACUUM behavior. Built pgvis tool.

### Chapter 2: Shared Buffers & Read/Write Path ✅ (2026-05-04)
shared_buffers as page cache, EXPLAIN BUFFERS (hit vs read), ring buffer, clock-sweep eviction, dirty pages, checkpoint/bgwriter. Added `pgvis buffers`.

### Chapter 2b: OS Page Cache & Tuning ✅ (2026-05-04)
Why Postgres needs its own cache (shared memory, write ordering, pinning, locking), double-caching is unavoidable, page size alignment (8KB = 2× OS 4KB), 25% of RAM rule.

### Chapter 3: Transactions & Basic Concurrency ✅ (2026-05-05)
Transaction IDs (32-bit counter, virtual xids), xmin/xmax mechanics (INSERT/UPDATE/DELETE), CLOG, hint bits (reads dirtying pages), visibility rule, snapshots (xmin:xmax:xip_list), concurrent visibility experiments, row-level locking on concurrent writes, transaction ID wraparound and VACUUM FREEZE. Refactored pgvis into feature-based modules, added `pgvis sql` interactive REPL with panel-based TUI.

## Next Up

- Chapter 4: Query execution & EXPLAIN
