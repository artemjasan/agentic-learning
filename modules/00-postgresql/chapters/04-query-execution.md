# Chapter 4: Query Execution & EXPLAIN

## Plan

### 1. Query lifecycle
What happens between typing `SELECT` and getting rows back. The five stages: **parse** (SQL text → parse tree), **analyze** (resolve names, check types), **rewrite** (apply rules/views), **plan** (choose the best execution strategy), **execute** (run it). Brief and conceptual — the goal is orientation, knowing where the planner and executor sit in the pipeline.

### 2. The executor model
Postgres uses the **Volcano model** — a pull-based iterator tree. Each node in the plan implements `Init → Next → End`. The top node pulls a row, which causes its children to pull from their children, all the way down to the scan nodes touching actual heap pages. This is why EXPLAIN output is a tree, and understanding it makes every EXPLAIN readable.

*Hands-on:* Run a simple multi-node query (e.g., `SELECT ... WHERE ... ORDER BY ...`), trace the tree top-down and bottom-up.

### 3. Reading EXPLAIN
Start with a simple query, learn the output format:
- Node type (Seq Scan, Sort, etc.)
- **Cost** — `startup_cost..total_cost` (what these numbers actually represent)
- **Rows** — estimated row count
- **Width** — average row width in bytes

Then progressively add flags:
- `EXPLAIN ANALYZE` — actual rows, actual time, loops. Compare estimated vs actual.
- `EXPLAIN (ANALYZE, BUFFERS)` — shared hit vs read (direct connection to Ch 2 shared_buffers).
- `EXPLAIN (ANALYZE, BUFFERS, TIMING)` — per-node timing.

Build intuition by running the same query with each flag level.

### 4. The cost model
How the planner turns a plan into a number. The key constants:
- `seq_page_cost` (1.0) — cost of reading one page sequentially
- `random_page_cost` (4.0) — cost of reading one random page (4× sequential)
- `cpu_tuple_cost` (0.01) — cost of processing one tuple
- `cpu_index_tuple_cost` (0.005) — cost of processing one index entry
- `cpu_operator_cost` (0.0025) — cost of evaluating one operator/function
- `effective_cache_size` — planner's estimate of total available cache (shared_buffers + OS cache)

*Hands-on:* Calculate the expected cost of a sequential scan by hand (`seq_page_cost × pages + cpu_tuple_cost × tuples`), compare against EXPLAIN output. Understand why random I/O costs 4× sequential.

### 5. Sequential scan
The simplest scan: read every page, check every tuple. When it wins (small tables, low selectivity, no usable index). Cost formula applied to a real table. Observe how each tuple undergoes a visibility check (Ch 3 connection — snapshot evaluation on every row).

*Hands-on:* Run a seq scan on the `users` table, verify cost calculation, then add a WHERE clause and see the Filter node appear. Check how many rows are filtered vs returned.

### 6. Index scan variants
Three strategies the planner chooses from, each for different situations:
- **Index Scan** — walk the B-tree, fetch heap tuples one by one via random I/O. Good for high selectivity (few rows). Costly when many rows match (lots of random reads).
- **Index Only Scan** — answer entirely from the index, skip the heap. Only works when all needed columns are in the index AND the visibility map says the page is all-visible (Ch 3 connection). Falls back to heap fetch for non-visible pages.
- **Bitmap Heap Scan** — two phases: (1) scan index, build a bitmap of matching page numbers, (2) read those pages in physical order. Converts random I/O to sequential. Good for medium selectivity.

*Hands-on:* Create an index, run the same query with different WHERE selectivity to trigger each scan type. Use `SET enable_seqscan = off` etc. to force specific strategies and compare costs. Find the crossover point where the planner switches from index scan to seq scan.

### 7. Planner statistics
Where the row estimates come from. The planner doesn't look at actual data — it uses pre-computed statistics in `pg_statistic`:
- **Most Common Values (MCVs)** — the N most frequent values and their frequencies
- **Histogram bounds** — equal-frequency buckets for range queries
- **n_distinct** — estimated number of distinct values
- **correlation** — physical vs logical ordering (affects index scan cost)

The `ANALYZE` command: how it works (random sample of 30,000 rows by default), `default_statistics_target`, when stats go stale.

*Hands-on:* Query `pg_stats` for a column, read the histogram and MCVs. Delete all stats (`DELETE FROM pg_statistic`), see the planner go blind (terrible estimates). Run `ANALYZE`, see estimates snap back.

### 8. Joins (planner level)
Three strategies at a high level — when the planner picks each and why:
- **Nested Loop** — for each row in outer, scan inner. Good when outer is small or inner has an index.
- **Hash Join** — build hash table from smaller side, probe with larger. Good for equality joins on larger sets.
- **Merge Join** — sort both sides, merge. Good when both sides are pre-sorted or very large.

Focus: reading join nodes in EXPLAIN, understanding cost estimates, seeing the planner switch strategies based on data size and indexes. Deep algorithm internals (hash batching, merge duplicate handling) → Chapter 4b.

*Hands-on:* Create two tables with a foreign key, run joins with different sizes and indexes to trigger each strategy. Compare costs and actual times.

### 9. Sorting, aggregation & work_mem
- **Sort** — in-memory (quicksort) vs on-disk (external merge sort). Controlled by `work_mem`. The `Sort Method` line in EXPLAIN ANALYZE tells you which happened.
- **Aggregate** — plain (single group), sorted (GroupAggregate, needs sorted input), hashed (HashAggregate, builds hash table in memory).
- **Limit + Top-N sort** — Postgres optimizes `ORDER BY ... LIMIT N` with a heap-based top-N sort instead of sorting everything.

*Hands-on:* Run a sort, check EXPLAIN for "Sort Method: quicksort Memory: ...". Lower `work_mem`, see it switch to "external merge Disk: ...". Observe the performance difference.

### 10. Diagnosing bad plans
Practical scenarios where the planner picks the wrong plan:
- **Stale statistics** — data changed but ANALYZE hasn't run
- **Correlated columns** — planner assumes independence, real data is correlated
- **Skewed distributions** — most values are rare, but one value has millions of rows
- **Row estimation cascade** — one bad estimate propagates up the tree, wrong join order

*Hands-on:* Create a table with skewed data, observe the planner's estimate vs reality. Use `pg_stat_user_tables` to check when ANALYZE last ran.

### Next: Chapter 4b — Join Internals
Deep dive into how each join algorithm works under the hood: hash table construction and probing, multi-batch hash joins when work_mem overflows, merge join with duplicates, nested loop optimizations. Separate sub-chapter to keep Ch 4 focused on reading and understanding plans.

### Out of scope (deferred)
- Index internals (B-tree page layout, page splits, GIN/GiST) → Chapter 6/11
- Parallel query execution
- Prepared statement plan caching / generic vs custom plans
- JIT compilation
- CTEs and subquery optimization

---

## Findings

*(filled in as we go)*

---

## Retro

*(end of chapter)*
