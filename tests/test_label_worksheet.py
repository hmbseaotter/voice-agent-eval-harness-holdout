"""The owner's labeling worksheet, `tools/make_label_worksheet.py`.

Three refusals carry the design, so each is exercised rather than trusted: no
worksheet before `rubric-frozen-v1` resolves (D21), none over an existing file
(it holds the owner's notes), and none inside this repository outside
`private/` (where notes could be committed). The freeze is planted in a
throwaway git repository standing in for the harness, so no test depends on
whether the real tag exists yet.

The rendering test runs over this set's real transcripts and asserts structure
and counts only. It prints nothing a transcript says, and deletes the file it
wrote.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import make_label_worksheet as worksheet  # noqa: E402

HARNESS: Final[Path | None] = worksheet.harness_root()

if HARNESS is not None:  # pragma: no cover - import plumbing
    with contextlib.suppress(ImportError):
        import harness  # noqa: F401
    if "harness" not in sys.modules:
        sys.path.insert(0, str(HARNESS / "src"))

requires_harness = pytest.mark.skipif(
    HARNESS is None,
    reason="the harness repository was not found, so no transcript can be parsed",
)


def _stand_in_harness(root: Path, *, tagged: bool) -> Path:
    """A git repository standing in for the harness: one commit, the freeze tag only if asked."""
    root.mkdir(parents=True)
    (root / "README.md").write_text("stand-in harness\n", encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    commands = [["init", "-q"], ["add", "README.md"], ["commit", "-q", "-m", "stand-in"]]
    if tagged:
        commands.append(["tag", worksheet.FREEZE_TAG])
    for command in commands:
        subprocess.run(["git", "-C", str(root), *command], check=True, env=env, capture_output=True)
    return root


def test_the_worksheet_refuses_before_the_freeze(tmp_path: Path) -> None:
    """No tag, no worksheet, and nothing written: labels follow the freeze (D21)."""
    untagged = _stand_in_harness(tmp_path / "harness", tagged=False)
    out = tmp_path / "notes.md"

    assert worksheet.freeze_commit(untagged) is None
    assert worksheet.freeze_commit(tmp_path / "not-a-repository") is None
    assert worksheet.build(harness=untagged, out=out) == 1
    assert not out.exists()


def test_the_freeze_commit_is_read_from_the_tag(tmp_path: Path) -> None:
    """The planted tag resolves to the stand-in's one commit, which the header will cite."""
    tagged = _stand_in_harness(tmp_path / "harness", tagged=True)
    head = subprocess.run(
        ["git", "-C", str(tagged), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert worksheet.freeze_commit(tagged) == head


def test_the_worksheet_never_overwrites_notes(tmp_path: Path) -> None:
    """An existing file may hold the owner's notes, so it is refused and left byte-identical."""
    tagged = _stand_in_harness(tmp_path / "harness", tagged=True)
    out = tmp_path / "notes.md"
    out.write_text("the owner's notes\n", encoding="utf-8")

    assert worksheet.build(harness=tagged, out=out) == 1
    assert out.read_text(encoding="utf-8") == "the owner's notes\n"


def test_the_worksheet_refuses_the_repository_outside_private(tmp_path: Path) -> None:
    """Inside this repository only `private/` is gitignored, so anywhere else is refused."""
    tagged = _stand_in_harness(tmp_path / "harness", tagged=True)
    out = REPO_ROOT / "notes-in-the-wrong-place.md"
    assert not out.exists()

    assert worksheet.build(harness=tagged, out=out) == 2
    assert not out.exists()


@requires_harness
def test_every_label_value_the_harness_declares_is_defined() -> None:
    """The label table covers exactly the harness's own values, each with a meaning."""
    from harness.core.findings import DetectableBy, Owner, Tier

    rows = worksheet.label_rows()
    expected = (
        {("owner", member.value) for member in Owner}
        | {("detectable_by", member.value) for member in DetectableBy}
        | {("tier", member.value) for member in Tier}
    )
    assert {(field, value) for field, value, _ in rows} == expected
    assert all(meaning.strip() for _, _, meaning in rows)


@requires_harness
def test_an_undefined_label_value_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: drop one definition and the table refuses rather than rendering a gap."""
    monkeypatch.setitem(worksheet.DEFINITIONS, "tier", {"defect": "the system did something wrong"})
    with pytest.raises(SystemExit, match="tier"):
        worksheet.label_rows()


@requires_harness
def test_the_worksheet_lays_out_every_call_in_full(tmp_path: Path) -> None:
    """One section per transcript, in order, every event listed in order, one template each.

    Structure and counts only. The file is removed afterwards and nothing it contains is
    printed, including on failure: each message names a call identifier and nothing more.
    """
    from harness.corpus.text_adapter import parse_call

    tagged = _stand_in_harness(tmp_path / "harness", tagged=True)
    sha = worksheet.freeze_commit(tagged)
    assert sha is not None
    out = tmp_path / "notes.md"
    try:
        assert worksheet.build(harness=tagged, out=out) == 0
        text = out.read_text(encoding="utf-8")
        calls = [
            parse_call(path) for path in sorted((REPO_ROOT / "transcripts").glob("CALL-*.txt"))
        ]

        assert f"`{sha}`" in text.split("\n## ", 1)[0], "the header does not cite the freeze commit"
        parts = re.split(r"^## (CALL-\d{2})$", text, flags=re.MULTILINE)
        sections = dict(zip(parts[1::2], parts[2::2], strict=True))
        assert list(sections) == [call.record.call_id for call in calls], "sections out of order"

        for call in calls:
            call_id = call.record.call_id
            body = sections[call_id]
            listed = [
                int(index)
                for index in re.findall(r"^\| (\d+) \| \d+:\d{2}\.\d{3} \|", body, re.MULTILINE)
            ]
            assert listed == [event.index for event in call.events], (
                f"{call_id}: the event table does not list every event in order"
            )
            assert body.count(f"{call_id} · observation 1") == 1, f"{call_id}: no single template"
    finally:
        out.unlink(missing_ok=True)
