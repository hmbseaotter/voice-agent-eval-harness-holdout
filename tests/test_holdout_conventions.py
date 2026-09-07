"""The two conventions the harness enforces that this repository could not.

`HOLDOUT-REPAIR-BRIEF.md` states the case plainly: the harness's
`tests/test_corpus_hygiene.py` globs `corpus/transcripts/`, which holds design
calls only, so neither of the checks below had ever run against this tree. Both
conventions were settled on 2026-09-01 and the five transcripts here at the time
were authored before that, so for five days the rules existed and nothing
compared them against these files. The brief's own sentence is the reason this
file exists: *a repair with no check behind it is the state that produced this
brief.*

The set has since grown to six. Everything below globs the directory rather than
naming members, so a transcript added later is covered the moment it lands
instead of when someone remembers to widen a list.

**This is a port, and a port is two things that can disagree.** `_sourced_by`
below is copied from `test_corpus_hygiene.py` rather than imported, because it
is a private helper in that repository's test tree and a test module is not an
importable interface. That duplication is the weakness of this file and it is
better stated than hidden: if the rule changes there and not here, this suite
goes green against a stale convention -- which is the shape of failure the
obligations file was written to catch in the first place. The fix, if anyone
wants it, is for `_sourced_by` to move into the `harness` package so both
repositories import one implementation and this file deletes its copy.

**The harness is a separate repository, and both checks need it** -- one for the
parser, the other for `corpus/policies/`. When it is absent the tests skip with
a message naming what did not run, matching the shape `.github/workflows/
checks.yml` already uses for its parse step. A held-out set that could not be
validated without a second repository being public would be a worse trade.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import itertools
import os
import re
import shutil
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # pragma: no cover - types only, and the harness may be absent
    # Annotations only. A runtime import would break collection wherever the
    # harness is not checked out, which is the state every skip in this file
    # exists for -- and the copy of `_sourced_by` below dropped its parameter
    # annotations for exactly that reason, which is what made it fail the
    # harness's own strict type check while claiming to be verbatim.
    from harness.core.events import Call, ToolCallEvent

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
TRANSCRIPTS: Path = REPO_ROOT / "transcripts"


def _harness_root() -> Path | None:
    """Where the harness repository is, or None.

    Three places, in order of explicitness: an environment variable, the
    `.harness` path the workflow checks it out to, and the sibling directory a
    working copy has. The prefix-matched repository names make the third case
    the ordinary one on a developer machine.
    """
    candidates = [
        Path(value) if (value := os.environ.get("HARNESS_ROOT")) else None,
        REPO_ROOT / ".harness",
        REPO_ROOT.parent / "voice-agent-eval-harness",
    ]
    for candidate in candidates:
        if candidate is not None and (candidate / "corpus" / "policies").is_dir():
            return candidate
    return None


HARNESS: Final[Path | None] = _harness_root()

if HARNESS is not None:  # pragma: no cover - import plumbing
    with contextlib.suppress(ImportError):
        import harness  # noqa: F401
    if "harness" not in sys.modules:
        sys.path.insert(0, str(HARNESS / "src"))

requires_harness = pytest.mark.skipif(
    HARNESS is None,
    reason=(
        "the harness repository was not found, so the provenance and clause-count "
        "checks did not run; set HARNESS_ROOT, check it out to .harness, or clone "
        "it alongside this one"
    ),
)


def _transcripts() -> list[Path]:
    found = sorted(TRANSCRIPTS.glob("CALL-*.txt"))
    assert found, f"no transcripts under {TRANSCRIPTS}"
    return found


# --------------------------------------------------------------------------
# Provenance: no value enters a call from nowhere
# --------------------------------------------------------------------------

#: Tool-call arguments allowed to have no source inside the call, each with its
#: reason. Kept identical to the harness's list on purpose: a held-out set with
#: a laxer exception list than the design set is exactly the silent divergence
#: `HOLDOUT-OBLIGATIONS.md` exists to prevent.
_UNSOURCED_ARGUMENTS_ALLOWED: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "fetch_policy",
        "document",
        "the document's name is part of the tool's contract, the way the tool's "
        "own name is: an agent that can call fetch_policy knows Verso has a "
        "refund policy called refund.v1. What it cannot know without reading "
        "the document is which clause answers a question -- which is why the "
        "clause argument was removed (event-model.md 3.5) rather than declared "
        "here.",
    ),
)


def _sourced_by(call: Call, event: ToolCallEvent, value: str) -> str | None:
    """Where a tool-call argument's value came from, or None.

    Only earlier events count. A value first seen in the result of the call
    that used it has not been sourced -- it has been asserted and then
    confirmed, which is the shape this check exists to reject.

    Copied verbatim from the harness's `test_corpus_hygiene.py`. See this
    module's docstring on why that duplication is a known weakness.
    """
    from harness.core.events import SpeechEvent

    wanted = " ".join(value.split()).lower()
    if not wanted:
        return "empty"

    context = {" ".join(str(v).split()).lower() for _, v in call.context}
    # Exact, or a fragment of a LONGER context value: production="The Halloway
    # Ensemble" sits inside event_title. The reverse direction is not accepted --
    # it matched clause="2.2" against ticket_count=2 and hid five real cases.
    if any(wanted == c or (len(wanted) >= 4 and wanted in c) for c in context if c):
        return "context"

    record = {
        " ".join(str(getattr(call.record, f)).split()).lower()
        for f in dir(call.record)
        if not f.startswith("_") and getattr(call.record, f) is not None
    }
    if wanted in record:
        return "record"

    earlier = [e for e in call.events if e.index < event.index]
    speech = " ".join(
        " ".join(e.body.split()).lower() for e in earlier if isinstance(e, SpeechEvent)
    )
    if len(wanted) >= 3 and wanted in speech:
        return "speech"
    prior = " ".join(
        " ".join(e.body.split()).lower() for e in earlier if not isinstance(e, SpeechEvent)
    )
    if len(wanted) >= 3 and wanted in prior:
        return "prior result"

    # An amount the agent computed from values it was given.
    try:
        target = Decimal(wanted.replace(",", "").replace("$", ""))
    except InvalidOperation:
        return None  # not a number, so no arithmetic source is possible
    numbers = []
    for _, raw in call.context:
        # Most context values are not numbers; those simply cannot be an
        # arithmetic source, so skipping them is the whole handling.
        with contextlib.suppress(InvalidOperation):
            numbers.append(Decimal(str(raw).replace(",", "").replace("$", "")))
    for size in (1, 2, 3):
        if any(sum(combo) == target for combo in itertools.combinations(numbers, size)):
            return "arithmetic over context"
    return None


@requires_harness
def test_no_tool_call_argument_appears_from_nowhere() -> None:
    """Every value the agent passes to a tool must have a source in the call.

    D64's rule, ported. `_sourced_by` looks in exactly five places -- a context
    value, a field of the call record, earlier caller or agent speech, an
    earlier tool result, or arithmetic over context values -- and returns the
    one it found. Where it finds none, the agent has asserted a value rather
    than obtained one, and a transcript where that passes unremarked teaches a
    judge that an identifier arriving from nowhere is ordinary.

    Only earlier events count, and `_sourced_by`'s own docstring gives the
    reason: a value first seen in the *result* of the call that used it has not
    been sourced, it has been asserted and then confirmed.

    **What is examined, and therefore what is not.** The pattern reads quoted
    arguments, `name="value"`, so an unquoted argument is not examined at all.
    That is narrower than the rule this docstring opens with, and it is written
    down here rather than left for a reader to infer from the regex.

    **The floor is not decoration.** A parser change, or an argument syntax that
    stopped matching, would leave this loop iterating over nothing and reporting
    no problems. An empty comparison reads exactly like a passing one, so the
    check asserts that it examined something before it asserts that what it
    examined was clean.

    **Two rules govern the exception list, and each is enforced separately.**
    Every entry in `_UNSOURCED_ARGUMENTS_ALLOWED` carries a reason, and this
    test asserts the reason is non-empty, because an exemption nobody has to
    justify is one that grows. A sibling,
    `test_the_provenance_exceptions_are_all_still_used`, fails when an entry
    stops matching anything, because an exception nobody needs is an exception
    nobody rechecks (D64).

    `_sourced_by` is a copy rather than an import, since it is a private helper
    inside the harness's own test tree. The copy is held to the original by
    `test_the_copied_provenance_helper_is_the_same_code_as_the_harness_one`,
    which compares the two as abstract syntax trees -- comparing text would fail
    on formatting, and comparing behaviour would need inputs neither repository
    can share.

    **This docstring was rewritten on 2026-09-07 and its predecessor was not
    read.** An audit found held-out content living in it -- an account of what a
    repair had found -- outside `transcripts/`, where the read prohibition did
    not reach. The replacement was composed from this function's own body and
    from rules already published in the harness, so that removing the content
    did not require anybody to read it.
    """
    from harness.core.events import ToolCallEvent
    from harness.corpus.text_adapter import parse_call

    allowed = {(tool, arg) for tool, arg, _ in _UNSOURCED_ARGUMENTS_ALLOWED}
    for tool, arg, reason in _UNSOURCED_ARGUMENTS_ALLOWED:
        assert reason.strip(), f"{tool}({arg}) is excepted with no reason given"

    problems: list[str] = []
    checked = 0
    for transcript in _transcripts():
        call = parse_call(transcript)
        for event in call.events:
            if not isinstance(event, ToolCallEvent):
                continue
            for name, raw in re.findall(r'(\w+)="([^"]*)"', event.arguments or ""):
                if (event.name, name) in allowed:
                    continue
                checked += 1
                if _sourced_by(call, event, raw) is None:
                    problems.append(
                        f"{call.record.call_id} event {event.index}: "
                        f"{event.name}({name}={raw!r}) has no source in the call"
                    )

    assert checked, "no tool-call arguments were checked; the parser or the regex has drifted"
    assert not problems, "tool-call arguments with no origin in their own call:\n  " + "\n  ".join(
        problems
    )


@requires_harness
def test_the_provenance_exceptions_are_all_still_used() -> None:
    """An exception nobody needs is an exception nobody rechecks.

    Scoped to this tree, so it asks a different question than its counterpart in
    the harness: whether the *held-out* set still passes the excepted argument.
    If a future edit removes the last `fetch_policy` call from these five, the
    exception stops being load-bearing here and should be reconsidered rather
    than inherited.
    """
    from harness.core.events import ToolCallEvent
    from harness.corpus.text_adapter import parse_call

    used = {
        (event.name, name)
        for transcript in _transcripts()
        for event in parse_call(transcript).events
        if isinstance(event, ToolCallEvent)
        for name, _ in re.findall(r'(\w+)="([^"]*)"', event.arguments or "")
    }
    for tool, arg, _ in _UNSOURCED_ARGUMENTS_ALLOWED:
        assert (tool, arg) in used, (
            f"{tool}({arg}) is declared as an allowed unsourced argument and no "
            "held-out transcript passes it; the exception is stale here"
        )


# --------------------------------------------------------------------------
# Policy retrieval returns a document, and says how big it was
# --------------------------------------------------------------------------


@requires_harness
def test_every_policy_retrieval_states_the_document_s_real_clause_count() -> None:
    """`fetch_policy` returns a document and the result says how many clauses it
    returned. That number is comparable against the harness's
    `corpus/policies/`, so it should be compared.

    Three of these five carried the retired `fetch_policy(document=..., clause=...)`
    shape with a result that named neither the document nor a count, which is
    unfalsifiable by construction: there is no number in it to be wrong. The
    repaired form states a count, and a count is checkable.
    """
    from harness.core.events import ToolResultEvent
    from harness.corpus.text_adapter import parse_call

    assert HARNESS is not None  # narrowed by the skipif marker
    policies = HARNESS / "corpus" / "policies"
    counts = {
        document.stem: len(
            re.findall(r"^\*\*(\d+\.\d+)\*\*", document.read_text(encoding="utf-8"), re.MULTILINE)
        )
        for document in sorted(policies.glob("*.md"))
    }
    assert counts and all(counts.values()), f"no clauses parsed out of {sorted(counts)}"

    stated = re.compile(r"(?P<document>[\w.]+) returned; (?P<count>\d+) clauses")
    checked = 0
    for transcript in _transcripts():
        call = parse_call(transcript)
        for event in call.events:
            if not isinstance(event, ToolResultEvent):
                continue
            match = stated.search(" ".join(event.body.split()))
            if match is None:
                continue
            checked += 1
            document = match.group("document")
            assert document in counts, (
                f"{call.record.call_id} event {event.index} names {document!r}, which is "
                f"not a document in the harness's corpus/policies/ ({sorted(counts)})"
            )
            assert int(match.group("count")) == counts[document], (
                f"{call.record.call_id} event {event.index} says {document} returned "
                f"{match.group('count')} clauses; the document has {counts[document]}"
            )
    assert checked, "no policy retrieval stated a clause count; the format has drifted"


@requires_harness
def test_no_policy_retrieval_still_takes_a_clause() -> None:
    """The retired signature must not come back.

    The clause-count check above is silent about a `fetch_policy` call that
    passes a clause and returns the old `:: clause returned` detail, because
    such a result states no count for it to compare. So the count check would
    have passed on this set unchanged, on all five, while three transcripts
    carried the very defect it was ported to catch. A check that cannot fail on
    the thing it is named for needs the companion that can.
    """
    from harness.core.events import ToolCallEvent
    from harness.corpus.text_adapter import parse_call

    offenders = [
        f"{call.record.call_id} event {event.index}: {event.name}({event.arguments})"
        for transcript in _transcripts()
        for call in [parse_call(transcript)]
        for event in call.events
        if isinstance(event, ToolCallEvent)
        and event.name == "fetch_policy"
        and "clause=" in (event.arguments or "")
    ]
    assert not offenders, (
        "fetch_policy takes a document and no clause (event-model.md 3.5):\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------
# One event id means one event
# --------------------------------------------------------------------------

#: Context fields that describe the *event* rather than the booking, and so must
#: agree wherever the same `event_id` appears. Deliberately not every shared
#: field: `ticket_count`, `booking_reference` and the rest belong to one
#: caller's purchase and are expected to differ between two calls about the same
#: show.
_EVENT_SCOPED_FIELDS: Final[tuple[str, ...]] = ("event_title", "door_time")


@requires_harness
def test_one_event_id_means_one_event() -> None:
    """Two calls naming the same `event_id` must agree about that event.

    One identifier means one performance, so the fields describing the *event*
    rather than the booking must match wherever the identifier is reused.
    `_EVENT_SCOPED_FIELDS` is deliberately not every shared field:
    `ticket_count`, `booking_reference` and the rest belong to one caller's
    purchase, and two callers holding seats to one show are expected to differ
    on them.

    **`door_time` is the field that most needed including.** Deadlines in the
    policy set are measured against it -- in the design set, `exchange.v1` 2.1
    closes the exchange window 48 hours before the doors open -- so an agent
    reasoning about a window against the wrong door time reasons correctly to a
    wrong answer, and the transcript reads as though the agent erred.

    **A titles-only guard would have passed here, which is why this one
    exists.** D85 is the record: two calls in this set shared an `event_id` and
    an `event_title` and disagreed about `door_time`, so a check comparing names
    ran, compared, and reported nothing on exactly the transcripts carrying the
    contradiction.

    **The widening started here and reached the harness afterwards.** D85
    widened this port first, because the contradiction surfaced in this set;
    `tests/test_corpus_hygiene.py::test_one_event_id_means_one_event` was added
    to the harness later, when the same undeclared drift was found in the design
    corpus. The harness keeps
    `test_one_event_title_per_event_id_except_where_drift_is_seeded` alongside
    it -- a separate guard over names, not a superseded one.

    **No seeded-drift exemption here, deliberately.** The harness's version
    carries one because naming drift is a seeded defect class in the *design*
    set. A transcript here that needs an exemption should get one added
    explicitly, with its reason, rather than inheriting a hole sized for another
    corpus.

    **The floor is an aggregate, and that is a known weakness.** Two sets this
    size may legitimately share no identifier at all, in which case this
    compares nothing -- and silence should not read as agreement, so it says so
    rather than passing quietly. But it counts comparisons across every field in
    `_EVENT_SCOPED_FIELDS` together: were `door_time` to stop being compared
    while `event_title` still was, the total would stay non-zero and this would
    stay green. The harness's counterpart asserts a **per-field** minimum for
    that reason (D74). Narrowing this one to match is worth doing, and is not
    done here.

    **This docstring was rewritten on 2026-09-07 and its predecessor was not
    read.** An audit found held-out content living in it -- an account of a
    contradiction this check was written after -- outside `transcripts/`, where
    the read prohibition did not reach. The replacement was composed from this
    function's own body and from rules already published in the harness, so that
    removing the content did not require anybody to read it.
    """
    from harness.corpus.text_adapter import parse_call

    seen: dict[tuple[str, str], dict[str, str]] = {}
    problems: list[str] = []
    compared = 0
    for transcript in _transcripts():
        call = parse_call(transcript)
        context = dict(call.context)
        event_id = context.get("event_id")
        if not event_id:
            continue
        for field in _EVENT_SCOPED_FIELDS:
            value = context.get(field)
            if value is None:
                continue
            previous = seen.setdefault((event_id, field), {})
            for other_call, other_value in previous.items():
                compared += 1
                if other_value != value:
                    problems.append(
                        f"{event_id} has {field}={value!r} in {call.record.call_id} "
                        f"and {other_value!r} in {other_call}"
                    )
            previous[call.record.call_id] = value

    assert compared, (
        "no two transcripts share an event id, so this check compared nothing. That is a "
        "legitimate state for a set this small -- but it means a contradiction could not "
        "be detected, and silence should not read as agreement."
    )
    assert not problems, "one event id, two events:\n  " + "\n  ".join(problems)


@requires_harness
def test_a_call_naming_an_event_also_identifies_it() -> None:
    """Without this, the check above silently skips a call.

    Ported from the harness, where its docstring records why it exists: a call
    once named its event non-canonically *and* declared no `event_id`, so the
    check keyed to `event_id` never looked at it. A guard narrower than the rule
    it enforces is green and blind.
    """
    from harness.corpus.text_adapter import parse_call

    for transcript in _transcripts():
        call = parse_call(transcript)
        names = {name for name, _ in call.context}
        if "event_title" in names:
            assert "event_id" in names, (
                f"{call.record.call_id} names an event without identifying it"
            )


# --------------------------------------------------------------------------
# One event id names one event, across BOTH corpora
# --------------------------------------------------------------------------
#
# `test_one_event_id_means_one_event` above compares this set to itself, and the
# harness's `test_one_event_id_means_one_event` compares the design set to
# itself. **Neither looks across the boundary**, and the two sets draw
# identifiers from one `EV-#####` space: D85 allocated a new id here, and the
# harness allocated `EV-88214` there, each without being able to see the other.
# A collision would put two calls on one event with different door times, which
# is the defect D85 and D87 each spent an entry repairing on their own side.
#
# This is the only place the comparison can be made, which is what
# `HOLDOUT-OBLIGATIONS.md` O-4 says: the workflow already checks the harness out
# at `.harness/`, and nothing in the harness can ever see this directory.

_EVENT_SCOPED_ACROSS_CORPORA: Final[tuple[str, ...]] = ("event_title", "door_time")


def _context_events(transcripts: list[Path]) -> dict[str, dict[str, dict[str, str]]]:
    """`{event_id: {call_id: {field: value}}}` over the event-scoped fields."""
    from harness.corpus.text_adapter import parse_call

    found: dict[str, dict[str, dict[str, str]]] = {}
    for transcript in transcripts:
        call = parse_call(transcript)
        context = dict(call.context)
        event_id = context.get("event_id")
        if not event_id:
            continue
        fields = {
            field: context[field] for field in _EVENT_SCOPED_ACROSS_CORPORA if field in context
        }
        found.setdefault(event_id, {})[call.record.call_id] = fields
    return found


def _cross_corpus_disagreements(
    here: dict[str, dict[str, dict[str, str]]],
    there: dict[str, dict[str, dict[str, str]]],
) -> list[str]:
    """Event ids both corpora name, where an event-scoped field differs.

    Separated from its test so the control can drive it with records it built,
    rather than with transcripts. A check whose only evidence is that it has
    never fired has been proven against nothing -- and the plant for this one
    **cannot** come from a transcript, because building it would mean editing a
    held-out file to make it wrong.
    """
    problems: list[str] = []
    for event_id in sorted(set(here) & set(there)):
        for held_out_call, held_out_fields in sorted(here[event_id].items()):
            for design_call, design_fields in sorted(there[event_id].items()):
                for field in _EVENT_SCOPED_ACROSS_CORPORA:
                    mine, theirs = held_out_fields.get(field), design_fields.get(field)
                    if mine is not None and theirs is not None and mine != theirs:
                        problems.append(
                            f"{event_id}: {field} is {mine!r} in {held_out_call} and "
                            f"{theirs!r} in the design set's {design_call}"
                        )
    return problems


@requires_harness
def test_no_event_id_names_two_different_events_across_the_two_corpora() -> None:
    """An event id means one performance in both repositories or in neither.

    Discharges `HOLDOUT-OBLIGATIONS.md` O-4. The obligation exists because the
    two sets share one identifier space and each side allocated into it while
    unable to read the other: this set gained an id at D85, the design set
    gained `EV-88214` at D87, and no check anywhere compared them.

    **A disjoint id set is a pass, not a gap.** The two corpora need not share
    any event, and the expected state today is that they share none. So there is
    no comparison floor here -- a floor would fail on the correct outcome. What
    is asserted instead is that both sides were actually *read*, because the
    failure worth guarding is "this compared nothing because it loaded nothing",
    not "these sets are disjoint".
    """
    assert HARNESS is not None
    design = sorted((HARNESS / "corpus" / "transcripts").glob("CALL-*.txt"))
    assert design, f"no design transcripts under {HARNESS / 'corpus' / 'transcripts'}"

    here = _context_events(_transcripts())
    there = _context_events(design)
    assert here, "no held-out transcript declares an event_id, so this compared nothing"
    assert there, "no design transcript declares an event_id, so this compared nothing"

    problems = _cross_corpus_disagreements(here, there)
    assert not problems, (
        "one event id, two events, across the two corpora. Either this set and the design "
        "set disagree about a performance both name, or an identifier was allocated twice "
        "for two different shows:\n  " + "\n  ".join(problems)
    )


# --------------------------------------------------------------------------
# The escalation convention, which the register states and only this suite can
# check here
# --------------------------------------------------------------------------

#: The three fields a call handed to a human sets, for a handoff that succeeded.
#: Kept identical to the harness's `ESCALATION_RECORD` on purpose, and for the
#: same reason the unsourced-argument list is: a held-out set holding a laxer
#: convention than the design set is the silent divergence the obligations file
#: exists to prevent. The rule itself is stated in `corpus/entities.md`, which
#: this repository's authoring packet carries.
_ESCALATION_RECORD: Final[dict[str, str]] = {
    "disconnection_reason": "transferred",
    "outcome": "resolved",
    "outcome_reason": "escalated",
}


def _call_records() -> dict[str, dict[str, str]]:
    from harness.corpus.text_adapter import parse_call

    return {
        call.record.call_id: {
            "disconnection_reason": call.record.disconnection_reason.value,
            "outcome": call.record.outcome.value,
            "outcome_reason": call.record.outcome_reason,
        }
        for call in (parse_call(transcript) for transcript in _transcripts())
    }


def _escalated(records: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Calls filed as an escalation, by `outcome_reason`."""
    return {
        call_id: fields
        for call_id, fields in records.items()
        if fields["outcome_reason"] == _ESCALATION_RECORD["outcome_reason"]
    }


