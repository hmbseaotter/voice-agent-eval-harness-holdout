#!/usr/bin/env python3
"""Write the owner's worksheet for labeling the held-out set into `private/labels/`.

    python tools/make_label_worksheet.py
    python tools/make_label_worksheet.py --out private/labels/notes-owner.md

WHY THIS EXISTS
---------------
`PHASE-5-LABELS.md` §5: the owner and an independent reviewer each write down
everything wrong with every held-out call, in one template, before either has
seen the other's list. This writes the owner's copy -- each call laid out in
full and in order, then an empty template -- and `build_review_folder.py`
renders the reviewer's copy through the same function, so the two lists cannot
drift into different shapes.

WHY IT REFUSES BEFORE THE FREEZE
--------------------------------
The notes written into this file are the first draft of the held-out labels,
and D21 holds that the labels do not exist until after `rubric-frozen-v1`. A
promise to wait depends on someone remembering; a worksheet that cannot be
produced until the tag resolves does not. The freeze commit goes into the
header, so every note in the file was written under a known frozen rubric.

WHY IT WILL NOT OVERWRITE
-------------------------
The owner writes into the file this produces. Regenerating over it would erase
the notes, so an existing file is refused, and there is no flag to force it.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It proposes nothing and pre-fills nothing (D38). It shows no rubric: which entry
should catch a finding is decided later, with the rubric open, and a list of
entries beside a reviewer turns noticing into matching. And inside this
repository it writes nowhere except the gitignored `private/`.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import subprocess
import sys
from enum import Enum, StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

import freeze_proof

if TYPE_CHECKING:  # pragma: no cover - types only, and the harness may be absent
    from collections.abc import Sequence

    from harness.core.events import Call

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
TRANSCRIPTS: Final[Path] = REPO_ROOT / "transcripts"
PRIVATE: Final[Path] = REPO_ROOT / "private"
DEFAULT_OUT: Final[Path] = PRIVATE / "labels" / "notes-owner.md"
FREEZE_TAG: Final[str] = "rubric-frozen-v1"

#: What each label value means, in the words both reviewers read. The values
#: themselves come from the harness's enums at run time, and `label_rows`
#: refuses when this table and those enums stop matching: a value the harness
#: adds must be defined here before anyone is asked to use it.
DEFINITIONS: Final[dict[str, dict[str, str]]] = {
    "owner": {
        "agent": "the agent's own behavior: what it said, what it chose to do",
        "platform": (
            "the system around the agent: a gate not enforced, a state not recorded, a "
            "disposition derived from something other than the tool results"
        ),
        "data": (
            "the records themselves: contradictions, missing components, values the agent "
            "could not have spoken correctly whatever it did"
        ),
    },
    "detectable_by": {
        "assert": (
            "derivable from the context, the tool calls and results, the recorded state and "
            "their order, with no reading of what was said"
        ),
        "judge": "needs someone to read what was said and judge it",
        "human": "only a person would notice it",
    },
    "tier": {
        "defect": "the system did something wrong",
        "question": (
            "something is wrong or absent in a way the transcript cannot settle, so it is a "
            "question for whoever owns the system rather than a defect charged to the call"
        ),
    },
}

#: What changes between the owner's copy and the reviewer's.
READERS: Final[dict[str, tuple[str, ...]]] = {
    "owner": (
        "**You are one of two reviewers.** A separate session reviews the same calls in the same",
        "template, and neither of you sees the other's list until both are saved. Save this file",
        "before you open theirs. Do not open the rubric until the entry-mapping step",
        "(`PHASE-5-LABELS.md` §5).",
    ),
    "reviewer": (
        "**You are one of two reviewers.** The project's owner reviews the same calls in the same",
        "template, and neither of you sees the other's list until both are saved. Work only from",
        "the folder this file is in; `BRIEF.md` there says why.",
    ),
}


def harness_root() -> Path | None:
    """Where the harness repository is, or None: the same three places as the other tools."""
    for candidate in (
        Path(value) if (value := os.environ.get("HARNESS_ROOT")) else None,
        REPO_ROOT / ".harness",
        REPO_ROOT.parent / "voice-agent-eval-harness",
    ):
        if candidate is not None and (candidate / "corpus" / "policies").is_dir():
            return candidate
    return None


def freeze_commit(harness: Path) -> str | None:
    """The freeze commit `harness` names, however that checkout is able to name it.

    Two checkouts have to work, and they name it differently. A clone of the private working
    repository still carries the annotated tag, and is asked for it by name. The published
    harness is a snapshot (harness D208) and cannot carry a ref reaching the freeze, so it
    publishes the commit object instead and the id is recomputed from its bytes (O-12).

    The proof is preferred where both exist, because an id recomputed from bytes cannot be
    moved and a tag can. A tag read from that checkout's own refs, never from GitHub, so one
    that exists remotely and was never fetched reads as absent -- the safe direction to be
    wrong in, and the reason None is still a possible answer.
    """
    try:
        proof = freeze_proof.load(harness)
    except freeze_proof.ProofError:
        return None
    if proof is not None:
        return proof.commit_sha
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(harness),
                "rev-parse",
                "-q",
                "--verify",
                f"refs/tags/{FREEZE_TAG}^{{commit}}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and len(sha) == 40 else None


def load_calls(transcripts: Path, harness: Path) -> list[Call]:
    """Every transcript under `transcripts`, parsed by the harness's own adapter."""
    if str(harness / "src") not in sys.path:
        sys.path.insert(0, str(harness / "src"))
    from harness.corpus.text_adapter import parse_call

    return [parse_call(path) for path in sorted(transcripts.glob("CALL-*.txt"))]


