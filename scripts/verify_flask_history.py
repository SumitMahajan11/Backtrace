import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.history_extractor import HistoryExtractorService

repo_dir = Path("tests/fixtures/real_repos/flask")
if not repo_dir.exists():
    print("Flask repo fixture not found at tests/fixtures/real_repos/flask")
    sys.exit(0)

print(f"Executing history extraction on fixture: {repo_dir}")
service = HistoryExtractorService()
result = service.extract_history(repo_dir)

print(f"history_available: {result.history_available}")
print(f"history_confidence: {result.history_confidence}")
print(f"commit_count_processed: {result.commit_count_processed}")
print(f"commit_count_total: {result.commit_count_total}")
print(f"file_first_appearance count: {len(result.file_first_appearance)}")
