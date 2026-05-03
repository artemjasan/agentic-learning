# PostgreSQL — From Practitioner to Expert

## Goal

Go from "I use Postgres daily and know it well" to "I understand what Postgres is doing at every level — page layout, tuple lifecycle, WAL records, snapshot visibility, index internals, replication mechanics." The kind of understanding where you can diagnose weird production behavior from first principles, not just Stack Overflow.

## Questions

### Storage & Physical Layout
- What does a row actually look like on disk? What's in the tuple header besides data?
- How does TOAST decide when to compress or move data out-of-line? What are the TOAST strategies (PLAIN, EXTENDED, EXTERNAL, MAIN) and when does each apply?
- What's the relationship between the OS page cache and shared_buffers?
- How does page size (default 8KB) affect OLTP vs OLAP workloads? What's the tradeoff?

### Transactions & MVCC
- When two transactions read the same row, what exactly determines which version each sees?
- How does a snapshot get constructed, and what's the cost of a long-running transaction?
- What happens to the transaction ID counter over time — what's the wraparound problem?

### Vacuum & Bloat
- Why can autovacuum fall behind, and what are the real-world consequences?
- What's the difference between vacuum and vacuum full? When does each make sense?
- How does the visibility map interact with vacuum and index-only scans?

### WAL & Crash Recovery
- What actually goes into a WAL record? Is it physical or logical?
- How does crash recovery decide where to start replaying?
- What's the tradeoff between checkpoint frequency and recovery time?

### Isolation & Concurrency
- How does SERIALIZABLE actually detect conflicts? What's SSI (Serializable Snapshot Isolation)?
- What's the real performance cost of SERIALIZABLE vs READ COMMITTED under contention?
- Can advisory locks solve problems that row-level locks can't?

### Optimistic Concurrency Control
- How does OCC compare to pessimistic locking in practice — when does each win?
- Application-level OCC (version columns, conditional UPDATE ... WHERE version = N) — what are the edge cases?
- SSI as database-level OCC: Postgres proceeds optimistically then aborts on conflict — what does the abort rate look like under real contention?
- Retry strategies: when OCC aborts a transaction, what's the right backoff pattern?

### Indexes
- What does the inside of a B-tree page look like? How does a page split work?
- When does GIN beat GiST for the same data type, and why?
- Why can BRIN be orders of magnitude smaller than B-tree, and what's the catch?

### Replication
- What exactly gets shipped in streaming replication — WAL segments or individual records?
- How does logical replication decode WAL into logical changes?
- What determines replication lag, and what can you actually do about it?

### Process Architecture & Connection Management
- Why does Postgres fork a new process per connection instead of using threads? What are the tradeoffs?
- What processes make up a running Postgres instance? (postmaster, background writer, checkpointer, autovacuum, WAL writer, etc.)
- What's the real cost of a new Postgres connection (memory, process fork, catalog loading)?
- How does shared memory (shared_buffers, lock tables, etc.) work across processes?
- Why does PgBouncer transaction mode break prepared statements?
- Where's the breaking point — how many direct connections before Postgres degrades?

### High Load & Deadlocks
- How does Postgres detect deadlocks — what's the detection algorithm and how fast is it?
- What does lock contention actually look like under 1000 concurrent writers hitting the same rows?
- How does Postgres behave when every connection is blocked — what breaks first?
- What real-world access patterns cause deadlocks, and what does `pg_stat_activity` + `pg_locks` look like when it happens?
- How do slow queries create cascading failures under load?

### Breaking Postgres
- What happens when you kill -9 the postmaster mid-checkpoint? Mid-vacuum?
- What does Postgres do when the disk fills up during a write-heavy workload?
- How close can you get to transaction ID wraparound, and what does the emergency autovacuum look like?
- Can you corrupt a data file and still recover? What tools exist (`pg_resetwal`, `pg_amcheck`)?
- What happens when shared_buffers is set absurdly high or low?

### Extensions & Plugins
- What's the anatomy of a Postgres extension — control file, SQL script, shared library?
- How does the hook system work — what can you intercept (planner, executor, auth)?
- Can you write a background worker that runs continuously inside Postgres?
- What's the difference between a C extension and a procedural language extension?

## Prior Knowledge

- Solid daily Postgres user: schemas, queries, indexes, transactions, basic replication concepts
- Knows EXPLAIN ANALYZE but doesn't always know why the planner makes certain choices
- Understands MVCC conceptually ("old versions stick around") but hasn't observed it at the tuple level
- Has used PgBouncer but not benchmarked or stress-tested it
- Hasn't looked at WAL internals, page layout, or pageinspect

---

## Findings

### Chapter 1: Physical Storage

