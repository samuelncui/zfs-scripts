#!/usr/bin/env python3
import argparse
import logging
import os
import subprocess
import sys

LOG_FILE = "transmission_finish.log"


def setup_logger():
    logger = logging.getLogger("TransmissionFinish")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


logger = setup_logger()


def run_rewrite(target_path, dry_run):
    cmd = ["zfs", "rewrite", "-P", "-r", "-v"]
    cmd.append(target_path)
    cmd_str = " ".join(cmd)
    if dry_run:
        logger.info(f"[DRYRUN] Would execute: {cmd_str}")
        return True
    if os.geteuid() != 0:
        logger.error("Running zfs rewrite requires root privileges. Please run with sudo or as root.")
        return False
    logger.info(f"Executing command: {cmd_str}")
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            logger.info(f"[ZFS Rewrite] {line.strip()}")
        process.wait()
        if process.returncode == 0:
            logger.info("Rewrite completed successfully.")
            return True
        logger.error(f"Rewrite failed (return code {process.returncode}).")
        return False
    except FileNotFoundError:
        logger.error("zfs command not found. Ensure ZFS tools are installed.")
        return False
    except KeyboardInterrupt:
        logger.warning("Interrupt signal received! Aborting rewrite.")
        process.terminate()
        sys.exit(130)
    except Exception as e:
        logger.error(f"Exception occurred while executing command: {e}")
        return False


def same_inode(src, dst):
    src_stat = os.stat(src, follow_symlinks=False)
    dst_stat = os.stat(dst, follow_symlinks=False)
    return src_stat.st_ino == dst_stat.st_ino and src_stat.st_dev == dst_stat.st_dev


def link_file(dst, src, dry_run, counts):
    if os.path.islink(src):
        counts["skipped"] += 1
        logger.warning(f"Skipping symlink source: {src}")
        return
    try:
        src_stat = os.stat(src, follow_symlinks=False)
        if src_stat.st_nlink > 1:
            counts["skipped"] += 1
            logger.info(f"Source already hardlinked elsewhere, skipping: {src}")
            return
        if os.path.exists(dst):
            if src_stat.st_ino == os.stat(dst, follow_symlinks=False).st_ino and src_stat.st_dev == os.stat(dst, follow_symlinks=False).st_dev:
                counts["skipped"] += 1
                logger.info(f"Already linked: {dst}")
                return
            counts["conflicts"] += 1
            logger.warning(f"Destination exists and differs, skipping: {dst}")
            return
        if not dry_run:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.link(src, dst)
        counts["linked"] += 1
        logger.info(f"Linked: {dst}")
    except Exception as e:
        counts["errors"] += 1
        logger.error(f"Failed to link {src} -> {dst}: {e}")


def link(dst, src, dry_run):
    counts = {"linked": 0, "skipped": 0, "conflicts": 0, "errors": 0}
    if os.path.isfile(src):
        link_file(dst, src, dry_run, counts)
        return counts

    for root, _, files in os.walk(src):
        rel_root = os.path.relpath(root, src)
        dst_root = dst if rel_root == "." else os.path.join(dst, rel_root)
        for filename in files:
            src_file = os.path.join(root, filename)
            dst_file = os.path.join(dst_root, filename)
            link_file(dst_file, src_file, dry_run, counts)
    return counts


def main():
    parser = argparse.ArgumentParser(description="Transmission finish script: ZFS rewrite + hardlink to target path")
    parser.add_argument("--source", help="Absolute path to finished download")
    parser.add_argument("--target", help="Absolute path to target library root")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without writing")
    args = parser.parse_args()

    source_path = os.path.abspath(args.source) if args.source else None
    target_path = os.path.abspath(args.target) if args.target else None

    if not source_path:
        logger.error("Source path not provided. Use --source.")
        sys.exit(1)
    if not target_path:
        logger.error("Target path not provided. Use --target.")
        sys.exit(1)
    if not os.path.exists(source_path):
        logger.error(f"Source path does not exist: {source_path}")
        sys.exit(1)

    logger.info(f"Source: {source_path}")
    logger.info(f"Target: {target_path}")

    counts = link(target_path, source_path, args.dry_run)
    logger.info(
        f"Link summary: linked={counts['linked']} skipped={counts['skipped']} conflicts={counts['conflicts']} errors={counts['errors']}"
    )

    if counts["errors"] > 0:
        sys.exit(1)

    if not run_rewrite(source_path, args.dry_run):
        sys.exit(1)


if __name__ == "__main__":
    main()
