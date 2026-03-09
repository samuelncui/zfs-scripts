#!/usr/bin/env python3
import os
import sys
import json
import logging
import argparse
import subprocess

# ================= Configuration =================
STATE_FILE = "rewrite_state.json"
LOG_FILE = "zfs_rewrite.log"
DEFAULT_MAX_GB = 500
# =================================================

def setup_logger():
    """Configure detailed bidirectional logging for console and file."""
    logger = logging.getLogger("ZFSRewrite")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # File handler (INFO level and above)
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console handler (DEBUG level and above)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger

logger = setup_logger()

def get_tree_size(path):
    """Calculate the total size of a directory or file (in bytes)."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    
    total_size = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp): # Skip symbolic links
                    total_size += os.path.getsize(fp)
    except Exception as e:
        logger.error(f"Unable to read size for directory {path}: {e}")
    return total_size

def generate_tasks(target_path, max_bytes):
    """Recursively traverse directories to generate a list of tasks not exceeding max_bytes."""
    tasks = []
    
    if os.path.isfile(target_path):
        size = os.path.getsize(target_path)
        tasks.append({"path": target_path, "is_dir": False, "size_bytes": size, "status": "pending"})
        return tasks

    # If it's a directory, evaluate its total size first
    logger.info(f"Calculating directory size: {target_path} ...")
    total_size = get_tree_size(target_path)
    
    if total_size <= max_bytes:
        logger.info(f"Directory {target_path} ({total_size / 1024**3:.2f} GB) is below the threshold, creating as a single task.")
        tasks.append({"path": target_path, "is_dir": True, "size_bytes": total_size, "status": "pending"})
    else:
        logger.info(f"Directory {target_path} ({total_size / 1024**3:.2f} GB) exceeds the threshold, splitting further...")
        try:
            with os.scandir(target_path) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    # Recursively split subdirectories or files
                    sub_tasks = generate_tasks(entry.path, max_bytes)
                    tasks.extend(sub_tasks)
        except PermissionError:
            logger.error(f"Permission denied, cannot access: {target_path}")

    return tasks

def save_state(tasks, state_file=STATE_FILE):
    """Save the current task state to a JSON file."""
    with open(state_file, 'w') as f:
        json.dump({"tasks": tasks}, f, indent=4)

def load_state(state_file=STATE_FILE):
    """Load the task state from a JSON file."""
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                data = json.load(f)
                tasks = data.get("tasks", [])
                return tasks if isinstance(tasks, list) else None
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load state file '{state_file}': {e}")
            return None
    return []

def execute_rewrite(task, dry_run):
    """Execute a single ZFS rewrite task."""
    path = task["path"]
    is_dir = task["is_dir"]
    size_gb = task.get("size_bytes", 0) / 1024**3

    # Build command: use -r for directories, -P to protect physical time, -v for verbose output
    cmd = ["zfs", "rewrite", "-P", "-v"]
    if is_dir:
        cmd.insert(2, "-r")
    cmd.append(path)

    cmd_str = " ".join(cmd)
    
    if dry_run:
        logger.info(f"[DRYRUN] Would execute: {cmd_str} (Estimated size: {size_gb:.2f} GB)")
        return True

    logger.info(f"Starting rewrite task: {path} ({size_gb:.2f} GB)")
    logger.debug(f"Executing command: {cmd_str}")

    try:
        # Use subprocess to call zfs rewrite and capture output
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # Real-time printing of zfs rewrite's verbose output (-v) to debug level
        for line in process.stdout:
            logger.debug(f"  {line.strip()}")
            
        process.wait()
        
        if process.returncode == 0:
            logger.info(f"Task completed successfully: {path}")
            return True
        else:
            logger.error(f"Task failed (return code {process.returncode}): {path}")
            return False
            
    except KeyboardInterrupt:
        logger.warning(f"Interrupt signal received! Aborting task: {path}")
        process.terminate()
        sys.exit(130)
    except Exception as e:
        logger.error(f"Exception occurred while executing command: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="ZFS Rewrite Chunking and Auto-Resume Manager")
    parser.add_argument("target", help="The absolute path of the target directory to rewrite (e.g., /data)")
    parser.add_argument("--max-gb", type=int, default=DEFAULT_MAX_GB, help=f"Maximum chunk size in GB (default: {DEFAULT_MAX_GB})")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution: generate task list and print commands without rewriting")
    parser.add_argument("--reset", action="store_true", help="Ignore existing state file, rescan, and generate a new task list")
    
    args = parser.parse_args()
    target_path = os.path.abspath(args.target)
    max_bytes = args.max_gb * 1024**3

    if not os.path.exists(target_path):
        logger.error(f"Target path does not exist: {target_path}")
        sys.exit(1)

    if os.geteuid() != 0 and not args.dry_run:
        logger.error("Running zfs rewrite requires root privileges. Please run with sudo or as root.")
        sys.exit(1)

    tasks = None
    
    # Logic: Check if we need to resume tasks
    if not args.reset and os.path.exists(STATE_FILE):
        logger.info(f"Found existing state file '{STATE_FILE}', loading tasks...")
        tasks = load_state()
        if tasks is None:
            logger.warning("State file is invalid or unreadable. Regenerating task list.")
            tasks = generate_tasks(target_path, max_bytes)
            save_state(tasks)
            logger.info(f"Scan complete! Generated {len(tasks)} tasks, saved to {STATE_FILE}.")
    if tasks is None:
        logger.info(f"Scanning '{target_path}' and its subdirectories, splitting tasks by a maximum of {args.max_gb} GB...")
        logger.info("This might take a few minutes depending on the number of files, please wait...")
        tasks = generate_tasks(target_path, max_bytes)
        save_state(tasks)
        logger.info(f"Scan complete! Generated {len(tasks)} tasks, saved to {STATE_FILE}.")

    if not tasks:
        logger.warning("No tasks generated. Please check if the path is correct or empty.")
        sys.exit(0)

    # Statistics
    completed_count = sum(1 for t in tasks if t["status"] == "completed")
    pending_tasks = [t for t in tasks if t["status"] == "pending"]
    
    logger.info(f"Task Overview: Total {len(tasks)} | Completed {completed_count} | Pending {len(pending_tasks)}")

    if not pending_tasks:
        logger.info("All rewrite tasks are already completed!")
        sys.exit(0)

    # Execute pending tasks sequentially
    for i, task in enumerate(tasks):
        if task["status"] == "completed":
            continue
            
        progress = f"[{completed_count + 1}/{len(tasks)}]"
        logger.info(f"{progress} Preparing to process: {task['path']}")
        
        success = execute_rewrite(task, args.dry_run)
        
        if success and not args.dry_run:
            task["status"] = "completed"
            save_state(tasks)
            completed_count += 1
        elif not success:
            logger.error("Execution stopped due to an error. Fix the issue and re-run this script to resume from the breakpoint.")
            sys.exit(1)

    if args.dry_run:
        logger.info("[DRYRUN] Simulation finished. No actual disk writes were performed.")
    else:
        logger.info("🎉 All rewrite tasks completed successfully! You can safely delete the state file.")

if __name__ == "__main__":
    main()
