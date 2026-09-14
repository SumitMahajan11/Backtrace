"""Deterministic Baseline Ordering & Cycle Handling Engine (Layer 6 Stage A)."""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from app.parser.schema import FileNode, ImportEdge
from app.segmentation.schema import SegmentationResult, SegmentedFileNode
from app.sequence.schema import BaselineOrderingResult, NodeMetadata, Tier


GENERIC_SYMBOL_BLACKLIST = {
    # Common language keywords, standard library names, and ultra-generic variable names
    "app", "cli", "json", "data", "get", "run", "test", "error", "name", "main", "dict", "list",
    "map", "path", "type", "file", "self", "cls", "val", "key", "args", "kwargs", "config",
    "req", "res", "response", "request", "url", "route", "helper", "helpers", "utils", "util",
    "handler", "handlers", "opts", "options", "params", "param", "init", "setup", "info",
    "log", "logger", "trace", "debug", "warning", "warn", "critical", "exception", "exc",
    "sys", "os", "re", "time", "math", "base", "core", "default", "node", "tree", "item",
    "items", "builder", "manager", "service", "client", "server", "ctx", "context", "engine",
    "parser", "schema", "result", "status", "code", "event", "events", "flag", "flags",
    "rule", "rules", "state", "model", "view", "controller", "err", "resp"
}


