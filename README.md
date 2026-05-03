# Systems Engineering Lab

A hands-on learning repository for deep-diving into systems infrastructure: databases, distributed systems, messaging, networking, security, and more.

## Approach

Each topic is an independent deep dive. The goal is not to build a product but to **understand how things actually work** — by building, breaking, and benchmarking real systems.

- **Primary language**: Go (learning it alongside the topics)
- **Also used**: Python for visualization tooling, Rust for kernel/systems work
- **Structure**: each topic is a self-contained module under `modules/`

## Topics

See [TOPICS.md](TOPICS.md) for the full list with hands-on objectives and status.

## How This Repo Works

This is an agent-assisted project. Each Claude Code session reads `CLAUDE.md` on startup, which points to `AGENTS.md` (conventions), `PROGRESS.md` (current state), and `TOPICS.md` (what to work on). Any new session can pick up where the last one left off.

See [AGENTS.md](AGENTS.md) for the full agent workflow.
