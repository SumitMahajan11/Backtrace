"""Unit tests for Shell Script structural parser (Layer 2 Part 2)."""

import pytest
from app.parser.shell_parser import ShellLanguageParser
from app.parser.schema import ImportCategory


def test_shell_source_and_dot_imports():
    code = """#!/bin/bash
source ./utils/common.sh
. ./config/env.sh
source "../lib/helper.sh"
"""
    parser = ShellLanguageParser()
    all_files = {
        "scripts/main.sh",
        "scripts/utils/common.sh",
        "scripts/config/env.sh",
        "lib/helper.sh",
    }

    node, edges = parser.parse_single_file("scripts/main.sh", code, all_files)

    assert node.path == "scripts/main.sh"
    assert node.language == "shell"
    assert node.entry_point is True
    assert node.entry_point_type == "shell_script"

    source_edges = [e for e in edges if e.import_type == "source"]
    assert len(source_edges) == 3

    common_edge = next(e for e in source_edges if "common.sh" in e.target)
    assert common_edge.resolved is True
    assert common_edge.category == ImportCategory.STATIC

    env_edge = next(e for e in source_edges if "env.sh" in e.target)
    assert env_edge.resolved is True

    helper_edge = next(e for e in source_edges if "helper.sh" in e.target)
    assert helper_edge.resolved is True


def test_shell_direct_script_invocations():
    code = """#!/bin/sh
./scripts/build.sh
bash ./scripts/test.sh
sh bin/deploy.sh
"""
    parser = ShellLanguageParser()
    all_files = {
        "main.sh",
        "scripts/build.sh",
        "scripts/test.sh",
        "bin/deploy.sh",
    }

    node, edges = parser.parse_single_file("main.sh", code, all_files)

    invocations = [e for e in edges if e.import_type == "invocation"]
    assert len(invocations) == 3

    build_edge = next(e for e in invocations if "build.sh" in e.target)
    assert build_edge.resolved is True
    assert build_edge.category == ImportCategory.STATIC

    test_edge = next(e for e in invocations if "test.sh" in e.target)
    assert test_edge.resolved is True

    deploy_edge = next(e for e in invocations if "deploy.sh" in e.target)
    assert deploy_edge.resolved is True


def test_shell_dynamic_variable_paths():
    code = """#!/usr/bin/env bash
source "$SCRIPT_DIR/config.sh"
. "${LIB_PATH}/utils.sh"
bash "$1"
"""
    parser = ShellLanguageParser()
    all_files = {"scripts/main.sh", "scripts/config.sh"}

    node, edges = parser.parse_single_file("scripts/main.sh", code, all_files)

    dynamic_edges = [e for e in edges if e.import_type == "dynamic"]
    assert len(dynamic_edges) >= 2

    for edge in dynamic_edges:
        assert edge.resolved is False
        assert edge.category == ImportCategory.DYNAMIC


def test_shell_extensionless_shebang_file():
    code = """#!/bin/bash
source ./helpers.sh
"""
    parser = ShellLanguageParser()
    file_paths = ["bin/deploy", "bin/helpers.sh"]
    file_contents = {"bin/deploy": code, "bin/helpers.sh": "#!/bin/bash\necho ok"}

    result = parser.parse_repository(file_paths, file_contents)

    assert len(result.files) == 2
    deploy_node = next(f for f in result.files if f.path == "bin/deploy")
    assert deploy_node.entry_point is True
    assert len(deploy_node.imports) == 1
    assert deploy_node.imports[0].resolved is True


def test_shell_malformed_binary_content():
    binary_content = "#!/bin/bash\n\x00\x01\x02\x03\xff\xfe"
    parser = ShellLanguageParser()
    file_contents = {"bad.sh": binary_content}

    result = parser.parse_repository(["bad.sh"], file_contents)

    assert len(result.parse_errors) == 1
    assert result.parse_errors[0].path == "bad.sh"
    assert result.parse_errors[0].language == "shell"
    assert "binary content" in result.parse_errors[0].error_message.lower()
