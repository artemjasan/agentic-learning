# Chapter 5b: Join Internals

## Plan

### 1. The join problem
What a join actually does at the mechanical level: given two sets of rows and a condition, produce all matching pairs. The three algorithms are three different answers to the same problem, each with different tradeoffs in CPU, memory, and I/O. We'll build all three in Go, reading real rows from Postgres, and compare them against each other and against Postgres's own execution.

### 2. Nested Loop Join
The simplest: for each row in the outer set, scan the inner set for matches. O(N×M) in the worst case. Implement in Go with two variants:
- **Naive**: double loop, no index. Baseline performance.
- **With index lookup**: simulate what Postgres does — outer loop drives, inner side does an indexed lookup per row.

*Hands-on:* Implement both variants. Join `big_users` (filtered) with `orders`. Compare row counts against Postgres. Benchmark at different outer sizes (1, 10, 100, 1000 rows) to see the N×M scaling.

### 3. Hash Join
Two-phase algorithm: build a hash table from the smaller side, probe it with each row from the larger side. O(N+M) time, O(smaller) memory. Implement in Go:
- **Single-batch**: entire build side fits in memory. Hash on the join key, probe with each outer row.
- **Multi-batch**: build side exceeds a configurable memory budget. Split into batches using hash partitioning — rows that don't fit go to temp files on disk. Process one batch at a time.

*Hands-on:* Implement single-batch first, verify correctness. Then add a memory budget (e.g., 1MB) and implement batch spilling. Compare batch count against Postgres's Hash Batches in EXPLAIN.

### 4. Merge Join
Sort both sides by the join key, then merge with two cursors in a single pass. O(N log N + M log M) for sorting, O(N+M) for the merge. Implement in Go:
- Handle the one-to-many case: when multiple rows on one side match the same key, need to "rewind" and re-read the duplicates.
- Pre-sorted inputs skip the sort step entirely.

*Hands-on:* Implement the merge. Test with pre-sorted inputs (skip sort) and unsorted inputs (sort first). Handle duplicate join keys correctly.

### 5. Comparison and crossover
Run all three implementations on the same data at different scales. Find the crossover points: when does Hash Join beat Nested Loop? When does Merge Join beat Hash Join? Compare against Postgres's choices.

*Hands-on:* Benchmark matrix — varying outer size, inner size, selectivity, memory budget. Plot or tabulate results. Force Postgres to use each strategy and compare timings.

