# Chapter 5: Query Execution & EXPLAIN

## Plan

### 1. The executor model
Postgres uses the **Volcano model** — a pull-based iterator tree. Each node in the plan implements three operations: `Init` (set up state), `Next` (return one tuple), `End` (clean up). The top node pulls a tuple, which causes its children to pull from their children, all the way down to the scan nodes touching actual heap pages.

This is why EXPLAIN output is a tree — it's a direct map of the executor's node structure. Understanding the pull model makes every EXPLAIN readable: data flows up from leaves (scans) through intermediate nodes (sorts, joins, aggregates) to the root (result delivery).

Key distinction: the planner builds the tree (picks the strategy), the executor runs it (pulls the tuples). We studied the planner's place in the pipeline in Ch 4. Now we see what it produces and how that gets executed.

*Hands-on:* Run a multi-node query (e.g., `SELECT name FROM users WHERE id > 100 ORDER BY name LIMIT 10`). Read the EXPLAIN tree top-down and bottom-up. Identify each node, its inputs, and the pull direction.

### 2. Reading EXPLAIN output
Start with a simple query, learn the output format:
- **Node type** — what operation this node performs (Seq Scan, Sort, Index Scan, etc.)
- **Cost** — `startup_cost..total_cost` in abstract cost units. Startup cost = work before the first tuple. Total cost = work to get all tuples.
- **Rows** — estimated number of tuples this node will produce
- **Width** — average row width in bytes

Then progressively add flags:
- `EXPLAIN ANALYZE` — actual rows, actual time, loops. Compare estimated vs actual.
- `EXPLAIN (ANALYZE, BUFFERS)` — shared hit vs read (direct connection to Ch 2 shared_buffers).
- `EXPLAIN (ANALYZE, BUFFERS, TIMING)` — per-node timing breakdown.

Build intuition by running the same query with each flag level and comparing what each adds.

*Hands-on:* Pick a query, run it through all four EXPLAIN levels. Note where estimates diverge from actuals — this is where planner mistakes become visible.

### 3. The cost model
How the planner turns a plan into a number. The key constants:
- `seq_page_cost` (1.0) — cost of reading one page sequentially
- `random_page_cost` (4.0) — cost of reading one random page (4× sequential because disk seek)
- `cpu_tuple_cost` (0.01) — cost of processing one tuple
- `cpu_index_tuple_cost` (0.005) — cost of processing one index entry
- `cpu_operator_cost` (0.0025) — cost of evaluating one operator/function
- `effective_cache_size` — planner's estimate of total available cache (shared_buffers + OS cache). Doesn't allocate memory — just influences whether the planner expects random reads to hit cache. Connects directly to Ch 2 (shared_buffers) and Ch 2b (OS page cache).

The cost formula for a sequential scan: `seq_page_cost × pages + cpu_tuple_cost × tuples`. Every plan choice ultimately reduces to comparing these cost estimates.

*Hands-on:* Calculate the expected cost of a sequential scan on `users` by hand. Look up the page count (`pg_class.relpages`) and tuple count (`pg_class.reltuples`), plug into the formula, compare against EXPLAIN output. Then do the same with a WHERE clause and see how the Filter node adds cpu_operator_cost per tuple.

### 4. Sequential scan
The simplest access method: read every page, check every tuple against the filter condition. Postgres evaluates visibility (Ch 3 — snapshot check on every row) and the WHERE clause for each tuple.

When seq scan wins:
- Small tables (fewer pages than the overhead of index traversal)
- Low selectivity (most rows match — index would visit most pages anyway)
- No usable index on the filtered column

Cost formula in practice: `1.0 × relpages + 0.01 × reltuples` (base) + `0.0025 × reltuples` (per filter operator). Compare to what EXPLAIN reports.

*Hands-on:* Run a seq scan on `users`, verify cost calculation matches EXPLAIN. Add a WHERE clause, see the Filter node appear. Check `rows_removed_by_filter` in ANALYZE output — how many rows were read but discarded.

### 5. Index scan variants
Three strategies the planner chooses from, each for different data access patterns:

**Index Scan** — walk the B-tree, for each matching entry fetch the heap tuple via its TID (page, offset). Each heap fetch is a random I/O. Good for high selectivity (few rows match). Expensive when many rows match — lots of random page reads.

**Index Only Scan** — answer entirely from the index without touching the heap. Only works when: (1) all columns the query needs are in the index, and (2) the visibility map says the page is all-visible (Ch 1 VM, Ch 3 visibility). For pages not marked all-visible, must fetch from heap anyway to check tuple visibility.

