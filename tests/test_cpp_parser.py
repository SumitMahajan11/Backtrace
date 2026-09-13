"""Unit tests for C++ structural parser via libclang (Layer 2 Part 2)."""

import pytest
from app.parser.cpp_parser import CppLanguageParser
from app.parser.schema import ImportCategory


def test_cpp_missing_header_diagnostic_is_non_fatal():
    """Confirms missing header diagnostic does NOT trigger a ParseError and symbols are extracted."""
    code = """
#include <iostream>
#include "non_existent_header.h"

class Calculator {
public:
    int add(int a, int b) {
        return a + b;
    }
};

int main() {
    Calculator calc;
    return 0;
}
"""
    parser = CppLanguageParser()
    all_files = {"src/main.cpp"}

    node, edges = parser.parse_single_file("src/main.cpp", code, all_files)

    assert node.path == "src/main.cpp"
    assert node.language == "cpp"
    assert node.entry_point is True
    assert node.entry_point_type == "main_function"
    assert "Calculator" in node.classes
    assert "main" in node.functions

    # System include <iostream>
    sys_edge = next(e for e in edges if e.target == "iostream")
    assert sys_edge.resolved is True

    # Missing local header "non_existent_header.h" -> resolved=False, NOT a ParseError!
    local_edge = next(e for e in edges if "non_existent_header.h" in e.target)
    assert local_edge.resolved is False


def test_cpp_genuine_syntax_error_produces_parse_error():
    """Confirms genuine syntax error in file code produces a ParseError."""
    malformed_code = """
class BrokenClass {
public:
    int calc(int a { // Syntax error: missing closing parenthesis and brace
        return 0;
"""
    parser = CppLanguageParser()
    file_contents = {"src/broken.cpp": malformed_code}

    result = parser.parse_repository(["src/broken.cpp"], file_contents)

    assert len(result.parse_errors) == 1
    assert result.parse_errors[0].path == "src/broken.cpp"
    assert result.parse_errors[0].language == "cpp"
    assert "syntax error" in result.parse_errors[0].error_message.lower() or "expected" in result.parse_errors[0].error_message.lower() or "error" in result.parse_errors[0].error_message.lower()


def test_cpp_header_file_parsing():
    """Confirms .h / .hpp header files are parsed as first-class inputs."""
    header_code = """
#ifndef UTILS_H
#define UTILS_H

#include <string>

namespace Utils {
    class StringHelper {
    public:
        static std::string trim(const std::string& str);
    };
}

#endif
"""
    parser = CppLanguageParser()
    all_files = {"include/utils.h"}

    node, edges = parser.parse_single_file("include/utils.h", header_code, all_files)

    assert node.path == "include/utils.h"
    assert node.language == "cpp"
    assert node.entry_point is False
    assert "StringHelper" in node.classes


def test_cpp_local_include_resolution_and_macros():
    """Confirms local include resolution against all_repo_files and explicit macro/template tracking."""
    cpp_code = """
#include "helper.h"
#define MAX_SIZE 100

template <typename T>
class Container {
public:
    T data;
};

template <typename T>
T identity(T val) {
    return val;
}

int main() {
    int x = MAX_SIZE;
    return 0;
}
"""
    parser = CppLanguageParser()
    all_files = {"src/main.cpp", "src/helper.h"}

    node, edges = parser.parse_single_file("src/main.cpp", cpp_code, all_files)

    # 1. Local include helper.h exists in all_files -> resolved=True
    inc_edge = next(e for e in edges if e.target == "src/helper.h")
    assert inc_edge.resolved is True
    assert inc_edge.is_external is False

    # 2. Template class & function declarations extracted in symbols
    assert "Container" in node.classes
    assert "identity" in node.functions

    # 3. Macro edges tracked
    macro_edges = [e for e in edges if e.target == "macro::MAX_SIZE"]
    assert len(macro_edges) >= 1
    assert macro_edges[0].import_type == "macro"
