"""Graph-based dependency clustering fallback for file segmentation using networkx."""

from collections import Counter
from typing import Dict, List, Optional, Set, Tuple
import networkx as nx

from app.parser.schema import FileNode
from app.segmentation.schema import ClassificationMethod, ConfidenceLevel, DomainType, SegmentedFileNode


class DependencyGraphClusterer:
    """Secondary classifier that uses Layer 2 dependency edges and graph community detection."""

    @classmethod
    def classify_unclassified(
        cls,
        unclassified_paths: Set[str],
        file_nodes: List[FileNode],
        classified_domains: Dict[str, DomainType],
        consensus_threshold: float = 0.5,
    ) -> Dict[str, Tuple[DomainType, ClassificationMethod, ConfidenceLevel]]:
        """Classifies uncategorized files based on graph community consensus.

        Args:
            unclassified_paths: Paths of files not yet classified by conventions.
            file_nodes: All FileNode objects from Layer 2 parsing.
            classified_domains: Dict mapping path -> DomainType for convention-classified files.
            consensus_threshold: Minimum required fraction of classified community member consensus
                                 (default 0.5 = 50% majority requirement). Tunable hyperparameter.

        Returns:
            Dict mapping path -> (DomainType, ClassificationMethod, ConfidenceLevel).
        """
        results: Dict[str, Tuple[DomainType, ClassificationMethod, ConfidenceLevel]] = {}
        if not unclassified_paths or not file_nodes:
            return results

        # 1. Build undirected graph from internal resolved imports
        G = nx.Graph()

        all_paths = {fn.path for fn in file_nodes}
        for path in all_paths:
            G.add_node(path)

        for fn in file_nodes:
            src_path = fn.path
            for edge in fn.imports:
                if edge.resolved and not edge.is_external:
                    tgt_path = edge.target
                    if tgt_path in all_paths and src_path != tgt_path:
                        G.add_edge(src_path, tgt_path)

        # 2. Run community detection if graph has edges
        if G.number_of_edges() == 0:
            for path in unclassified_paths:
                results[path] = (DomainType.UNCATEGORIZED, ClassificationMethod.UNCATEGORIZED, ConfidenceLevel.LOW)
            return results

        try:
            communities = list(nx.community.greedy_modularity_communities(G))
        except Exception:
            # Fallback to connected components if community detection fails
            communities = [set(c) for c in nx.connected_components(G)]

        # 3. For each community, evaluate domain consensus of convention-classified members
        for community in communities:
            community_set = set(community)
            unclassified_in_comm = community_set.intersection(unclassified_paths)
            if not unclassified_in_comm:
                continue

            # Gather domains of classified nodes in this community
            classified_members = [
                classified_domains[p] for p in community_set
                if p in classified_domains and classified_domains[p] != DomainType.UNCATEGORIZED
            ]

            if classified_members:
                counts = Counter(classified_members)
                most_common_domain, top_count = counts.most_common(1)[0]
                total_classified = len(classified_members)

                # Require >= consensus_threshold fraction of classified members in the community
                if (top_count / total_classified) >= consensus_threshold:
                    for path in unclassified_in_comm:
                        results[path] = (most_common_domain, ClassificationMethod.GRAPH, ConfidenceLevel.MEDIUM)
                    continue

            # If no consensus or no classified members, remain UNCATEGORIZED
            for path in unclassified_in_comm:
                results[path] = (DomainType.UNCATEGORIZED, ClassificationMethod.UNCATEGORIZED, ConfidenceLevel.LOW)

        # Handle any remaining unclassified paths not touched by communities
        for path in unclassified_paths:
            if path not in results:
                results[path] = (DomainType.UNCATEGORIZED, ClassificationMethod.UNCATEGORIZED, ConfidenceLevel.LOW)

        return results
