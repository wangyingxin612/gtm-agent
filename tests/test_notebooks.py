"""
Structural tests for notebooks — verify they are valid JSON with compilable code cells.
These catch syntax errors and broken imports before an operator runs them.
"""
import ast
import json
import os

import pytest

NOTEBOOKS_DIR = os.path.join(os.path.dirname(__file__), "..", "notebooks")

EXPECTED_NOTEBOOKS = [
    "gtm_pipeline.ipynb",
    "weekly_signal_analysis.ipynb",
]


def _load_notebook(name: str) -> dict:
    path = os.path.join(NOTEBOOKS_DIR, name)
    assert os.path.exists(path), f"Notebook not found: {path}"
    with open(path) as f:
        return json.load(f)


def _code_cells(nb: dict):
    return [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]


def _markdown_cells(nb: dict):
    return [c for c in nb.get("cells", []) if c.get("cell_type") == "markdown"]


# ---------------------------------------------------------------------------
# File existence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", EXPECTED_NOTEBOOKS)
def test_notebook_exists(name):
    path = os.path.join(NOTEBOOKS_DIR, name)
    assert os.path.exists(path), f"Missing notebook: {name}"


@pytest.mark.parametrize("name", EXPECTED_NOTEBOOKS)
def test_notebook_is_valid_json(name):
    nb = _load_notebook(name)
    assert isinstance(nb, dict)
    assert "cells" in nb
    assert "nbformat" in nb


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", EXPECTED_NOTEBOOKS)
def test_notebook_has_markdown_cells(name):
    nb = _load_notebook(name)
    assert len(_markdown_cells(nb)) >= 1, f"{name} should have at least one markdown cell"


@pytest.mark.parametrize("name", EXPECTED_NOTEBOOKS)
def test_notebook_has_code_cells(name):
    nb = _load_notebook(name)
    assert len(_code_cells(nb)) >= 1, f"{name} should have at least one code cell"


@pytest.mark.parametrize("name", EXPECTED_NOTEBOOKS)
def test_code_cells_are_valid_python(name):
    nb = _load_notebook(name)
    for i, cell in enumerate(_code_cells(nb)):
        source = "".join(cell.get("source", []))
        # Skip IPython magic lines (e.g. %pip install, !command)
        clean_lines = [
            ln for ln in source.splitlines()
            if not ln.strip().startswith(("%", "!"))
        ]
        clean = "\n".join(clean_lines)
        if not clean.strip():
            continue
        try:
            ast.parse(clean)
        except SyntaxError as e:
            pytest.fail(f"{name} code cell {i} has syntax error: {e}\nSource:\n{clean}")


# ---------------------------------------------------------------------------
# Content requirements — gtm_pipeline.ipynb
# ---------------------------------------------------------------------------

def test_pipeline_notebook_imports_run_pipeline():
    nb = _load_notebook("gtm_pipeline.ipynb")
    all_source = "\n".join(
        "".join(c.get("source", []))
        for c in _code_cells(nb)
    )
    assert "run_pipeline" in all_source


def test_pipeline_notebook_imports_export_to_csv():
    nb = _load_notebook("gtm_pipeline.ipynb")
    all_source = "\n".join(
        "".join(c.get("source", []))
        for c in _code_cells(nb)
    )
    assert "export_to_csv" in all_source


def test_pipeline_notebook_references_company_website():
    nb = _load_notebook("gtm_pipeline.ipynb")
    all_source = "\n".join(
        "".join(c.get("source", []))
        for c in nb.get("cells", [])
    )
    assert "company_website" in all_source


# ---------------------------------------------------------------------------
# Content requirements — weekly_signal_analysis.ipynb
# ---------------------------------------------------------------------------

def test_analysis_notebook_references_signal_snapshots():
    nb = _load_notebook("weekly_signal_analysis.ipynb")
    all_source = "\n".join(
        "".join(c.get("source", []))
        for c in nb.get("cells", [])
    )
    assert "signal_snapshots" in all_source


def test_analysis_notebook_references_override_events():
    nb = _load_notebook("weekly_signal_analysis.ipynb")
    all_source = "\n".join(
        "".join(c.get("source", []))
        for c in nb.get("cells", [])
    )
    assert "override_events" in all_source


def test_analysis_notebook_references_tier1_precision():
    nb = _load_notebook("weekly_signal_analysis.ipynb")
    all_source = "\n".join(
        "".join(c.get("source", []))
        for c in nb.get("cells", [])
    )
    assert "Tier 1" in all_source or "tier_1" in all_source or "precision" in all_source.lower()
