# Chapter 3: Transactions & Basic Concurrency

## Findings

### Transaction IDs

Every write transaction gets a **transaction ID (xid)** — a monotonically increasing 32-bit counter in shared memory. Read-only transactions don't get one; they use lightweight virtual xids (e.g., `91/2`) to avoid wasting counter space. The real xid is assigned lazily, on the first write statement, not at `BEGIN`.

### xmin / xmax Mechanics

The tuple header carries two xid fields that drive all visibility decisions:

- **INSERT**: creates a new tuple, `xmin = current xid`, `xmax = 0`
- **UPDATE**: sets `xmax` on the old tuple, creates a new tuple with `xmin = current xid`, `xmax = 0`. The old tuple's `ctid` points forward to the new one (update chain). Both tuples exist physically on the page.
- **DELETE**: sets `xmax` on the tuple. No new tuple created.

None of these operations modify existing tuple data in-place. Postgres only appends new tuples and marks old ones.

### CLOG (Commit Log)

A compact bitmap where every xid maps to 2 bits: `IN_PROGRESS`, `COMMITTED`, `ABORTED`, or `SUB_COMMITTED`. This is how Postgres answers "did transaction X commit?" without scanning the WAL.

Abort does not undo physical changes — xmax values written by a rolled-back transaction remain on the tuples. The CLOG entry flips to ABORTED, and future readers ignore the xmax.

### Hint Bits

Checking the CLOG on every tuple read is expensive. The first backend to check a tuple's xmin/xmax status writes the result directly onto the tuple header as flag bits: `XMIN_COMMITTED`, `XMIN_ABORTED`, `XMAX_COMMITTED`, `XMAX_ABORTED`. After that, future reads skip the CLOG.

Consequence: a pure SELECT can dirty a page in shared_buffers by setting hint bits. This triggers checkpoint I/O even though no "real" data changed.

### Visibility Rule

A tuple is visible when:
1. `xmin` is committed (tuple is "born")
2. `xmax` is zero OR `xmax` is not committed (tuple is still "alive")

This rule applies to every tuple on every read.

### Snapshots

A snapshot freezes the question "committed as of when?" into three fields:

- **xmin**: all xids below this are finished
- **xmax**: all xids at or above this haven't started yet
- **xip_list**: in-progress xids between xmin and xmax

Example: `878:880:878` means transactions < 878 are done, >= 880 don't exist yet, and 878 is still running (even though 879 committed). This is how Postgres sees 879's changes but hides 878's.

In **READ COMMITTED** (default), every statement takes a fresh snapshot. That's why a transaction can see data committed after it started — each SELECT re-evaluates.

In **REPEATABLE READ**, the snapshot is taken once at the first statement and frozen for the entire transaction.

### Concurrent Writes

Reads never block reads (MVCC). But writes to the same row cause blocking:

1. T1 updates a row → sets xmax, takes row-level lock
2. T2 tries to update the same row → sees xmax set by in-progress T1 → blocks
3. T1 commits → T2 wakes up, re-reads the row, applies its update to T1's new version
4. T1 rolls back → T2 wakes up, updates the original row (T1 never happened)

Last writer wins in READ COMMITTED.

### Transaction ID Wraparound

The xid counter is 32-bit (~4.2 billion values). Postgres uses modular arithmetic — roughly 2 billion xids are "past" and 2 billion are "future." If the counter wraps, past xids flip to future, making committed data invisible.

Prevention: **VACUUM FREEZE** replaces real xmin values with a frozen marker that is always "in the past." Safety thresholds:

- 50M (`vacuum_freeze_min_age`): VACUUM can freeze tuples older than this
- 150M (`vacuum_freeze_table_age`): VACUUM does aggressive full-table freezing scans
- 200M (`autovacuum_freeze_max_age`): autovacuum forces a freeze vacuum

Postgres refuses new writes before reaching the danger zone.

---

## Retro

### Summary

Understood MVCC at the mechanical level: xmin/xmax on tuples, CLOG for transaction status, hint bits to cache CLOG results on the tuple header, snapshots as the visibility filter. Saw all of this live across concurrent sessions — uncommitted rows invisible, committed rows appearing, snapshots with gaps (xip_list), row-level blocking on concurrent writes. Transaction ID wraparound is a real production concern solved by VACUUM FREEZE.

### Key Takeaways

- Postgres never modifies tuples in-place. INSERT appends, UPDATE appends + marks old, DELETE just marks.
- Abort doesn't undo physical changes — xmax stays on the tuple, CLOG says "ignore it."
- Reading can cause writes (hint bits), which dirties pages and creates checkpoint I/O.
- Snapshot = three fields (xmin, xmax, xip_list). READ COMMITTED takes a fresh one per statement.
- Concurrent writes block; concurrent reads never block. MVCC is optimistic for reads, pessimistic for writes.
- The 32-bit xid counter is a real limit. VACUUM FREEZE is the safety mechanism.

### Connections

- **Chapter 1 (Physical Storage)**: xmin/xmax fields on tuple headers — now understood in context
- **Chapter 2 (Shared Buffers)**: dirty pages from hint bits, checkpoint I/O from reads
- **Chapter 8 (Vacuum & Bloat)**: dead tuples from UPDATE/DELETE accumulate until VACUUM reclaims them
- **Chapter 10 (Isolation & OCC)**: snapshots are the mechanism — isolation levels just control when the snapshot is taken