### What you'll know after this chapter
- How each join algorithm works at the implementation level, not just conceptually
- Why Hash Join needs equality conditions (you can't hash a range comparison)
- How multi-batch hash join handles memory overflow — the same problem work_mem solves
- When Merge Join wins (pre-sorted data, very large inputs)
- The mechanical reason Nested Loop is best for small outer + indexed inner

### Out of scope
- Parallel join execution (worker coordination)
- Semi-joins, anti-joins (EXISTS, NOT EXISTS optimizations)
- Lateral joins
- Join order optimization (the planner's search through join permutations)

---

## Findings

### Join types vs join algorithms
Two orthogonal concepts: the **join type** (INNER, LEFT, RIGHT, FULL OUTER) decides which rows appear in the result. The **join algorithm** (Nested Loop, Hash, Merge) decides how to find the matching rows efficiently. You choose the type in SQL; the planner chooses the algorithm. Any algorithm can execute any join type.

### Nested Loop
Double for-loop: for each outer row, scan every inner row. O(N×M). Simple but scales badly. The planner picks it when the outer side is tiny (1-50 rows) and the inner has an index — each inner lookup becomes O(log M) instead of O(M). Visualized step-by-step with 5 users × 8 orders = 40 comparisons.

### Hash Join
Two phases. Build: load the smaller side into a hash table keyed by the join column. Probe: scan the larger side, hash each join key, O(1) lookup. Total O(N+M) vs Nested Loop's O(N×M). Requires equality condition (can't hash a range). The planner picks it for medium-to-large sides when the hash table fits in work_mem. Visualized with 8-bucket hash table showing insertions and probes.

### Merge Join
Sort both sides by join key, then merge with two cursors in one forward pass. O(N log N + M log M + N + M). The planner picks it when both sides are pre-sorted (free from an index) or very large. Also works with range conditions, unlike Hash Join. Visualized with sorted lists and cursor advancement rules (left < right → advance left, left > right → advance right, equal → match).

### When the planner picks each algorithm

**Nested Loop** — the planner's go-to when one side is small.

The key factor is the outer row count. If the outer side returns 1-50 rows and the inner side has an index on the join column, each inner lookup is a B-tree traversal (O(log N), ~3-4 pages). Total cost: `outer_rows × index_lookup_cost`. For 1 row, that's 1 lookup — unbeatable.

Example: `SELECT * FROM orders o JOIN users u ON u.id = o.user_id WHERE u.id = 42` — 1 user drives the loop, index on orders.user_id does 1 lookup. Postgres saw this as Nested Loop with Index Scan on the inner side, cost 24.76.

Falls apart when the outer side grows: 5,000 outer rows × index lookup each = 5,000 random I/O operations. At that point Hash Join wins.

**Hash Join** — the planner's choice for medium-to-large equality joins.

The key factors: (1) equality condition (`=`) on the join column — you can't hash a `<` or `>`, (2) the smaller side fits in `work_mem` as a hash table. Build phase loads the smaller side into a hash table, probe phase scans the larger side with O(1) lookups. Total: O(N+M) — one pass through each side.

Example: `SELECT * FROM users u JOIN orders o ON o.user_id = u.id WHERE u.score = 42` — 5,047 users × 1M orders. Hash table from users used 320kB (1 batch), single pass through orders. Postgres showed Hash Join, cost 17,137 vs Nested Loop's estimated 5,000 × index_lookup = much more.

If the hash table overflows work_mem, Postgres splits into multiple batches (visible as `Hash Batches: N` in EXPLAIN). Each batch spills to temp files on disk — slower but still better than Nested Loop at scale.

**Merge Join** — the planner's choice when data arrives pre-sorted or both sides are huge.

The key factors: (1) both inputs can be sorted cheaply (already sorted by an index, or the sort is needed for ORDER BY anyway), (2) both sides are very large (hash table would overflow work_mem badly), (3) the join uses range conditions (`<`, `>`, `BETWEEN`) which Hash Join can't handle.

Example: `SELECT * FROM users u JOIN orders o ON o.user_id = u.id ORDER BY u.id` — if both sides come from index scans sorted by the join key, the sort step is free and the merge is a single forward pass. Also used for `JOIN ... ON o.date BETWEEN u.start_date AND u.end_date` where hashing is impossible.

Rare in practice — Hash Join handles most equality cases, Nested Loop handles small-outer cases. Merge Join fills the gap: pre-sorted data, range joins, or extreme scale where hash table batching would be too expensive.

### Join type behavior
With sample data where dave and eve have no orders, and orders uid=99,55,88 have no matching user:
- **INNER**: 5 matched rows. Unmatched rows from both sides excluded.
- **LEFT**: 7 rows. dave, eve kept with NULL order. Unmatched orders excluded.
- **RIGHT**: 8 rows. uid=99,55,88 kept with NULL user. Unmatched users excluded.
- **FULL OUTER**: 10 rows. All unmatched rows from both sides kept with NULLs.

### Tool: pgvis join
Built `pgvis join {nested|hash|merge}` — interactive slideshow visualization of each join algorithm. Navigate with ← → arrow keys. Features:
- Shows the SQL query and both tables on the first frame
- Explains the algorithm strategy and when the planner picks it, with example queries
- Step-by-step walkthrough showing comparisons, cursor positions, hash table state
- `--type {inner|left|right|full}` flag shows different join types with appropriate SQL and result explanation
- Progress bar and match counter throughout
- Summary with complexity analysis and comparison between algorithms

---

## Retro

### Summary
Built an interactive visualization tool for all three join algorithms with all four join types. The key insight: join type (SQL concept — which rows to keep) is orthogonal to join algorithm (execution concept — how to find matches). The visualization makes each algorithm's mechanics visible — especially Hash Join's build/probe phases and Merge Join's cursor advancement rules.

### Key Takeaways
- Nested Loop is O(N×M) but wins when N is tiny and inner has an index
- Hash Join is O(N+M) but needs equality conditions and the hash table must fit in work_mem
- Merge Join wins when data is pre-sorted or both sides are too large for a hash table
- LEFT/RIGHT/FULL only affect what happens with unmatched rows — the matching algorithm is the same
- You write the join type; the planner picks the algorithm

### Connections
- **Ch 5 (Query Execution)**: saw these algorithms in EXPLAIN output, now understand their mechanics
- **Ch 5 (work_mem)**: Hash Join's hash table uses work_mem; overflow → multi-batch (not yet implemented in visualization)
- **Ch 5 (pgvis explain)**: "Why this strategy?" explanations connect to what we visualized here

### Open Questions
- Multi-batch hash join: what does the disk spill look like? How does Postgres partition rows across batches?
- Semi-joins and anti-joins: how do EXISTS/NOT EXISTS optimize the join to stop early?
