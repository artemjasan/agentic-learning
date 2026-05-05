import click
import psycopg
from rich.text import Text

from pgvis.core import connect, console
from pgvis.format import PanelBuilder


@click.command()
@click.pass_context
def locks(ctx) -> None:
    """Visualize current locks: who holds what, who's blocking whom."""
    with connect(ctx.obj["dsn"]) as conn:
        lock_data = _fetch_locks(conn)
        wait_data = _fetch_lock_waits(conn)
        _render(lock_data, wait_data)


# ── Queries ──────────────────────────────────────────────────────────────────


def _fetch_locks(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """
        SELECT l.pid,
               l.locktype,
               l.mode,
               l.granted,
               l.waitstart,
               COALESCE(c.relname, '') AS relname,
               l.page,
               l.tuple,
               l.transactionid,
               l.virtualxid,
               a.state AS backend_state,
               a.wait_event_type,
               a.wait_event,
               a.query,
               a.xact_start,
               a.backend_type
        FROM pg_locks l
        JOIN pg_stat_activity a ON a.pid = l.pid
        LEFT JOIN pg_class c ON c.oid = l.relation
        WHERE l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
           OR l.database IS NULL
        ORDER BY l.pid, l.granted DESC, l.locktype
        """
    ).fetchall()


def _fetch_lock_waits(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """
        SELECT blocked.pid AS blocked_pid,
               blocked.query AS blocked_query,
               blocking.pid AS blocking_pid,
               blocking.query AS blocking_query,
               bl.mode AS blocked_mode,
               bl.locktype,
               COALESCE(c.relname, '') AS relname
        FROM pg_locks bl
        JOIN pg_stat_activity blocked ON blocked.pid = bl.pid
        JOIN pg_locks kl ON kl.locktype = bl.locktype
            AND kl.database IS NOT DISTINCT FROM bl.database
            AND kl.relation IS NOT DISTINCT FROM bl.relation
            AND kl.page IS NOT DISTINCT FROM bl.page
            AND kl.tuple IS NOT DISTINCT FROM bl.tuple
            AND kl.virtualxid IS NOT DISTINCT FROM bl.virtualxid
            AND kl.transactionid IS NOT DISTINCT FROM bl.transactionid
            AND kl.pid != bl.pid
            AND kl.granted
        JOIN pg_stat_activity blocking ON blocking.pid = kl.pid
        LEFT JOIN pg_class c ON c.oid = bl.relation
        WHERE NOT bl.granted
        """
    ).fetchall()


# ── Rendering ────────────────────────────────────────────────────────────────


def _render(locks: list[dict], waits: list[dict]) -> None:
    if waits:
        _render_blocked(waits)
    _render_by_backend(locks)
    if not waits:
        console.print("[green]  No blocked processes[/green]\n")


def _render_blocked(waits: list[dict]) -> None:
    p = PanelBuilder()

    # Check for deadlocks first
    blockers: dict[int, set[int]] = {}
    for w in waits:
        blockers.setdefault(w["blocked_pid"], set()).add(w["blocking_pid"])

    deadlock_pids: set[int] = set()
    for pid, blocking_pids in blockers.items():
        for bp in blocking_pids:
            if bp in blockers and pid in blockers[bp]:
                deadlock_pids.add(pid)
                deadlock_pids.add(bp)

    if deadlock_pids:
        dl = Text()
        dl.append("  ⚠  DEADLOCK DETECTED: ", style="red bold")
        dl.append(f"PIDs {', '.join(str(p) for p in sorted(deadlock_pids))}", style="red bold")
        p.add(dl)
        p.blank()

    seen_chains: set[tuple[int, int]] = set()
    for w in waits:
        chain_key = (w["blocking_pid"], w["blocked_pid"])
        if chain_key in seen_chains:
            continue
        seen_chains.add(chain_key)

        line = Text()
        line.append(f"  PID {w['blocking_pid']}", style="red bold")
        line.append("  ──blocks──▶  ", style="red")
        line.append(f"PID {w['blocked_pid']}", style="yellow bold")
        p.add(line)

        detail = Text()
        detail.append("    ", style="dim")
        detail.append(f"lock: {w['blocked_mode']}", style="white")
        detail.append("  on ", style="dim")
        if w["relname"]:
            detail.append(f"{w['relname']}", style="cyan")
        else:
            detail.append(f"{w['locktype']}", style="cyan")
        p.add(detail)

        blocker_q = (w["blocking_query"] or "")[:80]
        blocked_q = (w["blocked_query"] or "")[:80]
        p.add(Text(f"    blocker: {blocker_q}", style="dim"))
        p.add(Text(f"    blocked: {blocked_q}", style="dim"))
        p.blank()

    p.print(title="[bold]Blocked Processes[/bold]", border_style="red")


def _render_by_backend(locks: list[dict]) -> None:
    by_pid: dict[int, list[dict]] = {}
    for lock in locks:
        by_pid.setdefault(lock["pid"], []).append(lock)

    p = PanelBuilder()

    for pid, pid_locks in sorted(by_pid.items()):
        first = pid_locks[0]
        is_waiting = any(not lk["granted"] for lk in pid_locks)

        header = Text()
        header.append(f"  PID {pid}", style="bold yellow" if is_waiting else "bold cyan")
        header.append("  │  ", style="dim")
        header.append(f"{first['backend_type']}", style="dim")
        header.append("  │  ", style="dim")
        header.append(
            f"{first['backend_state'] or 'idle'}",
            style="green" if first["backend_state"] == "active" else "dim",
        )
        if is_waiting:
            header.append("  │  ", style="dim")
            header.append("WAITING", style="yellow bold")
        p.add(header)

        query = (first["query"] or "")[:80]
        if query:
            p.add(Text(f"    query: {query}", style="dim"))

        for lock in pid_locks:
            lk = Text()
            lk.append("    ", style="dim")

            if lock["granted"]:
                lk.append("✓ ", style="green")
            else:
                lk.append("✗ ", style="red bold")

            lk.append(f"{lock['mode']:<25}", style="white" if lock["granted"] else "yellow")

            if lock["relname"]:
                target = lock["relname"]
            elif lock["transactionid"]:
                target = f"txid:{lock['transactionid']}"
            elif lock["virtualxid"]:
                target = f"vxid:{lock['virtualxid']}"
            else:
                target = lock["locktype"]

            lk.append("  on ", style="dim")
            lk.append(target, style="cyan")

            if lock["tuple"] is not None:
                lk.append(f"  (page={lock['page']}, tuple={lock['tuple']})", style="dim")

            p.add(lk)

        p.blank()

    if not by_pid:
        p.add(Text("  No locks held", style="dim"))

    p.print(title=f"[bold]Locks by Backend ({len(by_pid)} backends)[/bold]", border_style="cyan")
