import pytest
from app.services.scaffold_generator import ScaffoldGenerator
from app.services.grading_engine import GradingEngine


SAMPLE_PYTHON_MODULE = '''"""
Core math and string transformation leaf utility module.
"""
import math
from typing import List, Optional

DEFAULT_PRECISION = 4
MAX_BUFFER_SIZE = 1024

class VectorTransformer:
    """Transforms 2D/3D vectors with scaling."""
    def __init__(self, scale_factor: float = 1.0):
        """Initialize the vector transformer."""
        self.scale_factor = scale_factor

    def transform(self, values: List[float]) -> List[float]:
        """Apply scaling to all vector coordinates."""
        return [v * self.scale_factor for v in values]

def calculate_hypotenuse(a: float, b: float) -> float:
    """Calculate the hypotenuse using the Pythagorean theorem."""
    squared_sum = a ** 2 + b ** 2
    return math.sqrt(squared_sum)

def format_coordinates(x: float, y: float, precision: Optional[int] = None) -> str:
    """Format coordinates as a string with custom precision."""
    p = precision if precision is not None else DEFAULT_PRECISION
    return f"({x:.{p}f}, {y:.{p}f})"
'''

PURE_CONSTANTS_MODULE = '''"""
Type definitions and shared system constants.
"""
from typing import TypedDict, List

API_VERSION = "v1"
TIMEOUT_SECONDS = 30
SUPPORTED_ENCODINGS = ["utf-8", "ascii", "latin-1"]

class ConfigDict(TypedDict):
    host: str
    port: int
    debug: bool
'''


def test_generate_scaffold_sample_python_file():
    result = ScaffoldGenerator.generate_scaffold(
        code=SAMPLE_PYTHON_MODULE,
        language="python",
        file_path="src/utils/math_utils.py",
    )

    assert result["has_scaffold"] is True
    assert result["blanked_count"] == 4
    assert len(result["blanked_functions"]) == 4

    # Verify function names detected
    fn_names = [f["full_name"] for f in result["blanked_functions"]]
    assert "VectorTransformer.__init__" in fn_names
    assert "VectorTransformer.transform" in fn_names
    assert "calculate_hypotenuse" in fn_names
    assert "format_coordinates" in fn_names

    scaffold_code = result["scaffold_code"]

    # Top level structure preserved
    assert "import math" in scaffold_code
    assert "DEFAULT_PRECISION = 4" in scaffold_code
    assert "MAX_BUFFER_SIZE = 1024" in scaffold_code
    assert '"""Transforms 2D/3D vectors with scaling."""' in scaffold_code
    assert '"""Calculate the hypotenuse using the Pythagorean theorem."""' in scaffold_code

    # Function bodies replaced with pass / TODO stubs
    assert "squared_sum = a ** 2 + b ** 2" not in scaffold_code
    assert "return math.sqrt(squared_sum)" not in scaffold_code
    assert "return [v * self.scale_factor for v in values]" not in scaffold_code
    assert "pass" in scaffold_code


def test_generate_scaffold_pure_constants_disables_fill_mode():
    result = ScaffoldGenerator.generate_scaffold(
        code=PURE_CONSTANTS_MODULE,
        language="python",
        file_path="src/types/constants.py",
    )

    assert result["has_scaffold"] is False
    assert result["blanked_count"] == 0
    assert result["blanked_functions"] == []
    assert result["reason"] is not None
    assert "no function bodies" in result["reason"].lower()
    # Unmodified code returned
    assert result["scaffold_code"] == PURE_CONSTANTS_MODULE


