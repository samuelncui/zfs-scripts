# ZFS Scripts

A collection of utility scripts for ZFS workflows. This repository currently includes the ZFS rewrite manager, and is intended to grow with additional scripts over time.
This repo is done by vibe coding with some test and manual debugging on Debian 13 with ZFS 2.4.0, use at your own risk.

## Included Scripts

- ZFS Rewrite Manager: Chunk and resume `zfs rewrite` operations by scanning a target path, splitting work into size-bounded tasks, and persisting progress to a state file.
- Transmission Finish: Hardlink finished downloads to a library path and run `zfs rewrite`.
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

## Transmission Finish

### Requirements

```bash
./transmission_finish.sh --source /path/to/download --target /path/to/library
```

Dry run (no writes):

```bash
./transmission_finish.sh --source /path/to/download --target /path/to/library --dry-run
```

### Functions

- Source is provided via `--source` in `transmission_finish.sh`.
- Target is provided via `--target` in `transmission_finish.sh`.
- Hardlinks files from source to target, so you can move files to a different location while continuing to seed.
- Runs `zfs rewrite` on the source path after linking (requires root unless `--dry-run`) to defragment the downloaded files.

### Usage

- Reads `TARGET_DIR` from a `.env` file via `transmission_finish.sh`, then hardlinks files into that library path.
- Set Transmission's `script-torrent-done-filename` to this script to run on completion.

If Transmission runs as the `debian-transmission` user:

- Add a sudoers entry:

```bash
echo 'debian-transmission ALL=(ALL) NOPASSWD: SETENV: /opt/scripts/zfs-scripts/transmission_finish.sh' >> /etc/sudoers.d/transmission-daemon
```

- Add following to `/etc/systemd/system/transmission-daemon.service.d/finish-script.conf`:

```bash
cat <<EOF >> /etc/systemd/system/transmission-daemon.service.d/finish-script.conf
[Service]
NoNewPrivileges=false
RestrictSUIDSGID=false

# Reset and explicitly define capabilities. 
# Added CAP_SYS_ADMIN, which is mandatory for issuing ZFS ioctls to the kernel.
CapabilityBoundingSet=
CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_AUDIT_WRITE CAP_SYS_ADMIN

# Punch a minimal hole for the ZFS device.
# This avoids needing "PrivateDevices=false", keeping other hardware hidden.
DeviceAllow=/dev/zfs rw
BindPaths=/dev/zfs

# This must be false. If isolated, ZFS cannot read the system's true 
# mount points to figure out which dataset /data/PT/... belongs to.
PrivateMounts=false

EOF
```
