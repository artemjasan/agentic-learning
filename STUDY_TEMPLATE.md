# Study Document Template

Every module gets its own `STUDY.md`. Copy this structure and fill it in across three phases.

---

## Phase 1 — Before

Written when the topic is picked, before any code. This is the prep.

```markdown
# <Topic Name>

## Goal

What we want to understand and why it matters. 2-3 sentences.

## Questions

Specific things we want to answer. Not vague ("how does Kafka work?") but targeted:
- How does MVCC handle concurrent updates to the same row?
- What happens to Kafka throughput when a broker dies mid-produce?
- How much latency does PgBouncer add in transaction pooling mode?

## Prior Knowledge

What we already know or assume going in. Write it down honestly — the retro will check which assumptions held up and which didn't.

## Plan

The hands-on experiments we'll run, in rough order:
1. Set up X
2. Build Y
3. Observe Z
4. Benchmark A vs B
```

## Phase 2 — During

Added as we work. Don't rewrite phase 1 — append below it.

```markdown
## Findings

Answers to the questions from phase 1. Link each back to the original question. Include evidence: benchmark numbers, log snippets, screenshots, EXPLAIN ANALYZE output — whatever proves the point.

### Q: <original question>

<answer with evidence>

## Surprises

Things that contradicted assumptions or were non-obvious. These are the most valuable part of the document. Be specific:
- BAD: "Vacuum was slower than expected"
- GOOD: "Vacuum on a 1M-row table with 40% dead tuples took 12s with default settings. Increasing maintenance_work_mem from 64MB to 256MB brought it to 3s. The bottleneck was index cleanup — disabling index_cleanup dropped it to 0.8s but left bloated indexes."

## Code Notes

Brief pointers to what each experiment demonstrates. Not code narration — just signposts:
- `bench_isolation.go` — runs concurrent transactions at each isolation level, logs anomalies
- `docker-compose.yml` — 3-node Kafka cluster with configurable replication factor
```

## Phase 3 — After

Written when we consider the topic done. This is the retro.

```markdown
## Summary

3-5 sentences. If someone reads nothing else in this document, they read this.

## Key Takeaways

The non-obvious lessons. Things we'd tell a colleague over coffee:
- <takeaway 1>
- <takeaway 2>
- <takeaway 3>

## What I'd Do Differently

Anything we'd change about our approach if starting over.

## Connections

How this topic connects to others — studied or planned:
- "Understanding WAL here made PostgreSQL replication make much more sense"
- "The consumer group rebalancing problem is essentially a consensus problem — see module 05"

## Open Questions

Things we didn't get to or that came up during study and deserve their own deep dive.
```

---

## Rules

- **The document is cumulative.** Each phase appends, nothing gets deleted. Phase 1 questions stay even if they turned out to be the wrong questions — that's valuable context.
- **Evidence over narrative.** Numbers, logs, command output. "It was slow" means nothing a month later. "p99 latency was 340ms at 10k req/s" means something.
- **Honest priors.** If you assumed something and it turned out wrong, that's the best kind of learning. Don't sanitize phase 1 after the fact.
- **Keep it scannable.** Use headers, bullet points, code blocks. Someone should be able to skim in 60 seconds and know what was learned.
