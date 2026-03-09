#!/usr/bin/env python3
import sys
import os
import subprocess

def get_file_info(filepath):
    """Retrieves the ZFS dataset and Object ID (inode) for the given file."""
    # Get Object ID (inode)
    try:
        stat_out = subprocess.check_output(['stat', '-c', '%i', filepath], text=True)
        obj_id = stat_out.strip()
    except subprocess.CalledProcessError:
        print(f"Error: Could not get inode for {filepath}")
        sys.exit(1)

    # Get Dataset
    try:
        df_out = subprocess.check_output(['df', '--output=source', filepath], text=True)
        dataset = df_out.strip().split('\n')[1].strip()
    except subprocess.CalledProcessError:
        print(f"Error: Could not get dataset for {filepath}")
        sys.exit(1)

    # Fix for root pool MOS conflict (e.g., prevents 'data' from defaulting to the pool MOS by appending '/')
    if '/' not in dataset:
        dataset += '/'

    return dataset, obj_id

def analyze_fragmentation(dataset, obj_id):
    """Runs zdb and calculates the physical extents (fragments)."""
    cmd = ['sudo', 'zdb', '-ddddd', dataset, obj_id]
    print(f"Running: {' '.join(cmd)}")
    
    try:
        # Use Popen to process line-by-line and avoid loading massive output into RAM
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        print("Error: 'zdb' command not found. Ensure you are on a ZFS system.")
        sys.exit(1)

    blocks = 0
    fragments = 0
    prev_vdev = None
    prev_end = None

    for line in process.stdout:
        parts = line.split()
        
        # Look for the L0 block line. Example format:
        # 7c560000 L0 0:e0552a68000:2d000 20000L/20000P ...
        if len(parts) >= 3 and parts[1] == "L0":
            try:
                # Extract the physical address block, e.g., 0:e0552a68000:2d000
                dva_parts = parts[2].split(":")
                if len(dva_parts) >= 3:
                    vdev = int(dva_parts[0])
                    offset = int(dva_parts[1], 16)
                    asize = int(dva_parts[2], 16)
                    
                    blocks += 1
                    
                    # Calculate fragmentation
                    if prev_end is None:
                        fragments = 1
                    elif vdev != prev_vdev or offset != prev_end:
                        fragments += 1
                    
                    prev_vdev = vdev
                    prev_end = offset + asize
            except ValueError:
                continue

    process.wait()
    
    if process.returncode != 0 and blocks == 0:
        err = process.stderr.read()
        print(f"zdb command failed. Error:\n{err}")
        sys.exit(1)

    return blocks, fragments

def main():
    if len(sys.argv) != 2:
        print(f"Usage: python3 {sys.argv[0]} <file_path>")
        sys.exit(1)

    filepath = sys.argv[1]
    
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' does not exist.")
        sys.exit(1)

    # Sync to ensure recent writes are flushed to physical disk so zdb can see them
    print("Flushing pending transactions to disk (sync)...")
    subprocess.run(['sync'])

    dataset, obj_id = get_file_info(filepath)
    print(f"Dataset: {dataset} | Object ID: {obj_id}")

    blocks, fragments = analyze_fragmentation(dataset, obj_id)

    if blocks > 0:
        print("\n--- ZFS File Fragmentation Report ---")
        print(f"File: {filepath}")
        print(f"Total Blocks (L0): {blocks}")
        print(f"Physical Extents:  {fragments}")
        
        rate = (fragments / blocks) * 100
        print(f"Fragmentation:     {rate:.2f}%")
        
        if rate < 10:
            print("Status: Excellent (Mostly contiguous)")
        elif rate < 50:
            print("Status: Moderate Fragmentation")
        else:
            print("Status: Severe Fragmentation (Typical for BitTorrent/VMs)")
    else:
        print("\nNo L0 data blocks found. The file might be empty, or purely resident in metadata.")

if __name__ == "__main__":
    main()
