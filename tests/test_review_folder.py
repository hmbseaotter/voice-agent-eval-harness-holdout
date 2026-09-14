"""The independent reviewer's folder, `tools/build_review_folder.py`.

Its refusals are exercised rather than trusted: nothing before `rubric-frozen-v1`
resolves, nothing inside this repository or the harness checkout, nothing where a
git repository would track the notes, nothing over an existing folder, and a
folder carrying a design-set identifier is deleted rather than kept.

**Every test that builds into a temporary directory sets `GIT_CEILING_DIRECTORIES`
to it.** A temporary directory can sit inside a repository the machine happens to
have -- on the owner's machine the home directory is one -- and git would then
discover that repository from inside the test. The ceiling bounds discovery
exactly as it bounds every git command, so the real check runs, and it runs only
over repositories the test created.

The clean-build test runs over this set's real transcripts and asserts the
folder's shape only. It prints nothing a transcript says, and it deletes the
folder it wrote.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import build_review_folder as review  # noqa: E402
import make_label_worksheet as worksheet  # noqa: E402
from build_authoring_packet import design_ids, find_leaks  # noqa: E402

HARNESS: Final[Path | None] = worksheet.harness_root()

if HARNESS is not None:  # pragma: no cover - import plumbing
    with contextlib.suppress(ImportError):
        import harness  # noqa: F401
    if "harness" not in sys.modules:
        sys.path.insert(0, str(HARNESS / "src"))

requires_harness = pytest.mark.skipif(
    HARNESS is None,
    reason="the harness repository was not found, so there are no documents to build from",
)

#: The harness documents the folder is built from, and nothing else.
_COPIED: Final[tuple[str, ...]] = (
    "specs/transcript-format.md",
    "specs/event-model.md",
    "corpus/entities.md",
    "corpus/DESIGN_SET",
)

_IDENTITY: Final[dict[str, str]] = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


@pytest.fixture
def bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`tmp_path`, with git discovery unable to climb above it."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", tmp_path.as_posix())
    return tmp_path


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        env={**os.environ, **_IDENTITY},
        capture_output=True,
    )


def _stand_in_harness(root: Path, *, tagged: bool, register_suffix: str = "") -> Path:
    """A git repository holding copies of the harness documents; tagged only if asked."""
    assert HARNESS is not None
    for relative in _COPIED:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HARNESS / relative, root / relative)
    if register_suffix:
        register = root / "corpus" / "entities.md"
        register.write_text(
            register.read_text(encoding="utf-8") + register_suffix, encoding="utf-8"
        )
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "stand-in")
    if tagged:
        _git(root, "tag", worksheet.FREEZE_TAG)
    return root


def test_the_default_destination_would_not_be_tracked() -> None:
    """The default is safe wherever this suite runs: no repository here would track it."""
    assert review.tracking_repository(review.DEFAULT_OUT) is None


def test_a_repository_that_would_track_the_folder_is_named(bounded: Path) -> None:
    """Rule two, both ways: tracked is named, ignored is not."""
    other = bounded / "other"
    other.mkdir()
    _git(other, "init", "-q")
    assert review.tracking_repository(other / "review") == other.resolve()

    # Both pattern forms. The directory-only one is the case that matters: the folder does
    # not exist yet, so a check that asked about the bare name reported it tracked.
    for pattern in ("review/\n", "review\n"):
        (other / ".gitignore").write_text(pattern, encoding="utf-8")
        assert review.tracking_repository(other / "review") is None, f"pattern {pattern!r}"
    assert review.tracking_repository(bounded / "outside") is None


@requires_harness
def test_the_folder_refuses_before_the_freeze(bounded: Path) -> None:
    """No tag, no folder: the reviewer's notes are label drafts, and labels follow the freeze."""
    untagged = _stand_in_harness(bounded / "harness", tagged=False)
    out = bounded / "review"

    assert review.build(harness=untagged, out=out) == 1
    assert not out.exists()


