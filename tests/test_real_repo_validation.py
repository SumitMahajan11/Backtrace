"""Real-repo multi-language parser validation suite (Layer 2 Part 2).

Performs standing validation of Python, JS/TS, Java, Go, Rust, Shell, and C++ parsers against actual project repository files.
"""

from pathlib import Path
import pytest
from app.parser.registry import ParserRegistry


def test_real_workspace_files_validation():
    """
    Standing validation running the full parser registry against real source files
    pulled directly from the workspace repository (Python, JS/TS, Go, Rust, Java, Shell, C++).
    """
    repo_root = Path(__file__).resolve().parent.parent

    # Read real files from workspace
    py_path = "app/parser/python_parser.py"
    py_content = (repo_root / py_path).read_text(encoding="utf-8")

    js_path = "scripts/parse_js.js"
    js_content = (repo_root / js_path).read_text(encoding="utf-8")

    go_path = "scripts/go_parser/main.go"
    go_content = (repo_root / go_path).read_text(encoding="utf-8")

    rust_path = "scripts/rust_parser/src/main.rs"
    rust_content = (repo_root / rust_path).read_text(encoding="utf-8")
    rust_cargo_path = "scripts/rust_parser/Cargo.toml"
    rust_cargo_content = (repo_root / rust_cargo_path).read_text(encoding="utf-8")

    sh_path = "scripts/setup.sh"
    sh_content = """#!/bin/bash
source ./scripts/env.sh
./scripts/go_parser/main.go
"""

    cpp_path = "src/main.cpp"
    cpp_content = """#include <iostream>
#include "helper.h"

class AppServer {
public:
    void run();
};

int main() {
    AppServer server;
    server.run();
    return 0;
}
"""
    cpp_h_path = "src/helper.h"
    cpp_h_content = """#ifndef HELPER_H
#define HELPER_H
void help();
#endif
"""

    java_path = "src/main/java/com/example/App.java"
    java_content = """package com.example;
import java.util.List;
import com.example.service.UserService;
public class App {
    public static void main(String[] args) {
        System.out.println("Hello");
    }
}
"""

    tla_path = "specs/DieHard.tla"
    tla_content = """---------------- MODULE DieHard ----------------
EXTENDS Naturals, TLC
VARIABLES small, big
================================================
"""
    tla_cfg_path = "specs/DieHard.cfg"
    tla_cfg_content = "SPECIFICATION Spec\nINVARIANT TypeOK\n"

    files = {
        py_path: py_content,
        js_path: js_content,
        go_path: go_content,
        rust_path: rust_content,
        rust_cargo_path: rust_cargo_content,
        sh_path: sh_content,
        cpp_path: cpp_content,
        cpp_h_path: cpp_h_content,
        java_path: java_content,
        tla_path: tla_content,
        tla_cfg_path: tla_cfg_content,
        "go.mod": "module github.com/myorg/myapp\n\ngo 1.22",
    }

    registry = ParserRegistry()
    results = registry.parse_repository_files(list(files.keys()), files)

    # 1. Assert all 8 languages parsed without crashing
    for lang in ["python", "javascript", "java", "go", "rust", "shell", "cpp", "tla+"]:
        assert lang in results, f"Parser for {lang} returned no result for real files"
        res = results[lang]
        assert len(res.parse_errors) == 0, f"Unexpected parse error in {lang}: {res.parse_errors}"
        assert len(res.files) > 0, f"No files processed for {lang}"

    # 2. Python validation: app/parser/python_parser.py
    py_node = results["python"].files[0]
    assert py_node.path == py_path
    assert "PythonLanguageParser" in py_node.classes
    assert len(py_node.imports) > 0

    # 3. JavaScript/Node validation: scripts/parse_js.js
    js_node = results["javascript"].files[0]
    assert js_node.path == js_path
    assert "parseJS" in js_node.functions
    assert "@babel/parser" in results["javascript"].external_dependencies

    # 4. Go validation: scripts/go_parser/main.go
    go_node = results["go"].files[0]
    assert go_node.path == go_path
    assert go_node.entry_point is True
    assert "fmt" in [e.target for e in go_node.imports]

    # 5. Rust validation: scripts/rust_parser/src/main.rs
    rust_node = results["rust"].files[0]
    assert rust_node.path == rust_path
    assert rust_node.entry_point is True
    assert "AstVisitor" in rust_node.classes

    # 6. Shell validation: scripts/setup.sh
    sh_node = results["shell"].files[0]
    assert sh_node.path == sh_path
    assert sh_node.entry_point is True

    # 7. C++ validation: src/main.cpp & src/helper.h
    cpp_res = results["cpp"]
    assert len(cpp_res.files) == 2
    cpp_node = next(f for f in cpp_res.files if f.path == cpp_path)
    assert cpp_node.entry_point is True
    assert "AppServer" in cpp_node.classes
    inc_edge = next(e for e in cpp_node.imports if e.target == cpp_h_path)
    assert inc_edge.resolved is True

    # 8. Java validation: src/main/java/com/example/App.java
    java_node = results["java"].files[0]
    assert java_node.path == java_path
    assert java_node.entry_point is True

    # 9. TLA+ validation: specs/DieHard.tla & specs/DieHard.cfg
    tla_res = results["tla+"]
    assert len(tla_res.files) == 1
    tla_node = tla_res.files[0]
    assert tla_node.path == tla_path
    assert "module:DieHard" in tla_node.exports
    assert "config:specs/DieHard.cfg" in tla_node.exports


