# orphan-proc-cleaner

Quick tool I wrote to clean up those annoying orphaned, zombie, and defunct processes that accumulate on long-running servers.

## Why I Made This

Ever had a server that's been running for months and suddenly you notice it's sluggish? You run `ps aux` and see a bunch of `<defunct>` processes or processes with PPID 1 that really shouldn't be there. This script finds and cleans them up.

## What It Does

- **Orphaned processes**: Finds processes whose parent died and got reparented to init (PID 1), but aren't legitimate daemons
- **Zombie processes**: Finds processes in Z state that are waiting for their parent to read their exit status
- **Defunct processes**: Finds processes marked as `<defunct>` in their command line

The script tries to be smart about it - it won't kill your actual daemons like systemd, docker, nginx, etc. It filters those out based on known patterns.

## Installation

No dependencies needed - it uses only Python stdlib. But if you want to be fancy:

```bash
pip install -r requirements.txt
```

(Though honestly, `requirements.txt` is basically empty. This is pure Python 3.6+.)

## Usage

### See what's out there (dry run)

```bash
python orphan_proc_cleaner.py --orphans --dry-run
python orphan_proc_cleaner.py --zombies --dry-run
python orphan_proc_cleaner.py --all --dry-run
```

### Actually clean things up

```bash
# Clean orphaned processes
python orphan_proc_cleaner.py --orphans

# Clean zombies
python orphan_proc_cleaner.py --zombies

# Nuke everything
python orphan_proc_cleaner.py --all --force
```

### With logging

```bash
python orphan_proc_cleaner.py --all --log /var/log/orphan-cleaner.log
```

## Command Line Options

| Flag | Description |
|------|-------------|
| `--orphans` | Target orphaned processes (PPID=1, not known daemons) |
| `--zombies`, `-z` | Target zombie processes (state=Z) |
| `--defunct`, `-d` | Target defunct processes |
| `--all`, `-a` | Target all of the above |
| `--dry-run`, `-n` | Show what would be done, don't actually kill anything |
| `--force`, `-f` | Use SIGKILL immediately (skip graceful SIGTERM) |
| `--log`, `-l` | Write actions to a log file |
| `--min-age` | Only target processes older than N seconds |

## How It Works

1. Scans `/proc` to get all PIDs
2. Reads `/proc/[pid]/stat` and `/proc/[pid]/cmdline` for each process
3. Identifies problematic processes based on:
   - PPID = 1 (orphaned)
   - State = Z (zombie)
   - Cmdline contains `<defunct>`
4. Filters out known daemon patterns
5. Sends SIGTERM first, waits a bit, then SIGKILL if needed
6. Reports what happened

## Safety Notes

- Always run with `--dry-run` first on a new system
- The daemon filter isn't perfect - review what it finds
- Don't run this on production without testing
- Zombies can't actually be killed (they're already dead) - only their parent can reap them. This script attempts anyway but YMMV

## Example Output

```
$ python orphan_proc_cleaner.py --all --dry-run

Orphan Process Cleaner
Mode: DRY-RUN
----------------------------------------

======================================================================
Zombie Processes (2 found)
======================================================================
PID      PPID     State  Command
----------------------------------------------------------------------
12345    1        Z      [python]
12346    1        Z      [node]
----------------------------------------------------------------------

======================================================================
Orphaned Processes (3 found)
======================================================================
PID      PPID     State  Command
----------------------------------------------------------------------
23456    1        S      /tmp/rogue_script.py
23457    1        R      python worker.py --stuck
23458    1        S      bash -c while true; do sleep 1; done
----------------------------------------------------------------------

Total unique processes to clean: 5
----------------------------------------
[DRY-RUN] Would terminate PID 12345: [python]
[DRY-RUN] Would terminate PID 12346: [node]
[DRY-RUN] Would terminate PID 23456: /tmp/rogue_script.py
[DRY-RUN] Would terminate PID 23457: python worker.py --stuck
[DRY-RUN] Would terminate PID 23458: bash -c while true; do sleep 1; done

========================================
Cleanup Summary
========================================
Attempted:  5
Succeeded:  0
Failed:     0
Skipped:    5 (dry-run mode)
```

## License

Do whatever you want with it. It's not that complicated.
