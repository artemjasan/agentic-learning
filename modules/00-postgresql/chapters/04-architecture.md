# Chapter 4: Postgres Architecture & Query Pipeline

## Plan

### 1. The postmaster & fork-per-connection model
Postgres uses **processes, not threads**. The postmaster is the supervisor: it listens for connections, forks a backend process for each client, and manages the lifecycle of all children.

Why processes: crash isolation (one backend can't corrupt another), simplicity (no intra-backend locking), historical roots (predates reliable POSIX threading). Trade-offs: fork overhead, per-process memory footprint, OS process limits at scale.

How the postmaster communicates with children: Unix signals. `SIGHUP` = reload config, `SIGTERM` = smart shutdown (wait for clients), `SIGQUIT` = fast shutdown, `SIGKILL` = immediate (skip cleanup). When a backend crashes, the postmaster kills all other backends and restarts — crash isolation means one bad backend can't leave shared memory in a corrupt state.

*Hands-on:* Run `ps auxf | grep postgres` (or equivalent in Docker) to see the process tree. Identify the postmaster and its children. Open two `pgvis sql -i` sessions, watch new backend processes appear in the tree and in `pg_stat_activity`.

### 2. Connection lifecycle & cost
What happens when a client connects, step by step: TCP connect → startup message (protocol version, database, user) → authentication (pg_hba.conf lookup, SCRAM/md5/trust) → backend fork → catalog cache warming → ready for queries.

What "fork is expensive" means concretely:
- OS creates a new process (copy page tables, allocate PID)
- Copy-on-write for the parent's memory pages
- New backend loads catalog caches (pg_class, pg_type, etc.) on first queries
- Backend allocates private memory regions

The query loop: backend sits in a read-wait loop, processes one query at a time (parse → plan → execute → result → wait), until disconnect or error.

On disconnect: backend releases locks, aborts any open transaction, cleans up private memory, exits. Postmaster detects child exit.

*Hands-on:* Measure connection cost — time a fresh `pgvis sql "SELECT 1"` (includes connect + fork + query + disconnect) vs the same query inside an open `pgvis sql -i` session (query only). Run it multiple times, compare the difference. This is the cost PgBouncer eliminates (→ Ch 15).

### 3. Backend memory (private)
Each backend has its own private memory, invisible to other processes:
- **work_mem** — per-operation budget for sorts, hashes, bitmap operations. A single query can use multiple work_mem allocations.
- **maintenance_work_mem** — larger budget for maintenance operations (VACUUM, CREATE INDEX)
- **temp_buffers** — private cache for temporary tables
- **Catalog cache** — frequently accessed system catalog rows (pg_class, pg_attribute, pg_type)
- **Plan cache** — prepared statement plans (parse once, execute many)

The multiplication problem: `max_connections × work_mem × operations_per_query` = potential memory consumption. 200 connections × 4MB × 3 sort operations = 2.4GB just for sorts. This is why "too many connections" is a memory problem, not just a process limit.

*Hands-on:* `SHOW work_mem`, `SHOW maintenance_work_mem`. Calculate worst-case memory for your current `max_connections` setting.

### 4. Shared memory layout
All backends and background processes share a single shared memory segment. We've already studied two pieces — this section maps the full territory:

**Already studied:**
- **shared_buffers** — page cache, clock-sweep eviction (Ch 2)
- **CLOG / pg_xact buffers** — transaction status bitmap (Ch 3)

**New:**
- **WAL buffers** — staging area for write-ahead log records before flush to disk (→ Ch 11)
- **ProcArray** — array of all backend/process slots with their current xid, snapshot info. This is what `txid_current_snapshot()` reads to build snapshots (Ch 3 connection)
- **Lock manager** — shared hash tables for heavyweight locks (row, table, advisory). Lock wait queues and deadlock detection data
- **Buffer mapping table** — hash table mapping (tablespace, relation, block number) → buffer slot index. How Postgres finds a page in shared_buffers without scanning all slots
- **Lightweight lock (LWLock) arrays** — fast, short-duration locks protecting shared memory structures internally. Not visible to users, but show up in `wait_event` when contended

*Hands-on:* `SELECT name, size, allocated_size FROM pg_shmem_allocations ORDER BY size DESC LIMIT 20` — see actual shared memory regions and their sizes. Match them to the structures above.

### 5. The background process crew
The postmaster spawns these at startup. Each has a specific job maintaining the system:

**Data integrity:**
- **Checkpointer** — periodically flushes all dirty pages and advances the WAL recovery point (already seen in Ch 2)
- **Background writer (bgwriter)** — trickle-writes dirty pages between checkpoints to smooth I/O (already seen in Ch 2)
- **WAL writer** — flushes WAL buffers to disk. Backends can also flush WAL themselves at commit (→ Ch 11)

**Maintenance:**
- **Autovacuum launcher** — monitors tables, spawns autovacuum worker processes when thresholds are hit (→ Ch 10)
- **Stats collector / cumulative stats system** — aggregates per-table, per-index access statistics reported by backends. Feeds `pg_stat_user_tables`, `pg_stat_activity`, etc.

**Replication & archiving (if configured):**
- **Archiver** — copies completed WAL segments to archive storage (→ Ch 11/14)
- **WAL sender / receiver** — streaming replication processes (→ Ch 14)
- **Logical replication launcher** — manages logical replication workers (→ Ch 14)

Each process is a loop: wake up (on timer or signal), do work, go back to sleep. They coordinate via shared memory and signals from the postmaster.

*Hands-on:* `SELECT pid, backend_type, state, wait_event FROM pg_stat_activity ORDER BY backend_type` — see every process from inside Postgres. Match to what `ps` shows outside.

### 6. The query pipeline
The five stages every SQL statement passes through inside a backend process:

**1. Parser** — SQL text → parse tree. A Bison/Flex grammar. Purely syntactic — checks structure, not meaning. Doesn't know if tables or columns exist.
*How to observe:* A syntax error (`SELECTT * FROM users`) dies here.

**2. Analyzer** — parse tree → query tree. Resolves table names against `pg_class`, column names against `pg_attribute`, function calls against `pg_proc`. Checks types and adds implicit casts.
*How to observe:* An unknown table (`SELECT * FROM nonexistent`) dies here — syntax is valid but the name doesn't resolve.

**3. Rewriter** — applies rule-based transformations. Views are implemented as rules — `SELECT * FROM my_view` gets rewritten into the view's underlying query. Also handles `INSTEAD OF` rules.
*How to observe:* Create a simple view, run EXPLAIN on it — you'll see the underlying table scan, not a "view scan."

**4. Planner/Optimizer** — query tree → plan tree. Generates possible execution strategies, estimates their costs using statistics (pg_statistic) and the cost model (seq_page_cost, random_page_cost, etc.), picks the cheapest one. The most complex stage — this is the focus of Ch 5.
*How to observe:* `EXPLAIN` shows the planner's chosen plan.

**5. Executor** — runs the plan tree using the Volcano/pull iterator model. Each node (Seq Scan, Sort, Hash Join, etc.) implements Init/Next/End. The top node pulls rows, triggering pulls down the tree to the leaf scan nodes that touch actual heap pages.
*How to observe:* `EXPLAIN ANALYZE` shows actual execution — times, row counts, buffer access.

*Hands-on:* Run a single query through each observation method above. Trigger errors at each stage to prove which stage caught it. Then run EXPLAIN and EXPLAIN ANALYZE to see the planner and executor outputs.

### What you'll know after this chapter
- The full Postgres process architecture — postmaster, backends, background workers
- What every running process does and how they coordinate via shared memory and signals
- The concrete cost of a connection — measured, not theoretical
- What lives in shared memory and how it maps to concepts from earlier chapters
- Why backend memory × connection count = the real scalability constraint
- The five-stage query pipeline and how to observe each stage
- Why connection pooling exists (motivating Ch 15)

### Out of scope (deferred)
- Autovacuum internals → Ch 10
- WAL mechanics → Ch 11
- Replication processes → Ch 14
- Connection pooling (PgBouncer) → Ch 15
- Hook system, custom background workers → Ch 19
- Thread-per-connection model (Postgres 17+ experiments)

---

## Findings

### Process Model
Postgres is a multi-process system. The **postmaster** (PID 1 in the container) is the supervisor — it listens for connections, forks a backend for each client, and manages all children via Unix signals (SIGHUP = reload, SIGTERM = shutdown). When a backend crashes, the postmaster kills all children and restarts to protect shared memory integrity.

Each connection = one OS process. Verified by watching `ps` and `pg_stat_activity` as connections opened — new backend process appears for each.

### Connection Cost
Measured with psycopg3 timing (10 runs):
- **Connect** (TCP + auth + fork + catalog cache): ~5-9ms (~7ms average)
- **Query** (SELECT 1 on existing connection): ~0.4-1.0ms (~0.6ms average)

Connecting is ~10× more expensive than querying. This is the fundamental motivation for connection pooling.

### Backend Memory
Each backend has private memory, measured via `/proc/<pid>/status`:
- Baseline: VmRSS ~16MB, VmData ~2.6MB (private heap)
- After sorting 1M rows: VmRSS jumped to ~79MB, VmHWM peaked at 86MB
- `work_mem` (default 4MB) controls per-operation sort/hash budget — each node in a plan gets its own allocation, so a query with 3 sort/hash nodes can use 3 × work_mem
- The multiplication: `connections × work_mem × operations = memory pressure`

VmSize (~224MB) includes shared memory mapping but the physical pages are shared — not duplicated per process. The real per-backend private cost is VmData (~3-5MB baseline).

### Shared Memory
Inspected via `pg_shmem_allocations`. Dominated by Buffer Blocks (134MB = shared_buffers). Other regions: XLOG Ctl (4MB WAL buffers), Buffer Descriptors (1MB metadata — hot/cold split from blocks for cache-friendly scanning), AIO structures (6MB), transaction/CLOG buffers (0.5MB).

Buffer Descriptors are separated from Buffer Blocks so clock-sweep can scan the compact 1MB descriptor array without touching the 128MB data blocks — same principle as item pointers vs tuple data on a heap page.

### Background Processes
Observed via `pg_stat_activity`: checkpointer, background writer, walwriter, autovacuum launcher, logical replication launcher, io workers. All sit in loops — sleep, wake, do work, sleep. Each has a dedicated chapter for deep dive. Stats collector was replaced by shared memory-based stats in Postgres 15+.

### Query Pipeline
Proved each stage exists by triggering errors:
1. **Parser** — `SELECTT 1` → syntax error (grammar check only)
2. **Analyzer** — `SELECT * FROM nonexistent` → relation not found (resolves names against catalog)
3. **Rewriter** — view `user_emails` → EXPLAIN shows scan on underlying `users` table (view expanded away)
4. **Planner** — chose `Index Scan using users_pkey`, estimated cost 0.28..8.29, 1 row
5. **Executor** — runs the plan (deep dive in Ch 5)

---

## Retro

### Summary
Understood Postgres as a system of cooperating processes sharing memory. The postmaster forks a backend per connection (~7ms cost), each backend has private memory (work_mem × operations = scaling concern), all share a common memory segment (dominated by shared_buffers). Background processes maintain the system in loops. Every query passes through five pipeline stages — parser, analyzer, rewriter, planner, executor — each with a distinct responsibility.

### Key Takeaways
- Fork-per-connection: crash isolation at the cost of per-process overhead
- Connection cost (~7ms) is 10× query cost (~0.6ms) — never open-and-close per request
- work_mem is per-operation, not per-query or per-connection — multiply carefully
- Shared memory is mapped into every process's virtual space but physical pages are shared (copy-on-write)
- Buffer Descriptors are split from Buffer Blocks for cache-efficient scanning — same pattern as heap page item pointers
- Views are syntactic sugar — the rewriter eliminates them before the planner ever sees them

### Connections
- **Ch 2 (Shared Buffers)**: Buffer Blocks and Descriptors in shared memory, bgwriter/checkpointer roles
- **Ch 3 (Transactions)**: CLOG buffers in shared memory, ProcArray for snapshot construction
- **Ch 5 (Query Execution)**: planner and executor stages get their deep dive
- **Ch 4b (Parsing Internals)**: parser, analyzer, rewriter deep dive with Go implementations
- **Ch 10 (Vacuum)**: autovacuum launcher/worker internals
- **Ch 11 (WAL)**: walwriter, XLOG Ctl buffers
- **Ch 15 (PgBouncer)**: connection pooling to solve the fork cost problem