**Bitmap Heap Scan** — two phases: (1) scan the index, build a bitmap of matching page numbers (not tuple positions), (2) read those pages in physical order. Converts random I/O to sequential. Good for medium selectivity — too many rows for Index Scan (too much random I/O), too few for Seq Scan (would read every page). When multiple indexes apply, Postgres can BitmapAnd/BitmapOr the bitmaps.

The crossover: as selectivity decreases (more rows match), the planner transitions Index Scan → Bitmap Heap Scan → Seq Scan. The random_page_cost vs seq_page_cost ratio (4:1 by default) drives this decision.

*Hands-on:* Create an index on a column, run queries with different WHERE selectivity to trigger each scan type. Use `SET enable_seqscan = off` (etc.) to force specific strategies, compare costs. Find the crossover point where the planner switches strategy.

### 6. Planner statistics
Where the row estimates come from. The planner doesn't examine actual data at plan time — it uses pre-computed statistics stored in `pg_statistic` (readable via `pg_stats`):

- **Most Common Values (MCVs)** — the N most frequent values and their frequencies. For `WHERE status = 'active'`, the planner checks if 'active' is in the MCV list and uses its exact frequency.
- **Histogram bounds** — equal-frequency buckets for range queries. For `WHERE id > 500`, the planner interpolates within histogram buckets.
- **n_distinct** — estimated number of distinct values. Used for GROUP BY estimates.
- **correlation** — how well physical tuple order matches logical value order. High correlation (close to ±1.0) means an index range scan reads pages sequentially in practice — lowers the effective random I/O cost.

The `ANALYZE` command samples ~30,000 rows (configurable via `default_statistics_target`, default 100 = 100 histogram buckets) and computes these stats. Stats go stale as data changes — `autovacuum` runs ANALYZE periodically.

*Hands-on:* Query `pg_stats` for a column — read the MCV array and histogram bounds. Then delete stats (`DELETE FROM pg_statistic WHERE ...` or `ALTER TABLE ... ALTER COLUMN ... SET STATISTICS 0; ANALYZE`), observe terrible row estimates in EXPLAIN. Restore stats with `ANALYZE`, see estimates snap back.

### 7. Joins
Three algorithms the executor uses, each chosen by the planner based on data characteristics:

**Nested Loop** — for each row in the outer relation, scan the inner relation. O(N×M) in the worst case, but excellent when the outer side is small and the inner side has an index (effectively O(N×log M)). The planner's default for small outer sets.

**Hash Join** — two phases: (1) build a hash table from the smaller relation (the "build" side), (2) probe with each row from the larger relation (the "probe" side). O(N+M) time, O(smaller) memory. Requires an equality join condition (hash on the join key). Uses work_mem for the hash table — if it overflows, spills to disk in batches.

**Merge Join** — sort both sides by the join key, then merge in a single pass. O(N log N + M log M) for the sorts, O(N+M) for the merge. Wins when both inputs are already sorted (e.g., by an index) or when both are very large (sort + merge beats hash table overflow). Handles equality and range conditions.

*Hands-on:* Create two tables with a foreign key relationship. Run joins with different data sizes and index availability to trigger each strategy. Disable specific strategies (`SET enable_hashjoin = off`, etc.) to compare costs. Watch for Hash Batches in EXPLAIN ANALYZE — that's work_mem overflow.

### 8. Sorting, aggregation & work_mem
**Sort** — two methods visible in EXPLAIN ANALYZE:
- `Sort Method: quicksort Memory: NkB` — fits in work_mem, fast
- `Sort Method: external merge Disk: NkB` — overflows work_mem, spills to temp files, slower

**Aggregate** — three strategies:
- Plain Aggregate — single group, one pass (`SELECT count(*) FROM users`)
- GroupAggregate — needs sorted input, streams through groups (`GROUP BY` on sorted data)
- HashAggregate — builds hash table keyed on GROUP BY columns, O(1) group lookup. Uses work_mem.

**Top-N sort** — `ORDER BY ... LIMIT N` uses a heap-based top-N sort. Only keeps N tuples in memory regardless of input size. Shows as `Sort Method: top-N heapsort` in EXPLAIN.

Connection to Ch 4: work_mem is per-operation, not per-query. A query with 3 sort nodes can use 3 × work_mem. This is the multiplication problem we measured.

*Hands-on:* Run a sort that fits in work_mem, check EXPLAIN ANALYZE for "quicksort Memory." Lower work_mem (`SET work_mem = '64kB'`), run again, see it switch to "external merge Disk." Measure the performance difference. Try a LIMIT query and observe top-N heapsort.