#### Where Data Lives on Disk

Database path: `/var/lib/postgresql/18/docker/base/<database_OID>/<relfilenode>`

PG 18 changed the data directory layout — mount goes to `/var/lib/postgresql` (not `data/`), and PG creates version-specific subdirs (`18/docker/`).

```sql
-- Find a table's file path
SELECT pg_relation_filepath('users');  -- e.g., base/16384/16507
```

- `16384` = database OID (first user-created object gets OID 16384 = `FirstNormalObjectId`)
- `16507` = relfilenode (maps to the filename, can change after VACUUM FULL)
- OIDs below 16384 are reserved for system catalogs, types, functions (hardcoded at compile time)
- OID is permanent identity; relfilenode is the current physical file. Same indirection pattern as item pointers inside pages.

Three default databases: `template1` (default template for CREATE DATABASE), `template0` (pristine clean room, never modify), `postgres` (convenience default).

#### Relation Forks

Each table has up to 3 files:
- **Main fork** (`16507`) — the heap data (pages with tuples)
- **FSM** (`16507_fsm`) — Free Space Map, tracks free space per page so INSERT doesn't scan every page
- **VM** (`16507_vm`) — Visibility Map, tracks all-visible and all-frozen pages; created on first VACUUM

The VM didn't exist until we ran VACUUM — it gets created lazily.

#### Page Layout (8KB = 8192 bytes)

```
Byte 0      ┌─────────────────────────┐
            │ Page Header (24 bytes)   │  LSN, lower, upper, special, flags
Byte 24     ├─────────────────────────┤
            │ Item Pointers (4B each)  │  ← grows downward
            │ LP 1, LP 2, LP 3 ...    │
Byte lower  ├─────────────────────────┤
            │ Free Space               │
Byte upper  ├─────────────────────────┤
            │ Tuples                   │  ← grows upward from bottom
            │ (newest at lowest offset)│
Byte 8192   └─────────────────────────┘
```

- Item pointers grow from top, tuples grow from bottom — they share the free space pool
- Page is full when `lower` meets `upper`
- `lower` = end of item pointers, `upper` = start of first tuple
- This design means no pre-allocation needed — neither side knows in advance how much space it needs

Verified with `pageinspect`: page 0 had 131 tuples, lower=548 (24 + 131×4), upper=600, only 52 bytes free.

#### Heap = Unordered Pile

Tables are "heap" files — rows stored in no particular order, wherever there's space. Even with a PRIMARY KEY, the heap isn't sorted. The index is a separate structure pointing into the heap.

This is different from MySQL InnoDB which uses a clustered index (data stored sorted by primary key).

#### Tuple Structure

Each tuple: 23-byte header + alignment padding + data.

Header fields:
- `xmin` — transaction ID that created this tuple
- `xmax` — transaction ID that deleted/updated it (0 = alive)
- `ctid` — physical address as (page, item_pointer_number)
- `infomask` — bit flags for tuple state
- `t_hoff` — offset where data starts within the tuple (always 24 for us: 23 + 1 padding)

Actual data: for our `users` table (id integer, name text, email text):
```
id=1:  24 header + 4 (int) + 7 (varlena "user_1") + 19 (varlena "user_1@example.com") = 54 bytes
id=10: 24 header + 4 + 8 + 20 = 56 bytes
id=100: 24 header + 4 + 9 + 21 = 58 bytes
```

Tuple sizes vary because text/varchar uses **varlena** format:
- Short strings (≤126 bytes): 1-byte length header + data bytes
- `varchar(10000)` storing "hello" = 6 bytes, not 10000 — max length is a constraint, not storage allocation

#### Alignment (MAXALIGN)

Tuple start offsets must be 8-byte aligned on 64-bit systems. For a 54-byte tuple:
- 8192 - 54 = 8138, but 8138 isn't 8-byte aligned
- Rounds down to 8136 → tuple at bytes 8136-8189, bytes 8190-8191 are padding
- Cost: up to 7 "wasted" bytes per tuple

#### Item Pointers (Line Pointers)

4 bytes each: offset + length + flags. They're the indirection layer between references and physical bytes.

```
Index entry → (page 5, LP 3)  →  LP 3 says "offset 7800, len 56"  →  tuple at byte 7800
```

Why indirection matters:
- VACUUM compacts a page → updates LP offsets, indexes don't change
- HOT updates → old LP redirects to new LP, indexes don't change

LP flag states:
- `normal` (1) — points to a live tuple
- `redirect` (2) — HOT chain redirect
- `dead` (3) — tombstone; tuple data removed but LP kept because indexes may still reference it
- `unused` (0) — fully reclaimable by new inserts

#### Filenode vs OID

