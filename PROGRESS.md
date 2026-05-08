# Progress

**Branch:** `study/from-scratch` — personal track: working through the material **from scratch**, with your own hands and notes. `main` on `origin` is a friend's original lab repo that has moved on — we keep their write-ups and code as **reference**, not as “our” completed milestones.

## Current Focus

**PostgreSQL** (`modules/00-postgresql/`) — **Chapter 1: Physical Storage**  
Goal: run the environment, follow the plan in `chapters/01-physical-storage.md`, capture your conclusions (chapter **`Findings` / `Retro`**, optional personal notes).

**Now:** finished **Steps A–E** (page layout, Lower/Upper, tuple header, Step E — line pointers and index). **Next — Step F:** `DELETE` a row, then inspect **`t_xmax`** via `heap_page_items` / `pgvis`; paused until the next session. Details: `chapters/01-physical-storage.md` → **Your findings** → **Where we stopped**.

## Completed

*(empty for now — add chapters here as you finish them)*

## Next Up

- Finish Chapter 1 (heap pages, tuple header, FSM/VM, `pgvis` / `pageinspect`)
- Then Chapter 2 — shared buffers and the read/write path

## Reference — friend's `main` (upstream lab notes)

These are **their** chapter summaries and tooling from the original repo on `main` / `origin`. Useful when you want context or to peek ahead; **not** a record of how far *you* are.

### Chapter 4b: SQL Parsing Internals ✅ (2026-05-08)

Built full pre-planner pipeline from scratch in Go: lexer (tokenizer), recursive descent parser, analyzer (with lazy catalog cache mirroring Postgres SysCache), rewriter (view expansion). Used pg_query_go to compare with real Postgres parser output. sqlparse tool with 5 commands: parse, lex, myparse, analyze, rewrite.

### Chapter 5: Query Execution & EXPLAIN ✅ (2026-05-11)

EXPLAIN output structure, cost model (verified by hand calculation), three scan types (Seq Scan, Index Scan, Bitmap Heap Scan) and the selectivity crossover, planner statistics (MCVs, histograms, pg_stats), three join strategies (Nested Loop, Hash Join, Merge Join), sorting (external merge vs quicksort vs top-N heapsort), work_mem effects, diagnosing bad plans. Built `pgvis explain` tool with step-by-step annotated output, strategy explanations, and cost formula breakdowns.

### Chapter 5b: Join Internals ✅ (2026-05-12)

Join algorithms visualized step by step: Nested Loop (O(N×M)), Hash Join (build + probe, O(N+M)), Merge Join (sort + merge). Join types (INNER, LEFT, RIGHT, FULL) orthogonal to algorithms. Built `pgvis join` interactive slideshow with ← → navigation, showing data, strategy, step-by-step execution, and when the planner picks each.

### Chapter 6: Indexes ✅ (2026-05-14)

B-tree internals: page layout (item pointers → index tuples, high key, special area), tree structure (depth 3 for 500K rows, fan-out ~350), lookup trace (root → internal → leaf → heap → MVCC). Index-only scans + visibility map. Multi-column leftmost prefix rule. Partial indexes (skip writes for non-matching rows). Index types: Hash (O(1) but loses everything else), BRIN (min/max per block range, tiny), GIN (inverted for arrays/JSONB). Write amplification, MVCC interaction (no xmin/xmax in indexes, ghost entries). CREATE INDEX CONCURRENTLY (sort-then-build, two-pass, never blocks writes). Built `pgvis index` tools: tree, page, lookup, range.

**Where their track goes next:** Chapter 7 (MVCC Under the Hood) or Chapter 8 (Vacuum & Bloat).
