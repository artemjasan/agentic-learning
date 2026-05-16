# Progress

**Branch:** `study/from-scratch` — personal track: working through the material **from scratch**, with your own hands and notes. `main` on `origin` is a friend's original lab repo that has moved on — we keep their write-ups and code as **reference**, not as “our” completed milestones.

## Study protocol (with Cursor / AI)

- **English:** use English for explanations, questions, and your own notes (vocabulary + consistency with upstream docs).
- **Visualization:** treat **`pgvis`** (`modules/00-postgresql/tools/pgvis/`) as the default way to *see* heap pages, the free-space map, and the visibility map — not only raw `pageinspect` / `psql` rows.
- **Pace (mandatory):** work in **small steps**. Each step = **full tool output** shown in the chat (e.g. complete `pgvis` screen) + **exactly one short question** to settle before moving on.
- **Evidence:** paste the same snippets into the chapter’s **Your findings** (e.g. `chapters/01-physical-storage.md`) or a personal note file so the lab stays reproducible.
- **Chapter files as curriculum:** when designing steps, examples, and questions, **use the matching file under** `modules/00-postgresql/chapters/*.md` **as the source of required concepts** — the **Plan** (ordered exercises), numbered sections, diagrams, and the filled-in **Findings** / **Retro** (treat those as a *reference run* after you have tried yourself, per each chapter’s intro). Stay consistent with terminology and tool commands already used there.

## Current Focus

**Paused** — pick up with **Chapter 2b** or a short **Chapter 2 Retro** when you return.

**PostgreSQL** (`modules/00-postgresql/`) — **Chapter 2: Shared Buffers** — **hands-on Plan §1–§5 done** (see `chapters/02-shared-buffers.md` → **Your findings**). Introduction + theory added to the chapter file; lab tables: `ch2_read_demo`, `ch2_ring_demo`.

## Completed

### Chapter 2 — Shared Buffers (hands-on, personal track) — paused 2026-05-16

- **§1:** `shared_buffers` = 128 MB, 16,384 × 8 KiB slots; `pgvis buffers` (pool utilization, cached relations).
- **§2:** Cold vs warm seq scan on `ch2_read_demo` — `shared read=1472` (~52 ms) then `shared hit=1472` (~5 ms); disk copy still exists alongside RAM.
- **§3:** Ring buffer on `ch2_ring_demo` (~116 MB) — ~14,848 heap pages on disk, only ~2,586 stayed in pool after big scan; `lesson1_items` not evicted.
- **§4:** Clock-sweep usage counts (`usage=1…5`); `ch2_ring_demo` avg_usage≈1 vs hot catalog pages (e.g. `pg_operator` at 5).
- **§5:** `UPDATE` on `users` → dirty heap/index pages; `CHECKPOINT` → dirty=0; visibility = **commit + MVCC**, not checkpoint.

### Chapter 1 — Physical Storage (hands-on, personal track)

- Plan **§1–§6** done (heap layout, MVCC delete/vacuum, FSM/VM, `VACUUM FULL` copy, TOAST skim). Optional: **Retro** in `01-physical-storage.md` + move here when you “close” Ch 1.

## Next Up

- **Chapter 2b** — `chapters/02b-os-page-cache.md` (OS page cache, double caching, ~25% tuning rule)
- Optional: **Chapter 2 Retro** in `02-shared-buffers.md`; optional Ch 1 **Retro** + `ls` on `base/<db_oid>/` from Ch 1 Plan §1

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
