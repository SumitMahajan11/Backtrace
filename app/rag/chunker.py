"""AST and symbol-aware code chunking engine."""

import hashlib
import re
from typing import List, Optional, Tuple

from app.parser.schema import FileNode
from app.rag.schema import CodeChunk


class ASTCodeChunker:
    """Chunks code files using AST symbol boundaries with sliding window overlap fallback."""

    def __init__(self, max_chunk_lines: int = 40, overlap_lines: int = 8):
        self.max_chunk_lines = max_chunk_lines
        self.overlap_lines = overlap_lines

    def chunk_file(
        self,
        file_path: str,
        code_content: str,
        file_node: Optional[FileNode] = None,
    ) -> List[CodeChunk]:
        """Chunks a file's content into CodeChunk objects."""
        if not code_content or not code_content.strip():
            return []

        lines = code_content.splitlines()
        total_lines = len(lines)
        if total_lines == 0:
            return []

        chunks: List[CodeChunk] = []
        symbol_spans: List[Tuple[str, int, int]] = []  # (symbol_name, start_line_1idx, end_line_1idx)

        # 1. Attempt symbol boundary identification using FileNode metadata
        if file_node:
            symbol_spans = self._extract_symbol_spans(lines, file_node)

        chunked_line_coverage = [False] * total_lines

        # Create symbol-aware chunks
        for sym_name, s_start, s_end in symbol_spans:
            s_start_0 = max(0, s_start - 1)
            s_end_0 = min(total_lines, s_end)
            if s_end_0 <= s_start_0:
                continue

            # If symbol block is larger than max_chunk_lines, split it into sliding sub-chunks
            sym_lines_count = s_end_0 - s_start_0
            if sym_lines_count > self.max_chunk_lines:
                sub_chunks = self._sliding_window_chunk(
                    file_path=file_path,
                    lines=lines[s_start_0:s_end_0],
                    line_offset_0=s_start_0,
                    symbol_name=sym_name,
                    language=file_node.language if file_node else None,
                )
                chunks.extend(sub_chunks)
            else:
                chunk_lines = lines[s_start_0:s_end_0]
                chunk_id = self._generate_chunk_id(file_path, s_start, s_end_0, sym_name)
                chunks.append(
                    CodeChunk(
                        chunk_id=chunk_id,
                        file_path=file_path,
                        start_line=s_start,
                        end_line=s_end_0,
                        content="\n".join(chunk_lines),
                        symbol_name=sym_name,
                        language=file_node.language if file_node else None,
                    )
                )

            for i in range(s_start_0, s_end_0):
                chunked_line_coverage[i] = True

        # 2. Sliding window chunking for unchunked lines (or full file if no symbols extracted)
        uncovered_start = None
        for idx in range(total_lines):
            if not chunked_line_coverage[idx]:
                if uncovered_start is None:
                    uncovered_start = idx
            else:
                if uncovered_start is not None:
                    block_lines = lines[uncovered_start:idx]
                    sub_chunks = self._sliding_window_chunk(
                        file_path=file_path,
                        lines=block_lines,
                        line_offset_0=uncovered_start,
                        symbol_name=None,
                        language=file_node.language if file_node else None,
                    )
                    chunks.extend(sub_chunks)
                    uncovered_start = None

        if uncovered_start is not None:
            block_lines = lines[uncovered_start:total_lines]
            sub_chunks = self._sliding_window_chunk(
                file_path=file_path,
                lines=block_lines,
                line_offset_0=uncovered_start,
                symbol_name=None,
                language=file_node.language if file_node else None,
            )
            chunks.extend(sub_chunks)

        # Sort chunks by start_line
        chunks.sort(key=lambda c: (c.start_line, c.end_line))
        return chunks

    def _extract_symbol_spans(self, lines: List[str], file_node: FileNode) -> List[Tuple[str, int, int]]:
        """Scans lines to find start and end line ranges for symbols in file_node."""
        spans: List[Tuple[str, int, int]] = []
        total_lines = len(lines)
        symbols = list(set(file_node.functions + file_node.classes))

        for sym in symbols:
            clean_sym = sym.split(".")[-1]
            # Multi-language pattern matching (Python def, Java/C++ type/modifiers, Go func, Rust fn, JS/TS function/class)
            pattern = re.compile(rf"\b(def|fn|func|class|struct|interface|function|public|private|protected|static|void|[A-Z]\w+)\s+.*\b{re.escape(clean_sym)}\b")

            for idx, line in enumerate(lines):
                if pattern.search(line) or f" {clean_sym}(" in line or f" {clean_sym} " in line:
                    start_line_1 = idx + 1
                    end_line_1 = total_lines
                    for next_idx in range(idx + 1, total_lines):
                        if any(s.split(".")[-1] in lines[next_idx] for s in symbols if s != sym):
                            if "def " in lines[next_idx] or "func " in lines[next_idx] or "fn " in lines[next_idx] or "public " in lines[next_idx] or "class " in lines[next_idx]:
                                end_line_1 = next_idx
                                break

                    spans.append((sym, start_line_1, end_line_1))
                    break

        return spans

    def _sliding_window_chunk(
        self,
        file_path: str,
        lines: List[str],
        line_offset_0: int,
        symbol_name: Optional[str] = None,
        language: Optional[str] = None,
    ) -> List[CodeChunk]:
        """Splits lines into overlapping windows."""
        chunks: List[CodeChunk] = []
        total = len(lines)
        if total == 0:
            return chunks

        start = 0
        step = max(1, self.max_chunk_lines - self.overlap_lines)

        while start < total:
            end = min(total, start + self.max_chunk_lines)
            chunk_lines = lines[start:end]

            s_line_1 = line_offset_0 + start + 1
            e_line_1 = line_offset_0 + end
            chunk_id = self._generate_chunk_id(file_path, s_line_1, e_line_1, symbol_name)

            chunks.append(
                CodeChunk(
                    chunk_id=chunk_id,
                    file_path=file_path,
                    start_line=s_line_1,
                    end_line=e_line_1,
                    content="\n".join(chunk_lines),
                    symbol_name=symbol_name,
                    language=language,
                )
            )

            if end >= total:
                break
            start += step

        return chunks

    @staticmethod
    def _generate_chunk_id(file_path: str, start_line: int, end_line: int, symbol: Optional[str]) -> str:
        raw = f"{file_path}:{start_line}-{end_line}:{symbol or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
