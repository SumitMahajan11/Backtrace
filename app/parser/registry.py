"""Parser Registry orchestrating multi-language parsing across repository files."""

from typing import Dict, List, Optional
from app.parser.base import BaseLanguageParser
from app.parser.cpp_parser import CppLanguageParser
from app.parser.go_parser import GoLanguageParser
from app.parser.java_parser import JavaLanguageParser
from app.parser.javascript_parser import JavaScriptLanguageParser
from app.parser.python_parser import PythonLanguageParser
from app.parser.rust_parser import RustLanguageParser
from app.parser.shell_parser import ShellLanguageParser
from app.parser.tla_parser import TlaLanguageParser
from app.parser.schema import ParserResult


class ParserRegistry:
    """Registry managing available language parsers and routing repository files."""

    def __init__(self):
        self._parsers: List[BaseLanguageParser] = []
        self._register_default_parsers()

    def register_parser(self, parser: BaseLanguageParser) -> None:
        """Registers a new per-language parser instance."""
        self._parsers.append(parser)

    def _register_default_parsers(self) -> None:
        self.register_parser(PythonLanguageParser())
        self.register_parser(JavaScriptLanguageParser())
        self.register_parser(JavaLanguageParser())
        self.register_parser(GoLanguageParser())
        self.register_parser(RustLanguageParser())
        self.register_parser(ShellLanguageParser())
        self.register_parser(CppLanguageParser())
        self.register_parser(TlaLanguageParser())


    def get_parser_for_file(self, file_path: str) -> Optional[BaseLanguageParser]:
        """Finds matching language parser for a file path by extension."""
        ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        for parser in self._parsers:
            if ext in parser.file_extensions:
                return parser
        return None

    def parse_repository_files(
        self, file_paths: List[str], file_contents: Dict[str, str]
    ) -> Dict[str, ParserResult]:
        """
        Groups repository files by language and executes static analysis for each parser.
        Returns a dictionary mapping language_name to ParserResult.
        """
        results: Dict[str, ParserResult] = {}
        for parser in self._parsers:
            res = parser.parse_repository(file_paths, file_contents)
            if res.file_nodes or res.parse_errors:
                results[parser.language_name] = res
        return results
