# Progress

**Branch:** `study/from-scratch` — personal track: working through the material **from scratch**, with your own hands and notes. `main` on `origin` is a friend's original lab repo that has moved on — we keep their write-ups and code as **reference**, not as “our” completed milestones.

## Study protocol (with Cursor / AI)

- **English:** use English for explanations, questions, and your own notes (vocabulary + consistency with upstream docs).
- **Visualization:** treat **`pgvis`** (`modules/00-postgresql/tools/pgvis/`) as the default way to *see* heap pages, the free-space map, and the visibility map — not only raw `pageinspect` / `psql` rows.
- **Pace (mandatory):** work in **small steps**. Each step = **full tool output** shown in the chat (e.g. complete `pgvis` screen) + **exactly one short question** to settle before moving on.
- **Evidence:** paste the same snippets into the chapter’s **Your findings** (e.g. `chapters/01-physical-storage.md`) or a personal note file so the lab stays reproducible.
- **Chapter files as curriculum:** when designing steps, examples, and questions, **use the matching file under** `modules/00-postgresql/chapters/*.md` **as the source of required concepts** — the **Plan** (ordered exercises), numbered sections, diagrams, and the filled-in **Findings** / **Retro** (treat those as a *reference run* after you have tried yourself, per each chapter’s intro). Stay consistent with terminology and tool commands already used there.

## Current Focus

**PostgreSQL** (`modules/00-postgresql/`) — **Chapter 2: Shared Buffers & Read/Write Path** (next)  
Follow `chapters/02-shared-buffers.md` **Plan** first; same study protocol (English, `pgvis` where it fits, evidence in **Your findings**).

**Chapter 1 (personal track) — where you left off:** core **Plan §1–§6** hands-on is done in the lab: heap layout, tuples, line pointers, **`DELETE` / `xmax`**, **`VACUUM`**, **`VACUUM FULL`** on a copy (**`oid` vs `relfilenode`**), **FSM / VM** (`pgvis` + `pg_visibility`), **TOAST skim** (`ch1_toast_demo` + `pgvis page --no-data` vs `pg_toast_*`). Segment files and page-size tradeoffs were covered **read / discuss** (no multi-GB demo in this clone). Optional: if you never did it, one **`ls`** in the container on `base/<db_oid>/<relfilenode>*` from Plan §1 — quick closure.

## Completed

*(Chapter 1 not moved here yet — add when you write a short **Retro** in the chapter and call the chapter “closed” for your track.)*

## Next Up

- **Chapter 2** — `chapters/02-shared-buffers.md` (shared_buffers, read path, `pgvis buffers`, double-buffering intro toward Ch 2b)
- Optional: Chapter 1 **Retro** paragraph in `01-physical-storage.md` + then mark Ch 1 complete in this file

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
