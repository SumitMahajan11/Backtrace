"""Unit tests for TLA+ Presence Detection Parser (Layer 2 core)."""

from app.parser.tla_parser import TlaLanguageParser
from app.parser.schema import ImportCategory


def test_tla_module_name_extraction():
    parser = TlaLanguageParser()

    content_dash = """---------------- MODULE KeyValueStore ----------------
EXTENDS Naturals, TLC
VARIABLES store, tx
======================================================
"""
    node_dash, edges_dash = parser.parse_single_file("specs/KeyValueStore.tla", content_dash, {"specs/KeyValueStore.tla"})
    assert node_dash.path == "specs/KeyValueStore.tla"
    assert node_dash.language == "tla+"
    assert "module:KeyValueStore" in node_dash.exports

    content_eq = """================ MODULE TwoPhase ================
EXTENDS Integers
=================================================
"""
    node_eq, _ = parser.parse_single_file("specs/TwoPhase.tla", content_eq, {"specs/TwoPhase.tla"})
    assert "module:TwoPhase" in node_eq.exports


def test_tla_extends_resolution_and_stdlib():
    parser = TlaLanguageParser()

    main_content = """---------------- MODULE DieHard ----------------
EXTENDS Naturals, TLC, CustomHelper
VARIABLES small, big
================================================
"""
    all_files = {
        "specs/DieHard.tla",
        "specs/CustomHelper.tla",
    }

    node, edges = parser.parse_single_file("specs/DieHard.tla", main_content, all_files)
    
    targets = {e.target: e for e in edges}
    assert "Naturals" in targets
    assert targets["Naturals"].is_external is True
    assert targets["Naturals"].resolved is False

    assert "TLC" in targets
    assert targets["TLC"].is_external is True
    assert targets["TLC"].resolved is False

    assert "specs/CustomHelper.tla" in targets
    assert targets["specs/CustomHelper.tla"].is_external is False
    assert targets["specs/CustomHelper.tla"].resolved is True
    assert targets["specs/CustomHelper.tla"].category == ImportCategory.STATIC


def test_tla_malformed_header_resilience():
    parser = TlaLanguageParser()

    malformed_content = """\\* Just some random comments or broken text
VARIABLE x
x' = x + 1
"""
    node, edges = parser.parse_single_file("specs/broken.tla", malformed_content, {"specs/broken.tla"})
    assert node.path == "specs/broken.tla"
    assert node.language == "tla+"
    # Must NOT fail or raise ParseError
    assert len(node.exports) == 0


def test_tla_associated_cfg_file_discovery():
    parser = TlaLanguageParser()

    content = """---------------- MODULE DieHard ----------------
EXTENDS Naturals
================================================
"""
    all_files = {
        "specs/DieHard.tla",
        "specs/DieHard.cfg",
    }

    node, _ = parser.parse_single_file("specs/DieHard.tla", content, all_files)
    assert "module:DieHard" in node.exports
    assert "config:specs/DieHard.cfg" in node.exports
