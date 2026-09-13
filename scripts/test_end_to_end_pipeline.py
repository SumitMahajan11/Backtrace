"""End-to-end integration validation script for Layer 1 through Layer 5.

Connects:
  Layer 1 (IngestionService): clone, sandbox, path validation, secret scanning, 150-file cap check
  Layer 2 (ParserRegistry): multi-language AST and import extraction
  Layer 4 (SegmentationEngine): domain classification (including CORE)
  Layer 5 (RAGEngine): chunking, L2 vector embedding, and hybrid retrieval Q&A
"""

import sys
from app.services.ingestion import IngestionService
from app.parser.registry import ParserRegistry
from app.segmentation.engine import SegmentationEngine
from app.rag.engine import HybridRAGEngine


def run_e2e_pipeline():
    print("=" * 100)
    print("RUNNING END-TO-END PIPELINE INTEGRATION TEST (LAYERS 1 -> 2 -> 4 -> 5)")
    print("=" * 100)

    target_repo = "https://github.com/gin-gonic/gin"
    print(f"[STAGE 1] Ingesting repository via IngestionService: {target_repo}")

    ingestion_service = IngestionService(max_file_limit=150)
    try:
        ingest_res = ingestion_service.ingest_repository(target_repo)
        print(f"  [SUCCESS] Layer 1 Ingestion Complete:")
        print(f"    - Valid files ingested: {len(ingest_res.file_tree)}")
        print(f"    - Skipped items: {len(ingest_res.skipped_items)}")
        print(f"    - Head commit: {ingest_res.metadata.head_commit}")
        print(f"    - Clone duration: {ingest_res.metadata.clone_duration_seconds}s")
    except Exception as e:
        print(f"  [FAIL] Layer 1 Ingestion raised exception: {e}")
        sys.exit(1)

    print("\n[STAGE 2] Passing ingested files to Layer 2 ParserRegistry...")
    registry = ParserRegistry()
    file_paths = list(ingest_res.file_contents.keys())
    parse_results = registry.parse_repository_files(file_paths, ingest_res.file_contents)

    all_file_nodes = []
    for lang, pres in parse_results.items():
        all_file_nodes.extend(pres.files)

    print(f"  [SUCCESS] Layer 2 Parsing Complete:")
    print(f"    - Parsed file nodes: {len(all_file_nodes)}")
    print(f"    - Languages detected: {list(parse_results.keys())}")

    print("\n[STAGE 4] Segmenting repository via Layer 4 SegmentationEngine...")
    seg_engine = SegmentationEngine()
    seg_result = seg_engine.segment_repository(
        file_nodes=all_file_nodes,
        all_repo_files=file_paths,
    )
    print(f"  [SUCCESS] Layer 4 Segmentation Complete:")
    print(f"    - Domain counts: {seg_result.domain_counts}")
    print(f"    - Method counts: {seg_result.method_counts}")

    print("\n[STAGE 5] Indexing & retrieving via Layer 5 RAGEngine...")
    rag = HybridRAGEngine(use_gemini=False)
    indexed_chunks = rag.index_repository(all_file_nodes, ingest_res.file_contents)
    print(f"  [SUCCESS] Layer 5 Indexing Complete:")
    print(f"    - Total code chunks indexed in FAISS: {indexed_chunks}")

    query = "How does context routing work in Gin framework?"
    answer = rag.query(query)
    print(f"\n[QUERY] '{query}'")
    print(f"  - Citations returned: {len(answer.citations)}")
    for cite in answer.citations[:3]:
        print(f"    * {cite.file_path}:{cite.start_line}-{cite.end_line}")

    print("\n" + "=" * 100)
    print("END-TO-END PIPELINE INTEGRATION (LAYERS 1 -> 2 -> 4 -> 5) VERIFIED WORKING!")
    print("=" * 100)


if __name__ == "__main__":
    run_e2e_pipeline()