def test_grade_fill_blanks_all_implemented():
    scaffold_info = ScaffoldGenerator.generate_scaffold(
        code=SAMPLE_PYTHON_MODULE,
        language="python",
        file_path="src/utils/math_utils.py",
    )

    # User submits working implementations for all 4 blanked functions
    user_submission = '''"""
Core math and string transformation leaf utility module.
"""
import math
from typing import List, Optional

DEFAULT_PRECISION = 4
MAX_BUFFER_SIZE = 1024

class VectorTransformer:
    def __init__(self, scale_factor: float = 1.0):
        self.scale_factor = scale_factor

    def transform(self, values: List[float]) -> List[float]:
        scaled = []
        for x in values:
            scaled.append(x * self.scale_factor)
        return scaled

def calculate_hypotenuse(a: float, b: float) -> float:
    return math.hypot(a, b)

def format_coordinates(x: float, y: float, precision: Optional[int] = None) -> str:
    prec = precision or DEFAULT_PRECISION
    return f"({round(x, prec)}, {round(y, prec)})"
'''

    grade_result = ScaffoldGenerator.grade_fill_blanks(
        submitted_code=user_submission,
        scaffold_info=scaffold_info,
        language="python",
    )

    assert grade_result["is_verified"] is True
    assert grade_result["structurally_verified"] is True
    assert grade_result["blanked_evaluated"] == 4
    assert grade_result["implemented_count"] == 4
    assert all(b["status"] == "implemented" for b in grade_result["blank_details"])


def test_grade_fill_blanks_partially_unimplemented():
    scaffold_info = ScaffoldGenerator.generate_scaffold(
        code=SAMPLE_PYTHON_MODULE,
        language="python",
        file_path="src/utils/math_utils.py",
    )

    # User only implemented calculate_hypotenuse, leaving others as pass/TODO
    partial_submission = '''import math

class VectorTransformer:
    def __init__(self, scale_factor: float = 1.0):
        pass

    def transform(self, values):
        # TODO: implement
        pass

def calculate_hypotenuse(a: float, b: float) -> float:
    return (a * a + b * b) ** 0.5

def format_coordinates(x: float, y: float, precision = None):
    pass
'''

    grade_result = ScaffoldGenerator.grade_fill_blanks(
        submitted_code=partial_submission,
        scaffold_info=scaffold_info,
        language="python",
    )

    assert grade_result["is_verified"] is False
    assert grade_result["structurally_verified"] is False
    assert grade_result["blanked_evaluated"] == 4
    assert grade_result["implemented_count"] == 1

    details = {b["name"]: b for b in grade_result["blank_details"]}
    assert details["calculate_hypotenuse"]["status"] == "implemented"
    assert details["format_coordinates"]["status"] == "unimplemented_stub"


def test_grade_fill_blanks_missing_function():
    scaffold_info = ScaffoldGenerator.generate_scaffold(
        code=SAMPLE_PYTHON_MODULE,
        language="python",
        file_path="src/utils/math_utils.py",
    )

    # User completely removed VectorTransformer class
    missing_submission = '''import math

def calculate_hypotenuse(a: float, b: float) -> float:
    return math.sqrt(a * a + b * b)

def format_coordinates(x: float, y: float, precision = None) -> str:
    return f"{x}, {y}"
'''

    grade_result = ScaffoldGenerator.grade_fill_blanks(
        submitted_code=missing_submission,
        scaffold_info=scaffold_info,
        language="python",
    )

    assert grade_result["is_verified"] is False
    details = {b["name"]: b for b in grade_result["blank_details"]}
    assert details["VectorTransformer.__init__"]["status"] == "missing"
    assert details["VectorTransformer.transform"]["status"] == "missing"


def test_grade_fill_blanks_syntax_error():
    scaffold_info = ScaffoldGenerator.generate_scaffold(
        code=SAMPLE_PYTHON_MODULE,
        language="python",
        file_path="src/utils/math_utils.py",
    )

    invalid_syntax_code = '''def calculate_hypotenuse(a, b):
    return a +++ b ???
'''

    grade_result = ScaffoldGenerator.grade_fill_blanks(
        submitted_code=invalid_syntax_code,
        scaffold_info=scaffold_info,
        language="python",
    )

    assert grade_result["is_verified"] is False
    assert grade_result["structurally_verified"] is False
    assert "Syntax error" in grade_result["error_message"]


