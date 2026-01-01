#!/usr/bin/env python3
"""
Orphan Process Cleaner - Automatically detects and cleans up orphaned processes.
"""

import os
import sys
import signal
import argparse
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Set


def get_process_info(pid: int) -> Optional[Dict]:
    """Retrieve process information from /proc filesystem."""
    proc_path = Path(f"/proc/{pid}")
    if not proc_path.exists():
        return None

    try:
        stat_path = proc_path / "stat"
        cmdline_path = proc_path / "cmdline"
        status_path = proc_path / "status"

        with open(stat_path, "r") as f:
            stat_content = f.read().strip()

        parts = stat_content.split(")", 1)
        if len(parts) < 2:
            return None

        stat_fields = parts[1].split()
        ppid = int(stat_fields[1])
        state = stat_fields[0]

        cmdline = ""
        if cmdline_path.exists():
            with open(cmdline_path, "r") as f:
                cmdline = f.read().replace("\x00", " ").strip()

        pgrp = int(stat_fields[2])
        session = int(stat_fields[4])

        return {
            "pid": pid,
            "ppid": ppid,
            "pgrp": pgrp,
            "session": session,
            "state": state,
            "cmdline": cmdline or f"[{pid}]",
        }
    except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError):
        return None


def get_all_pids() -> Set[int]:
    """Get all current process IDs from /proc."""
    pids = set()
    proc_path = Path("/proc")

    try:
        for entry in proc_path.iterdir():
            if entry.name.isdigit():
                pids.add(int(entry.name))
    except PermissionError:
        pass

    return pids


def find_orphaned_processes() -> List[Dict]:
    """
    Find orphaned processes - those whose parent PID is 1 (init/systemd)
    but are not expected to be daemon processes.
    """
    all_pids = get_all_pids()
    orphaned = []

    known_daemon_patterns = [
        "systemd", "init", "docker", "containerd", "sshd", "cron",
        "rsyslog", "nginx", "apache", "mysql", "postgres", "redis",
        "supervisord", "gunicorn", "uwsgi", "node", "python", "java"
    ]

    for pid in all_pids:
        proc_info = get_process_info(pid)
        if proc_info is None:
            continue

        if proc_info["ppid"] == 1 and pid != 1:
            cmdline = proc_info["cmdline"].lower()

            is_known_daemon = any(
                pattern in cmdline for pattern in known_daemon_patterns
            )

            if not is_known_daemon:
                state = proc_info["state"]
                if state in ["R", "S", "D"]:
                    orphaned.append(proc_info)

    return orphaned


def find_zombie_processes() -> List[Dict]:
    """Find zombie processes (state = Z)."""
    all_pids = get_all_pids()
    zombies = []

    for pid in all_pids:
        proc_info = get_process_info(pid)
        if proc_info is None:
            continue

        if proc_info["state"] == "Z":
            zombies.append(proc_info)

    return zombies


def find_defunct_processes() -> List[Dict]:
    """Find defunct processes by checking cmdline."""
    all_pids = get_all_pids()
    defunct = []

    for pid in all_pids:
        proc_info = get_process_info(pid)
        if proc_info is None:
            continue

        if "<defunct>" in proc_info["cmdline"]:
            defunct.append(proc_info)

    return defunct


def send_signal_to_process(pid: int, sig: int) -> bool:
    """Send a signal to a process and return success status."""
    try:
        os.kill(pid, sig)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def graceful_terminate(pid: int, timeout: int = 5) -> bool:
    """
    Attempt graceful termination with SIGTERM, then SIGKILL if needed.
    """
    proc_info = get_process_info(pid)
    if proc_info is None:
        return False

    if send_signal_to_process(pid, signal.SIGTERM):
        for _ in range(timeout * 10):
            time.sleep(0.1)
            if get_process_info(pid) is None:
                return True

    if send_signal_to_process(pid, signal.SIGKILL):
        time.sleep(0.1)
        return get_process_info(pid) is None

    return False