def _non_conforming_escalations(records: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Escalated calls whose three fields are not the convention.

    Separated so the control drives this rather than restating it. The first
    draft of that control compared two dictionaries it had just built and could
    not fail -- the fourth time in this run of work that the first thing written
    was an assertion incapable of failing.
    """
    return {
        call_id: fields
        for call_id, fields in _escalated(records).items()
        if fields != _ESCALATION_RECORD
    }


@requires_harness
def test_an_escalated_call_records_the_escalation_convention() -> None:
    """`outcome_reason: escalated` fixes the other two fields.

    Discharges `HOLDOUT-OBLIGATIONS.md` O-5. The convention was settled at D73
    and lived only in `corpus/seeding-manifest.md` -- a design-set artifact a
    curated authoring packet deliberately does not carry -- so an authoring
    session here received the vocabulary without the rule and set the field
    wrongly. D86 records that the author did not err and the register did not
    say. The register says now, and this is what holds it on this side.

    **The floor is a rule, not content.** That this set contains an escalation
    is recorded publicly in the harness's own decision record (D83 decided to
    seed one; D86 accepted it), so asserting at least one is a count of the kind
    this project already publishes, not a fact about any transcript.
    """
    records = _call_records()
    escalated = _escalated(records)
    assert escalated, (
        "no call here is filed as an escalation, so this check compared nothing. D83 "
        "decided to seed one and D86 accepted it -- if that call has been removed, this "
        "check and the reach statement it supports both need revisiting"
    )
    wrong = _non_conforming_escalations(records)
    assert not wrong, (
        f"a call filed as an escalation does not carry the convention {_ESCALATION_RECORD}. "
        "See the escalation passage in the entity canon:\n  "
        + "\n  ".join(f"{call_id}: {fields}" for call_id, fields in sorted(wrong.items()))
    )


@requires_harness
def test_no_call_files_its_outcome_as_transferred() -> None:
    """`Outcome.transferred` is declared, accepted by the parser, and never used.

    The other half of O-5, and the half that actually went wrong once. The token
    is in the closed vocabulary because real platforms emit it and an adapter
    has to receive what vendors send (D39), not because a call should carry it:
    `disconnection_reason` already records how a call ended, so `outcome:
    transferred` straddles the two axes those fields exist to separate.
    """
    offenders = sorted(
        call_id for call_id, fields in _call_records().items() if fields["outcome"] == "transferred"
    )
    assert not offenders, (
        f"{offenders} file outcome as transferred. outcome records whether the caller's "
        "need was met and disconnection_reason records how the call ended; a successful "
        "handoff is resolved and a failed one unresolved"
    )


# --------------------------------------------------------------------------
# The packet's redactions, against the documents they redact
# --------------------------------------------------------------------------


def _stale_redactions(
    exact: list[tuple[str, str]],
    patterns: list[tuple[re.Pattern[str], str]],
    documents: dict[str, str],
) -> list[str]:
    """Redactions with no subject left in the documents they redact."""
    stale: list[str] = []
    for old, _ in exact:
        if not any(old in text for text in documents.values()):
            stale.append(f"exact string, matches nothing: {old[:70]!r}...")
    for pattern, _ in patterns:
        if not any(pattern.search(text) for text in documents.values()):
            stale.append(f"pattern, matches nothing: {pattern.pattern[:70]!r}")
    return stale


@requires_harness
def test_every_redaction_still_matches_the_harness() -> None:
    """A redaction that matches nothing is a redaction that redacts nothing.

    Discharges `HOLDOUT-OBLIGATIONS.md` O-6. `tools/build_authoring_packet.py`
    says it in its own docstring -- *"two of the five original patterns had
    already gone stale within a day, because the register was edited twice for
    unrelated reasons"* -- and its answer is that the leak scan is the gate. It
    is a good gate and it fires at **build** time, which means a stale pattern
    is discovered by whoever is trying to assemble a packet, under time
    pressure, rather than by the commit that staled it.

    This is the earlier signal. It asserts nothing about safety -- the scan
    remains the guarantee -- only that every pattern still has a subject. When
    the harness rewrote the `matched_by` sentence at D89 the exact-string
    pattern stopped matching, and nothing said so until a person went looking.
    """
    assert HARNESS is not None
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from build_authoring_packet import LINE_REDACTIONS, REDACTIONS

    documents = {
        "specs/event-model.md": (HARNESS / "specs" / "event-model.md").read_text(encoding="utf-8"),
        "corpus/entities.md": (HARNESS / "corpus" / "entities.md").read_text(encoding="utf-8"),
    }
    assert all(documents.values()), "a redacted source document is empty"

    assert REDACTIONS and LINE_REDACTIONS, "the redaction lists are empty"
    stale = _stale_redactions(REDACTIONS, LINE_REDACTIONS, documents)
    assert not stale, (
        "a redaction in the packet builder no longer matches the document it redacts. The "
        "leak scan would still stop a leaking packet, at build time -- this is the earlier "
        "warning. Re-target the pattern against the harness's current text:\n  "
        + "\n  ".join(stale)
    )


# --------------------------------------------------------------------------
# The controls, all three planted synthetically
# --------------------------------------------------------------------------
#
# None of these mutates a transcript. Every other control in this project plants
# its defect in a copy of the artefact under test, and that route is closed
# here: editing a held-out file to make it wrong means opening it, and the
# session that discharged these obligations is barred from doing so. So each
# comparison was lifted into a function that takes records, and the plants are
# records. The trade is stated rather than hidden -- these prove the comparison
# logic rejects the defect, not that it would find it in a real file. The
# passing run against the real six is what covers the second half.


def test_the_cross_corpus_check_fires_on_an_event_id_that_means_two_events() -> None:
    """O-4's control: one id, two door times, one on each side."""
    here = {"EV-00001": {"CALL-XX": {"event_title": "A Show", "door_time": "2027-01-01T19:00:00Z"}}}
    there = {
        "EV-00001": {"CALL-YY": {"event_title": "A Show", "door_time": "2027-01-08T19:00:00Z"}}
    }

    problems = _cross_corpus_disagreements(here, there)
    assert problems and "door_time" in problems[0], (
        "two calls naming one event id a week apart were not reported"
    )
    assert not _cross_corpus_disagreements(here, here), (
        "agreeing records were reported as a disagreement, so the check fires on "
        "sharing an id rather than on disagreeing about the event"
    )
    assert not _cross_corpus_disagreements(here, {"EV-00002": there["EV-00001"]}), (
        "disjoint id sets were reported, and a disjoint set is the expected state"
    )