def test_grading_engine_fill_mode_integration():
    engine = GradingEngine()

    class MockJob:
        def __init__(self):
            self.id = 1
            self.repo_url = "https://github.com/example/repo"
            self.repo_name = "example/repo"
            self.github_url = self.repo_url
            self.graph_data = {
                "nodes": [
                    {
                        "id": "src/utils/math_utils.py",
                        "path": "src/utils/math_utils.py",
                        "source_code": SAMPLE_PYTHON_MODULE,
                        "tier": 1,
                    }
                ],
                "milestones": [
                    {
                        "tier": 1,
                        "included_files": ["src/utils/math_utils.py"],
                    }
                ]
            }

    job = MockJob()

    user_implemented_code = '''import math
class VectorTransformer:
    def __init__(self, scale_factor=1.0):
        self.scale = scale_factor
    def transform(self, values):
        return [x * self.scale for x in values]

def calculate_hypotenuse(a, b):
    return (a**2 + b**2)**0.5

def format_coordinates(x, y, precision=None):
    return f"({x}, {y})"
'''

    res = engine.grade_attempt(
        job=job,
        milestone_tier=1,
        submitted_code=user_implemented_code,
        graph_data=job.graph_data,
        mode="fill",
        target_file="src/utils/math_utils.py",
    )

    assert res["grading_method"] == "fill_the_blanks"
    assert res["verification"]["is_verified"] is True
    assert res["verification"]["structurally_verified"] is True


def test_generate_scaffold_non_python_extension_shows_clear_message():
    """Verifies that non-Python files return has_scaffold=False with clear explanatory reason,
    skipping Python AST parsing and never raising or returning a raw SyntaxError."""
    sample_go_code = '''package main

import "fmt"

func CalculateTotal(a int, b int) int {
    return a + b
}

func main() {
    fmt.Println(CalculateTotal(10, 20))
}
'''
    result_go = ScaffoldGenerator.generate_scaffold(
        code=sample_go_code,
        language="go",
        file_path="src/main.go",
    )
    assert result_go["has_scaffold"] is False
    assert result_go["reason"] == "Fill the Blanks mode is currently available for Python files. Try Guess It or Just Read It for this file instead."
    assert "Syntax error" not in (result_go["reason"] or "")

    # Test Rust file
    sample_rs_code = 'pub fn solve(x: i32) -> i32 { x * 2 }'
    result_rs = ScaffoldGenerator.generate_scaffold(
        code=sample_rs_code,
        language="rust",
        file_path="src/lib.rs",
    )
    assert result_rs["has_scaffold"] is False
    assert result_rs["reason"] == "Fill the Blanks mode is currently available for Python files. Try Guess It or Just Read It for this file instead."

    # Test TypeScript file
    sample_ts_code = 'export function add(a: number, b: number): number { return a + b; }'
    result_ts = ScaffoldGenerator.generate_scaffold(
        code=sample_ts_code,
        language="typescript",
        file_path="src/index.ts",
    )
    assert result_ts["has_scaffold"] is False
    assert result_ts["reason"] == "Fill the Blanks mode is currently available for Python files. Try Guess It or Just Read It for this file instead."


def test_generate_scaffold_genuine_python_syntax_error_preserves_error():
    """Verifies that a genuine Python file with an actual syntax error still surfaces the syntax error."""
    invalid_python_code = '''def broken_function(a, b::
    return a + b
'''
    result = ScaffoldGenerator.generate_scaffold(
        code=invalid_python_code,
        language="python",
        file_path="src/broken.py",
    )
    assert result["has_scaffold"] is False
    assert result["reason"] is not None
    assert "Syntax error in source file:" in result["reason"]
    assert "Fill the Blanks mode is currently available for Python files" not in result["reason"]


def test_generate_scaffold_python_no_functions_preserves_no_functions_message():
    """Verifies that a genuine Python file with no function bodies still returns the specific constants/types message."""
    pure_constants = '''
VERSION = "1.0.0"
CONFIG = {"host": "localhost", "port": 8080}
'''
    result = ScaffoldGenerator.generate_scaffold(
        code=pure_constants,
        language="python",
        file_path="src/config.py",
    )
    assert result["has_scaffold"] is False
    assert result["reason"] is not None
    assert "File contains only constants, type declarations, or exports with no function bodies to scaffold." in result["reason"]