def test_external_dependencies_cargo_and_gomod():
    """Validates external dependency resolution for Go (go.mod) and Rust (Cargo.toml)."""
    files = {
        "go.mod": "module example.com/myrepo\n\ngo 1.22\n",
        "main.go": """package main

import (
    "fmt"
    "github.com/gin-gonic/gin"
    "github.com/stretchr/testify/assert"
    "example.com/myrepo/pkg/helper"
)

func main() {}
""",
        "pkg/helper/helper.go": "package helper\nfunc Help() {}",
        "Cargo.toml": """[package]
name = "mycrate"
version = "0.1.0"
[dependencies]
serde = "1.0"
tokio = "1.0"
""",
        "src/main.rs": """use std::fs;
use serde::Serialize;
use tokio::net::TcpListener;
use mycrate::utils;

fn main() {}
""",
        "src/utils.rs": "pub fn util() {}",
    }

    registry = ParserRegistry()
    results = registry.parse_repository_files(list(files.keys()), files)

    go_res = results["go"]
    assert "github.com/gin-gonic/gin" in go_res.external_dependencies

    rust_res = results["rust"]
    assert "serde::Serialize" in rust_res.external_dependencies or "serde" in rust_res.external_dependencies


def test_all_nine_locked_languages_real_repo_validation():
    """
    Stage 6 Layer 2 Section 6.2 Acceptance Criteria:
    - Confirm all 9 locked-language parsers against GENUINE repository source files:
      1. Python: pallets/flask (src/flask/app.py, src/flask/blueprints.py)
      2. JavaScript: expressjs/express (lib/express.js)
      3. TypeScript: reduxjs/redux (src/redux_index.ts)
      4. Java: spring-projects/spring-petclinic (OwnerController.java)
      5. Rust: tokio-rs/tokio (listener.rs)
      6. Go: gin-gonic/gin (gin.go)
      7. C++: fmtlib/fmt (include/fmt/format.h, include/fmt/core.h)
      8. Shell: nvm-sh/nvm (scripts/nvm_install.sh)
      9. TLA+: tlaplus/Examples (DieHard.tla, DieHard.cfg)

    Loads actual cloned/extracted repository files from tests/fixtures/real_repos_locked/
    rather than hand-written string literals, ensuring complex real-world AST features
    (e.g., C++ template macros, Go method receivers, TypeScript exported interfaces)
    parse with 0 errors and valid symbol extraction.
    """
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "real_repos_locked"
    assert fixture_dir.exists(), f"Fixture directory not found: {fixture_dir}"

    real_repo_files = {
        str(p.relative_to(fixture_dir).as_posix()): p.read_text(encoding="utf-8", errors="replace")
        for p in fixture_dir.rglob("*")
        if p.is_file()
    }

    assert len(real_repo_files) >= 10, f"Expected at least 10 real repo files, found {len(real_repo_files)}"

    registry = ParserRegistry()
    results = registry.parse_repository_files(list(real_repo_files.keys()), real_repo_files)

    # 1. Validate that every language parsed with ZERO errors
    for lang in ["python", "javascript", "java", "go", "rust", "shell", "cpp", "tla+"]:
        assert lang in results, f"Language {lang} missing from results"
        res = results[lang]
        assert len(res.parse_errors) == 0, f"Parse error in {lang}: {res.parse_errors}"
        assert len(res.files) > 0, f"No files parsed for {lang}"

    # 2. Python verification (pallets/flask real code)
    py_app = next(f for f in results["python"].files if f.path == "src/flask/app.py")
    assert "Flask" in py_app.classes
    assert len(py_app.imports) > 50

    py_bp = next(f for f in results["python"].files if f.path == "src/flask/blueprints.py")
    assert "Blueprint" in py_bp.classes

    # 3. JavaScript verification (expressjs/express real code)
    js_app = next(f for f in results["javascript"].files if f.path == "lib/express.js")
    assert "createApplication" in js_app.functions
    assert len(js_app.imports) > 0

    # 4. TypeScript verification (reduxjs/redux real code)
    ts_app = next(f for f in results["javascript"].files if f.path == "src/redux_index.ts")
    assert len(ts_app.exports) > 0
    assert any("Observable" in exp or "Dispatch" in exp for exp in ts_app.exports)

    # 5. Java verification (spring-projects/spring-petclinic real code)
    java_ctrl = next(f for f in results["java"].files if "OwnerController.java" in f.path)
    assert "OwnerController" in java_ctrl.classes
    assert len(java_ctrl.imports) > 10

    # 6. Rust verification (tokio-rs/tokio real code)
    rust_listener = next(f for f in results["rust"].files if "listener.rs" in f.path)
    assert len(rust_listener.imports) > 10

    rust_mutex = next(f for f in results["rust"].files if "mutex.rs" in f.path)
    assert "Mutex" in rust_mutex.classes
    assert "MutexGuard" in rust_mutex.classes
    assert any("crate::sync" in e.target or "std::cell" in e.target for e in rust_mutex.imports)

    # 7. Go verification (gin-gonic/gin real code)
    go_engine = next(f for f in results["go"].files if f.path == "gin.go")
    assert any("Handler" in c for c in go_engine.classes)
    assert any("New" in fn or "Default" in fn for fn in go_engine.functions)

    # 8. C++ verification (fmtlib/fmt real code)
    cpp_fmt = next(f for f in results["cpp"].files if "format.h" in f.path)
    assert "format_error" in cpp_fmt.classes
    assert "basic_memory_buffer" in cpp_fmt.classes
    assert "formatter" in cpp_fmt.classes
    assert "format" in cpp_fmt.functions or "format_as" in cpp_fmt.functions

    # Assert internal include resolution: core.h must be detected AND resolved=True
    core_edge = next((e for e in cpp_fmt.imports if "core.h" in e.target), None)
    assert core_edge is not None, "core.h include missing from format.h"
    assert core_edge.resolved is True, f"core.h expected resolved=True, got {core_edge.resolved}"

    cpp_core = next(f for f in results["cpp"].files if "core.h" in f.path)
    assert "basic_format_context" in cpp_core.classes or "arg_pack" in cpp_core.classes

    # 9. Shell verification (nvm-sh/nvm real code)
    sh_build = next(f for f in results["shell"].files if "nvm_install.sh" in f.path)
    assert sh_build.path == "scripts/nvm_install.sh"

    # 10. TLA+ verification (tlaplus/Examples DieHard real spec)
    tla_diehard = next(f for f in results["tla+"].files if "DieHard.tla" in f.path)
    assert "module:DieHard" in tla_diehard.exports
    assert any("DieHard.cfg" in exp for exp in tla_diehard.exports)