def test_the_escalation_check_fires_on_the_field_that_was_got_wrong() -> None:
    """O-5's control, planting D86's actual defect: `outcome: transferred`.

    Driven through `_non_conforming_escalations`, the function the check itself
    calls, so this fails if that logic stops rejecting the defect. A control
    that restates the comparison proves the restatement.
    """
    conforming = {"CALL-XX": dict(_ESCALATION_RECORD)}
    planted = {"CALL-XX": dict(_ESCALATION_RECORD, outcome="transferred")}

    assert not _non_conforming_escalations(conforming), (
        "a record that is the convention was reported as non-conforming"
    )
    assert _non_conforming_escalations(planted) == planted, (
        "outcome: transferred under outcome_reason: escalated was not rejected -- "
        "this is the exact field D86 records being authored wrongly and returned"
    )
    not_an_escalation = {"CALL-YY": dict(_ESCALATION_RECORD, outcome_reason="refund_issued")}
    assert _escalated(not_an_escalation) == {}, (
        "a call that is not an escalation was picked up, so the check would hold "
        "every call to the escalation convention"
    )


def test_the_redaction_check_fires_on_a_pattern_that_matches_nothing() -> None:
    """O-6's control, driven through `_stale_redactions`.

    The plant is the sentence that actually went stale: the register's old
    `caller_ani` count, which the harness rewrote at D89 and which the packet
    builder's pattern went on naming afterwards.
    """
    documents = {"stand-in": "Every design call is matched on `caller_ani` except one."}
    went_stale = "Thirteen design calls carry `caller_ani`"

    assert _stale_redactions([(went_stale, "")], [], documents) != [], (
        "the sentence D89 rewrote was not reported as a stale redaction"
    )
    assert _stale_redactions([("is matched on `caller_ani`", "")], [], documents) == [], (
        "a redaction that does still match was reported as stale"
    )
    assert _stale_redactions([], [(re.compile(r"nothing here"), "")], documents) != [], (
        "a regex redaction matching nothing was not reported"
    )


