# Progress

## Current Focus

**PostgreSQL Deep Dive** (`modules/00-postgresql/`) — Chapters 1, 2, 2b, 3, 4, 4b, 5 complete. Next: Chapter 5b (Join Internals) or Chapter 6 (Indexes).

## Completed

### Chapter 1: Physical Storage ✅ (2026-05-03)
Page layout, tuple structure, MVCC fields, relation forks (FSM, VM), filenode vs OID, VACUUM behavior. Built pgvis tool.

### Chapter 2: Shared Buffers & Read/Write Path ✅ (2026-05-04)
shared_buffers as page cache, EXPLAIN BUFFERS (hit vs read), ring buffer, clock-sweep eviction, dirty pages, checkpoint/bgwriter. Added `pgvis buffers`.

### Chapter 2b: OS Page Cache & Tuning ✅ (2026-05-04)
Why Postgres needs its own cache (shared memory, write ordering, pinning, locking), double-caching is unavoidable, page size alignment (8KB = 2× OS 4KB), 25% of RAM rule.

### Chapter 3: Transactions & Basic Concurrency ✅ (2026-05-05)
Transaction IDs (32-bit counter, virtual xids), xmin/xmax mechanics (INSERT/UPDATE/DELETE), CLOG, hint bits (reads dirtying pages), visibility rule, snapshots (xmin:xmax:xip_list), concurrent visibility experiments, row-level locking on concurrent writes, transaction ID wraparound and VACUUM FREEZE. Refactored pgvis into feature-based modules, added `pgvis sql` interactive REPL with panel-based TUI.

### Chapter 4: Postgres Architecture & Query Pipeline ✅ (2026-05-08)
Process model (postmaster, fork-per-connection, signals), connection lifecycle and measured cost (~7ms connect vs ~0.6ms query), backend private memory (work_mem per-operation multiplication), shared memory layout (Buffer Blocks/Descriptors split, XLOG, CLOG, AIO), background processes via pg_stat_activity, query pipeline (parser/analyzer/rewriter/planner/executor proved by triggering errors at each stage). Added timing to pgvis sql.

### Chapter 4b: SQL Parsing Internals ✅ (2026-05-08)
Built full pre-planner pipeline from scratch in Go: lexer (tokenizer), recursive descent parser, analyzer (with lazy catalog cache mirroring Postgres SysCache), rewriter (view expansion). Used pg_query_go to compare with real Postgres parser output. sqlparse tool with 5 commands: parse, lex, myparse, analyze, rewrite.

### Chapter 5: Query Execution & EXPLAIN ✅ (2026-05-11)
EXPLAIN output structure, cost model (verified by hand calculation), three scan types (Seq Scan, Index Scan, Bitmap Heap Scan) and the selectivity crossover, planner statistics (MCVs, histograms, pg_stats), three join strategies (Nested Loop, Hash Join, Merge Join), sorting (external merge vs quicksort vs top-N heapsort), work_mem effects, diagnosing bad plans. Built `pgvis explain` tool with step-by-step annotated output, strategy explanations, and cost formula breakdowns.

## Next Up

- Chapter 5b: Join Internals (or Chapter 6: Indexes)