class BaselineOrderingEngine:
    """Computes deterministic baseline build order from Layer 2 dependency graph."""

    def compute_baseline_order(
        self,
        file_nodes: List[FileNode],
        segmentation_result: Optional[SegmentationResult] = None,
        segmented_files: Optional[List[SegmentedFileNode]] = None,
        all_repo_files: Optional[List[str]] = None,
        raw_edges: Optional[List[ImportEdge]] = None,
        file_contents: Optional[Dict[str, str]] = None,
    ) -> BaselineOrderingResult:
        """
        Builds dependency graph, resolves intra-package symbol usages, isolates unlinked files,
        detects cycle clusters via Tarjan's SCC, and computes topological tiers.
        """
        # 1. Build Domain Mapping from Layer 4 Segmentation
        domain_map: Dict[str, str] = {}
        if segmentation_result:
            for s_node in segmentation_result.files:
                domain_val = s_node.domain.value if hasattr(s_node.domain, "value") else str(s_node.domain)
                domain_map[self._norm_path(s_node.path)] = domain_val
        elif segmented_files:
            for s_node in segmented_files:
                domain_val = s_node.domain.value if hasattr(s_node.domain, "value") else str(s_node.domain)
                domain_map[self._norm_path(s_node.path)] = domain_val

        # 2. Gather All File Universe & Edges
        universe: Set[str] = set()
        if all_repo_files:
            universe.update(self._norm_path(p) for p in all_repo_files)

        for fn in file_nodes:
            universe.add(self._norm_path(fn.path))

        all_edges: List[ImportEdge] = list(raw_edges or [])
        for fn in file_nodes:
            all_edges.extend(fn.imports)

        # 3a. Filter & Resolve Import Edges: only resolved internal edges
        valid_edges: List[Tuple[str, str]] = []
        for edge in all_edges:
            if edge.is_external:
                continue

            src = self._norm_path(edge.source_path)
            raw_tgt = self._norm_path(edge.target)

            if not src or not raw_tgt:
                continue

            universe.add(src)

            # Resolve target string to actual file path(s) in universe
            resolved_targets = self._resolve_target_files(raw_tgt, universe)
            for tgt in resolved_targets:
                if src != tgt:  # Ignore self-loops for adjacency
                    valid_edges.append((src, tgt))

        # 3b. Intra-Package / Same-Directory Symbol Reference Linking (Go package scope)
        # Group file nodes by directory / package namespace (only for languages like Go where
        # files in the same directory share package scope without explicit import statements)
        dir_to_files: Dict[str, List[FileNode]] = {}
        for fn in file_nodes:
            if getattr(fn, "language", None) == "go" or fn.path.endswith(".go"):
                norm_p = self._norm_path(fn.path)
                d = str(Path(norm_p).parent)
                dir_to_files.setdefault(d, []).append(fn)

        for d, f_nodes in dir_to_files.items():
            if len(f_nodes) <= 1:
                continue

            symbol_to_file: Dict[str, str] = {}
            for fn in f_nodes:
                norm_p = self._norm_path(fn.path)
                all_symbols = set(fn.exports) | set(fn.classes) | set(fn.functions)
                for sym in all_symbols:
                    if sym and len(sym) >= 3 and sym.lower() not in GENERIC_SYMBOL_BLACKLIST:
                        symbol_to_file[sym] = norm_p

            if file_contents:
                import re
                for fn in f_nodes:
                    src_p = self._norm_path(fn.path)
                    code = file_contents.get(fn.path) or file_contents.get(src_p) or ""
                    if not code:
                        continue

                    for sym, target_p in symbol_to_file.items():
                        if target_p != src_p:
                            pattern = r"\b" + re.escape(sym) + r"\b"
                            if re.search(pattern, code):
                                valid_edges.append((src_p, target_p))

        # 4. Compute Node Degrees & Adjacency
        deps: Dict[str, Set[str]] = {node: set() for node in universe}
        dependents: Dict[str, Set[str]] = {node: set() for node in universe}

        for src, tgt in valid_edges:
            deps[src].add(tgt)
            dependents[tgt].add(src)

        # 5. Extract Isolated Files (0 internal edges in or out)
        isolated_files: List[str] = []
        connected_nodes: Set[str] = set()

        for node in universe:
            if len(deps[node]) == 0 and len(dependents[node]) == 0:
                isolated_files.append(node)
            else:
                connected_nodes.add(node)

        isolated_files.sort()

        if not connected_nodes:
            # All files are isolated
            node_metadata = {
                node: NodeMetadata(
                    path=node,
                    domain=domain_map.get(node, "uncategorized"),
                    is_cyclic=False,
                    dependencies_count=0,
                    dependents_count=0,
                )
                for node in sorted(universe)
            }
            return BaselineOrderingResult(
                tiers=[],
                isolated_files=isolated_files,
                cyclic_files=[],
                node_metadata=node_metadata,
            )

        # 6. Tarjan's Strongly Connected Components (SCC) on Connected Nodes
        sccs = self._tarjan_scc(connected_nodes, deps)

        # Classify SCCs into cyclic vs non-cyclic
        cyclic_files_set: Set[str] = set()
        scc_is_cyclic: Dict[int, bool] = {}

        for idx, scc in enumerate(sccs):
            if len(scc) > 1:
                is_cyc = True
            elif len(scc) == 1:
                single_node = list(scc)[0]
                is_cyc = single_node in deps[single_node]
            else:
                is_cyc = False

            scc_is_cyclic[idx] = is_cyc
            if is_cyc:
                cyclic_files_set.update(scc)

        cyclic_files = sorted(list(cyclic_files_set))

        # 7. Build Condensation Graph (DAG of SCCs) & Compute Topological Tiers
        node_to_scc: Dict[str, int] = {}
        for idx, scc in enumerate(sccs):
            for node in scc:
                node_to_scc[node] = idx

        scc_deps: Dict[int, Set[int]] = {idx: set() for idx in range(len(sccs))}
        for node in connected_nodes:
            src_scc = node_to_scc[node]
            for dep_node in deps[node]:
                tgt_scc = node_to_scc[dep_node]
                if src_scc != tgt_scc:
                    scc_deps[src_scc].add(tgt_scc)

        # Compute depth for each SCC in condensation DAG
        scc_depth: Dict[int, int] = {}

        def get_scc_depth(scc_idx: int) -> int:
            if scc_idx in scc_depth:
                return scc_depth[scc_idx]
            prereqs = scc_deps[scc_idx]
            if not prereqs:
                depth = 0
            else:
                depth = 1 + max(get_scc_depth(p) for p in prereqs)
            scc_depth[scc_idx] = depth
            return depth

        for idx in range(len(sccs)):
            get_scc_depth(idx)

        # Group SCCs by depth level
        depth_to_sccs: Dict[int, List[int]] = {}
        for idx, depth in scc_depth.items():
            depth_to_sccs.setdefault(depth, []).append(idx)

        # 8. Build Ordered Tiers
        tiers: List[Tier] = []
        current_tier_index = 0

        for depth in sorted(depth_to_sccs.keys()):
            scc_indices = depth_to_sccs[depth]

            # Separate non-cyclic vs cyclic SCCs at this depth level
            non_cyclic_files_at_depth: List[str] = []
            cyclic_sccs_at_depth: List[List[str]] = []

            for scc_idx in scc_indices:
                scc_nodes_list = sorted(list(sccs[scc_idx]))
                if scc_is_cyclic[scc_idx]:
                    cyclic_sccs_at_depth.append(scc_nodes_list)
                else:
                    non_cyclic_files_at_depth.extend(scc_nodes_list)

            # First emit non-cyclic tier if any files exist at this depth
            if non_cyclic_files_at_depth:
                non_cyclic_files_at_depth.sort()
                tiers.append(
                    Tier(
                        tier_index=current_tier_index,
                        files=non_cyclic_files_at_depth,
                        is_cyclic_cluster=False,
                    )
                )
                current_tier_index += 1

            # Next emit cyclic cluster tiers at this depth
            cyclic_sccs_at_depth.sort(key=lambda s: s[0] if s else "")
            for cyc_cluster in cyclic_sccs_at_depth:
                tiers.append(
                    Tier(
                        tier_index=current_tier_index,
                        files=cyc_cluster,
                        is_cyclic_cluster=True,
                    )
                )
                current_tier_index += 1

        # 9. Build Complete Node Metadata
        node_metadata: Dict[str, NodeMetadata] = {}
        for node in sorted(universe):
            node_metadata[node] = NodeMetadata(
                path=node,
                domain=domain_map.get(node, "uncategorized"),
                is_cyclic=node in cyclic_files_set,
                dependencies_count=len(deps[node]),
                dependents_count=len(dependents[node]),
            )

        return BaselineOrderingResult(
            tiers=tiers,
            isolated_files=isolated_files,
            cyclic_files=cyclic_files,
            node_metadata=node_metadata,
        )

    def _resolve_target_files(self, raw_tgt: str, universe: Set[str]) -> List[str]:
        """Resolves an import target to actual matching file path(s) in universe."""
        raw_tgt = self._norm_path(raw_tgt)
        if not raw_tgt:
            return []

        # 1. Exact match
        if raw_tgt in universe:
            return [raw_tgt]

        # 2. Match with standard extensions
        for ext in [".py", ".go", ".ts", ".js", ".java", ".rs", ".cpp", ".h", ".tla"]:
            cand = raw_tgt + ext
            if cand in universe:
                return [cand]

        # 3. Directory / Package match: target matches a directory prefix in universe
        matching_files: List[str] = []
        prefix = raw_tgt + "/"
        for f in universe:
            if f.startswith(prefix):
                matching_files.append(f)

        if matching_files:
            return matching_files

        # 4. Suffix match
        suffix_matches: List[str] = []
        for f in universe:
            if f.endswith("/" + raw_tgt) or f.endswith("/" + raw_tgt + ".py") or f.endswith("/" + raw_tgt + ".go"):
                suffix_matches.append(f)

        if suffix_matches:
            return suffix_matches

        return []

    def _norm_path(self, path: str) -> str:
        if not path:
            return ""
        return path.replace("\\", "/")

    def _tarjan_scc(self, nodes: Set[str], graph: Dict[str, Set[str]]) -> List[Set[str]]:
        """Standard Tarjan's Strongly Connected Components algorithm."""
        index = 0
        indices: Dict[str, int] = {}
        lowlink: Dict[str, int] = {}
        stack: List[str] = []
        on_stack: Set[str] = set()
        sccs: List[Set[str]] = []

        def strongconnect(v: str):
            nonlocal index
            indices[v] = index
            lowlink[v] = index
            index += 1
            stack.append(v)
            on_stack.add(v)

            for w in graph.get(v, set()):
                if w not in connected_nodes:
                    continue
                if w not in indices:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], indices[w])

            if lowlink[v] == indices[v]:
                scc: Set[str] = set()
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    scc.add(w)
                    if w == v:
                        break
                sccs.append(scc)

        connected_nodes = nodes
        for node in sorted(list(nodes)):
            if node not in indices:
                strongconnect(node)

        return sccs
