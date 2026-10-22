"""Protect the dependency boundaries that make providers and perspectives replaceable."""

import ast
from pathlib import Path

import disclosure_ai

ROOT = Path(disclosure_ai.__file__).parent


def imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_domain_has_no_workflow_or_external_service_dependencies():
    forbidden = (
        "fastapi",
        "langgraph",
        "openai",
        "mcp",
        "httpx",
        "sqlalchemy",
        "disclosure_ai.infrastructure",
        "disclosure_ai.workflow",
        "disclosure_ai.application",
        "disclosure_ai.analysis",
        "disclosure_ai.runtime",
    )
    for path in (ROOT / "domain").rglob("*.py"):
        assert not any(name.startswith(forbidden) for name in imports(path)), path


def test_application_and_analysis_do_not_import_concrete_adapters():
    for area in ("application", "analysis"):
        for path in (ROOT / area).rglob("*.py"):
            assert not any(
                name.startswith(
                    (
                        "disclosure_ai.infrastructure",
                        "openai",
                        "mcp",
                        "fastapi",
                        "pika",
                    )
                )
                for name in imports(path)
            ), path


def test_canonical_modules_do_not_depend_on_legacy_paths():
    for area in ("application", "analysis", "domain", "infrastructure", "runtime", "workflow"):
        for path in (ROOT / area).rglob("*.py"):
            if area == "workflow" and path.name in {
                "execution.py",
                "initial.py",
                "perspectives.py",
                "reporting.py",
                "shared.py",
            }:
                continue
            assert not any(
                name.startswith(
                    (
                        "disclosure_ai.harness",
                        "disclosure_ai.services",
                        "disclosure_ai.entrypoints",
                        "disclosure_ai.schemas",
                    )
                )
                for name in imports(path)
            ), path
