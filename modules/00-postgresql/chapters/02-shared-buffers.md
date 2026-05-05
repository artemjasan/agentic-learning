# Chapter 2: Shared Buffers & the Read/Write Path

## Findings

### What shared_buffers Is

A fixed chunk of shared memory (configured at startup, e.g. 128MB) divided into 8KB slots — one slot per page. All Postgres backends (connections) share the same buffer pool. When a query needs a page, it checks shared_buffers first. Cache hit = microseconds. Cache miss = load from disk/OS cache into a free slot.

### The Read Path

Measured with `EXPLAIN (ANALYZE, BUFFERS)`:
- `shared hit` = page found in shared_buffers (fast, ~µs)
- `shared read` = page loaded from disk/OS cache into shared_buffers (slower)

Observed on `cache_test` table (135MB, 17,280 pages):
```
Run 1: shared hit=2,236   read=15,044  → 23.0ms   (cold, parallel seq scan)
Run 2: shared hit=4       read=2       → 0.43ms   (warm, index-only scan)
Run 3: shared hit=6       read=0       → 0.35ms   (fully cached)
```

### Ring Buffer — Large Scan Protection

Sequential scans on tables larger than ~25% of shared_buffers use a ring buffer (~256KB) instead of flooding the cache. Verified: after a 135MB seq scan, `cache_test` only held 2,782 pages (~21MB) in shared_buffers, not all 17,280. All other cached relations (users, system catalogs, fsm_demo) survived untouched.

### Clock-Sweep Eviction

Not LRU — uses a clock-sweep algorithm. Each buffer slot has a usage count (0-5). Accessed pages get count incremented. The sweep hand decrements counts; evicts when it finds count=0. Cheap to implement (atomic counter, single pointer) vs LRU (linked list, lock contention).

Observed via `pgvis buffers`:
- `cache_test` pages at usage=1 (accessed once by seq scan, low priority)
- System catalog pages at usage=5 (frequently accessed, survive many sweeps)

### The Write Path

Writes modify pages IN shared_buffers, not on disk. The page is marked "dirty." The actual data file stays stale until a flush happens.

Why write to memory first:
- **Speed**: memory write ~0.1µs vs disk write ~100µs
- **Batching**: 50 UPDATEs to the same page = 1 disk write at checkpoint, not 50
- **Safety via WAL**: a small sequential WAL record ensures durability; full page flush can wait

Three ways dirty pages reach disk:
1. **Checkpointer** — periodic big flush (every ~5min or 1GB of WAL), writes ALL dirty pages
2. **Background writer** — continuous trickle, flushes low-usage dirty pages gradually
3. **Eviction flush** — if clock-sweep must evict a dirty page, it flushes first (worst case, causes query stall)

Verified: UPDATE 20 rows → `users dirty=3, users_pkey dirty=1`. CHECKPOINT → dirty counts drop to 0.

---

## Retro

### Summary

Explored shared_buffers as Postgres's page cache — a fixed pool of 8KB slots in shared memory. Measured the 1000x speed difference between cache hits and disk reads with EXPLAIN BUFFERS. Discovered the ring buffer that protects the cache from large sequential scans. Understood clock-sweep eviction (not LRU). Learned the write path: modifications happen in memory (dirty pages), flushed later by checkpointer/background writer, with WAL ensuring durability. Built `pgvis buffers` to visualize cache state.

### Key Takeaways

- Shared_buffers caches whole 8KB pages, not individual rows — same unit as disk I/O
- The cache doesn't proactively load "hot" data — it caches what queries request. Intelligence is in eviction (clock-sweep keeps frequently-accessed pages)
- Ring buffer prevents large seq scans from evicting the entire cache — a 135MB scan only kept ~21MB in the 128MB cache
- Writes go to memory first for speed (0.1µs vs 100µs) and batching (50 updates = 1 disk write). WAL handles durability.
- Dirty pages are NOT on disk until checkpoint/background writer flushes them

### What I'd Do Differently

- Could have demonstrated a truly cold cache by restarting Postgres (would have shown the full disk→cache loading time)
- The planner choosing different plans between runs was confusing — should have run ANALYZE first to stabilize plans

### Connections

- **Chapter 1 (Physical storage)**: shared_buffers caches the exact same 8KB pages we inspected with pageinspect
- **Chapter 8 (WAL)**: WAL is what makes the "write to memory, flush later" pattern safe — will see WAL records in detail
- **Cache algorithms topic (TOPICS.md)**: clock-sweep connects to implementing cache eviction algorithms from scratch

### Open Questions

- What's the actual cache hit ratio in a production-like workload? How do you monitor it?
- How does the background writer decide which dirty pages to flush and when?
