# ZFS Scripts

A collection of utility scripts for ZFS workflows. This repository currently includes the ZFS rewrite manager, and is intended to grow with additional scripts over time.
This repo is done by vibe coding with some test, use at your own risk.

## Included Scripts

- ZFS Rewrite Manager: Chunk and resume `zfs rewrite` operations by scanning a target path, splitting work into size-bounded tasks, and persisting progress to a state file.
- ZFS Fragmentation Analyzer: Report physical fragmentation for a file by running `zdb` on its dataset and object ID.

## Requirements

- Python 3
- ZFS with `zfs rewrite` available on the host
- Root privileges for non-dry runs

## ZFS Rewrite Manager

### Requirements

```bash
sudo ./zfs_rewrite_manager.py /data
```

Dry run (no writes):

```bash
./zfs_rewrite_manager.py /data --dry-run
```

Limit chunk size to 200 GB:

```bash
sudo ./zfs_rewrite_manager.py /data --max-gb 200
```

Regenerate tasks from scratch:

```bash
sudo ./zfs_rewrite_manager.py /data --reset
```

### Usage

- Scans the target path and creates tasks sized at or under `--max-gb`.
- Saves progress to `rewrite_state.json` in the current working directory.
- Resumes from the state file on subsequent runs unless `--reset` is provided.
- Writes logs to `zfs_rewrite.log` in the current working directory.

### Behavior

### Exit Codes

- `0` when all tasks complete or there is nothing to do
- `1` on errors
- `130` on interrupt