### 9. Diagnosing bad plans
Practical scenarios where the planner picks the wrong strategy:
- **Stale statistics** — data changed significantly but ANALYZE hasn't run. Row estimates are wrong, leading to wrong join order or wrong scan type.
- **Correlated columns** — planner assumes column values are independent. `WHERE country = 'US' AND city = 'New York'` — planner multiplies selectivities, underestimates the actual count.
- **Skewed distributions** — one value has millions of rows, most values have few. MCV statistics help for common values, but a parameterized query might get a plan optimized for the common case applied to the rare case.
- **Row estimation cascade** — one bad estimate at a leaf node propagates up: wrong row count → wrong join strategy → wrong join order → catastrophically slow plan.

Diagnostic tools: compare `estimated rows` vs `actual rows` in EXPLAIN ANALYZE at every node. Large divergence = the source of the bad plan. Check `pg_stat_user_tables.last_analyze` for stale stats.

*Hands-on:* Create a table with heavily skewed data (one value appears 100,000 times, others appear once). Observe EXPLAIN estimates vs actuals. Use `pg_stat_user_tables` to check when ANALYZE last ran.

### What you'll know after this chapter
- How the Volcano executor model works — pull-based iteration, Init/Next/End
- How to read any EXPLAIN tree — node types, costs, estimated vs actual rows, buffer access
- How the planner calculates costs and what each cost constant means
- When seq scan, index scan, index-only scan, and bitmap scan each win — and why
- Where row estimates come from (pg_statistic) and how to inspect them
- How nested loop, hash join, and merge join work and when each is chosen
- How work_mem controls in-memory vs on-disk sorting and hashing
- How to diagnose bad plans by tracing estimation errors

### Out of scope (deferred)
- Index internals (B-tree page structure, page splits, GIN/GiST/BRIN) → Chapter on indexes
- Parallel query execution → later chapter
- Prepared statement plan caching (generic vs custom plans)
- JIT compilation
- CTEs and subquery optimization
- Join algorithm internals (hash batching, merge duplicate handling) → Chapter 5b if needed

---

## Findings

### Reading EXPLAIN Output
Every EXPLAIN line has: node type, cost (startup..total), estimated rows, width. Adding ANALYZE shows actual rows, actual time, loops. Adding BUFFERS shows shared hit (cache) vs read (disk). The two cost numbers: startup = work before first row, total = work for all rows. Startup is zero for Seq Scan (can return immediately), nonzero for Sort (must sort everything first).

### The Cost Model
Cost is arithmetic with five constants: `seq_page_cost` (1.0), `random_page_cost` (4.0), `cpu_tuple_cost` (0.01), `cpu_operator_cost` (0.0025), `cpu_index_tuple_cost` (0.005). Verified by hand: Seq Scan cost = `seq_page_cost × relpages + cpu_tuple_cost × reltuples + cpu_operator_cost × reltuples` matched EXPLAIN output exactly (19.24 for `users` with WHERE clause).

### Sequential Scan
Reads every page, checks every tuple. Cost is always the same regardless of WHERE selectivity — the filter only adds CPU cost. Wins when most rows match or the table is small.

### Index Scan
Walks B-tree, fetches heap tuples by TID. Each heap fetch is random I/O (cost 4.0 vs 1.0 for sequential). Wins for pinpoint lookups. The 4:1 ratio means the crossover to Seq Scan happens around 10-20% selectivity.

`random_page_cost = 4.0` reflects HDD-era seek penalty. On SSDs, lowering it to 1.1-1.5 makes the planner more willing to use indexes.

### Bitmap Heap Scan
Two-phase: (1) Bitmap Index Scan builds a bitmap of page numbers, (2) Bitmap Heap Scan reads those pages in physical order. Deduplicates pages (multiple matching rows on same page = one read) and converts random I/O to sequential. "Recheck Cond" exists because the bitmap only tracks pages, not tuples. "exact" vs "lossy" tracking depends on available memory.

Tested on big_users (500K rows): `score = 42` (~1%, 5047 rows) → Bitmap. `score > 10` (~90%) → Seq Scan. `id = 42` (1 row) → Index Scan. The selectivity crossover is clear.

### Planner Statistics
The planner uses pre-computed stats from `pg_statistic` (readable via `pg_stats`):
- **MCVs** — most common values and their frequencies. For `score` (101 distinct, uniform), all values listed with ~1% frequency each.
- **Histogram bounds** — equal-frequency buckets for range queries. `id` column has no MCVs (all unique, `n_distinct = -1.0`), uses histogram instead.
- **n_distinct** — negative means fraction of table that's distinct (-1.0 = 100% unique).

