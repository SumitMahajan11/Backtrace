"""Unit tests for Go static structural parser (Layer 2 Part 2)."""

import pytest
from app.parser.go_parser import GoLanguageParser
from app.parser.schema import ImportCategory


def test_go_static_imports():
    code = 'package main\nimport "fmt"\nimport "os"'
    parser = GoLanguageParser()
    node, edges = parser.parse_single_file("main.go", code, {"main.go"})
    targets = {e.target: e for e in edges}
    assert "fmt" in targets
    assert targets["fmt"].category == ImportCategory.STATIC
    assert targets["fmt"].is_external is False


def test_go_grouped_imports():
    code = 'package main\nimport (\n    "math"\n    "strings"\n)'
    parser = GoLanguageParser()
    node, edges = parser.parse_single_file("main.go", code, {"main.go"})
    targets = {e.target: e for e in edges}
    assert "math" in targets
    assert "strings" in targets


def test_go_aliased_imports():
    code = 'package main\nimport f "path/filepath"'
    parser = GoLanguageParser()
    node, edges = parser.parse_single_file("main.go", code, {"main.go"})
    edge = edges[0]
    assert edge.target == "path/filepath"
    assert edge.raw_import_symbol == 'f "path/filepath"'


def test_go_blank_imports():
    code = 'package main\nimport _ "github.com/lib/pq"'
    parser = GoLanguageParser()
    node, edges = parser.parse_single_file("main.go", code, {"main.go"})
    edge = edges[0]
    assert edge.target == "github.com/lib/pq"
    assert edge.category == ImportCategory.BLANK
    assert edge.is_external is True


def test_go_entry_point_detection():
    code = 'package main\nfunc main() {}\nfunc helper() {}'
    parser = GoLanguageParser()
    node, edges = parser.parse_single_file("main.go", code, {"main.go"})
    assert node.entry_point is True
    assert node.entry_point_type == "main_function"
    assert "main" in node.functions
    assert "helper" in node.functions


def test_go_internal_vs_external_import_resolution():
    code = """
package server

import (
    "github.com/gin-gonic/gin"
    "github.com/myorg/myapp/pkg/utils"
    "github.com/myorg/myapp/pkg/missing"
)

func Serve() {}
"""
    parser = GoLanguageParser()
    parser.set_module_name("github.com/myorg/myapp")

    all_files = {
        "server/main.go",
        "pkg/utils/helper.go",
    }

    node, edges = parser.parse_single_file("server/main.go", code, all_files)

    # Gin is external
    gin_edge = next(e for e in edges if e.target == "github.com/gin-gonic/gin")
    assert gin_edge.is_external is True
    assert gin_edge.resolved is False

    # pkg/utils exists in all_files -> internal resolved
    utils_edge = next(e for e in edges if e.target == "pkg/utils")
    assert utils_edge.is_external is False
    assert utils_edge.resolved is True

    # pkg/missing does not exist in all_files -> internal unresolved
    missing_edge = next(e for e in edges if e.target == "pkg/missing")
    assert missing_edge.is_external is False
    assert missing_edge.resolved is False


def test_go_malformed_syntax_error():
    malformed_code = """
package main

func main( { // syntax error: missing closing parenthesis
    fmt.Println("hello")
"""
    parser = GoLanguageParser()
    file_contents = {"bad.go": malformed_code}

    result = parser.parse_repository(["bad.go"], file_contents)

    assert len(result.parse_errors) == 1
    assert result.parse_errors[0].path == "bad.go"
    assert result.parse_errors[0].language == "go"
    assert "syntax error" in result.parse_errors[0].error_message.lower() or "expected" in result.parse_errors[0].error_message.lower()
