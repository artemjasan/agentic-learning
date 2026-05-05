# Chapter 1: Physical Storage

## Findings

### Where Data Lives on Disk

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

### Relation Forks

Each table has up to 3 files:
- **Main fork** (`16507`) — the heap data (pages with tuples)
- **FSM** (`16507_fsm`) — Free Space Map, tracks free space per page so INSERT doesn't scan every page
- **VM** (`16507_vm`) — Visibility Map, tracks all-visible and all-frozen pages; created on first VACUUM

The VM didn't exist until we ran VACUUM — it gets created lazily.

### Page Layout (8KB = 8192 bytes)

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

### Heap = Unordered Pile

Tables are "heap" files — rows stored in no particular order, wherever there's space. Even with a PRIMARY KEY, the heap isn't sorted. The index is a separate structure pointing into the heap.

This is different from MySQL InnoDB which uses a clustered index (data stored sorted by primary key).

### Tuple Structure

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

### Alignment (MAXALIGN)

Tuple start offsets must be 8-byte aligned on 64-bit systems. For a 54-byte tuple:
- 8192 - 54 = 8138, but 8138 isn't 8-byte aligned
- Rounds down to 8136 → tuple at bytes 8136-8189, bytes 8190-8191 are padding
- Cost: up to 7 "wasted" bytes per tuple

### Item Pointers (Line Pointers)

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

### Filenode vs OID

`relfilenode` starts equal to OID but changes when the physical file is rewritten:
```sql
SELECT oid, relfilenode FROM pg_class WHERE relname = 'users';
VACUUM FULL users;  -- relfilenode changes, OID stays the same
```

VACUUM FULL writes a new file → new relfilenode. Catalog, indexes, foreign keys all reference the OID which never changes.

### DELETE, Pruning, and VACUUM

DELETE doesn't remove data — it sets `xmax`. The tuple stays physically present.

**Page pruning** happens on next page access (not during DELETE): wipes tuple bytes, sets LP to `dead`. Any page read can trigger this — our `pgvis` query triggered it before we could see the raw dead tuples.

**Regular VACUUM**: sets dead LPs to `unused`, updates FSM with freed space, updates VM, removes dead index entries. Does NOT move rows between pages, does NOT shrink the file.

**VACUUM FULL**: rewrites entire table into new file, packs tightly, changes relfilenode, file actually shrinks. Requires exclusive lock (blocks all reads/writes).

Observed: after DELETE of 101 rows + VACUUM, FSM showed ~12KB free across 3 pages. After VACUUM FULL, all pages packed full again with fewer total pages.

### FSM and VM in Practice

FSM stores approximate free space per page (32-byte granularity) in a binary tree. INSERT checks FSM to find a page with room.

VM tracks two bits per page:
- `all_visible` — all tuples visible to all transactions → VACUUM can skip, index-only scans can skip heap
- `all_frozen` — all tuples frozen (xmin replaced with permanent marker) → never needs wraparound vacuum again

After VACUUM, we observed pages flipping to FROZEN state — Postgres freezes tuple xmin values to prevent transaction ID wraparound.

### Segment Files

Tables >1GB are split: `16507`, `16507.1`, `16507.2`, etc. Compile-time setting (`--with-segsize`). Originally a filesystem limitation workaround. Not worth changing on modern systems — the overhead is negligible and smaller files are easier for backup tools.

### Page Size Tradeoffs

Default 8KB. Compile-time setting (`--with-blocksize`).
- Larger pages (16-32KB): better for OLAP, wide rows, sequential scans. Fewer page headers per byte. But more wasted I/O for random reads.
- Smaller pages: better for OLTP with small random reads. But more page header overhead.
- Rarely changed in practice — 8KB is a good general-purpose balance.

### TOAST (brief)

Triggers when tuple exceeds ~2KB. Four strategies: PLAIN (never TOAST), EXTENDED (compress then move out-of-line), EXTERNAL (move without compression), MAIN (try to keep inline).

Observed: `repeat('x', 2000)` compressed from 2000 bytes to 35 bytes inline. `repeat('x', 1000000)` compressed to 11,452 bytes and moved to TOAST table. Compression can be dramatic for repetitive data. Full deep dive in Chapter 17.

---

## Retro

### Summary

Explored how PostgreSQL physically stores data on disk: 8KB pages with a split layout (item pointers growing down, tuples growing up), tuple headers carrying MVCC metadata (xmin/xmax), variable-length storage via varlena, and the three relation forks (main, FSM, VM). Built a visualization tool (pgvis) that made the internal structures tangible. Observed DELETE/VACUUM/VACUUM FULL behavior at the physical level — seeing dead tuples, page pruning, and FSM/VM updates with real data.

### Key Takeaways

- The page layout is a clever shared-free-space design — pointers and tuples grow toward each other, no pre-allocation needed
- Item pointers are the unsung hero — the indirection layer that lets tuples move without breaking index references. Same pattern appears at file level (OID vs relfilenode)
- DELETE doesn't delete. It sets xmax. Page pruning and VACUUM are separate cleanup passes, each with different scope
- `varchar(N)` max length is a constraint, not a storage allocation — a common misconception cleared up by looking at actual tuple bytes
- The FSM is a binary tree for O(log N) free space lookup — not a scan. Visualizing it made the algorithm click
- The VM is just 2 bits per page, but it enables two critical optimizations (vacuum skip, index-only scan heap skip)
- Regular VACUUM never shrinks the file — it reclaims space within pages. Only VACUUM FULL compacts, at the cost of an exclusive lock

### What I'd Do Differently

- Should have installed `pg_freespacemap` extension upfront before first FSM observation — missed seeing accurate FSM state after VACUUM FULL
- Could have caught dead-but-not-yet-pruned tuples by being more careful about page access triggering pruning
- The interactive learning format (user runs commands, discusses results) worked much better than agent-runs-everything — established this early

### Connections

- **Chapter 2 (Shared buffers)**: pages we saw on disk also live in shared_buffers — the caching layer sits between these files and queries
- **Chapter 6 (MVCC)**: xmin/xmax in tuple headers are the foundation — we saw them but didn't yet understand visibility rules
- **Chapter 7 (Vacuum & bloat)**: we saw VACUUM/VACUUM FULL behavior physically; the dedicated chapter will cover tuning, autovacuum, and bloat measurement
- **Chapter 4 (Query execution)**: VM's all_visible flag enables index-only scans — will see this in EXPLAIN output
- **Chapter 17 (TOAST)**: briefly saw compression (2000 chars → 35 bytes); full deep dive with all strategies later
- **Cache algorithms topic (TOPICS.md)**: Postgres's clock-sweep in shared_buffers connects to implementing LRU/LFU/ARC from scratch

### Open Questions

- Why did the FSM show 0 free for all pages after VACUUM FULL when the last page was clearly not full? Timing/extension installation issue, or something deeper?
- How exactly does page pruning decide when to trigger? Is it every page access or only certain operations?
