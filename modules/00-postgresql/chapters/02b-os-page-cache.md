# Chapter 2b: OS Page Cache, Double-Caching & Tuning

## Findings

### Why Postgres Needs Its Own Cache

The OS page cache is a dumb byte cache — it caches every file read automatically but has no awareness of Postgres semantics. Postgres needs shared_buffers for:

1. **Shared memory** — all backends (separate processes) share the same buffer slots. Without it, 10 connections reading the same page = 10 copies in process memory.
2. **Dirty page control** — Postgres must ensure WAL is written before dirty data pages. OS cache can flush whenever it wants — no control over write ordering.
3. **Pinning** — backends pin buffer slots during reads/writes so pages can't be evicted mid-operation. OS cache has no pinning concept.
4. **Buffer locks** — concurrent access to the same page needs lightweight locks for coordination.

### The Double-Caching Problem

Every page read by Postgres goes through the OS page cache (Linux always caches file reads). After loading into shared_buffers, the same page exists in both caches. This is wasteful but unavoidable — Postgres can't opt out of OS caching without `O_DIRECT` (which Postgres doesn't use by default because it loses OS read-ahead benefits).

### Page Size Alignment

Postgres pages (8KB) = 2× OS pages (4KB) = 2× disk blocks (4KB). Clean alignment is intentional — avoids straddling OS page boundaries during I/O.

### Tuning Rule: 25% of RAM

Set `shared_buffers` to ~25% of total RAM. Leave the rest for OS page cache + application memory. If shared_buffers is too high (e.g., 90% of RAM), the OS cache starves and sequential scans lose read-ahead benefits. If too low, Postgres relies more on the OS cache (extra syscalls per page access).

---

## Retro

### Summary

Understood why Postgres needs its own cache despite the OS already caching file reads: shared memory across processes, dirty page write ordering (WAL-before-data), pinning during access, and buffer-level locking. The double-caching (same page in both shared_buffers and OS page cache) is unavoidable but explains the 25% tuning rule — leave room for the OS cache. Page size alignment (8KB = 2× OS 4KB pages) is intentional for I/O efficiency.

### Key Takeaways

- Postgres calls read() and the OS transparently returns data from its cache or disk — Postgres doesn't know which
- OS always caches file reads — double-caching is unavoidable without O_DIRECT
- shared_buffers = smart cache (shared, pinnable, lockable, write-ordered). OS cache = dumb byte cache (fast, transparent, no control).
- 25% of RAM for shared_buffers leaves 75% for OS cache + apps. Going higher starves the OS cache.

### Connections

- **Chapter 8 (WAL)**: write ordering (WAL before data pages) is the key reason Postgres can't delegate dirty page management to the OS
- **Cache algorithms topic**: could experiment with O_DIRECT to measure double-caching overhead
