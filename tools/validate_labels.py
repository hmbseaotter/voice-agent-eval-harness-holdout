#!/usr/bin/env python3
"""Validate the held-out labels before they are sealed: format, evidence, placement.

    python tools/validate_labels.py drafts     # private/labels/drafts.yaml
    python tools/validate_labels.py findings   # private/labels/findings.yaml
    python tools/validate_labels.py            # findings.yaml and traces.yaml, as sealing needs

WHY THIS EXISTS
---------------
`PHASE-5-LABELS.md` §5 steps 6 to 8. The drafts are formatted by an AI from two
people's notes, the findings are generated from the drafts and the owner's
ledger, and the entry mapping is written by hand. Each step can misquote an
event, cite one that does not exist, or leave a finding placed nowhere. Once the
manifest is committed, a label cannot be corrected without voiding the run
measured against it (§9), so this finds those errors while they cost nothing.

WHAT IT CHECKS
--------------
Every stage:
- every id is shaped `HF-NN` and is not a design finding's id;
- every `call_ref` is declared in the harness's `HELDOUT_SET` and has a
  transcript here;
- every evidence fragment holds to the design set's evidence rules, and every
  event a finding's prose cites exists.

`drafts` checks the drafts' own shape: the gold-set format's text fields and no
classification. `owner`, `detectable_by` and `tier` are the owner's to rule on
in the ledger (D10), and a draft that proposed them would put in front of the
owner the default D38 refused to collect.

`findings` loads the document with the harness's own gold-set loader instead.

`all`, the default, adds `traces.yaml` (§4). It must name the freeze commit, its
keys must be exactly the entry ids of `rubric.yaml` **at that commit**, and
every finding must sit under at least one entry or in `uncovered`, never both.
Every held-out call must be referenced by a finding or listed under
`calls_without_findings`, never both (§6 step 1). A call can have nothing wrong
with it, and saying so is then a decision rather than an omission. That check
waits for this stage because the list lives in `traces.yaml`.

THE EVIDENCE RULES ARE THE DESIGN SET'S
--------------------------------------
Ported from the harness's `tests/test_findings_evidence.py`, so a held-out
finding is held to exactly what a design finding is: quoted and unquoted event
text, context values, call-record fields, spans, gap claims, the final event's
end, and citations into another call. Prose about an absence is still the
reviewer's to judge, and is counted as such rather than as checked.

The patterns are copies, compared with the harness's by
`tests/test_validate_labels.py`. The branches that apply them are a port, held to
their behavior by that file's controls rather than by a comparison. The
seeding-manifest check is not ported, because it reads the design set's
manifest.

WHAT IT PRINTS
--------------
Counts, and for each problem the finding or draft it is in and the rule it
breaks. It never prints a quote, an event's text, a ruled value, or which entry
a finding sits under, because this output lands in terminals and in session
transcripts that later sessions can search (§2). The one exception is a document
the harness's loader refuses, which is reported in the loader's own words.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypeGuard

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_label_worksheet import (
    FREEZE_TAG,
    PRIVATE,
    TRANSCRIPTS,
    freeze_commit,
    harness_root,
    load_calls,
)

if TYPE_CHECKING:  # pragma: no cover - types only, and the harness may be absent
    from collections.abc import Iterable, Mapping, Sequence

    from harness.core.events import Call

LABELS: Final[Path] = PRIVATE / "labels"
STAGES: Final[tuple[str, ...]] = ("drafts", "findings", "all")

#: Held-out finding ids. The loader accepts any non-empty string, so the shape is
#: this repository's rule. A prefix no design finding carries makes a collision
#: impossible rather than unlikely, and `H-` was already taken: the harness's
#: audit records number their own findings `H-1` onward.
HELDOUT_ID: Final[re.Pattern[str]] = re.compile(r"^HF-(\d{2,})$")

#: The gold-set format's text fields, which are all a draft may carry.
DRAFT_KEYS: Final[tuple[str, ...]] = ("id", "call_ref", "observation", "evidence", "consequence")
#: What only the owner's ledger may state.
RULED: Final[tuple[str, ...]] = ("owner", "detectable_by", "tier")
#: The `traces.yaml` list of held-out calls with no finding, and the shape of an entry in it.
WITHOUT_FINDINGS: Final[str] = "calls_without_findings"
_CALL_ID: Final[re.Pattern[str]] = re.compile(r"^CALL-\d+$")


@dataclass(frozen=True, slots=True)
class Row:
    """What the evidence and citation rules read, from a finding or from a draft."""

    id: str
    call_ref: str
    observation: str
    evidence: tuple[str, ...]
    consequence: str


# --------------------------------------------------------------------------
# The design set's evidence patterns, copied from the harness's
# `tests/test_findings_evidence.py`, where each one's comment says which drift
# it was written for. `tests/test_validate_labels.py` compares them with it.
# --------------------------------------------------------------------------

_EVENT_QUOTE = re.compile(r"^event\s+(\d+)\s*[—-]\s*[\"“](?P<quote>.+)[\"”]\s*$", re.DOTALL)
_EVENT_PLAIN = re.compile(r"^event\s+(\d+)\s*[—-]\s*(?P<text>.+)$", re.DOTALL)
_RECORD = re.compile(r"^call record\s*[—-]\s*(?P<rest>.+)$", re.DOTALL)
_SPAN = re.compile(
    r"^events\s+(?P<first>\d+)\s+to\s+(?P<second>\d+)\s*[—-]\s*.*?from\s+(?P<start>\d+:\d\d\.\d\d\d)\s+to\s+(?P<end>\d+:\d\d\.\d\d\d)",
    re.DOTALL,
)
_FINAL_EVENT = re.compile(r"final event .*?ends at\s+(?P<ms>\d+)\s*ms", re.DOTALL)
_CROSS_CALL = re.compile(
    r"^(?P<call>CALL-\d+)\s+event\s+(?P<index>\d+)\s*[—-]\s*(?P<text>.+)$",
    re.DOTALL,
)
_GAP_CLAIM = re.compile(
    r"No (?P<kind>[A-Z_]+|event of any kind|event)"
    r"[^.]{0,60}?between events\s+(?P<first>\d+)\s+and\s+(?P<second>\d+)",
    re.DOTALL,
)
_CONTEXT = re.compile(
    r"^context\s*[—-]\s*(?P<name>[A-Za-z_][\w.]*)\s*:=\s*(?P<value>.+)$", re.DOTALL
)
_PROSE_EVENT = re.compile(
    r"\b(?:(?P<call>CALL-\d+)\s+)?events?\s+(?P<first>\d+)"
    r"(?:\s*(?:and|to|[-\u2013\u2014])\s*(?P<second>\d+))?",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Whitespace-insensitive, as the harness compares: both sides wrap, at different columns."""
    return " ".join(text.split())