def cleanup_processes(
    processes: List[Dict],
    dry_run: bool = False,
    force: bool = False
) -> Dict[str, int]:
    """
    Clean up the given list of processes.
    Returns statistics about the cleanup operation.
    """
    stats = {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0}

    for proc in processes:
        pid = proc["pid"]
        cmdline = proc["cmdline"]
        stats["attempted"] += 1

        if dry_run:
            print(f"[DRY-RUN] Would terminate PID {pid}: {cmdline}")
            stats["skipped"] += 1
            continue

        print(f"Terminating PID {pid}: {cmdline}")

        if force:
            success = send_signal_to_process(pid, signal.SIGKILL)
        else:
            success = graceful_terminate(pid)

        if success:
            print(f"  -> Successfully terminated PID {pid}")
            stats["succeeded"] += 1
        else:
            print(f"  -> Failed to terminate PID {pid}")
            stats["failed"] += 1

    return stats


def print_process_table(processes: List[Dict], title: str) -> None:
    """Print a formatted table of processes."""
    if not processes:
        print(f"\nNo {title} found.")
        return

    print(f"\n{'=' * 70}")
    print(f"{title} ({len(processes)} found)")
    print(f"{'=' * 70}")
    print(f"{'PID':<8} {'PPID':<8} {'State':<6} {'Command'}")
    print(f"{'-' * 70}")

    for proc in sorted(processes, key=lambda x: x["pid"]):
        pid = proc["pid"]
        ppid = proc["ppid"]
        state = proc["state"]
        cmdline = proc["cmdline"][:45] if len(proc["cmdline"]) > 45 else proc["cmdline"]
        print(f"{pid:<8} {ppid:<8} {state:<6} {cmdline}")

    print(f"{'-' * 70}")


def write_log_entry(log_path: Path, action: str, processes: List[Dict]) -> None:
    """Write a log entry about the cleanup action."""
    timestamp = datetime.now().isoformat()

    with open(log_path, "a") as f:
        f.write(f"[{timestamp}] {action}\n")
        for proc in processes:
            f.write(f"  PID {proc['pid']}: {proc['cmdline']}\n")
        f.write("\n")


def main() -> int:
    """Main entry point for the orphan process cleaner."""
    parser = argparse.ArgumentParser(
        description="Clean up orphaned, zombie, and defunct processes."
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be done without actually terminating processes"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Use SIGKILL immediately instead of graceful SIGTERM first"
    )
    parser.add_argument(
        "--orphans",
        action="store_true",
        help="Clean up orphaned processes (parent PID = 1)"
    )
    parser.add_argument(
        "--zombies", "-z",
        action="store_true",
        help="Clean up zombie processes"
    )
    parser.add_argument(
        "--defunct", "-d",
        action="store_true",
        help="Clean up defunct processes"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Clean up all types of problematic processes"
    )
    parser.add_argument(
        "--log", "-l",
        type=str,
        default=None,
        help="Path to log file for recording actions"
    )
    parser.add_argument(
        "--min-age",
        type=int,
        default=0,
        help="Minimum process age in seconds to consider for cleanup"
    )

    args = parser.parse_args()

    if not any([args.orphans, args.zombies, args.defunct, args.all]):
        parser.print_help()
        return 1

    if args.all:
        args.orphans = True
        args.zombies = True
        args.defunct = True

    print("Orphan Process Cleaner")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print("-" * 40)

    all_targeted = []

    if args.zombies:
        zombies = find_zombie_processes()
        print_process_table(zombies, "Zombie Processes")
        all_targeted.extend(zombies)

    if args.defunct:
        defunct = find_defunct_processes()
        print_process_table(defunct, "Defunct Processes")
        all_targeted.extend(defunct)

    if args.orphans:
        orphans = find_orphaned_processes()
        print_process_table(orphans, "Orphaned Processes")
        all_targeted.extend(orphans)

    if not all_targeted:
        print("\nNo processes matching criteria found.")
        return 0

    unique_pids = {proc["pid"]: proc for proc in all_targeted}.values()
    all_targeted = list(unique_pids)

    print(f"\nTotal unique processes to clean: {len(all_targeted)}")
    print("-" * 40)

    stats = cleanup_processes(all_targeted, dry_run=args.dry_run, force=args.force)

    print("\n" + "=" * 40)
    print("Cleanup Summary")
    print("=" * 40)
    print(f"Attempted:  {stats['attempted']}")
    print(f"Succeeded:  {stats['succeeded']}")
    print(f"Failed:     {stats['failed']}")
    if args.dry_run:
        print(f"Skipped:    {stats['skipped']} (dry-run mode)")

    if args.log and not args.dry_run:
        log_path = Path(args.log)
        write_log_entry(log_path, "Cleanup completed", all_targeted)
        print(f"\nLog written to: {args.log}")

    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
