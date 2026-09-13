"""Main Layer 4 Segmentation Engine orchestrator."""

from collections import Counter
from typing import Dict, List, Optional, Set

from app.parser.schema import FileNode
from app.segmentation.graph_clusterer import DependencyGraphClusterer
from app.segmentation.rules import ConventionRulesEngine
from app.segmentation.schema import (
    ClassificationMethod,
    ConfidenceLevel,
    DomainType,
    SegmentedFileNode,
    SegmentationResult,
)


class SegmentationEngine:
    """Orchestrates primary convention matching and secondary graph-clustering segmentation."""

    def __init__(self):
        self.rules_engine = ConventionRulesEngine()
        self.clusterer = DependencyGraphClusterer()

    def segment_repository(
        self,
        file_nodes: List[FileNode],
        all_repo_files: Optional[List[str]] = None,
    ) -> SegmentationResult:
        """Segments all repository files into architectural domains.

        Args:
            file_nodes: Parsed FileNode objects from Layer 2.
            all_repo_files: Optional list of all repository relative file paths.

        Returns:
            SegmentationResult containing SegmentedFileNodes and summary counts.
        """
        # Determine total paths to analyze
        node_map: Dict[str, FileNode] = {fn.path: fn for fn in file_nodes}
        all_paths: Set[str] = set(node_map.keys())
        if all_repo_files:
            all_paths.update(all_repo_files)

        convention_domains: Dict[str, DomainType] = {}
        convention_results: Dict[str, SegmentedFileNode] = {}
        unclassified_paths: Set[str] = set()

        # Step 1: Primary folder / naming convention classification
        for path in sorted(list(all_paths)):
            node = node_map.get(path)
            lang = node.language if node else None
            domain, confidence = self.rules_engine.classify(path, language=lang)

            if domain != DomainType.UNCATEGORIZED:
                convention_domains[path] = domain
                convention_results[path] = SegmentedFileNode(
                    path=path,
                    domain=domain,
                    classification_method=ClassificationMethod.CONVENTION,
                    confidence=confidence,
                    language=lang,
                )
            else:
                unclassified_paths.add(path)

        # Step 2: Secondary dependency graph fallback for unclassified files
        graph_results = self.clusterer.classify_unclassified(
            unclassified_paths=unclassified_paths,
            file_nodes=file_nodes,
            classified_domains=convention_domains,
        )

        # Step 3: Combine all classification results
        final_file_nodes: List[SegmentedFileNode] = []
        for path in sorted(list(all_paths)):
            if path in convention_results:
                final_file_nodes.append(convention_results[path])
            elif path in graph_results:
                domain, method, confidence = graph_results[path]
                node = node_map.get(path)
                final_file_nodes.append(
                    SegmentedFileNode(
                        path=path,
                        domain=domain,
                        classification_method=method,
                        confidence=confidence,
                        language=node.language if node else None,
                    )
                )
            else:
                node = node_map.get(path)
                final_file_nodes.append(
                    SegmentedFileNode(
                        path=path,
                        domain=DomainType.UNCATEGORIZED,
                        classification_method=ClassificationMethod.UNCATEGORIZED,
                        confidence=ConfidenceLevel.LOW,
                        language=node.language if node else None,
                    )
                )

        # Step 4: Compute summary metrics
        domain_counts = dict(Counter(f.domain.value for f in final_file_nodes))
        method_counts = dict(Counter(f.classification_method.value for f in final_file_nodes))

        return SegmentationResult(
            files=final_file_nodes,
            domain_counts=domain_counts,
            method_counts=method_counts,
        )