def label_rows() -> list[tuple[str, str, str]]:
    """`(field, value, meaning)` for every label value, in the harness's own order."""
    from harness.core.findings import DetectableBy, Owner, Tier

    enums: tuple[tuple[str, type[StrEnum]], ...] = (
        ("owner", Owner),
        ("detectable_by", DetectableBy),
        ("tier", Tier),
    )
    rows: list[tuple[str, str, str]] = []
    for field, enum in enums:
        values = [str(member.value) for member in enum]
        if set(values) != set(DEFINITIONS[field]):
            raise SystemExit(
                f"the harness's {field} values are {sorted(values)} and this tool defines "
                f"{sorted(DEFINITIONS[field])}; define every value before asking anyone to use it"
            )
        rows += [(field, value, DEFINITIONS[field][value]) for value in values]
    return rows


def _cell(value: object) -> str:
    """A Markdown table cell cannot hold a raw pipe or a newline."""
    text = str(value.value) if isinstance(value, Enum) else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _clock(milliseconds: int) -> str:
    minutes, rest = divmod(milliseconds, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{minutes}:{seconds:02d}.{millis:03d}"


def _template(call_id: str) -> list[str]:
    choices = {
        field: [value for f, value, _ in label_rows() if f == field] for field in DEFINITIONS
    }

    def options(field: str) -> str:
        return " | ".join([*choices[field], "not sure"])

    return [
        "```",
        f"{call_id} · observation 1",
        "  What went wrong:",
        "  Where (event numbers):",
        f"  Owner:               {options('owner')}",
        f"  Could be caught by:  {options('detectable_by')}",
        f"  Defect or question:  {options('tier')}",
        "  Consequence (optional):",
        "```",
    ]


def _render_call(call: Call) -> list[str]:
    call_id = call.record.call_id
    lines = [f"## {call_id}", "", "**Call record**", "", "| field | value |", "|---|---|"]
    for field in dataclasses.fields(call.record):
        lines.append(f"| `{field.name}` | {_cell(getattr(call.record, field.name))} |")

    lines += [
        "",
        "**Context: everything the agent could see before it spoke**",
        "",
        "| name | value |",
        "|---|---|",
    ]
    if call.context:
        lines += [f"| `{name}` | {_cell(value)} |" for name, value in call.context]
    else:
        lines.append("| *(none)* | The agent was given nothing at call start. |")

    lines += [
        "",
        "**Every event, in order**",
        "",
        "| # | start | end | kind | body |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {event.index} | {_clock(event.started_at_ms)} | {_clock(event.ended_at_ms)} "
        f"| `{_cell(event.kind)}` | {_cell(event.body)} |"
        for event in call.events
    ]
    if call.unparsed:
        lines += ["", "**Lines the parser could not read**", ""]
        lines += [f"- line {line.line_number}: {line.reason}" for line in call.unparsed]

    lines += ["", f"### {call_id}: observations", "", *_template(call_id), "", "---", ""]
    return lines


def render_notes(calls: Sequence[Call], *, freeze_sha: str, reader: str) -> str:
    """The worksheet for `reader`, which is `owner` or `reviewer`."""
    if reader not in READERS:
        raise ValueError(f"reader must be one of {sorted(READERS)}, not {reader!r}")
    lines = [
        f"# Held-out labeling notes: {reader}",
        "",
        f"*Generated by `tools/make_label_worksheet.py` under `{FREEZE_TAG}` = `{freeze_sha}`. "
        "A private working file: never commit it, and copy nothing from it anywhere else before "
        "the labels are published (D61).*",
        "",
        "## How to use this",
        "",
        "Each call is laid out **in full and in order**: the call record, everything the agent",
        "could see before it spoke, and every event. Read the whole call before writing anything,",
        "because whether something was wrong depends on everything that came before it.",
        "",
        "Then, for **every** problem you find, copy the template block under that call, number",
        "it, and fill it in. List everything: what the agent said or did, the system around it,",
        "and the records themselves, plus anything the transcript cannot settle. **A problem left",
        'off this page is read later as "nothing wrong here"**, so a full pass beats a quick one.',
        "`not sure` is always an allowed answer.",
        "",
        *READERS[reader],
        "",
        "## What the labels mean",
        "",
        "| field | value | meaning |",
        "|---|---|---|",
        *(f"| `{field}` | `{value}` | {meaning} |" for field, value, meaning in label_rows()),
        "",
        "In the template, **Owner** is `owner`, **Could be caught by** is `detectable_by`, and",
        "**Defect or question** is `tier`.",
        "",
        "---",
        "",
    ]
    for call in calls:
        lines += _render_call(call)
    return "\n".join(lines).rstrip("\n") + "\n"


def build(*, harness: Path, out: Path, transcripts: Path = TRANSCRIPTS) -> int:
    """Write the owner's worksheet to `out`, or refuse and say why."""
    sha = freeze_commit(harness)
    if sha is None:
        print(
            f"error: {FREEZE_TAG} does not resolve in {harness}. Held-out labels are written only "
            "after the freeze (D21), so this refuses. If the tag exists on GitHub, fetch tags "
            "into that checkout and run this again.",
            file=sys.stderr,
        )
        return 1

    target = out.resolve()
    if REPO_ROOT.resolve() in target.parents and PRIVATE.resolve() not in target.parents:
        print(
            f"error: {out} is inside this repository but outside private/, where notes could be "
            "committed. Write under private/ or outside the repository.",
            file=sys.stderr,
        )
        return 2
    if out.exists():
        print(
            f"error: {out} already exists and may hold notes; refusing to overwrite it. Move it "
            "aside first if a fresh copy is really wanted.",
            file=sys.stderr,
        )
        return 1

    calls = load_calls(transcripts, harness)
    if not calls:
        print(f"error: no transcripts under {transcripts}", file=sys.stderr)
        return 1

    rendered = render_notes(calls, freeze_sha=sha, reader="owner")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    events = sum(len(call.events) for call in calls)
    print(f"wrote {out}: {len(calls)} calls, {events} events, under {FREEZE_TAG} {sha[:12]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the owner's held-out labeling worksheet.")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="where to write it (default: private/labels/notes-owner.md)",
    )
    args = parser.parse_args(argv)

    harness = harness_root()
    if harness is None:
        print(
            "error: the harness was not found, and it holds both the parser and the freeze tag.\n"
            "Set HARNESS_ROOT, check it out to .harness, or clone it alongside this one.",
            file=sys.stderr,
        )
        return 1
    return build(harness=harness, out=args.out)


if __name__ == "__main__":
    raise SystemExit(main())