@requires_harness
def test_the_folder_refuses_both_repositories_whatever_they_ignore(bounded: Path) -> None:
    """Rule one: not the harness checkout, and not this repository, not even its `private/`."""
    tagged = _stand_in_harness(bounded / "harness", tagged=True)

    inside_harness = tagged / "review"
    assert review.build(harness=tagged, out=inside_harness) == 2
    assert not inside_harness.exists()

    inside_here = REPO_ROOT / "private" / "review-folder-probe"
    assert not inside_here.exists()
    assert review.build(harness=tagged, out=inside_here) == 2
    assert not inside_here.exists()


@requires_harness
def test_the_folder_refuses_where_a_repository_would_track_it(bounded: Path) -> None:
    """Rule two, wired into the build: a repository that would track the notes stops it."""
    tagged = _stand_in_harness(bounded / "harness", tagged=True)
    other = bounded / "other"
    other.mkdir()
    _git(other, "init", "-q")
    out = other / "review"

    assert review.build(harness=tagged, out=out) == 2
    assert not out.exists()


@requires_harness
def test_the_folder_never_overwrites_an_existing_one(bounded: Path) -> None:
    """An existing folder may hold the reviewer's notes, so it is refused and left untouched."""
    tagged = _stand_in_harness(bounded / "harness", tagged=True)
    out = bounded / "review"
    out.mkdir()
    (out / "notes-reviewer.md").write_text("the reviewer's notes\n", encoding="utf-8")

    assert review.build(harness=tagged, out=out) == 1
    assert (out / "notes-reviewer.md").read_text(encoding="utf-8") == "the reviewer's notes\n"


@requires_harness
def test_a_folder_naming_a_design_call_is_deleted(bounded: Path) -> None:
    """The control for the shared gate: plant a design identifier no redaction removes."""
    assert HARNESS is not None
    planted = sorted(design_ids(HARNESS))[0]
    tagged = _stand_in_harness(
        bounded / "harness",
        tagged=True,
        register_suffix=f"\n\nAn unredacted mention of {planted} that no pattern removes.\n",
    )
    out = bounded / "review"

    assert review.build(harness=tagged, out=out) == 1
    assert not out.exists(), "a folder carrying a design-set identifier was left on disk"


@requires_harness
def test_a_clean_folder_holds_exactly_what_the_brief_describes(bounded: Path) -> None:
    """The brief, the reviewer's worksheet, three redacted or copied documents, the transcripts.

    Shape only: file names, the freeze commit in two headers, and a count of design-set
    identifiers, which must be zero. Nothing a transcript says is asserted or printed.
    """
    tagged = _stand_in_harness(bounded / "harness", tagged=True)
    sha = worksheet.freeze_commit(tagged)
    assert sha is not None
    out = bounded / "review"
    try:
        assert review.build(harness=tagged, out=out) == 0

        files = sorted(
            path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file()
        )
        transcripts = [f"transcripts/{path.name}" for path in (REPO_ROOT / "transcripts").glob("*")]
        assert files == sorted(
            [
                "BRIEF.md",
                "notes-reviewer.md",
                "reference/entity-canon.md",
                "specs/event-model.md",
                "specs/transcript-format.md",
                *transcripts,
            ]
        )

        leak_count = len(find_leaks(out, design_ids(tagged)))
        assert leak_count == 0, f"{leak_count} lines name a design-set call"

        notes = (out / "notes-reviewer.md").read_text(encoding="utf-8")
        notes_header = notes.split("\n## ", 1)[0]
        assert notes_header.startswith("# Held-out labeling notes: reviewer")
        assert f"`{sha}`" in notes_header

        brief = (out / "BRIEF.md").read_text(encoding="utf-8")
        assert "**Work only inside this folder.**" in brief
        assert f"`{sha}`" in brief
    finally:
        shutil.rmtree(out, ignore_errors=True)
