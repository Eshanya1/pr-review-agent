from pathlib import Path

from pr_review_agent.rag.chunking import chunk_markdown_file, chunk_python_file

SAMPLE_PY = '''\
import os

CONST = 1


def foo():
    return 1


class Bar:
    def method(self):
        return 2
'''

SAMPLE_MD = """\
# Title

Intro text.

## Section A

Body A.

## Section B

Body B.
"""


def test_chunk_python_file_splits_by_function_and_class(tmp_path: Path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    chunks = chunk_python_file(f, "sample.py")
    kinds = {c.name: c.kind for c in chunks}
    assert kinds["foo"] == "function"
    assert kinds["Bar"] == "class"
    assert any(c.kind == "module_prologue" for c in chunks)


def test_chunk_python_file_function_text_is_complete(tmp_path: Path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    chunks = chunk_python_file(f, "sample.py")
    foo_chunk = next(c for c in chunks if c.name == "foo")
    assert "def foo():" in foo_chunk.text
    assert "return 1" in foo_chunk.text
    assert "class Bar" not in foo_chunk.text


def test_chunk_python_file_handles_syntax_error(tmp_path: Path):
    f = tmp_path / "broken.py"
    f.write_text("def broken(:\n    pass")
    chunks = chunk_python_file(f, "broken.py")
    assert len(chunks) == 1
    assert chunks[0].kind == "file"


def test_chunk_markdown_file_splits_by_heading(tmp_path: Path):
    f = tmp_path / "doc.md"
    f.write_text(SAMPLE_MD)
    chunks = chunk_markdown_file(f, "doc.md")
    names = [c.name for c in chunks]
    assert "Section A" in names
    assert "Section B" in names
    section_a = next(c for c in chunks if c.name == "Section A")
    assert "Body A." in section_a.text
    assert "Body B." not in section_a.text