#: Copied from the harness's `tests/test_speech_plausibility.py`, and asserted
#: against it below rather than trusted. D48 set the band deliberately wider
#: than conversation occupies.
_SLOWEST_PLAUSIBLE_WPM: Final[float] = 110.0
_FASTEST_PLAUSIBLE_WPM: Final[float] = 185.0
_MINIMUM_WORDS_FOR_A_RATE: Final[int] = 4


# --------------------------------------------------------------------------
# Conventions the harness enforces on its own corpus and could not enforce here
# --------------------------------------------------------------------------
#
# An audit checked four of these against this set by hand and found them all
# holding -- **by luck, because nothing here ran them**. A convention that holds
# today and is enforced nowhere is a convention that holds until the next
# transcript, which is `HOLDOUT-OBLIGATIONS.md`'s entire subject.
#
# Ported rather than imported, for the reason the module docstring already
# gives: the harness's checks live in a test tree and a test module is not an
# importable interface. Every port is two things that can disagree, so the ones
# that copy a helper get an equality test rather than a promise.
#
# **The persona check is deliberately absent.** It is the fifth convention and
# the one the audit found *failing*: the agent personas used here are declared
# nowhere -- not in the harness register, which lists the design set's, and not
# in this repository, which has no declaration file. Porting it would commit a
# knowingly red build. The declaration has to exist first, and producing it is
# mechanical rather than a reading task; the harness's O-1 entry carries the
# design.


