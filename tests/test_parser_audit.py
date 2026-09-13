"""Audit test suite for Python, JS/TS, and Java parsers.

Verifies:
1. Real-repo validation on complex real files.
2. Filesystem-verified import resolution (resolved: true ONLY if present in all_repo_files).
3. Malformed-file error handling (populates parse_errors without crashing).
"""

import pytest
from app.parser.python_parser import PythonLanguageParser
from app.parser.javascript_parser import JavaScriptLanguageParser
from app.parser.java_parser import JavaLanguageParser
from app.parser.registry import ParserRegistry
from app.parser.schema import ImportCategory


def test_audit_python_real_file():
    """Audit Criterion 2: Python parser against real codebase files."""
    parser = PythonLanguageParser()
    with open("app/services/ingestion.py", "r", encoding="utf-8") as f:
        code = f.read()

    all_files = {
        "app/services/ingestion.py",
        "app/utils/url_validator.py",
        "app/utils/file_filter.py",
        "app/security/secret_scanner.py",
    }
    node, edges = parser.parse_single_file("app/services/ingestion.py", code, all_files)

    assert node.path == "app/services/ingestion.py"
    assert node.language == "python"
    assert "IngestionService" in node.classes
    assert len(edges) > 0

    # Verify resolved edges point to files actually in all_files
    for edge in edges:
        if edge.resolved:
            assert edge.target in all_files


def test_audit_javascript_real_file_ast():
    """Audit Criterion 1 & 2: JS/TS Babel AST parser against real TS/JSX constructs."""
    code = """
import React, { useState, useEffect } from 'react';
import { Button } from './components/Button';
import type { UserProfile } from './types/user';
import * as Utils from './utils';

export interface AppProps {
    title: string;
}

export class MainApp extends React.Component<AppProps> {
    private state = { count: 0 };

    public render() {
        return <Button onClick={() => this.setState({ count: this.state.count + 1 })} />;
    }
}

export const helperFunc = async (id: string): Promise<boolean> => {
    const lazy = await import('./lazyService');
    return true;
};
    """
    parser = JavaScriptLanguageParser()
    all_files = {
        "src/App.tsx",
        "src/components/Button.tsx",
        "src/types/user.ts",
        "src/utils/index.ts",
        "src/lazyService.ts",
    }

    node, edges = parser.parse_single_file("src/App.tsx", code, all_files)

    assert node.language == "javascript"
    assert "MainApp" in node.classes
    assert "helperFunc" in node.functions
    assert "MainApp" in node.exports
    assert "helperFunc" in node.exports

    # Check edges
    react_edge = next(e for e in edges if e.target == "react")
    assert react_edge.is_external is True

    btn_edge = next(e for e in edges if e.target == "src/components/Button.tsx")
    assert btn_edge.is_external is False
    assert btn_edge.resolved is True

    lazy_edge = next(e for e in edges if e.target == "src/lazyService.ts")
    assert lazy_edge.import_type == "dynamic"
    assert lazy_edge.resolved is False  # dynamic imports marked resolved=False per spec


def test_audit_java_real_file():
    """Audit Criterion 2: Java parser against real Java source with packages and main."""
    code = """
package com.example.service;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import com.example.model.UserRecord;
import com.example.repository.UserRepository;

public class UserService implements IUserService {
    private final UserRepository repository;

    public UserService(UserRepository repository) {
        this.repository = repository;
    }

    public List<UserRecord> listUsers() {
        return repository.findAll();
    }

    public static void main(String[] args) {
        System.out.println("UserService CLI runner");
    }
}
    """
    parser = JavaLanguageParser()
    all_files = {
        "src/main/java/com/example/service/UserService.java",
        "src/main/java/com/example/model/UserRecord.java",
        "src/main/java/com/example/repository/UserRepository.java",
    }

    node, edges = parser.parse_single_file("src/main/java/com/example/service/UserService.java", code, all_files)

    assert node.language == "java"
    assert node.entry_point is True
    assert node.entry_point_type == "public_static_void_main"
    assert "UserService" in node.classes
    assert "listUsers" in node.functions

    user_edge = next(e for e in edges if "UserRecord" in e.raw_import_symbol)
    assert user_edge.is_external is False
    assert user_edge.resolved is True
    assert user_edge.target == "src/main/java/com/example/model/UserRecord.java"


def test_audit_import_resolution_missing_target_verification():
    """Audit Criterion 3: Missing internal import targets must be resolved=False."""
    py_code = "import app.missing_module"
    py_parser = PythonLanguageParser()
    py_res = py_parser.parse_repository(["main.py"], {"main.py": py_code})
    py_edge = py_res.file_nodes[0].imports[0]
    assert py_edge.is_external is True  # Top package not found in repo -> external
    assert py_edge.resolved is False

    js_code = "import { Foo } from './missingComponent';"
    js_parser = JavaScriptLanguageParser()
    # Notice all_files does NOT contain missingComponent
    js_node, js_edges = js_parser.parse_single_file("src/App.js", js_code, {"src/App.js"})
    js_edge = js_edges[0]
    assert js_edge.is_external is False
    assert js_edge.resolved is False  # Target file missing from all_files -> resolved=False!

    java_code = "import com.missing.PackageClass;"
    java_parser = JavaLanguageParser()
    java_node, java_edges = java_parser.parse_single_file("Main.java", java_code, {"Main.java"})
    java_edge = java_edges[0]
    assert java_edge.is_external is True  # Missing Java class -> external fallback
    assert java_edge.resolved is False


def test_audit_malformed_file_resilience_all_languages():
    """Audit Criterion 4: Malformed-file handling across Python, JS/TS, and Java."""
    registry = ParserRegistry()
    files = {
        "broken.py": "def malformed_python_func(:",
        "broken.js": "const brokenJS = {;",
        "broken.java": "public class BrokenJava { void foo( {",
    }

    results = registry.parse_repository_files(list(files.keys()), files)

    # Verify each language recorded a parse error without crashing the batch run
    for lang in ["python", "javascript", "java"]:
        assert lang in results, f"Language {lang} missing from results"
        res = results[lang]
        assert len(res.parse_errors) == 1, f"Expected 1 parse error for {lang}, got {len(res.parse_errors)}"
        err = res.parse_errors[0]
        assert err.language == lang
        assert err.error_message is not None and len(err.error_message) > 0
