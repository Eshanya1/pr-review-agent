from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path

IGNORE_DIRS = {
    ".venv", ".git", "__pycache__", "eval_data", ".pytest_cache", "node_modules",
    "assets", "build", "dist", ".rag_index",
}
IGNORE_SUFFIXES = (".egg-info",)


@dataclass
class Chunk:
    id: str
    source: str
    kind: str
    name: str
    text: str
    start_line: int | None = None
    end_line: int | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "kind": self.kind,
            "name": self.name,
            "text": self.text,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }

    @staticmethod
    def from_dict(d: dict) -> "Chunk":
        return Chunk(**d)


def chunk_python_file(path: Path, rel_path: str) -> list[Chunk]:
    """Splits a Python file at function/class boundaries instead of fixed-size
    windows, so a chunk never cuts a function in half."""
    source = path.read_text()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return [Chunk(id=rel_path, source=rel_path, kind="file", name=rel_path, text=source)]

    lines = source.splitlines()
    chunks: list[Chunk] = []
    covered: set[int] = set()

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start, end = node.lineno, node.end_lineno or node.lineno
            text = "\n".join(lines[start - 1 : end])
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            chunks.append(
                Chunk(
                    id=f"{rel_path}:{node.name}",
                    source=rel_path,
                    kind=kind,
                    name=node.name,
                    text=text,
                    start_line=start,
                    end_line=end,
                )
            )
            covered.update(range(start, end + 1))

    prologue = "\n".join(l for i, l in enumerate(lines, start=1) if i not in covered).strip()
    if prologue:
        chunks.append(Chunk(id=f"{rel_path}:module", source=rel_path, kind="module_prologue", name=rel_path, text=prologue))

    return chunks


def chunk_markdown_file(path: Path, rel_path: str) -> list[Chunk]:
    """Splits markdown at heading boundaries -- one chunk per section."""
    lines = path.read_text().splitlines()
    chunks: list[Chunk] = []
    heading = "intro"
    buf: list[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            chunks.append(Chunk(id=f"{rel_path}#{heading}", source=rel_path, kind="doc_section", name=heading, text=body))

    for line in lines:
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip() or heading
            buf = [line]
        else:
            buf.append(line)
    flush()
    return chunks


def chunk_git_log(repo_path: Path, max_commits: int = 200) -> list[Chunk]:
    """One chunk per commit: date, subject, body. Lets questions like
    'what changed in the eval harness last week' be answered from real history."""
    result = subprocess.run(
        ["git", "-C", str(repo_path), "log", f"-{max_commits}", "--date=short", "--pretty=format:%H%x1f%ad%x1f%s%x1f%b%x1e"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    chunks: list[Chunk] = []
    for entry in filter(None, result.stdout.split("\x1e")):
        parts = entry.strip("\n").split("\x1f")
        if len(parts) < 3:
            continue
        sha, date, subject = parts[0], parts[1], parts[2]
        body = parts[3].strip() if len(parts) > 3 else ""
        text = f"{date} {sha[:7]}: {subject}"
        if body:
            text += f"\n\n{body}"
        chunks.append(Chunk(id=f"commit:{sha[:7]}", source="git-log", kind="commit", name=subject[:60], text=text))
    return chunks


def ingest_repo(repo_path: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(repo_path.rglob("*")):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS or part.endswith(IGNORE_SUFFIXES) for part in path.parts):
            continue
        rel = str(path.relative_to(repo_path))
        if path.suffix == ".py":
            chunks.extend(chunk_python_file(path, rel))
        elif path.suffix == ".md":
            chunks.extend(chunk_markdown_file(path, rel))
    chunks.extend(chunk_git_log(repo_path))
    return chunks