`ANALYZE` command samples ~30K rows and computes these. `autovacuum` runs ANALYZE when ~10% of rows change. Stale stats → bad row estimates → bad plans. Always ANALYZE after bulk loads.

### Joins
**Nested Loop**: for each outer row, run inner side. Best when outer is small + inner has index. Execution order: outer first, then inner per row.

**Hash Join**: build hash table from smaller side, probe with larger side. Execution order: inner (build) first, then outer (probe). The hash table must be complete before probing begins — that's why `startup cost = total cost` on the Hash node. Tested: 5K users × 1M orders → Hash Join with 320kB hash table, single batch.

**Merge Join**: sort both sides, merge in one pass. Efficient when inputs are pre-sorted or very large.

The planner switches strategies based on data size: 1 user → Nested Loop (1 inner lookup), 5000 users → Hash Join (hash table + single pass beats 5000 lookups).

### Sorting & work_mem
Three sort methods observed:
- **external merge** (Disk): work_mem too small, spills to temp files. 500K rows with 4MB work_mem → 26MB on disk, 334ms.
- **quicksort** (Memory): fits in work_mem. Same query with 64MB work_mem → 43MB in RAM, but *slower* at 1008ms (CPU cache thrashing on large data).
- **top-N heapsort**: `ORDER BY ... LIMIT 10` keeps only 10 rows in a tiny heap (26kB), scans all rows. 27ms vs 334ms — 12× faster, 1000× less memory.

Surprising finding: quicksort in memory was 3× slower than external merge on disk for 500K rows. External merge works with smaller cache-friendly chunks. More work_mem doesn't always mean faster.

### Diagnosing Bad Plans
Tested skewed data: 990K rows with status='common', 10K with unique status values.
- 'common' → planner estimated 989,067 (actual 990,000). Exact from MCV list. Picked Seq Scan correctly.
- 'rare_999999' → planner estimated 33 (actual 1). Not in MCV list, fell back to generic formula. Still picked Index Scan — wrong estimate didn't cause a bad plan here.

The diagnostic rule: compare estimated vs actual rows at every EXPLAIN ANALYZE node. The first node with large divergence is the root cause. Check `pg_stat_user_tables.last_analyze` for stale stats.

### Tool: pgvis explain
Built `pgvis explain "SQL"` command that runs EXPLAIN (ANALYZE, BUFFERS) and annotates every node:
- Shows full plan first, then step-by-step breakdown in execution order
- Groups nodes by role (OUTER/INNER/JOIN) with execution order explanation
- Annotates every field: rows (with ⚠ divergence warnings), cost (with formula for Seq Scan), time, buffers, conditions
- "Why this strategy?" section explains why the planner chose each scan/join type
- Handles Hash Join execution order correctly (build side first)
- Detects sort disk spills and hash batch overflows

---

## Retro

### Summary

Learned to read and reason about Postgres query execution plans. Started from the simplest possible EXPLAIN (single Seq Scan), built up to parallel Hash Joins with 6 nodes. Verified the cost model by computing Seq Scan cost by hand and matching EXPLAIN output exactly. Explored all three scan types on the same table by varying selectivity, saw the planner switch strategies. Understood where row estimates come from (pg_stats MCVs and histograms) and how stale or missing stats lead to bad plans. Built `pgvis explain` — a step-by-step annotated EXPLAIN tool that shows execution order, cost formulas, strategy reasoning, and divergence warnings.

### Key Takeaways

- The cost model is just arithmetic: `seq_page_cost × pages + cpu_tuple_cost × tuples + cpu_operator_cost × tuples`. Not a black box — you can calculate it by hand.
- `random_page_cost = 4.0` is the single most important number for scan strategy selection. It's why Index Scan loses to Seq Scan above ~10-20% selectivity — random I/O costs 4× sequential.
- Bitmap Heap Scan exists because there's a gap between "few rows" (Index Scan) and "most rows" (Seq Scan). It deduplicates pages and reads them sequentially — two wins.
- EXPLAIN text is a tree, not an execution sequence. For Hash Join, the build side (inner) runs first; for Nested Loop, the outer runs first. The text layout doesn't reflect this.
- Hash Join's `startup cost = total cost` on the Hash node — nothing comes out until the entire hash table is built. This is why the build side must complete before probing starts.
- `top-N heapsort` for ORDER BY...LIMIT is 1000× less memory and 12× faster than sorting everything. The planner detects the LIMIT and switches algorithm.
- More work_mem doesn't always mean faster. Quicksort on 43MB (in-memory) was 3× slower than external merge on 26MB (disk) for 500K rows — CPU cache locality matters more than avoiding disk at this scale.
- For unknown values not in the MCV list, the planner falls back to `remaining_frequency / remaining_distinct`. This produces a generic estimate that's often wrong for skewed data.
- The diagnostic rule: run EXPLAIN ANALYZE, compare estimated vs actual at every node. The first large divergence is the root cause.

