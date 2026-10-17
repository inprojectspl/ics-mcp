"""Everything the model reads, plus comments and docstrings, is English.

Tool descriptions, parameter schemas, prompts, resources, the server
INSTRUCTIONS and the `ics_help` pages are sent to the model verbatim, so a
Polish leftover there changes how the assistant behaves. The check looks for
Polish diacritics, which catches almost every Polish sentence.
"""

from __future__ import annotations

import ast
import re
import tokenize
from pathlib import Path

import pytest

from ics_mcp.server import build_mcp
from ics_mcp.version import INSTRUCTIONS, SERVER_INFO
from tests.conftest import (
    list_prompts,
    list_resource_templates,
    list_resources,
    list_tools,
)

PACKAGE = Path(__file__).resolve().parent.parent / "ics_mcp"
POLISH = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")


def _hits(label: str, text: str | None) -> list[str]:
    return [f"{label}: {m.group()!r} in {text!r}"[:200] for m in POLISH.finditer(text or "")][:1]


@pytest.mark.asyncio
async def test_model_facing_texts_are_english(settings):
    mcp = build_mcp(settings)
    problems: list[str] = []
    problems += _hits("INSTRUCTIONS", INSTRUCTIONS)
    problems += _hits("SERVER_INFO", str(SERVER_INFO))
    for tool in await list_tools(mcp):
        problems += _hits(f"tool {tool.name}", tool.to_mcp_tool().model_dump_json())
    for prompt in await list_prompts(mcp):
        problems += _hits(f"prompt {prompt.name}", prompt.to_mcp_prompt().model_dump_json())
    for res in await list_resources(mcp):
        problems += _hits(f"resource {res.uri}", res.to_mcp_resource().model_dump_json())
    for tpl in await list_resource_templates(mcp):
        problems += _hits(f"template {tpl.uri_template}", tpl.to_mcp_template().model_dump_json())
    for page in sorted((PACKAGE / "help_md").glob("*.md")):
        problems += _hits(f"help_md/{page.name}", page.read_text(encoding="utf-8"))
    assert not problems, "\n".join(problems)


def _comment_hits(path: Path) -> list[str]:
    hits = []
    with path.open("rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type == tokenize.COMMENT and POLISH.search(tok.string):
                hits.append(f"{tok.start[0]}: {tok.string.strip()}")
    return hits


def _docstring_hits(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        doc = ast.get_docstring(node, clean=False)
        if doc and POLISH.search(doc):
            hits.append(f"docstring of {getattr(node, 'name', '<module>')}")
    return hits


def test_comments_and_docstrings_are_english():
    problems = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        problems += [f"{rel}:{hit}" for hit in _comment_hits(path) + _docstring_hits(path)]
    assert not problems, "\n".join(problems)


def test_detector_catches_polish_comments_and_docstrings(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text('def f():\n    """Zwraca coś."""\n    return 1  # zażółć\n', encoding="utf-8")
    assert _comment_hits(sample)
    assert _docstring_hits(sample)


def test_detector_ignores_string_literals(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text('MSG = "Brak dostępu"\n', encoding="utf-8")
    assert not _comment_hits(sample)
    assert not _docstring_hits(sample)