`relfilenode` starts equal to OID but changes when the physical file is rewritten:
```sql
SELECT oid, relfilenode FROM pg_class WHERE relname = 'users';
VACUUM FULL users;  -- relfilenode changes, OID stays the same
```

VACUUM FULL writes a new file → new relfilenode. Catalog, indexes, foreign keys all reference the OID which never changes.

#### DELETE, Pruning, and VACUUM

DELETE doesn't remove data — it sets `xmax`. The tuple stays physically present.

**Page pruning** happens on next page access (not during DELETE): wipes tuple bytes, sets LP to `dead`. Any page read can trigger this — our `pgvis` query triggered it before we could see the raw dead tuples.

**Regular VACUUM**: sets dead LPs to `unused`, updates FSM with freed space, updates VM, removes dead index entries. Does NOT move rows between pages, does NOT shrink the file.

**VACUUM FULL**: rewrites entire table into new file, packs tightly, changes relfilenode, file actually shrinks. Requires exclusive lock (blocks all reads/writes).

Observed: after DELETE of 101 rows + VACUUM, FSM showed ~12KB free across 3 pages. After VACUUM FULL, all pages packed full again with fewer total pages.

#### FSM and VM in Practice

FSM stores approximate free space per page (32-byte granularity) in a binary tree. INSERT checks FSM to find a page with room.

VM tracks two bits per page:
- `all_visible` — all tuples visible to all transactions → VACUUM can skip, index-only scans can skip heap
- `all_frozen` — all tuples frozen (xmin replaced with permanent marker) → never needs wraparound vacuum again

After VACUUM, we observed pages flipping to FROZEN state — Postgres freezes tuple xmin values to prevent transaction ID wraparound.

#### Segment Files

Tables >1GB are split: `16507`, `16507.1`, `16507.2`, etc. Compile-time setting (`--with-segsize`). Originally a filesystem limitation workaround. Not worth changing on modern systems — the overhead is negligible and smaller files are easier for backup tools.

#### Page Size Tradeoffs

Default 8KB. Compile-time setting (`--with-blocksize`).
- Larger pages (16-32KB): better for OLAP, wide rows, sequential scans. Fewer page headers per byte. But more wasted I/O for random reads.
- Smaller pages: better for OLTP with small random reads. But more page header overhead.
- Rarely changed in practice — 8KB is a good general-purpose balance.

#### TOAST (brief)

Triggers when tuple exceeds ~2KB. Four strategies: PLAIN (never TOAST), EXTENDED (compress then move out-of-line), EXTERNAL (move without compression), MAIN (try to keep inline).

Observed: `repeat('x', 2000)` compressed from 2000 bytes to 35 bytes inline. `repeat('x', 1000000)` compressed to 11,452 bytes and moved to TOAST table. Compression can be dramatic for repetitive data. Full deep dive in Chapter 17.

### Code Notes

- `tools/pgvis/` — PostgreSQL page visualizer (Python, Click, Rich, psycopg3)
  - `pgvis page <table> <N>` — renders heap page layout with header, LPs, tuples, space bar
  - `pgvis page <table> <N> --all` — show all tuples instead of preview
  - `pgvis fsm <table>` — free space per page with fill bars
  - `pgvis fsm <table> --tree` — FSM as binary search tree showing how Postgres finds free space
  - `pgvis vm <table>` — visibility and frozen flags per page
  - Connection: `localhost:5433`, user `study`, db `study`
  - Extensible via Click command group — add new visualizations as subcommands

---

## Retro

### Chapter 1: Physical Storage

#### Summary

Explored how PostgreSQL physically stores data on disk: 8KB pages with a split layout (item pointers growing down, tuples growing up), tuple headers carrying MVCC metadata (xmin/xmax), variable-length storage via varlena, and the three relation forks (main, FSM, VM). Built a visualization tool (pgvis) that made the internal structures tangible. Observed DELETE/VACUUM/VACUUM FULL behavior at the physical level — seeing dead tuples, page pruning, and FSM/VM updates with real data.

#### Key Takeaways

- The page layout is a clever shared-free-space design — pointers and tuples grow toward each other, no pre-allocation needed
- Item pointers are the unsung hero — the indirection layer that lets tuples move without breaking index references. Same pattern appears at file level (OID vs relfilenode)
- DELETE doesn't delete. It sets xmax. Page pruning and VACUUM are separate cleanup passes, each with different scope
- `varchar(N)` max length is a constraint, not a storage allocation — a common misconception cleared up by looking at actual tuple bytes
- The FSM is a binary tree for O(log N) free space lookup — not a scan. Visualizing it made the algorithm click
- The VM is just 2 bits per page, but it enables two critical optimizations (vacuum skip, index-only scan heap skip)
- Regular VACUUM never shrinks the file — it reclaims space within pages. Only VACUUM FULL compacts, at the cost of an exclusive lock