def _declared_in_register(section: str) -> set[str]:
    """Backticked lower-case identifiers under a heading in the entity canon."""
    assert HARNESS is not None
    register = (HARNESS / "corpus" / "entities.md").read_text(encoding="utf-8")
    start = register.index(section)
    rest = register[start + len(section) :]
    end = rest.find("\n## ")
    return set(re.findall(r"`([a-z_]+)`", rest if end == -1 else rest[:end]))


@requires_harness
def test_every_name_used_here_is_declared_in_the_entity_register() -> None:
    """The register claims to be the canonical list for both corpora.

    `tests/test_corpus_hygiene.py::test_every_name_the_corpus_uses_is_in_the_register`
    asserts used-implies-declared over `corpus/transcripts/`, which is the
    design set only. The register says so itself -- *"the held-out set is not in
    this tree and this check does not reach it; keeping the two consistent is a
    manual step at authoring time"* -- and this is that manual step becoming a
    check.

    Read as one pooled comparison rather than section by section. The harness
    splits context, state, tools and disclosures because it reports which list a
    name is missing from; here the useful question is narrower and blunter:
    **is this name anywhere in the canon at all?** A name that is in the wrong
    section of the register is a harness-side tidiness problem, and a name in no
    section is a corpus that invented vocabulary its own canon does not know.
    """
    from harness.core.events import DisclosureEvent, StateEvent, ToolCallEvent
    from harness.corpus.text_adapter import parse_call

    assert HARNESS is not None
    register = (HARNESS / "corpus" / "entities.md").read_text(encoding="utf-8")
    declared = set(re.findall(r"`([a-z_][a-z0-9_]*)`", register))
    assert len(declared) > 40, (
        f"only {len(declared)} names parsed out of the register; the extraction has broken "
        "and this check would pass by comparing against almost nothing"
    )

    used: dict[str, set[str]] = {
        "context": set(),
        "state": set(),
        "tool": set(),
        "disclosure": set(),
    }
    for transcript in _transcripts():
        call = parse_call(transcript)
        used["context"].update(name for name, _ in call.context)
        for event in call.events:
            if isinstance(event, StateEvent):
                used["state"].add(event.name)
            elif isinstance(event, ToolCallEvent):
                used["tool"].add(event.name)
            elif isinstance(event, DisclosureEvent):
                used["disclosure"].add(event.body.split(" ")[0])

    undeclared = {kind: sorted(names - declared) for kind, names in used.items()}
    problems = {kind: names for kind, names in undeclared.items() if names}
    assert not problems, (
        "names used in this set and absent from the harness's entity register:\n  "
        + "\n  ".join(f"{kind}: {names}" for kind, names in sorted(problems.items()))
        + "\nThe register is the canonical list for both corpora, so this is either a "
        "transcript inventing vocabulary or a register that was not updated."
    )


