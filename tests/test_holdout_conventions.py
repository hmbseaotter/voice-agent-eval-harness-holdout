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

import contextlib
import itertools
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

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


def _sourced_by(call, event, value: str) -> str | None:
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

    The held-out set carried one of these when the check was ported:
    `reserve_seats` took a bare seat count that no context value, no prior
    result and no arithmetic over the call's numbers produced. It was repaired
    the way the design set's `CALL-09` was -- not by deleting the argument, but
    by keying the call on something the transcript already established.

    Worth recording for whoever reads a future failure here: **no bare integer
    of one or two characters can ever pass this check.** The speech and
    prior-event paths require three characters, and the arithmetic path sums
    context numbers rather than subtracting them. That is deliberate -- the
    length floor is what stopped `clause="2.2"` matching `ticket_count=2` and
    hiding five real cases -- but it means a small-integer argument has no
    honest repair available, only a coincidental match. The repair is to change
    what the argument *is*, not to widen the check.
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

    The harness has `test_one_event_title_per_event_id_except_where_drift_is_
    seeded`, and it compares **titles**. Ported here as-is it would have passed
    while this set contained a real contradiction: two calls shared an event id
    and its title and disagreed about the door time, one of them placing the
    show four days before the call that was arranging to attend it. Same guard,
    same event id, narrower field list -- green, and blind to the field that
    actually differed.

    So this compares every field scoped to the event, not just the one the
    original happened to pick. `door_time` is the field that matters most,
    because it is what every deadline in the policy set is measured against: a
    transfer window closes 24 hours before it, and an agent reasoning about that
    window against the wrong date reasons correctly to a wrong answer.

    The harness's own version carries a seeded-drift exemption, and this one
    deliberately does not. Naming drift is a *design*-set defect class; a
    held-out transcript that needs an exemption here should get one added
    explicitly, with the reason, rather than inheriting a hole sized for another
    corpus.
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
        call_id
        for call_id, fields in _call_records().items()
        if fields["outcome"] == "transferred"
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
        "EV-00001": {
            "CALL-YY": {"event_title": "A Show", "door_time": "2027-01-08T19:00:00Z"}
        }
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