#### What I'd Do Differently

- Should have installed `pg_freespacemap` extension upfront before first FSM observation — missed seeing accurate FSM state after VACUUM FULL
- Could have caught dead-but-not-yet-pruned tuples by being more careful about page access triggering pruning
- The interactive learning format (user runs commands, discusses results) worked much better than agent-runs-everything — established this early

#### Connections

- **Chapter 2 (Shared buffers)**: pages we saw on disk also live in shared_buffers — the caching layer sits between these files and queries
- **Chapter 6 (MVCC)**: xmin/xmax in tuple headers are the foundation — we saw them but didn't yet understand visibility rules
- **Chapter 7 (Vacuum & bloat)**: we saw VACUUM/VACUUM FULL behavior physically; the dedicated chapter will cover tuning, autovacuum, and bloat measurement
- **Chapter 4 (Query execution)**: VM's all_visible flag enables index-only scans — will see this in EXPLAIN output
- **Chapter 17 (TOAST)**: briefly saw compression (2000 chars → 35 bytes); full deep dive with all strategies later
- **Cache algorithms topic (TOPICS.md)**: Postgres's clock-sweep in shared_buffers connects to implementing LRU/LFU/ARC from scratch

#### Open Questions

- Why did the FSM show 0 free for all pages after VACUUM FULL when the last page was clearly not full? Timing/extension installation issue, or something deeper?
- How exactly does page pruning decide when to trigger? Is it every page access or only certain operations?
- What's the actual overhead of the double-caching (shared_buffers + OS page cache)? Worth measuring in Chapter 2.

## Plan

Seventeen chapters, each building on the last:

1. **Physical storage** ✅ — page layout, tuple structure, `ctid`, `pg_relation_filepath`, relation forks (FSM, VM), filenode vs OID, segment files, page size tradeoffs
2. **Shared buffers, OS page cache & the read/write path** — split into sessions:
   - a. Look inside shared_buffers with `pg_buffercache` — what's cached right now, cache hit vs miss
   - b. The read path — how a page moves from disk → OS cache → shared_buffers, measuring the difference
   - c. The write path — dirty pages, background writer, checkpointer, WAL-before-data rule, fsync
   - d. Tuning — why 25% of RAM, double-caching problem, monitoring hit ratios, `pg_stat_bgwriter`
3. **Transactions & basic concurrency** — lock types, blocking behavior, `pg_locks`, what happens under the hood during BEGIN/COMMIT
4. **Query execution & EXPLAIN** — scan types, join algorithms, cost model, `pg_stat_statements`, reading plans like an expert
5. **Indexes (user perspective)** — B-tree, partial, covering, expression indexes. When they help, when they hurt. The planner's decision-making.
6. **MVCC under the hood** — `xmin`/`xmax`, visibility rules, snapshots, transaction ID lifecycle, wraparound
7. **Vacuum & bloat** — dead tuples, autovacuum tuning, visibility map, `pg_stat_user_tables`, measuring and fixing bloat
8. **WAL** — record structure, `pg_waldump`, checkpoints, crash recovery, `wal_level` settings
9. **Isolation levels & OCC** — anomaly reproduction, SSI internals, optimistic vs pessimistic concurrency, application-level OCC patterns, retry strategies, performance cost measurement
10. **Index internals** — `pageinspect`, B-tree page structure, GIN/GiST/BRIN internals
11. **Replication** — streaming, logical, failover, lag measurement under load
12. **PgBouncer** — pooling modes, connection cost benchmarking, pool exhaustion
13. **Partitioning, tablespaces & sharding** — range/list/hash partitioning, partition pruning, tablespaces on different disks, sharding strategies (Citus, manual sharding), when to partition vs when to shard
14. **Postgres under fire** — high-load scenarios, deadlock creation and detection, lock contention storms, connection stampedes, slow query avalanches, `pg_stat_activity` forensics, realistic production failure scenarios
15. **Breaking Postgres** — kill it mid-transaction and watch recovery, corrupt data files and see what happens, fill the disk, hit transaction ID wraparound, `pg_resetwal` as last resort, push it to OOM, explore every failure mode
16. **Writing a PostgreSQL extension** — C extension basics, custom functions, custom data types, hook system, background workers, build and install into a running instance. Project idea: build an extension that exposes real-time visibility into internal processes (buffer manager, bgwriter, checkpointer activity)
17. **TOAST deep dive** — all four strategies hands-on, non-compressible data, chunk structure, lazy detoasting performance, changing storage strategies