@requires_harness
def test_every_outcome_and_reason_used_here_is_declared() -> None:
    """The call record's own vocabulary, which the check above does not reach.

    `outcome` and `disconnection_reason` are validated at extraction, so an
    unrecognized token aborts the parse and this adds nothing for them.
    `outcome_reason` is **not** a closed vocabulary in the model -- it is a
    plain string -- and the register is the only place it is enumerated. So it
    is the one field here where a typo produces a value nothing rejects and
    nothing compares against, which is the register's own argument for
    declaring reason codes at all.
    """
    from harness.corpus.text_adapter import parse_call

    declared = _declared_in_register("**Outcome reasons.**")
    assert declared, "the register's outcome-reason section no longer parses"

    used = {parse_call(transcript).record.outcome_reason for transcript in _transcripts()}
    assert used, "no outcome reasons were read"
    undeclared = sorted(used - declared)
    assert not undeclared, (
        f"outcome reasons used here and absent from the register: {undeclared}. "
        "outcome_reason is a plain string in the model, so nothing else rejects a typo"
    )


@requires_harness
def test_every_utterance_here_is_spoken_at_a_plausible_rate() -> None:
    """Speech timing gets a floor, not a model (D48).

    Ported from `tests/test_speech_plausibility.py`. The band is deliberately
    wider than the 130-160 wpm ordinary conversation occupies, because the
    check exists to catch a transcript whose timestamps were written without
    thinking about speech at all -- not to police delivery.

    The constants are copied, and copied constants drift. They are asserted
    against the harness's own file below rather than trusted, which is the same
    remedy the `_sourced_by` copy gets.
    """
    from harness.core.events import SpeechEvent
    from harness.corpus.text_adapter import parse_call

    rows: list[tuple[str, int, int, float]] = []
    for transcript in _transcripts():
        call = parse_call(transcript)
        for event in call.events:
            if not isinstance(event, SpeechEvent):
                continue
            words = len(event.body.split())
            seconds = (event.ended_at_ms - event.started_at_ms) / 1000.0
            if words < _MINIMUM_WORDS_FOR_A_RATE or seconds <= 0:
                continue
            rows.append((call.record.call_id, event.index, words, words / seconds * 60.0))

    assert len(rows) > 20, (
        f"only {len(rows)} utterances were measurable across this set; too few for the "
        "band to mean anything, which is a fact about the check rather than the corpus"
    )
    outliers = [
        f"{call_id} event {index}: {words} words = {rate:.0f} wpm"
        for call_id, index, words, rate in rows
        if not _SLOWEST_PLAUSIBLE_WPM <= rate <= _FASTEST_PLAUSIBLE_WPM
    ]
    assert not outliers, (
        f"{len(outliers)} of {len(rows)} utterances sit outside "
        f"{_SLOWEST_PLAUSIBLE_WPM:.0f}-{_FASTEST_PLAUSIBLE_WPM:.0f} wpm:\n  "
        + "\n  ".join(outliers)
    )


