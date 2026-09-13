"""Unit tests for Java static structural parser (Layer 2)."""

import pytest
from app.parser.java_parser import JavaLanguageParser
from app.parser.registry import ParserRegistry
from app.parser.schema import ImportCategory


def test_java_imports_and_entry_point():
    code = """
package com.example.app;

import java.util.List;
import java.util.Map;
import java.io.*;
import com.example.models.User;

public class MainApp {
    public static void main(String[] args) {
        System.out.println("Starting app...");
        try {
            Class.forName("org.postgresql.Driver");
        } catch (ClassNotFoundException e) {
            e.printStackTrace();
        }
    }
}
    """
    parser = JavaLanguageParser()
    all_files = {
        "src/main/java/com/example/app/MainApp.java",
        "src/main/java/com/example/models/User.java",
    }

    file_path = "src/main/java/com/example/app/MainApp.java"
    node, edges = parser.parse_single_file(file_path, code, all_files)

    assert node.path == file_path
    assert node.language == "java"
    assert node.is_entry_point is True
    assert node.entry_point_type == "public_static_void_main"
    assert "MainApp" in node.classes
    assert "main" in node.functions

    categories = {e.raw_import_symbol: e.category for e in edges}
    assert categories["import java.util.List"] == ImportCategory.STATIC
    assert categories["import java.io.*"] == ImportCategory.WILDCARD
    assert categories['Class.forName("org.postgresql.Driver")'] == ImportCategory.DYNAMIC

    # Check internal vs external resolution
    user_edge = next(e for e in edges if e.raw_import_symbol == "import com.example.models.User")
    assert user_edge.is_external is False
    assert user_edge.target_path == "src/main/java/com/example/models/User.java"

    jdk_edge = next(e for e in edges if e.raw_import_symbol == "import java.util.List")
    assert jdk_edge.is_external is True


def test_java_syntax_error_handling():
    code = "public class BrokenSyntax { void test( {"
    parser = JavaLanguageParser()
    res = parser.parse_repository(["src/BrokenSyntax.java"], {"src/BrokenSyntax.java": code})

    assert len(res.parse_errors) == 1
    assert res.parse_errors[0].path == "src/BrokenSyntax.java"
    assert res.parse_errors[0].language == "java"


def test_java_registry_integration():
    registry = ParserRegistry()
    files = {
        "src/main/java/com/example/Application.java": """
            package com.example;
            import java.util.ArrayList;
            public class Application {
                public static void main(String[] args) {}
            }
        """
    }

    results = registry.parse_repository_files(list(files.keys()), files)

    assert "java" in results
    java_res = results["java"]
    assert len(java_res.file_nodes) == 1
    assert java_res.file_nodes[0].is_entry_point is True
    assert "java.util.ArrayList" in java_res.external_dependencies
