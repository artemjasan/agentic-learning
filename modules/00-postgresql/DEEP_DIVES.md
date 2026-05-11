# Deep Dive Backlog

Topics we encountered during study but deferred for later hands-on exploration. Each links back to the chapter where it came up.

## Build from scratch

- **Scan engines** — implement Seq Scan, Index Scan, Bitmap Heap Scan in Go. Read real heap pages, deserialize tuples, evaluate filters. → [Ch 5](chapters/05-query-execution.md#scan-internals)
- **Join algorithms** — Nested Loop, Hash Join (single + multi-batch), Merge Join in Go. Benchmark crossover points. → [Ch 5](chapters/05-query-execution.md#join-internals)
- **Sort algorithms** — quicksort, external merge sort, top-N heapsort in Go with configurable memory budget. Profile cache misses. → [Ch 5](chapters/05-query-execution.md#sort-internals)
- **Mini ANALYZE** — sample rows, compute MCVs, histogram bounds, n_distinct. Compare against pg_stats. → [Ch 5](chapters/05-query-execution.md#statistics-internals)
- **SQL parser pipeline** — lexer, recursive descent parser, analyzer, rewriter (already done). → [Ch 4b](chapters/04b-parsing-internals.md)

## Investigate

- **Bitmap scan cost formula** — how the planner estimates distinct pages from selectivity. More complex than seq scan. → [Ch 5](chapters/05-query-execution.md#open-questions)
- **effective_cache_size** — how it changes plan selection in practice. → [Ch 5](chapters/05-query-execution.md#open-questions)
- **Generic vs custom plans** — prepared statement plan caching, when a cached plan hurts. → [Ch 5](chapters/05-query-execution.md#open-questions)
- **Quicksort vs external merge performance** — why in-memory sort was 3× slower at 500K rows. Cache miss profiling. → [Ch 5](chapters/05-query-execution.md#sort-internals)
- **Page pruning trigger** — when exactly does a page access trigger dead tuple cleanup? → [Ch 1](chapters/01-physical-storage.md#open-questions)
- **FSM after VACUUM FULL** — why FSM showed 0 free for non-full pages. → [Ch 1](chapters/01-physical-storage.md#open-questions)
- **Cache hit ratio monitoring** — how to measure and tune in production-like workloads. → [Ch 2](chapters/02-shared-buffers.md#open-questions)
- **Background writer policy** — how it picks which dirty pages to flush and when. → [Ch 2](chapters/02-shared-buffers.md#open-questions)
