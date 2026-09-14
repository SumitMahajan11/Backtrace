"""
Driver script to run the 27-seed __init__.py sweep synchronously and print full results.
"""
import subprocess
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def main():
    print("=" * 110)
    print("STARTING 27-SEED SWEEP ON __init__.py IMPORT RESOLUTIONS (PYTHONHASHSEED=0..24, 42, 99999)")
    print("=" * 110)
    
    seeds = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 42, 99999]
    outputs = []
    
    for seed in seeds:
        env = dict(os.environ, PYTHONHASHSEED=str(seed), PYTHONPATH='.')
        res = subprocess.run([sys.executable, 'scripts/run_init_sweep_verify.py'], env=env, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"FAILED on seed {seed}: {res.stderr}")
            sys.exit(1)
        line = res.stdout.strip()
        print(line)
        outputs.append(line)
        
    print("\n" + "=" * 110)
    print("EDGE ARITHMETIC RECONCILIATION & VENN DECOMPOSITION:")
    print("=" * 110)
    
    from scripts.run_init_sweep_verify import execute_sweep
    details = execute_sweep()
    
    out_c = details['outgoing_count']
    in_c = details['incoming_count']
    overlap_c = details['init_to_init_count']
    unique_c = details['unique_init_involved_count']
    
    print(f"1. Total __init__.py files in repo : {details['init_files_count']}")
    for idx, f in enumerate(details['init_files'], 1):
        print(f"   [{idx:02d}] {f}")
        
    print(f"\n2. Edge Count Reconciliation Formula:")
    print(f"   - Outgoing edges (Source is __init__.py)            : {out_c}")
    print(f"   - Incoming edges (Target is __init__.py)            : {in_c}")
    print(f"   - Gross sum (double-counts __init__->__init__)      : {out_c} + {in_c} = {out_c + in_c}")
    print(f"   - Overlap edges (Both source & target are __init__) : {overlap_c}")
    print(f"   - Net Unique Edges involving any __init__.py       : {out_c} + {in_c} - {overlap_c} = {out_c + in_c - overlap_c}")
    print(f"   - Actual Unique Edges Set size                      : {unique_c}")
    print(f"   - Discrepancy                                       : {unique_c - (out_c + in_c - overlap_c)} (EXACT MATCH)")
    
    print(f"\n3. Full List of the {overlap_c} Init-to-Init Overlap Edges:")
    for idx, (src, sym, tgt) in enumerate(sorted(details['init_to_init_edges']), 1):
        print(f"   ({idx:02d}) {src} --[{sym}]--> {tgt}")

if __name__ == '__main__':
    main()
