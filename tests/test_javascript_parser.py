"""Unit tests for JavaScript and TypeScript structural parser (Layer 2)."""

import pytest
from app.parser.javascript_parser import JavaScriptLanguageParser
from app.parser.registry import ParserRegistry
from app.parser.schema import ImportCategory


def test_js_commonjs_and_es_module_imports():
    code = """
const express = require('express');
const { helper } = require('./utils/helper');
import React from 'react';
import { render } from './components/App';
import * as helpers from './helpers';
export * from './types';

async function loadModule() {
    const lazy = await import('./lazyModule');
}
    """
    parser = JavaScriptLanguageParser()
    all_files = {
        "src/index.ts",
        "src/utils/helper.ts",
        "src/components/App.tsx",
        "src/helpers.ts",
        "src/types.ts",
        "src/lazyModule.ts",
    }

    node, edges = parser.parse_single_file("src/index.ts", code, all_files)

    assert node.path == "src/index.ts"
    assert node.language == "javascript"
    assert node.entry_point is True
    assert node.entry_point_type == "main_script"

    categories = {e.target: e.category for e in edges}
    assert categories["express"] == ImportCategory.STATIC
    assert categories["react"] == ImportCategory.STATIC
    assert categories["src/utils/helper.ts"] == ImportCategory.STATIC
    assert categories["src/components/App.tsx"] == ImportCategory.STATIC
    assert categories["src/helpers.ts"] == ImportCategory.WILDCARD
    assert categories["src/types.ts"] == ImportCategory.WILDCARD
    assert categories["src/lazyModule.ts"] == ImportCategory.DYNAMIC


def test_js_tsx_jsx_and_template_literals():
    code = """
import React, { useState } from 'react';
import Header from './Header';

export interface Props {
    title: string;
}

export function AppContainer({ title }: Props) {
    const [count, setCount] = useState<number>(0);
    const label = `Count is ${count}`;
    return (
        <div className="container">
            <Header text={label} />
            <button onClick={() => setCount(count + 1)}>Increment</button>
        </div>
    );
}
"""
    parser = JavaScriptLanguageParser()
    all_files = {"src/AppContainer.tsx", "src/Header.tsx"}

    node, edges = parser.parse_single_file("src/AppContainer.tsx", code, all_files)

    assert node.path == "src/AppContainer.tsx"
    assert "AppContainer" in node.functions
    assert "AppContainer" in node.exports
    assert any(e.target == "src/Header.tsx" for e in edges)


def test_js_syntax_error_produces_parse_error():
    malformed_code = """
import { useState } from 'react'
const x = ; // Syntax error
"""
    parser = JavaScriptLanguageParser()
    file_contents = {"src/bad.js": malformed_code}

    result = parser.parse_repository(["src/bad.js"], file_contents)

    assert len(result.parse_errors) == 1
    assert result.parse_errors[0].path == "src/bad.js"
    assert result.parse_errors[0].language == "javascript"
    assert "Unexpected token" in result.parse_errors[0].error_message or "syntax" in result.parse_errors[0].error_message.lower()


def test_js_internal_vs_external_npm_package_resolution():
    code = """
import lodash from 'lodash';
import { Button } from './components/Button';
    """
    parser = JavaScriptLanguageParser()
    all_files = {"src/index.js", "src/components/Button.jsx"}

    node, edges = parser.parse_single_file("src/index.js", code, all_files)

    ext_edge = next(e for e in edges if e.target == "lodash")
    assert ext_edge.is_external is True

    int_edge = next(e for e in edges if e.target == "src/components/Button.jsx")
    assert int_edge.is_external is False


def test_parser_registry_multi_language():
    registry = ParserRegistry()
    files = {
        "backend/main.py": "import os\nfrom app.db import session",
        "frontend/src/index.tsx": "import React from 'react';\nimport App from './App';",
        "frontend/src/App.tsx": "export default function App() { return <div/>; }",
    }

    results = registry.parse_repository_files(list(files.keys()), files)

    assert "python" in results
    assert "javascript" in results

    py_res = results["python"]
    assert len(py_res.file_nodes) == 1
    assert py_res.file_nodes[0].path == "backend/main.py"

    js_res = results["javascript"]
    assert len(js_res.file_nodes) == 2
    assert "react" in js_res.external_dependencies