### What I'd Do Differently

- Should have built `pgvis explain` earlier — it made every subsequent query much easier to understand. The tool-building paid for itself immediately.
- The work_mem experiment (quicksort slower than external merge) was a surprise worth digging into more. Could have profiled CPU cache misses to confirm the hypothesis.
- Could have demonstrated a join where bad row estimates actually cause the planner to pick the wrong strategy (e.g., Nested Loop on 100K rows). The skewed example showed bad estimates but not a bad plan choice.

### Connections

- **Ch 1 (Physical Storage)**: heap pages, visibility map (enables index-only scans), item pointers
- **Ch 2 (Shared Buffers)**: EXPLAIN BUFFERS shows shared hit vs read — direct measure of cache effectiveness. Ring buffer protects cache from large seq scans.
- **Ch 2b (OS Page Cache)**: `effective_cache_size` tells the planner how much total cache is available — influences random I/O cost estimates
- **Ch 3 (Transactions)**: every Seq Scan tuple undergoes a visibility check (snapshot evaluation). Bitmap Heap Scan's "Recheck Cond" also checks visibility.
- **Ch 4 (Architecture)**: work_mem is per-operation, not per-query — the multiplication problem (connections × operations × work_mem). Pipeline stages: planner builds the tree, executor runs it.
- **Ch 4b (Parsing)**: the analyzed query tree from parse → analyze → rewrite feeds directly into the planner
- **Ch 5b (Join Internals)**: hash batching when work_mem overflows, merge join duplicate handling — deferred
- **Ch 6 (Indexes)**: B-tree internals, index-only scans, covering indexes — how the index structures the planner relies on actually work
- **Ch 10 (Vacuum)**: autovacuum also runs ANALYZE — stale stats from skipped ANALYZE lead to bad plans

### Open Questions

- Why exactly is quicksort on 43MB slower than external merge on 26MB? Is it purely CPU cache, or does memory allocation overhead contribute?
- How does `effective_cache_size` actually change plan selection? We saw random_page_cost matters but didn't experiment with effective_cache_size.
- How does the planner estimate bitmap scan cost? The formula is more complex than seq scan — involves estimating how many distinct pages the matching rows span.
- What happens with prepared statements — does the planner cache a plan that's good for one parameter but bad for another (generic vs custom plan)?

---

## Deep Dive Ideas

Topics we touched on but would benefit from going much deeper — building it ourselves, reading the source, or benchmarking in detail.

### Scan internals
- **Seq Scan**: implement a page-by-page scanner in Go that reads heap pages, deserializes tuples, evaluates a filter. See the actual I/O pattern.
- **Index Scan**: walk a B-tree manually (pageinspect on index pages), follow TIDs to heap. Implement a simple B-tree lookup in Go.
- **Bitmap Heap Scan**: build a bitmap (bitset of page numbers) in Go, populate it from index entries, then read pages in sorted order. See how deduplication and sequential I/O emerge from the data structure.

### Join internals
- **Nested Loop**: implement in Go — outer iterator + inner iterator with index lookup. Measure the cost as outer size grows.
- **Hash Join**: build a hash table from one side, probe with the other. Implement single-batch and multi-batch (when hash table overflows work_mem). See how batch spilling to disk works.
- **Merge Join**: sort both sides, merge with two cursors. Handle duplicates (one-to-many joins). Compare performance against hash join at different data sizes.

### Statistics internals
- How ANALYZE samples rows (random page sampling, not sequential)
- How MCVs are selected (count frequencies in sample, keep top N)
- How histogram bounds are computed (equal-frequency bucketing from the sample)
- How `n_distinct` is estimated (number of distinct values in sample, extrapolated)
- Build a mini ANALYZE in Go: sample rows from a table, compute MCVs and histogram, compare against pg_stats

### Sort internals
- **Quicksort**: standard in-memory sort, how Postgres's tuplesort chooses pivot, memory layout
- **External merge sort**: split input into sorted runs that fit in work_mem, write to temp files, merge runs back. Implement in Go with configurable "work_mem"
- **Top-N heapsort**: maintain a min-heap of size N, scan all rows, replace root when a better row arrives. Implement and benchmark against full sort + limit
- Why external merge beat quicksort at 500K rows — profile cache misses, measure with different data sizes to find the crossover