@requires_harness
def test_the_copied_speech_constants_still_match_the_harness() -> None:
    """A copied number is a number that can drift.

    The band and the word floor are the harness's, and nothing but this
    connects the two copies. If the harness widens the band and this file does
    not, the held-out set is being held to a rule the design set no longer has
    -- which is `HOLDOUT-OBLIGATIONS.md`'s failure mode with the arrow reversed.
    """
    assert HARNESS is not None
    source = (HARNESS / "tests" / "test_speech_plausibility.py").read_text(encoding="utf-8")
    for name, value in (
        ("SLOWEST_PLAUSIBLE_WPM", _SLOWEST_PLAUSIBLE_WPM),
        ("FASTEST_PLAUSIBLE_WPM", _FASTEST_PLAUSIBLE_WPM),
        ("MINIMUM_WORDS_FOR_A_RATE", _MINIMUM_WORDS_FOR_A_RATE),
    ):
        found = re.search(rf"^{name}: \w+ = ([\d.]+)$", source, re.MULTILINE)
        assert found, f"{name} is no longer declared in the harness in the shape this reads"
        assert float(found.group(1)) == float(value), (
            f"{name} is {found.group(1)} in the harness and {value} here"
        )


@requires_harness
def test_the_copied_provenance_helper_is_the_same_code_as_the_harness_one() -> None:
    """`_sourced_by` is a copy, and two copies are two things that can disagree.

    D83 recorded this as the weakness of this file and left it open: *"if this
    one changes and that one does not, the held-out suite goes green against a
    stale convention -- which is `HOLDOUT-OBLIGATIONS.md`'s own failure mode,
    one layer down."*

    Compared as an **abstract syntax tree**, with three things normalized away
    because each differs for a reason that has nothing to do with the rule.
    **Annotations**, because the harness copy is typed and this one was not.
    **The docstring**, because each explains itself to its own reader.
    And **imports inside the body**: this copy takes `SpeechEvent` locally,
    since the harness is an optional dependency here and a module-level import
    would break collection when it is absent. Where a name comes from is not
    part of what the function computes.

    Comparing text would fail on formatting; comparing behaviour would need
    inputs neither repository can share. The tree is the thing that has to
    match, and the normalizations are listed rather than implied so that a
    future difference cannot be waved through as "just formatting".
    """
    assert HARNESS is not None

    def _body(source: str) -> str:
        module = ast.parse(source)
        for node in ast.walk(module):
            if isinstance(node, ast.FunctionDef) and node.name == "_sourced_by":
                stripped = copy.deepcopy(node)
                stripped.returns = None
                stripped.decorator_list = []
                for argument in stripped.args.args:
                    argument.annotation = None
                for inner in ast.walk(stripped):
                    if isinstance(inner, ast.AnnAssign):
                        inner.annotation = ast.Name(id="_", ctx=ast.Load())
                body = [
                    statement
                    for statement in stripped.body
                    if not isinstance(statement, (ast.Import, ast.ImportFrom))
                ]
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    body = body[1:]
                stripped.body = body
                return ast.dump(stripped)
        raise AssertionError("_sourced_by not found")

    mine = _body((REPO_ROOT / "tests" / "test_holdout_conventions.py").read_text(encoding="utf-8"))
    theirs = _body((HARNESS / "tests" / "test_corpus_hygiene.py").read_text(encoding="utf-8"))
    assert mine == theirs, (
        "the copy of _sourced_by here has diverged from the harness's. The two implement one "
        "convention and this suite would go green against a stale version of it. Re-copy it, "
        "or move the helper into the harness package so both import one implementation."
    )


# --------------------------------------------------------------------------
# The packet builder's guarantee, exercised rather than asserted
# --------------------------------------------------------------------------
#
# `tools/build_authoring_packet.py` says its own guarantee plainly: the
# redactions are best-effort and **the scan is the gate** -- after writing the
# packet, every file is searched for design-set identifiers, and a hit deletes
# the packet and fails the build. That is the sentence the whole apparatus rests
# on, and nothing exercised it. A guarantee no test has ever seen hold is a
# guarantee in the same category as the promise it replaced.


