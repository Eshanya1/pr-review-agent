from __future__ import annotations

from dataclasses import dataclass

from unidiff import PatchSet


@dataclass(frozen=True)
class AddedLine:
    file: str
    line_no: int
    text: str


def parse_added_lines(diff_text: str) -> list[AddedLine]:
    """Return every line a diff adds, with its target file and line number.

    Used by the critic to check that a finding's quoted evidence actually
    appears in the code the PR introduces, rather than being invented.
    """
    patch = PatchSet(diff_text)
    added: list[AddedLine] = []
    for patched_file in patch:
        path = patched_file.path
        for hunk in patched_file:
            for line in hunk:
                if line.is_added and line.value.strip():
                    added.append(
                        AddedLine(file=path, line_no=line.target_line_no, text=line.value.rstrip("\n"))
                    )
    return added


def touched_files(diff_text: str) -> list[str]:
    patch = PatchSet(diff_text)
    return [pf.path for pf in patch]
