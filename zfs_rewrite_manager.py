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

def generate_tasks(target_path, max_bytes):
    """Recursively traverse directories to generate a list of tasks not exceeding max_bytes."""
    # tasks = [{"targets": ["/path/to/file1", "/path/to/dir1"], "size_bytes": total_size, "status": "pending"}]
    if os.path.isfile(target_path):
        try:
            size_bytes = os.path.getsize(target_path)
        except OSError:
            size_bytes = 0
        return [{"targets": [target_path], "size_bytes": size_bytes, "status": "pending"}]

    children_map = {}
    size_map = {}
    is_dir_map = {}

    stack = [(target_path, False)]
    while stack:
        path, expanded = stack.pop()
        if expanded:
            total_size = 0
            for child_path in children_map.get(path, []):
                total_size += size_map.get(child_path, 0)
            size_map[path] = total_size
            continue

        stack.append((path, True))
        children = []
        try:
            with os.scandir(path) as it:
                for entry in it:
                    child_path = entry.path
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            children.append(child_path)
                            is_dir_map[child_path] = True
                            stack.append((child_path, False))
                            continue

                        size_map[child_path] = entry.stat(follow_symlinks=False).st_size
                        is_dir_map[child_path] = False
                        children.append(child_path)
                    except OSError as e:
                        logger.warning(f"Failed to access '{child_path}': {e}")

        except OSError as e:
            logger.warning(f"Failed to scan directory '{path}': {e}")
        children_map[path] = children

    tasks = []

    def add_task(targets, size_bytes):
        if targets:
            tasks.append({"targets": targets, "size_bytes": size_bytes, "status": "pending"})

    dir_stack = [target_path]
    while dir_stack:
        dir_path = dir_stack.pop()
        children = children_map.get(dir_path, [])
        if not children:
            continue

        current_targets = []
        current_size = 0

        for child_path in children:
            child_size = size_map.get(child_path, 0)
            if is_dir_map.get(child_path, False) and child_size > max_bytes:
                add_task(current_targets, current_size)
                current_targets = []
                current_size = 0
                dir_stack.append(child_path)
                continue

            if current_targets and current_size + child_size > max_bytes:
                add_task(current_targets, current_size)
                current_targets = [child_path]
                current_size = child_size
            else:
                current_targets.append(child_path)
                current_size += child_size

        add_task(current_targets, current_size)

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
    targets = task.get("targets")
    if not targets:
        logger.error("Task is missing targets.")
        return False

    size_gb = task.get("size_bytes", 0) / 1024**3

    # Build command: use -r for directories, -P to protect physical time, -v for verbose output
    cmd = ["zfs", "rewrite", "-P", "-v"]
    if any(os.path.isdir(path) for path in targets):
        cmd.insert(2, "-r")
    cmd.extend(targets)

    cmd_str = " ".join(cmd)    
    if dry_run:
        logger.info(f"[DRYRUN] Would execute: {cmd_str} (Estimated size: {size_gb:.2f} GB)")
        return True

    logger.info(f"Starting rewrite task: {', '.join(targets)} ({size_gb:.2f} GB)")
    logger.debug(f"Executing command: {cmd_str}")

    try:
        # Use subprocess to call zfs rewrite and capture output
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # Real-time printing of zfs rewrite's verbose output (-v) to debug level
        for line in process.stdout:
            logger.debug(f"  {line.strip()}")
            
        process.wait()
        
        if process.returncode == 0:
            logger.info(f"Task completed successfully: {', '.join(targets)}")
            return True
        else:
            logger.error(f"Task failed (return code {process.returncode}): {', '.join(targets)}")
            return False
            
    except KeyboardInterrupt:
        logger.warning(f"Interrupt signal received! Aborting task: {', '.join(targets)}")
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
        targets_label = ", ".join(task.get("targets", [task.get("path", "<unknown>")]))
        logger.info(f"{progress} Preparing to process: {targets_label}")
        
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