@requires_harness
def test_the_leak_scan_deletes_a_leaking_packet_and_fails(tmp_path: Path) -> None:
    """Plant a design-set identifier and assert the packet is gone.

    The plant is a **design-set** id, which is this session's to know: it comes
    from the harness's own `corpus/DESIGN_SET`. Nothing here reads a held-out
    transcript, and the packet the builder writes is deleted by the code under
    test, which is the behaviour being asserted.

    **Both halves matter and the builder's own comment says why.** A leaking
    packet left on disk beside a non-zero exit code is worse than no packet at
    all, because the exit code is a thing somebody can miss and the directory is
    a thing somebody can use. So this asserts the exit code *and* the absence.
    """
    assert HARNESS is not None
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from build_authoring_packet import build

    design = [
        line.strip()
        for line in (HARNESS / "corpus" / "DESIGN_SET").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert design, "the harness declares no design set, so there is nothing to plant"

    # A copy of the harness whose entity canon carries an unredactable mention
    # of a design call -- unredactable because no pattern in REDACTIONS or
    # LINE_REDACTIONS is written for this sentence, which is exactly the
    # situation a stale pattern produces.
    fake_harness = tmp_path / "harness"
    for relative in ("specs", "corpus", "corpus/policies"):
        (fake_harness / relative).mkdir(parents=True, exist_ok=True)
    for name in ("transcript-format.md", "event-model.md"):
        shutil.copy2(HARNESS / "specs" / name, fake_harness / "specs" / name)
    shutil.copy2(HARNESS / "corpus" / "DESIGN_SET", fake_harness / "corpus" / "DESIGN_SET")
    register = (HARNESS / "corpus" / "entities.md").read_text(encoding="utf-8")
    (fake_harness / "corpus" / "entities.md").write_text(
        register + f"\n\nAn unredacted mention of {design[0]} that no pattern removes.\n",
        encoding="utf-8",
    )

    out = tmp_path / "packet"
    code = build(fake_harness, out, "an assignment", "a title")

    assert code == 1, "a packet carrying a design-set identifier was reported as a success"
    assert not out.exists(), (
        "the leaking packet is still on disk. The builder's own comment is that a leaking "
        "packet beside a non-zero exit code is worse than none, because an exit code can be "
        "missed and a directory can be used"
    )


@requires_harness
def test_a_clean_packet_is_written_and_lands_outside_every_git_tree(tmp_path: Path) -> None:
    """The other half: the scan must not fire on a packet that is fine.

    A gate that refuses everything is not a gate, and this one deletes its
    output -- so a scan that fired spuriously would look exactly like a scan
    that worked, with nothing left behind to inspect.

    It also asserts where the packet lands. The builder defaults to a directory
    outside every repository, deliberately, so a packet cannot be committed by
    accident; that is a property of the default rather than of the code path,
    so it is read from the parser rather than inferred.
    """
    assert HARNESS is not None
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from build_authoring_packet import build, main

    out = tmp_path / "packet"
    assert build(HARNESS, out, "an assignment", "a title") == 0, (
        "the leak scan fired on an unmodified harness, so it is refusing packets it should "
        "pass -- and since the builder deletes a leaking packet, that failure leaves nothing "
        "behind to look at"
    )
    assert (out / "README.md").is_file()
    assert (out / "reference" / "entity-canon.md").is_file()
    assert sorted(p.name for p in (out / "transcripts").glob("*.txt")) == sorted(
        p.name for p in (REPO_ROOT / "transcripts").glob("CALL-*.txt")
    ), "the packet does not carry this repository's transcripts"

    # The redactions did their work: no design-set identifier survives.
    design = {
        line.strip()
        for line in (HARNESS / "corpus" / "DESIGN_SET").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    for path in (out / "reference" / "entity-canon.md", out / "specs" / "event-model.md"):
        found = set(re.findall(r"\bCALL-\d{2}\b", path.read_text(encoding="utf-8"))) & design
        assert not found, f"{path.name} still names design calls: {sorted(found)}"

    # Where the default lands, read from the parser rather than from the source
    # text. The first draft of this assertion checked that the default did not
    # mention `REPO_ROOT`, and the default is `REPO_ROOT.parent / ...` -- which
    # is correct and would have failed it. What matters is the resolved path,
    # not how it is spelled.
    parser = main.__globals__["argparse"].ArgumentParser()
    source = (REPO_ROOT / "tools" / "build_authoring_packet.py").read_text(encoding="utf-8")
    assert 'default=REPO_ROOT.parent / "holdout-authoring-packet"' in source, (
        "the --out default has moved; re-read it before trusting the assertion below"
    )
    default = REPO_ROOT.parent / "holdout-authoring-packet"
    assert REPO_ROOT not in default.parents, (
        "the packet's default output directory is inside this repository, so a default build "
        "could be committed by accident"
    )
    assert HARNESS.resolve() not in default.resolve().parents, (
        "the packet's default output directory is inside the harness repository"
    )
    for ancestor in [default, *default.parents]:
        assert not (ancestor / ".git").exists() or ancestor == default, (
            f"the packet's default output directory sits inside a git tree at {ancestor}"
        )
    assert parser is not None


# --------------------------------------------------------------------------
# Agent personas, the fifth convention, and the one that had no declaration
# --------------------------------------------------------------------------

_PERSONAS_FILE: Final[Path] = REPO_ROOT / "PERSONAS"


@requires_harness
def test_every_persona_used_here_is_declared() -> None:
    """The convention the other four could not be ported alongside.

    The harness's `test_every_agent_persona_is_declared` holds Class 1 in free
    speech: a persona is invented under the same substitution policy as the
    platform name, appears in every call, and was declared nowhere until a sweep
    counted them. Its register lists the *design* set's. This set uses others.

    **Skipped, loudly, until the declaration exists.** Porting the check with no
    `PERSONAS` file would commit a knowingly red build, and skipping quietly
    would be the hiding place this repository refuses everywhere else. The skip
    names the command that ends it, and the moment the file lands this becomes
    an ordinary check with nothing conditional about it.

    **Producing that file needs no reader.** The extraction is deterministic, so
    a program writes it -- which is why this is a skip waiting on one command
    rather than an obligation waiting on a cleared session.
    """
    if not _PERSONAS_FILE.is_file():
        pytest.skip(
            "PERSONAS does not exist yet, so there is nothing to check personas against. "
            "Run `python tools/declare_personas.py` and commit the result, adding PERSONAS "
            "to the tracked-file allowlist in .github/workflows/checks.yml in the same commit."
        )

    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from declare_personas import personas

    assert HARNESS is not None
    declared = {
        line.strip()
        for line in _PERSONAS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    declared |= set(
        re.findall(
            r"\*\*([A-Z][a-z]+)\*\*",
            (HARNESS / "corpus" / "entities.md").read_text(encoding="utf-8"),
        )
    )
    assert declared, "neither PERSONAS nor the register yields any name"

    used = personas()
    expected = {path.stem for path in _transcripts()}
    missing = sorted(expected - set(used))
    assert not missing, (
        f"no agent persona could be read from {missing}; either the agent stopped introducing "
        "itself or the phrasing changed and this check has gone half-blind"
    )
    undeclared = sorted(set(used.values()) - declared)
    assert not undeclared, (
        f"personas used here and declared nowhere: {undeclared}. Re-run "
        "`python tools/declare_personas.py` and commit, or add them to the harness register"
    )


@requires_harness
def test_the_persona_pattern_still_matches_the_harness_one() -> None:
    """Another copy, and the same remedy the other two copies get.

    `declare_personas.PERSONA_PATTERN` is a copy of the expression inside the
    harness's `_agent_personas`, for the reason every port here is a copy: it is
    a private helper in a test tree. If the harness widens the pattern -- a
    second way for an agent to introduce itself -- and this does not, the
    generator writes a short list, the check above passes against it, and the
    convention is enforced against a subset nobody chose.

    This binds them without needing the harness's helper to be importable, and
    it is deliberately compared as the pattern rather than as behaviour: the two
    read different corpora, so equal outputs would prove nothing.
    """
    assert HARNESS is not None
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from declare_personas import PERSONA_PATTERN

    source = (HARNESS / "tests" / "test_corpus_hygiene.py").read_text(encoding="utf-8")
    theirs = re.search(r're\.search\(\s*r"(\\bthis is [^"]+)"', source)
    assert theirs, (
        "the harness's persona pattern is no longer written in the shape this reads; "
        "re-read _agent_personas before trusting the copy in tools/declare_personas.py"
    )
    assert PERSONA_PATTERN.pattern == theirs.group(1), (
        f"the persona pattern here is {PERSONA_PATTERN.pattern!r} and the harness's is "
        f"{theirs.group(1)!r}. Two copies of one rule have diverged"
    )
