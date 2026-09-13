"""Unit tests for Rust static structural parser (Layer 2 Part 2)."""

import pytest
from app.parser.rust_parser import RustLanguageParser
from app.parser.schema import ImportCategory


def test_rust_use_import_categories_and_entry_point():
    code = """
use std::fs;
use std::{io, fmt};
use mycrate::utils::Helper as LocalHelper;
use mycrate::models::*;

#[derive(Debug, Clone)]
pub struct Config {
    pub port: u16,
}

pub fn new_config() -> Config {
    println!("Creating config");
    Config { port: 8080 }
}

fn main() {
    let cfg = new_config();
}
"""
    parser = RustLanguageParser()
    parser.set_crate_name("mycrate")
    all_files = {"src/main.rs", "src/utils.rs", "src/models.rs"}

    node, edges = parser.parse_single_file("src/main.rs", code, all_files)

    assert node.path == "src/main.rs"
    assert node.language == "rust"
    assert node.entry_point is True
    assert node.entry_point_type == "main_function"
    assert "Config" in node.classes
    assert "new_config" in node.functions
    assert "main" in node.functions
    assert "Config" in node.exports
    assert "new_config" in node.exports

    targets = {e.target: e for e in edges if not e.target.startswith("macro::")}

    # std::fs -> stdlib static
    assert "std::fs" in targets
    assert targets["std::fs"].category == ImportCategory.STATIC
    assert targets["std::fs"].is_external is False

    # std::{io, fmt} -> grouped imports expanded
    assert "std::io" in targets
    assert "std::fmt" in targets

    # mycrate::utils::Helper as LocalHelper -> aliased internal import
    assert "utils/Helper" in targets or "utils" in targets or "mycrate::utils::Helper" in targets
    helper_edge = next(e for e in edges if "utils" in e.target)
    assert helper_edge.raw_import_symbol == "mycrate::utils::Helper as LocalHelper"
    assert helper_edge.is_external is False

    # mycrate::models::* -> wildcard import
    wildcard_edge = next(e for e in edges if e.target.endswith("*"))
    assert wildcard_edge.category == ImportCategory.WILDCARD

    # Verify macro invocation recorded as uncertain/unresolved
    macro_edges = [e for e in edges if e.target.startswith("macro::")]
    assert len(macro_edges) > 0
    assert any("derive" in e.target for e in macro_edges)


def test_rust_mod_declarations_and_resolution():
    code = """
pub mod models;
mod controllers;
mod missing_mod;

pub fn start() {}
"""
    parser = RustLanguageParser()
    all_files = {
        "src/lib.rs",
        "src/models.rs",
        "src/controllers/mod.rs",
    }

    node, edges = parser.parse_single_file("src/lib.rs", code, all_files)

    # models -> src/models.rs (resolved)
    models_edge = next(e for e in edges if e.target == "src/models.rs")
    assert models_edge.resolved is True
    assert models_edge.is_external is False

    # controllers -> src/controllers/mod.rs (resolved)
    controllers_edge = next(e for e in edges if e.target == "src/controllers/mod.rs")
    assert controllers_edge.resolved is True

    # missing_mod -> src/missing_mod.rs (unresolved)
    missing_edge = next(e for e in edges if e.target == "src/missing_mod.rs")
    assert missing_edge.resolved is False


def test_rust_syntax_error_produces_parse_error():
    malformed_code = """
fn main( { // syntax error: unclosed parenthesis
    println!("hello");
"""
    parser = RustLanguageParser()
    file_contents = {"src/bad.rs": malformed_code}

    result = parser.parse_repository(["src/bad.rs"], file_contents)

    assert len(result.parse_errors) == 1
    assert result.parse_errors[0].path == "src/bad.rs"
    assert result.parse_errors[0].language == "rust"
    assert "syntax error" in result.parse_errors[0].error_message.lower() or "expected" in result.parse_errors[0].error_message.lower()
