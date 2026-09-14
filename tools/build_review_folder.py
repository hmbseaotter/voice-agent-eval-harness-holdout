#!/usr/bin/env python3
"""Build the folder an independent reviewer works in, for labeling the held-out set.

    python tools/build_review_folder.py                 # writes ~/holdout-review
    python tools/build_review_folder.py --out <folder>

WHY THIS EXISTS
---------------
`PHASE-5-LABELS.md` §5 step 3: a fresh session on a different model reviews the
held-out calls independently of the owner. Its list is only independent if it
was written without the material the evaluation system was built from -- the
rubric, the design set's findings, the seeding manifest. An instruction not to
read them depends on obedience; a folder that does not contain them does not.
The mechanism is the authoring packet's (D83, D86), and so are the redactions
and the leak scan, imported from `build_authoring_packet.py` rather than copied.

WHERE IT MAY BE BUILT
---------------------
Never inside this repository or the harness checkout, whatever their ignore
rules say: a session started there sits inside the material this folder exists
to keep out. And never where a git repository would track what the reviewer
writes -- the destination must be outside every repository, or ignored by the
one that encloses it, so the notes are committed only by forcing them.

The first version refused any destination below any `.git`, and on the owner's
machine the home directory is itself a repository, so every default and every
test's temporary directory was refused. The rule was too blunt rather than
wrong: that repository ignores both locations, which is exactly the property
that matters, and git's own discovery and ignore rules now decide it.

WHY IT REFUSES BEFORE THE FREEZE, AND WILL NOT OVERWRITE
-------------------------------------------------------
The reviewer's notes are a first draft of held-out labels, which do not exist
until after `rubric-frozen-v1` (D21), and they are written inside this folder.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_authoring_packet import design_ids, find_leaks, redact
from make_label_worksheet import (
    FREEZE_TAG,
    REPO_ROOT,
    TRANSCRIPTS,
    freeze_commit,
    harness_root,
    load_calls,
    render_notes,
)

DEFAULT_OUT: Final[Path] = Path.home() / "holdout-review"


def _brief(freeze_sha: str) -> str:
    """The reviewer's instructions. They name rules and the folder's contents, never a call."""
    lines = (
        "# Brief: independent review of the held-out calls",
        "",
        "*For the owner, before anything else: start the reviewer's session **in this folder**,",
        "on **Claude Fable 5.1** at effort **max**, with the opening message in",
        f"`PHASE-5-LABELS.md` Appendix A. This folder was built under `{FREEZE_TAG}` =",
        f"`{freeze_sha}`.*",
        "",
        "---",
        "",
        "You are an independent reviewer of six recorded voice-support calls. The project's owner",
        "is reviewing the same calls separately. The two lists are compared afterwards, and what",
        "survives the comparison becomes human-adjudicated ground truth for measuring an automated",
        "judge.",
        "",
        "## Read this first, because it is the one thing here that cannot be undone",
        "",
        "**Work only inside this folder.** Do not open, search or list anything outside it. In",
        "particular, do not open the repositories this material came from, and do not go looking",
        "for an evaluation rubric, a list of known findings, a seeding manifest or a decision",
        "record.",
        "",
        "**Why.** Your value is that your list was written without the material the automated",
        "judge was built from. Once you have seen that material your review is no longer",
        "independent, and no later step can make it so again. If you find yourself wanting",
        "anything outside this folder, stop and ask the owner instead of looking.",
        "",
        "**You will not see the owner's list, and you should not guess at it.** Write down",
        "what you find, not what you expect someone else to have found.",
        "",
        "## What is here",
        "",
        "```",
        "BRIEF.md                      this brief",
        "notes-reviewer.md             each call laid out in full, then the template you fill in",
        "transcripts/                  the six calls, one file each",
        "specs/transcript-format.md    how a transcript file is written",
        "specs/event-model.md          what each kind of event means; passages removed",
        "reference/entity-canon.md     names, tools and vocabularies used; passages removed",
        "```",
        "",
        "Where a passage was removed, a visible marker says so. The removed passages described",
        "other calls, which is exactly the material you should not read, so do not try to",
        "reconstruct them.",
        "",
        "## What to do",
        "",
        "1. For each call in `notes-reviewer.md`, read the whole call first: the call record, the",
        "   context, and every event in order. Whether something was wrong depends on everything",
        "   that came before it.",
        "2. For **every** problem you find, copy the template block under that call, number it,",
        "   and fill it in. The file's header defines each label; `not sure` is always allowed.",
        "3. List everything: what the agent said or did, the system around it, the records",
        "   themselves, and anything the transcript cannot settle. There is no checklist here, on",
        "   purpose: a checklist turns noticing into matching.",
        '4. **Be complete.** A problem left off your list is read later as "nothing wrong here".',
        "5. Cite events by the number in the first column of each call's event table. When you",
        "   quote, quote exactly.",
        "",
        "## What not to do",
        "",
        "- Do not rank how serious problems are, and do not propose fixes.",
        "- Do not write your observations in any other format, or anywhere but",
        "  `notes-reviewer.md`.",
        "- Do not summarize what the calls have in common, or count the problems across the set.",
        "- Do not edit the transcripts or any other file here, and commit nothing anywhere.",
        "- Keep your observations in the file rather than in chat; use chat for progress and",
        "  questions.",
        "",
        "## When you are done",
        "",
        "Tell the owner that `notes-reviewer.md` is complete. Both lists are saved before",
        "either is compared with the other. Turning the merged list into formal findings is a",
        "later step, with its own instructions.",
    )
    return "\n".join(lines) + "\n"


def _enclosing_repository(destination: Path) -> Path | None:
    """The git working tree that encloses `destination`, found by git's own discovery.

    The destination need not exist yet, so discovery starts at its nearest existing
    ancestor. `GIT_CEILING_DIRECTORIES` bounds it, as it bounds every git command.
    """
    start = destination
    while not start.exists() and start != start.parent:
        start = start.parent
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def tracking_repository(destination: Path) -> Path | None:
    """The repository that would track files written at `destination`, or None.

    None means either that no repository encloses it or that the enclosing one
    ignores it, so the notes could be committed only by forcing them. Anything but
    a clean "ignored" from `git check-ignore` counts as tracked: this fails closed.
    """
    target = destination.resolve()
    root = _enclosing_repository(target)
    if root is None:
        return None
    # Ask about the file the reviewer will write, not the folder. The folder does not
    # exist yet, so git cannot know it is a directory, and a directory-only pattern
    # such as `review/` does not match the bare name: `check-ignore review` reports it
    # tracked while `check-ignore review/notes-reviewer.md` reports it ignored. The
    # file inside is matched by both pattern forms, and it is the question that matters.
    probe = (Path(target.relative_to(root.resolve())) / "notes-reviewer.md").as_posix()
    ignored = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", "--", probe],
        capture_output=True,
        check=False,
    )
    return None if ignored.returncode == 0 else root


def build(*, harness: Path, out: Path, transcripts: Path = TRANSCRIPTS) -> int:
    """Write the review folder to `out`, or refuse and say why."""
    sha = freeze_commit(harness)
    if sha is None:
        print(
            f"error: {FREEZE_TAG} does not resolve in {harness}. The reviewer's notes are held-out "
            "label drafts, written only after the freeze (D21), so this refuses. If the tag exists "
            "on GitHub, fetch tags into that checkout and run this again.",
            file=sys.stderr,
        )
        return 1

    target = out.resolve()
    for protected, name in ((REPO_ROOT, "this repository"), (harness, "the harness checkout")):
        guarded = protected.resolve()
        if target == guarded or guarded in target.parents:
            print(
                f"error: {out} is inside {name}. A session started there sits inside the material "
                "this folder exists to keep out, whatever the ignore rules say. Choose a folder "
                "outside both repositories.",
                file=sys.stderr,
            )
            return 2
    tracker = tracking_repository(target)
    if tracker is not None:
        print(
            f"error: {out} is inside the git working tree at {tracker}, which would track the "
            "reviewer's notes. Choose a folder outside every repository, or one that repository "
            "ignores.",
            file=sys.stderr,
        )
        return 2
    if out.exists():
        print(
            f"error: {out} already exists and may hold the reviewer's notes; refusing to overwrite "
            "it. Move it aside first if a fresh folder is really wanted.",
            file=sys.stderr,
        )
        return 1

    design = design_ids(harness)
    if not design:
        print("error: the harness declares no design set; refusing to build", file=sys.stderr)
        return 2
    calls = load_calls(transcripts, harness)
    if not calls:
        print(f"error: no transcripts under {transcripts}", file=sys.stderr)
        return 1

    (out / "specs").mkdir(parents=True)
    (out / "reference").mkdir()
    (out / "transcripts").mkdir()
    shutil.copy2(harness / "specs" / "transcript-format.md", out / "specs" / "transcript-format.md")
    for source, dest in (
        (harness / "specs" / "event-model.md", out / "specs" / "event-model.md"),
        (harness / "corpus" / "entities.md", out / "reference" / "entity-canon.md"),
    ):
        dest.write_text(redact(source.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    for path in sorted(transcripts.glob("CALL-*.txt")):
        shutil.copy2(path, out / "transcripts" / path.name)
    (out / "BRIEF.md").write_text(_brief(sha), encoding="utf-8", newline="\n")
    (out / "notes-reviewer.md").write_text(
        render_notes(calls, freeze_sha=sha, reader="reviewer"), encoding="utf-8", newline="\n"
    )

    # The gate, shared with the authoring packet. A leaking folder beside a non-zero
    # exit code is one hurried moment from being opened anyway, so it is deleted.
    leaks = find_leaks(out, design)
    if leaks:
        shutil.rmtree(out, ignore_errors=True)
        print("\nLEAK: design-set identifiers survived redaction:", file=sys.stderr)
        print("\n".join(dict.fromkeys(leaks)), file=sys.stderr)
        print(
            "\nA redaction pattern has gone stale. Add one to build_authoring_packet.py and run "
            "again. **The folder has been deleted** rather than left for a session to open.",
            file=sys.stderr,
        )
        return 1

    enclosing = _enclosing_repository(target)
    where = f" (inside {enclosing}, which ignores it)" if enclosing is not None else ""
    print(f"review folder written to {out}{where}: {len(calls)} calls; no design-set id survives")
    print(
        "next: start a new session in that folder on Claude Fable 5.1 at effort max, and paste "
        "the opening message from PHASE-5-LABELS.md, Appendix A."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the held-out reviewer's folder.")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="where to build it (default: holdout-review in the home directory)",
    )
    args = parser.parse_args(argv)

    harness = harness_root()
    if harness is None:
        print(
            "error: the harness was not found, and it holds the parser, the freeze tag and the "
            "documents this folder is built from.\n"
            "Set HARNESS_ROOT, check it out to .harness, or clone it alongside this one.",
            file=sys.stderr,
        )
        return 1
    return build(harness=harness, out=args.out)


if __name__ == "__main__":
    raise SystemExit(main())
