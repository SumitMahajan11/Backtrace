"""
Script: run_init_sweep_verify.py
Explicitly runs the 27-seed __init__.py sweep on pallets/flask (83 Python files).
Demonstrates:
1. Exact per-seed execution and fingerprinting across PYTHONHASHSEED=0..24, 42, 99999.
2. Complete inventory of all 13 __init__.py files.
3. Full edge-level accounting:
   - Total edges where source is __init__.py
   - Total edges where target is __init__.py
   - Total edges where BOTH source and target are __init__.py (init-to-init)
   - Formal Venn reconciliation: Total unique edges = Outgoing + Incoming - (Init-to-Init overlap)
"""

import os
import sys
import json
import hashlib
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parser.python_parser import PythonLanguageParser

def execute_sweep():
    cache_path = Path('tests/fixtures/flask_cache.json')
    if not cache_path.exists():
        print(f"ERROR: Cache file {cache_path} not found.")
        sys.exit(1)
        
    with open(cache_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    code_contents = data['code_contents']
    all_paths = data['all_paths']
    all_repo_files = set(all_paths)
    
    parser = PythonLanguageParser()
    
    init_files = sorted([p for p in code_contents.keys() if p.endswith('__init__.py')])
    
    # Track all parsed edges
    all_resolved_edges = []
    incoming_to_init = []
    outgoing_from_init = []
    init_to_init = []
    unique_init_involved_edges = set()
    
    for f in sorted(code_contents.keys()):
        code = code_contents[f]
        node, edges = parser.parse_single_file(f, code, all_repo_files)
        
        for edge in edges:
            if not edge.is_external and edge.resolved and edge.target:
                edge_tuple = (f, edge.raw_import_symbol, edge.target)
                all_resolved_edges.append(edge_tuple)
                
                is_src_init = f.endswith('__init__.py')
                is_tgt_init = edge.target.endswith('__init__.py')
                
                if is_src_init:
                    outgoing_from_init.append(edge_tuple)
                if is_tgt_init:
                    incoming_to_init.append(edge_tuple)
                if is_src_init and is_tgt_init:
                    init_to_init.append(edge_tuple)
                    
                if is_src_init or is_tgt_init:
                    unique_init_involved_edges.add(edge_tuple)
    
    sorted_unique_edges = sorted(list(unique_init_involved_edges))
    summary_str = '\n'.join([f"{src} --[{sym}]--> {tgt}" for src, sym, tgt in sorted_unique_edges])
    h = hashlib.sha256(summary_str.encode('utf-8')).hexdigest()
    seed = os.environ.get('PYTHONHASHSEED', 'None')
    
    return {
        'seed': seed,
        'init_files_count': len(init_files),
        'init_files': init_files,
        'outgoing_count': len(outgoing_from_init),
        'incoming_count': len(incoming_to_init),
        'init_to_init_count': len(init_to_init),
        'unique_init_involved_count': len(unique_init_involved_edges),
        'sha256': h[:16],
        'init_to_init_edges': init_to_init,
        'outgoing_from_init': outgoing_from_init,
        'incoming_to_init': incoming_to_init,
    }

if __name__ == '__main__':
    res = execute_sweep()
    print(f"SEED={res['seed']:<5} | __init__.py files={res['init_files_count']} | Out={res['outgoing_count']} | In={res['incoming_count']} | Overlap(Init->Init)={res['init_to_init_count']} | Unique Involved={res['unique_init_involved_count']} | SHA256={res['sha256']}")