def _stamp(ms: int) -> str:
    """`0:55.913`, the form the transcripts and the findings both use."""
    return f"{ms // 60_000}:{(ms % 60_000) / 1000:06.3f}"


def id_order(finding_id: str) -> tuple[int, str]:
    """Numeric order for `HF-NN`, so `HF-10` follows `HF-09`; any other id sorts after them."""
    match = HELDOUT_ID.match(finding_id)
    return (int(match.group(1)), "") if match else (sys.maxsize, finding_id)


def yaml_problem(name: str, error: Exception) -> str:
    """Where a YAML error is, without the snippet of the offending line PyYAML quotes."""
    mark = getattr(error, "problem_mark", None)
    where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark is not None else ""
    return f"{name}: not valid YAML{where}"


def _id_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


# --------------------------------------------------------------------------
# What the harness declares
# --------------------------------------------------------------------------


def heldout_calls(harness: Path) -> set[str]:
    """The call identifiers `HELDOUT_SET` declares, read the way the workflow reads them."""
    text = (harness / "HELDOUT_SET").read_text(encoding="utf-8")
    return {
        "".join(line.split())
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def design_finding_ids(harness: Path) -> set[str]:
    """The ids of the design set's gold findings, which no held-out id may repeat."""
    import yaml

    document = yaml.safe_load((harness / "corpus" / "findings.yaml").read_text(encoding="utf-8"))
    rows = document.get("findings") if isinstance(document, dict) else None
    return {str(row["id"]) for row in rows or () if isinstance(row, dict) and "id" in row}


def rubric_entry_ids(harness: Path, freeze_sha: str) -> list[str] | None:
    """The entry ids of `rubric.yaml` at the freeze commit, or None when it cannot be read there.

    Read with `git show` and never from the working tree: the harness's `main` moves on
    after the freeze, and the mapping is to the rubric the judge was frozen with (§4).
    """
    import yaml

    shown = subprocess.run(
        ["git", "-C", str(harness), "show", f"{freeze_sha}:rubric.yaml"],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if shown.returncode != 0:
        return None
    document = yaml.safe_load(shown.stdout)
    entries = document.get("entries") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        return None
    return [str(entry["id"]) for entry in entries if isinstance(entry, dict) and "id" in entry]


# --------------------------------------------------------------------------
# The documents
# --------------------------------------------------------------------------


def parse_drafts(text: str) -> tuple[list[Row], list[str]]:
    """The drafts as rows, and every way the document departs from the drafts' shape."""
    import yaml

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return [], [yaml_problem("drafts.yaml", error)]
    entries = document.get("findings") if isinstance(document, dict) else None
    if not isinstance(entries, list) or not entries:
        return [], ["drafts.yaml: expected a mapping whose `findings` is a non-empty list"]

    rows: list[Row] = []
    problems: list[str] = []
    seen: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        where = f"draft {position}"
        if not isinstance(entry, dict):
            problems.append(f"{where}: expected a mapping")
            continue
        before = len(problems)
        claimed = [key for key in (*RULED, "severity") if key in entry]
        if claimed:
            problems.append(
                f"{where}: carries {', '.join(claimed)}, which only the owner's ledger states "
                "(D10); a draft proposes no classification (D38)"
            )
        missing = [key for key in DRAFT_KEYS if key not in entry]
        if missing:
            problems.append(f"{where}: missing {', '.join(missing)}")
        allowed = (*DRAFT_KEYS, *RULED, "severity")
        unknown = sorted(str(key) for key in entry if key not in allowed)
        if unknown:
            problems.append(f"{where}: unknown key(s) {', '.join(unknown)}")
        for key in ("id", "call_ref", "observation", "consequence"):
            value = entry.get(key)
            if key in entry and (not isinstance(value, str) or not value.strip()):
                problems.append(f"{where}: {key} must be a non-empty string")
        evidence = entry.get("evidence")
        if "evidence" in entry and (
            not isinstance(evidence, list)
            or not evidence
            or not all(isinstance(fragment, str) and fragment.strip() for fragment in evidence)
        ):
            problems.append(f"{where}: evidence must be a non-empty list of non-empty strings")
        if len(problems) > before:
            continue
        if entry["id"] in seen:
            problems.append(f"{where}: repeats the id of an earlier draft")
            continue
        seen.add(entry["id"])
        rows.append(
            Row(
                id=entry["id"],
                call_ref=entry["call_ref"],
                observation=entry["observation"],
                evidence=tuple(entry["evidence"]),
                consequence=entry["consequence"],
            )
        )
    return rows, problems


def parse_findings_document(text: str) -> tuple[list[Row], list[str]]:
    """The findings as rows, loaded by the harness's own gold-set loader, or its refusal."""
    import yaml
    from harness.core.findings import FindingsError, parse_findings

    try:
        findings = parse_findings(text)
    except yaml.YAMLError as error:
        return [], [yaml_problem("findings.yaml", error)]
    except FindingsError as error:
        return [], [f"findings.yaml: the harness's loader refuses it: {error}"]
    rows = [Row(f.id, f.call_ref, f.observation, f.evidence, f.consequence) for f in findings]
    return rows, []


# --------------------------------------------------------------------------
# The rules
# --------------------------------------------------------------------------


def identity_problems(
    rows: Sequence[Row], *, heldout: set[str], transcribed: Iterable[str], design: set[str]
) -> list[str]:
    """Ids shaped `HF-NN` and new; every `call_ref` a held-out call with a transcript here."""
    here = set(transcribed)
    problems: list[str] = []
    for position, row in enumerate(rows, start=1):
        shaped = HELDOUT_ID.match(row.id) is not None
        label = row.id if shaped else f"row {position}"
        if not shaped:
            problems.append(f"{label}: its id is not shaped HF-NN")
        elif row.id in design:
            problems.append(f"{label}: its id is a design-set finding's id")
        if row.call_ref not in heldout:
            problems.append(f"{label}: its call_ref is not declared in HELDOUT_SET")
        elif row.call_ref not in here:
            problems.append(f"{label}: its call_ref has no transcript in this repository")
    return problems


def coverage_problems(
    rows: Sequence[Row], heldout: set[str], without_findings: set[str]
) -> list[str]:
    """Every held-out call referenced by a finding or declared to have none, never both.

    §6 step 1. No call can be left out silently, and "nothing wrong here" is only ever a
    decision written into `traces.yaml`, never the absence of a row.
    """
    referenced = {row.call_ref for row in rows}
    problems = [
        f"{call_ref}: no finding references this held-out call, and {WITHOUT_FINDINGS} "
        "does not list it"
        for call_ref in sorted(heldout - referenced - without_findings)
    ]
    problems += [
        f"{call_ref}: {WITHOUT_FINDINGS} lists it, yet a finding references it"
        for call_ref in sorted(without_findings & referenced)
    ]
    strangers = without_findings - heldout
    problems += [
        f"{call_ref}: {WITHOUT_FINDINGS} lists it, but HELDOUT_SET does not declare it"
        for call_ref in sorted(strangers)
        if _CALL_ID.match(call_ref)
    ]
    unshaped = [call_ref for call_ref in strangers if not _CALL_ID.match(call_ref)]
    if unshaped:
        problems.append(
            f"traces.yaml: {len(unshaped)} entries of {WITHOUT_FINDINGS} are not call ids"
        )
    return problems


def evidence_problems(rows: Sequence[Row], calls: Mapping[str, Call]) -> tuple[list[str], int, int]:
    """Every evidence fragment held to the design set's rules.

    Returns the problems, how many fragments were checked, and how many were left to the
    reviewer as prose about an absence. A row whose own call has no transcript is skipped,
    because `identity_problems` already names it.
    """
    from harness.core.events import EventKind

    kinds = {member.name for member in EventKind}
    problems: list[str] = []
    checked = 0
    prose = 0
    for row in rows:
        call = calls.get(row.call_ref)
        if call is None:
            continue
        by_index = {event.index: event for event in call.events}
        context = dict(call.context)

        for position, fragment in enumerate(row.evidence, start=1):
            where = f"{row.id} evidence {position}"
            flat = _normalize(fragment)

            match_context = _CONTEXT.match(flat)
            if match_context is not None:
                checked += 1
                name = match_context.group("name")
                if name not in context:
                    problems.append(f"{where}: cites a context variable {row.call_ref} lacks")
                elif _normalize(context[name]) != _normalize(match_context.group("value")):
                    problems.append(f"{where}: states a context value {row.call_ref} does not hold")
                continue

            match_cross = _CROSS_CALL.match(flat)
            if match_cross is not None:
                checked += 1
                other = match_cross.group("call")
                other_call = calls.get(other)
                if other_call is None:
                    problems.append(f"{where}: cites {other}, which has no transcript here")
                    continue
                index = int(match_cross.group("index"))
                cited = {event.index: event for event in other_call.events}.get(index)
                if cited is None:
                    problems.append(f"{where}: cites {other} event {index}, which it lacks")
                    continue
                wanted = _normalize(match_cross.group("text"))
                body = _normalize(cited.body)
                if wanted not in body and wanted.split(",")[0] not in body:
                    problems.append(f"{where}: {other} event {index} does not hold what it quotes")
                continue

            match_record = _RECORD.match(flat)
            if match_record is not None:
                checked += 1
                rest = match_record.group("rest")
                fields = {
                    name: str(getattr(call.record, name))
                    for name in dir(call.record)
                    if not name.startswith("_") and not callable(getattr(call.record, name))
                }
                named = [name for name in fields if name in rest]
                # `outcome` is a substring of `outcome_reason`: keep only maximal matches.
                named = [n for n in named if not any(n != m and n in m for m in named)]
                if not named:
                    problems.append(f"{where}: cites the call record, naming none of its fields")
                for name in named:
                    if fields[name] not in rest:
                        problems.append(f"{where}: states a call-record {name} the record lacks")
                continue

            match_span = _SPAN.match(flat)
            if match_span is not None:
                checked += 1
                first = by_index.get(int(match_span.group("first")))
                second = by_index.get(int(match_span.group("second")))
                if first is None or second is None:
                    problems.append(
                        f"{where}: cites a span between events {match_span.group('first')} and "
                        f"{match_span.group('second')}, which {row.call_ref} does not both have"
                    )
                    continue
                actual = (_stamp(first.ended_at_ms), _stamp(second.started_at_ms))
                if actual != (match_span.group("start"), match_span.group("end")):
                    problems.append(
                        f"{where}: the span it states between events {first.index} and "
                        f"{second.index} is not the call's"
                    )
                continue

            match_gap = _GAP_CLAIM.search(flat)
            if match_gap is not None:
                checked += 1
                gap_first = int(match_gap.group("first"))
                gap_second = int(match_gap.group("second"))
                if gap_first >= gap_second:
                    problems.append(
                        f"{where}: claims a gap between events {gap_first} and {gap_second}, "
                        "which do not run forwards"
                    )
                    continue
                between = [event for event in call.events if gap_first < event.index < gap_second]
                kind = match_gap.group("kind")
                if kind in {"event of any kind", "event"}:
                    if between:
                        problems.append(
                            f"{where}: says no event falls between events {gap_first} and "
                            f"{gap_second}; {len(between)} do"
                        )
                elif kind not in kinds:
                    # An empty comparison reads exactly like a passing one, so a kind the
                    # event model does not have is refused rather than compared.
                    problems.append(
                        f"{where}: a gap claim naming no event kind the model has, so nothing "
                        "could be compared; name a kind from the event model or reword it"
                    )
                else:
                    of_kind = [event for event in between if event.kind.name == kind]
                    if of_kind:
                        problems.append(
                            f"{where}: says no {kind} occurs between events {gap_first} and "
                            f"{gap_second}; event {of_kind[0].index} is one"
                        )
                continue

            match_final = _FINAL_EVENT.search(flat)
            if match_final is not None:
                checked += 1
                if int(match_final.group("ms")) != max(event.ended_at_ms for event in call.events):
                    problems.append(
                        f"{where}: the end it states for the final event is not the call's"
                    )
                continue

            match_quote = _EVENT_QUOTE.match(flat)
            match_plain = _EVENT_PLAIN.match(flat) if match_quote is None else None
            if match_quote is not None:
                index, quoted = int(match_quote.group(1)), match_quote.group("quote")
            elif match_plain is not None:
                index, quoted = int(match_plain.group(1)), match_plain.group("text")
            else:
                prose += 1  # prose about an absence: the reviewer's to judge
                continue

            event = by_index.get(index)
            if event is None:
                problems.append(f"{where}: cites event {index}, which {row.call_ref} lacks")
                continue
            checked += 1
            wanted = _normalize(quoted)
            body = _normalize(event.body)
            # A plain fragment may end in a gloss after an em dash; compare the leading clause.
            if wanted not in body and wanted.split(" — ")[0] not in body:
                problems.append(f"{where}: event {index} does not hold what it quotes")
    return problems, checked, prose


def prose_problems(rows: Sequence[Row], calls: Mapping[str, Call]) -> tuple[list[str], int]:
    """Every event an observation or a consequence cites exists: F-68's class of drift."""
    problems: list[str] = []
    checked = 0
    for row in rows:
        for field in ("observation", "consequence"):
            for match in _PROSE_EVENT.finditer(_normalize(getattr(row, field))):
                call_ref = match.group("call") or row.call_ref
                call = calls.get(call_ref)
                if call is None:
                    if match.group("call"):
                        problems.append(
                            f"{row.id} {field}: cites {call_ref}, which has no transcript"
                        )
                    continue
                indices = {event.index for event in call.events}
                for group in ("first", "second"):
                    raw = match.group(group)
                    if raw is None:
                        continue
                    checked += 1
                    if int(raw) not in indices:
                        problems.append(
                            f"{row.id} {field}: cites {call_ref} event {raw}, which has only "
                            f"events {min(indices)} to {max(indices)}"
                        )
    return problems, checked


def traces_problems(
    document: object, *, finding_ids: Sequence[str], entry_ids: Sequence[str], freeze_sha: str
) -> list[str]:
    """`traces.yaml` against §4; which calls it lists is `coverage_problems`'s to judge.

    It names the freeze commit, keys exactly the frozen rubric's entries, and places every
    finding under at least one entry or in `uncovered`, never both. Placement is judged
    only once both lists can be read, so a missing list is reported once rather than
    again as every finding left unplaced.
    """
    expected = (FREEZE_TAG, "traces", "uncovered", WITHOUT_FINDINGS)
    if not isinstance(document, dict):
        return [f"traces.yaml: expected a mapping of {', '.join(expected)}"]
    problems: list[str] = []
    missing = [key for key in expected if key not in document]
    if missing:
        problems.append(f"traces.yaml: missing {', '.join(missing)}")
    unknown = sorted(str(key) for key in document if key not in expected)
    if unknown:
        problems.append(f"traces.yaml: unknown key(s) {', '.join(unknown)}")
    if FREEZE_TAG in document and document[FREEZE_TAG] != freeze_sha:
        problems.append(
            f"traces.yaml: {FREEZE_TAG} does not name the freeze commit; write its full "
            "40-character SHA, quoted"
        )

    traced: set[str] | None = None
    if "traces" in document:
        traces = document["traces"]
        if isinstance(traces, dict):
            placed: set[str] = set()
            frozen = set(entry_ids)
            absent = [entry for entry in entry_ids if entry not in traces]
            if absent:
                problems.append(
                    f"traces.yaml: {len(absent)} entries of the rubric at the freeze commit are "
                    f"absent: {', '.join(absent)}"
                )
            extra = sorted(str(key) for key in traces if key not in frozen)
            if extra:
                problems.append(
                    f"traces.yaml: {len(extra)} keys are not entries of the rubric at the freeze "
                    f"commit: {', '.join(extra)}"
                )
            for entry, listed in traces.items():
                if not _id_list(listed):
                    problems.append(
                        f"traces.yaml: {entry} must hold a list of finding ids; write [] for none"
                    )
                    continue
                if len(set(listed)) != len(listed):
                    problems.append(f"traces.yaml: {entry} lists a finding more than once")
                placed.update(listed)
            traced = placed
        else:
            problems.append(
                "traces.yaml: traces must map each rubric entry id to a list of finding ids"
            )

    uncovered: set[str] | None = None
    if "uncovered" in document:
        listed = document["uncovered"]
        if _id_list(listed):
            uncovered = set(listed)
            if len(uncovered) != len(listed):
                problems.append("traces.yaml: uncovered lists a finding more than once")
        else:
            problems.append(
                "traces.yaml: uncovered must be a list of finding ids; write [] for none"
            )

    if WITHOUT_FINDINGS in document:
        calls = document[WITHOUT_FINDINGS]
        if not _id_list(calls):
            problems.append(
                f"traces.yaml: {WITHOUT_FINDINGS} must be a list of call ids; write [] for none"
            )
        elif len(set(calls)) != len(calls):
            problems.append(f"traces.yaml: {WITHOUT_FINDINGS} lists a call more than once")

    known = set(finding_ids)
    strangers = ((traced or set()) | (uncovered or set())) - known
    if strangers:
        shown = sorted((item for item in strangers if HELDOUT_ID.match(item)), key=id_order)
        problems.append(
            f"traces.yaml: {len(strangers)} listed ids are not findings"
            + (f": {', '.join(shown)}" if shown else "")
        )
    if traced is not None and uncovered is not None:
        both = sorted(traced & uncovered & known, key=id_order)
        if both:
            problems.append(
                f"traces.yaml: {len(both)} findings are under an entry and in uncovered: "
                f"{', '.join(both)}"
            )
        nowhere = sorted(known - traced - uncovered, key=id_order)
        if nowhere:
            problems.append(
                f"traces.yaml: {len(nowhere)} findings are placed nowhere: {', '.join(nowhere)}"
            )
    return problems


def calls_without_findings(document: object) -> set[str] | None:
    """The calls `traces.yaml` declares to have no finding, or None if that list is unreadable.

    None rather than an empty set, so a missing or malformed list is reported once, by
    `traces_problems`, and not again as every unreferenced call.
    """
    listed = document.get(WITHOUT_FINDINGS) if isinstance(document, dict) else None
    return set(listed) if _id_list(listed) else None


# --------------------------------------------------------------------------
# Running it
# --------------------------------------------------------------------------


def validate(
    stage: str, *, harness: Path, freeze_sha: str, labels: Path, transcripts: Path
) -> tuple[list[str], str]:
    """Every problem in `stage`'s documents under `labels`, and a count of what was checked."""
    import yaml

    if str(harness / "src") not in sys.path:
        sys.path.insert(0, str(harness / "src"))
    name = "drafts.yaml" if stage == "drafts" else "findings.yaml"
    path = labels / name
    if not path.is_file():
        return [f"{name} does not exist under {labels}"], ""
    text = path.read_text(encoding="utf-8")
    rows, problems = parse_drafts(text) if stage == "drafts" else parse_findings_document(text)
    if problems:
        return problems, ""

    heldout = heldout_calls(harness)
    calls = {Path(call.source_path).stem: call for call in load_calls(transcripts, harness)}
    problems += identity_problems(
        rows, heldout=heldout, transcribed=calls, design=design_finding_ids(harness)
    )
    evidence, checked, prose = evidence_problems(rows, calls)
    problems += evidence
    if checked == 0:
        problems.append(
            f"{name}: no evidence fragment could be checked, so nothing was compared; every "
            "fragment reads as prose about an absence"
        )
    citations, cited = prose_problems(rows, calls)
    problems += citations

    noun = "drafts" if stage == "drafts" else "findings"
    summary = (
        f"{len(rows)} {noun} over {len({row.call_ref for row in rows})} calls; {checked} evidence "
        f"fragments checked, {prose} left to the reviewer as prose; {cited} event citations in "
        "prose checked"
    )
    if stage != "all":
        return problems, summary

    traces_path = labels / "traces.yaml"
    if not traces_path.is_file():
        return [*problems, f"traces.yaml does not exist under {labels}"], summary
    entries = rubric_entry_ids(harness, freeze_sha)
    if entries is None:
        return [*problems, f"rubric.yaml cannot be read at the freeze commit {freeze_sha}"], summary
    try:
        document = yaml.safe_load(traces_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [*problems, yaml_problem("traces.yaml", error)], summary
    problems += traces_problems(
        document, finding_ids=[row.id for row in rows], entry_ids=entries, freeze_sha=freeze_sha
    )
    declared = calls_without_findings(document)
    if declared is not None:
        problems += coverage_problems(rows, heldout, declared)
    return problems, (
        f"{summary}; traces place every finding against {len(entries)} frozen entries, and every "
        "held-out call is referenced or declared without findings"
    )


def check(
    stage: str, *, harness: Path, labels: Path = LABELS, transcripts: Path = TRANSCRIPTS
) -> int:
    """Validate `stage` and report, or refuse before the freeze. Exit 0 only when valid."""
    sha = freeze_commit(harness)
    if sha is None:
        print(
            f"error: {FREEZE_TAG} does not resolve in {harness}. Held-out labels exist only after "
            "the freeze (D21), so there is nothing to validate. If the tag exists on GitHub, "
            "fetch tags into that checkout and run this again.",
            file=sys.stderr,
        )
        return 1

    problems, summary = validate(
        stage, harness=harness, freeze_sha=sha, labels=labels, transcripts=transcripts
    )
    if problems:
        print(f"{stage}: {len(problems)} problem(s) under {FREEZE_TAG} {sha[:12]}", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"{stage}: valid under {FREEZE_TAG} {sha[:12]}. {summary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the held-out labels in private/labels/.")
    parser.add_argument(
        "stage",
        nargs="?",
        choices=STAGES,
        default="all",
        help="drafts, findings, or all: findings and traces together (the default)",
    )
    args = parser.parse_args(argv)

    harness = harness_root()
    if harness is None:
        print(
            "error: the harness was not found, and it holds the loader, the parser, the frozen "
            "rubric and the freeze tag.\n"
            "Set HARNESS_ROOT, check it out to .harness, or clone it alongside this one.",
            file=sys.stderr,
        )
        return 1
    return check(args.stage, harness=harness)


if __name__ == "__main__":
    raise SystemExit(main())
