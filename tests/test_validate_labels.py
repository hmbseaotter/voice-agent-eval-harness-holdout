"""The held-out label validator, `tools/validate_labels.py`.

Every document here is synthetic: two invented calls in the transcript format, a
stand-in harness with an invented rubric, and rows written against both. No test
reads a held-out transcript or a label, so a failure can print nothing either
holds.

Each rule is exercised by planting what it exists to catch: the refusal before
the freeze, the rubric read at the freeze commit rather than at the harness's
head, every evidence branch both ways, and every traces rule alone. The failing
cases also assert that nothing printed repeats the text the validator was
handed, because its output reaches terminals and session transcripts.

The evidence patterns are copies, so they are compared with the harness's
originals, and a control moves one to prove the comparison can fail.
"""

from __future__ import annotations

import ast
import contextlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest

if TYPE_CHECKING:  # pragma: no cover - types only, and the harness may be absent
    from collections.abc import Callable

    from harness.core.events import Call

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import make_label_worksheet as worksheet  # noqa: E402
import validate_labels as validator  # noqa: E402

HARNESS: Final[Path | None] = worksheet.harness_root()

if HARNESS is not None:  # pragma: no cover - import plumbing
    with contextlib.suppress(ImportError):
        import harness  # noqa: F401
    if "harness" not in sys.modules:
        sys.path.insert(0, str(HARNESS / "src"))

requires_harness = pytest.mark.skipif(
    HARNESS is None,
    reason="the harness repository was not found, so there is no parser or loader to run",
)

_IDENTITY: Final[dict[str, str]] = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

_HEADER: Final[str] = """\
#format: voice-agent-eval-harness/transcript v2

[call]
call_id: {call_id}
agent_id: fixture
agent_version: 1
environment: test
direction: inbound
from_number: +1 (415) 555-0190
to_number: +1 (415) 555-0100
started_at: 2027-01-01T00:00:00.000Z
answered_at: 2027-01-01T00:00:01.000Z
ended_at: 2027-01-01T00:00:20.000Z
duration_ms: 20000
disconnection_reason: caller_hangup
outcome: resolved
outcome_reason: fixture

[context]
identity_verified := false

[events]
"""

#: The first invented call. Its first turn wraps, as real turns do.
_CALL_90: Final[str] = """\
  1 |  0:01.000 |  0:09.400 | AGENT       | Thanks for calling, how can I help with the
    |           |           |             | marigold question today?
  2 |  0:10.000 |  0:10.000 | STATE       | long_value := marigold
  3 |  0:11.000 |  0:14.000 | CALLER      | Single line.
  4 |  0:15.000 |  0:15.200 | TOOL_CALL   | t1 do_something(arg="value")
  5 |  0:15.200 |  0:20.000 | TOOL_RESULT | t1 -> completed successful=true :: fine
"""

#: The second, for citations from one call into another.
_CALL_91: Final[str] = """\
  1 |  0:01.000 |  0:02.000 | CALLER      | Second call.
  2 |  0:03.000 |  0:04.000 | AGENT       | Still the second call.
"""

#: Text the synthetic documents carry. None of it may come back in anything printed.
_PLANTED: Final[tuple[str, ...]] = (
    "marigold",
    "sunflower",
    "single line",
    "second call",
    "0:09",
    "19999",
)

_FINDINGS: Final[str] = """\
findings:
  - id: HF-01
    call_ref: CALL-90
    owner: agent
    observation: An invented observation that cites event 3.
    evidence:
      - 'event 1 — "how can I help with the marigold question"'
      - 'context — identity_verified := false'
    consequence: An invented consequence.
    detectable_by: judge
    tier: defect
  - id: HF-02
    call_ref: CALL-91
    owner: platform
    observation: Another invented observation.
    evidence:
      - 'event 2 — "Still the second call."'
    consequence: Another invented consequence.
    detectable_by: assert
    tier: question
"""

#: The same rows as drafts: the text fields only.
_DRAFTS: Final[str] = "".join(
    line + "\n"
    for line in _FINDINGS.splitlines()
    if line.strip().split(":")[0] not in validator.RULED
)

_RUBRIC_AT_FREEZE: Final[str] = "version: '1'\nentries:\n  - id: A-alpha\n  - id: J-beta\n"
_ENTRY_ADDED_AFTER: Final[str] = "  - id: A-gamma\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        env={**os.environ, **_IDENTITY},
        capture_output=True,
    )


def _stand_in_harness(root: Path, *, tagged: bool) -> Path:
    """A git repository standing in for the harness.

    Its invented rubric is frozen by the tag and then gains an entry, so a test can tell
    the rubric at the freeze commit from the one at the head. Its design findings include
    an `HF-` id no real design finding carries, so the collision rule has one to catch.
    """
    (root / "corpus").mkdir(parents=True)
    (root / "HELDOUT_SET").write_text("# invented\n\nCALL-90\n  CALL-91 \n", encoding="utf-8")
    (root / "corpus" / "findings.yaml").write_text(
        "findings:\n  - id: F-01\n  - id: HF-77\n", encoding="utf-8"
    )
    (root / "rubric.yaml").write_text(_RUBRIC_AT_FREEZE, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "frozen")
    if tagged:
        _git(root, "tag", worksheet.FREEZE_TAG)
    (root / "rubric.yaml").write_text(_RUBRIC_AT_FREEZE + _ENTRY_ADDED_AFTER, encoding="utf-8")
    _git(root, "commit", "-q", "-am", "an entry added after the freeze")
    return root


def _transcripts(root: Path) -> Path:
    root.mkdir(parents=True)
    for call_id, events in (("CALL-90", _CALL_90), ("CALL-91", _CALL_91)):
        (root / f"{call_id}.txt").write_text(
            _HEADER.format(call_id=call_id) + events, encoding="utf-8", newline="\n"
        )
    return root


@pytest.fixture(scope="module")
def stand_in(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One tagged stand-in for the module, since every git command is a process to start."""
    return _stand_in_harness(tmp_path_factory.mktemp("stand-in") / "harness", tagged=True)


@pytest.fixture(scope="module")
def transcripts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _transcripts(tmp_path_factory.mktemp("invented") / "transcripts")


@pytest.fixture(scope="module")
def calls(transcripts: Path) -> dict[str, Call]:
    assert HARNESS is not None
    parsed = worksheet.load_calls(transcripts, HARNESS)
    return {Path(call.source_path).stem: call for call in parsed}


def _labels(root: Path, **documents: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in documents.items():
        (root / f"{name}.yaml").write_text(text, encoding="utf-8")
    return root


def _traces(
    sha: str,
    entries: tuple[str, ...] = ("A-alpha", "J-beta"),
    *,
    uncovered: str = "[HF-02]",
    without_findings: str = "[]",
) -> str:
    lines = [f"{worksheet.FREEZE_TAG}: '{sha}'", "traces:"]
    lines += [f"  {entry}: {'[HF-01]' if entry == 'A-alpha' else '[]'}" for entry in entries]
    lines.append(f"uncovered: {uncovered}")
    lines.append(f"calls_without_findings: {without_findings}")
    return "\n".join(lines) + "\n"


def _row(
    finding_id: str = "HF-01",
    call_ref: str = "CALL-90",
    *,
    evidence: tuple[str, ...] = ('event 3 — "Single line."',),
    observation: str = "An invented observation.",
    consequence: str = "An invented consequence.",
) -> validator.Row:
    return validator.Row(finding_id, call_ref, observation, evidence, consequence)


def _repeated(printed: str) -> list[str]:
    return [word for word in _PLANTED if word in printed.lower()]


# --------------------------------------------------------------------------
# End to end: the stages, the freeze, the rubric at the freeze commit
# --------------------------------------------------------------------------


def test_the_validator_refuses_before_the_freeze(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No tag, nothing validated: held-out labels exist only after the freeze (D21)."""
    untagged = _stand_in_harness(tmp_path / "harness", tagged=False)

    assert validator.check("all", harness=untagged, labels=tmp_path, transcripts=tmp_path) == 1
    printed = capsys.readouterr()
    assert worksheet.FREEZE_TAG in printed.err
    assert printed.out == ""


@requires_harness
def test_a_clean_label_set_passes_every_stage(
    stand_in: Path, transcripts: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Drafts, findings, and findings with traces: each passes, and says what it checked."""
    sha = worksheet.freeze_commit(stand_in)
    assert sha is not None
    labels = _labels(tmp_path / "labels", drafts=_DRAFTS, findings=_FINDINGS, traces=_traces(sha))

    for stage in validator.STAGES:
        assert (
            validator.check(stage, harness=stand_in, labels=labels, transcripts=transcripts) == 0
        ), stage
    printed = capsys.readouterr()
    assert printed.err == ""
    assert "drafts: valid" in printed.out
    assert (
        "2 findings over 2 calls; 3 evidence fragments checked, 0 left to the reviewer as prose; "
        "1 event citations in prose checked" in printed.out
    )
    assert "traces place every finding against 2 frozen entries" in printed.out
    assert "every held-out call is referenced or declared without findings" in printed.out
    assert not _repeated(printed.out)


@requires_harness
def test_the_rubric_is_read_at_the_freeze_commit_not_at_the_head(stand_in: Path) -> None:
    """The mapping is to the rubric the judge was frozen with, whatever the harness says now."""
    sha = worksheet.freeze_commit(stand_in)
    assert sha is not None

    assert validator.rubric_entry_ids(stand_in, sha) == ["A-alpha", "J-beta"]
    assert validator.rubric_entry_ids(stand_in, "HEAD") == ["A-alpha", "J-beta", "A-gamma"], (
        "the premise of this test is a head whose rubric differs from the frozen one"
    )
    assert validator.rubric_entry_ids(stand_in, "0" * 40) is None


@requires_harness
def test_traces_keyed_to_the_head_rubric_are_refused(
    stand_in: Path, transcripts: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An entry added after the freeze is not one a held-out finding can be placed under."""
    sha = worksheet.freeze_commit(stand_in)
    assert sha is not None
    head_keyed = _traces(sha, entries=("A-alpha", "J-beta", "A-gamma"))
    labels = _labels(tmp_path / "labels", findings=_FINDINGS, traces=head_keyed)

    assert validator.check("all", harness=stand_in, labels=labels, transcripts=transcripts) == 1
    assert "not entries of the rubric at the freeze commit: A-gamma" in capsys.readouterr().err


@requires_harness
def test_a_broken_label_set_fails_and_repeats_none_of_its_text(
    stand_in: Path, transcripts: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A misquote and a call neither referenced nor declared, each named but never quoted."""
    sha = worksheet.freeze_commit(stand_in)
    assert sha is not None
    only_the_first = _FINDINGS.split("  - id: HF-02")[0]
    broken = only_the_first.replace("marigold question", "sunflower question")
    labels = _labels(tmp_path / "labels", findings=broken, traces=_traces(sha, uncovered="[]"))

    assert validator.check("all", harness=stand_in, labels=labels, transcripts=transcripts) == 1
    printed = capsys.readouterr()
    assert "HF-01 evidence 1: event 1 does not hold what it quotes" in printed.err
    assert "CALL-91: no finding references this held-out call" in printed.err
    assert not _repeated(printed.out + printed.err)


@requires_harness
def test_a_call_declared_without_findings_passes(
    stand_in: Path, transcripts: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A call with nothing wrong is sealable by saying so, never by leaving it out."""
    sha = worksheet.freeze_commit(stand_in)
    assert sha is not None
    only_the_first = _FINDINGS.split("  - id: HF-02")[0]
    declared = _traces(sha, uncovered="[]", without_findings="[CALL-91]")
    labels = _labels(tmp_path / "labels", findings=only_the_first, traces=declared)

    findings_only = validator.check(
        "findings", harness=stand_in, labels=labels, transcripts=transcripts
    )
    assert findings_only == 0, "a call without findings is no problem before traces exist"
    assert validator.check("all", harness=stand_in, labels=labels, transcripts=transcripts) == 0
    assert capsys.readouterr().err == ""


# --------------------------------------------------------------------------
# The documents
# --------------------------------------------------------------------------


@requires_harness
def test_a_draft_may_carry_text_but_no_classification() -> None:
    """`owner`, `detectable_by` and `tier` are the ledger's; a draft stating them is refused."""
    rows, problems = validator.parse_drafts(_DRAFTS)
    assert [row.id for row in rows] == ["HF-01", "HF-02"]
    assert problems == []

    rows, problems = validator.parse_drafts(_FINDINGS)
    assert rows == []
    assert len(problems) == 2
    assert all("only the owner's ledger states" in problem for problem in problems)


@requires_harness
def test_a_yaml_error_is_located_without_quoting_the_line() -> None:
    """PyYAML's own message quotes the offending line; the validator gives its position only."""
    broken = "findings:\n  - id: HF-01\n    observation: [a sunflower that never closes\n"
    parsers = (
        (validator.parse_drafts, "drafts.yaml"),
        (validator.parse_findings_document, "findings.yaml"),
    )
    for parse, name in parsers:
        rows, problems = parse(broken)
        assert rows == []
        assert len(problems) == 1
        assert problems[0].startswith(f"{name}: not valid YAML at line "), problems
        assert "sunflower" not in problems[0]


def test_ids_are_heldout_shaped_and_new_and_calls_are_heldout() -> None:
    """`HF-NN`, never a design id, and a `call_ref` declared held-out with a transcript here."""
    rows = [
        _row("HF-01", "CALL-90"),
        _row("F-01", "CALL-90"),
        _row("HF-7", "CALL-90"),
        _row("HF-77", "CALL-90"),
        _row("HF-02", "CALL-05"),
        _row("HF-03", "CALL-92"),
    ]
    problems = validator.identity_problems(
        rows,
        heldout={"CALL-90", "CALL-91", "CALL-92"},
        transcribed={"CALL-90", "CALL-91"},
        design={"F-01", "HF-77"},
    )
    assert problems == [
        "row 2: its id is not shaped HF-NN",
        "row 3: its id is not shaped HF-NN",
        "HF-77: its id is a design-set finding's id",
        "HF-02: its call_ref is not declared in HELDOUT_SET",
        "HF-03: its call_ref has no transcript in this repository",
    ]


def test_every_heldout_call_is_referenced_or_declared_without_findings() -> None:
    """§6 step 1: no call is left out silently, and none is both declared clean and cited."""
    rows = [_row("HF-01", "CALL-90")]
    heldout = {"CALL-90", "CALL-91"}

    assert validator.coverage_problems(rows, heldout, set()) == [
        "CALL-91: no finding references this held-out call, and calls_without_findings "
        "does not list it"
    ]
    assert validator.coverage_problems(rows, heldout, {"CALL-91"}) == []
    assert validator.coverage_problems(rows, heldout, {"CALL-90", "CALL-91"}) == [
        "CALL-90: calls_without_findings lists it, yet a finding references it"
    ]
    assert validator.coverage_problems(rows, heldout, {"CALL-91", "CALL-99"}) == [
        "CALL-99: calls_without_findings lists it, but HELDOUT_SET does not declare it"
    ]


# --------------------------------------------------------------------------
# The evidence rules, each planted both ways
# --------------------------------------------------------------------------

_FRAGMENTS: Final[tuple[tuple[str, str, bool], ...]] = (
    ("quote", 'event 1 — "how can I help with the marigold question"', True),
    ("quote misquoted", 'event 1 — "how can I help with the sunflower question"', False),
    ("quote beyond the call", 'event 9 — "Single line."', False),
    ("plain", "event 5 — t1 -> completed successful=true", True),
    ("plain misquoted", "event 5 — t1 -> refused_sunflower successful=false", False),
    ("context", "context — identity_verified := false", True),
    ("context value", "context — identity_verified := sunflower", False),
    ("context name", "context — sunflower_name := false", False),
    ("record", "call record — duration_ms 20000", True),
    ("record value", "call record — duration_ms 19999", False),
    ("record naming no field", "call record — sunflower", False),
    ("span", "events 1 to 2 — the agent is silent from 0:09.400 to 0:10.000", True),
    ("span stale", "events 1 to 2 — the agent is silent from 0:09.000 to 0:10.000", False),
    (
        "span beyond the call",
        "events 1 to 9 — the agent is silent from 0:09.400 to 0:10.000",
        False,
    ),
    ("gap of a kind", "No TOOL_CALL occurs between events 1 and 3", True),
    ("gap of a kind broken", "No STATE occurs between events 1 and 3", False),
    ("gap of any kind", "No event of any kind falls between events 1 and 2", True),
    ("gap of any kind broken", "No event of any kind falls between events 1 and 3", False),
    ("gap backwards", "No event falls between events 3 and 1", False),
    ("gap naming no kind", "No SUNFLOWER occurs between events 1 and 3", False),
    ("final event", "The final event of the call ends at 20000ms", True),
    ("final event stale", "The final event of the call ends at 19999ms", False),
    ("another call", "CALL-91 event 2 — Still the second call", True),
    ("another call misquoted", "CALL-91 event 2 — Still the sunflower call", False),
    ("another call beyond it", "CALL-91 event 9 — Still the second call", False),
    ("a call with no transcript", "CALL-99 event 1 — Still the second call", False),
)


@requires_harness
@pytest.mark.parametrize(
    ("fragment", "holds"),
    [(fragment, holds) for _, fragment, holds in _FRAGMENTS],
    ids=[name for name, _, _ in _FRAGMENTS],
)
def test_each_evidence_rule_passes_the_true_and_names_the_false(
    calls: dict[str, Call], fragment: str, holds: bool
) -> None:
    """Every branch the design set's check has, planted true and false over an invented call."""
    problems, _, prose = validator.evidence_problems([_row(evidence=(fragment,))], calls)

    assert (not problems) is holds, problems
    assert prose == 0, "a checkable fragment was left to the reviewer as prose"
    assert not _repeated(" ".join(problems)), problems


@requires_harness
def test_prose_about_an_absence_is_left_to_the_reviewer_and_counted_as_such(
    calls: dict[str, Call],
) -> None:
    """A claim about what turns say is not a gap claim: nothing checked, one left as prose."""
    fragment = "No agent turn between events 1 and 3 asks for anything."
    result = validator.evidence_problems([_row(evidence=(fragment,))], calls)
    assert result == ([], 0, 1)


@requires_harness
def test_an_event_cited_in_prose_must_exist(calls: dict[str, Call]) -> None:
    """Citations in an observation or a consequence resolve, in the row's call or the one named."""
    good = _row(
        "HF-01",
        observation="At event 3 the caller speaks.",
        consequence="Then CALL-91 event 2 follows.",
    )
    bad = _row(
        "HF-02",
        observation="Events 4 to 12 are silent.",
        consequence="CALL-91 event 5 never happens.",
    )
    problems, checked = validator.prose_problems([good, bad], calls)

    assert checked == 5
    assert problems == [
        "HF-02 observation: cites CALL-90 event 12, which has only events 1 to 5",
        "HF-02 consequence: cites CALL-91 event 5, which has only events 1 to 2",
    ]


# --------------------------------------------------------------------------
# traces.yaml, each rule broken alone
# --------------------------------------------------------------------------

_SHA: Final[str] = "a" * 40
_FINDING_IDS: Final[tuple[str, ...]] = ("HF-01", "HF-02")
_ENTRY_IDS: Final[tuple[str, ...]] = ("A-alpha", "J-beta")


def _clean_traces() -> dict[str, Any]:
    return {
        worksheet.FREEZE_TAG: _SHA,
        "traces": {"A-alpha": ["HF-01"], "J-beta": []},
        "uncovered": ["HF-02"],
        "calls_without_findings": [],
    }


def _setting(path: tuple[str, ...], value: object) -> Callable[[dict[str, Any]], None]:
    def mutate(document: dict[str, Any]) -> None:
        target = document
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _dropping(path: tuple[str, ...]) -> Callable[[dict[str, Any]], None]:
    def mutate(document: dict[str, Any]) -> None:
        target = document
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]

    return mutate


_TRACE_BREAKS: Final[dict[str, tuple[Callable[[dict[str, Any]], None], str]]] = {
    "the wrong freeze commit": (
        _setting((worksheet.FREEZE_TAG,), "b" * 40),
        "does not name the freeze commit",
    ),
    "an entry absent": (_dropping(("traces", "J-beta")), "are absent: J-beta"),
    "a key the frozen rubric lacks": (
        _setting(("traces", "A-gamma"), []),
        "at the freeze commit: A-gamma",
    ),
    "an entry left blank": (_setting(("traces", "J-beta"), None), "J-beta must hold a list"),
    "a finding placed nowhere": (_setting(("uncovered",), []), "placed nowhere: HF-02"),
    "a finding placed and uncovered": (
        _setting(("traces", "J-beta"), ["HF-02"]),
        "in uncovered: HF-02",
    ),
    "an id that is no finding": (_setting(("traces", "J-beta"), ["HF-09"]), "not findings: HF-09"),
    "a list repeating an id": (
        _setting(("traces", "A-alpha"), ["HF-01", "HF-01"]),
        "more than once",
    ),
    "a list missing": (_dropping(("uncovered",)), "missing uncovered"),
    "an unknown key": (_setting(("notes",), []), "unknown key(s) notes"),
    "the calls list missing": (
        _dropping(("calls_without_findings",)),
        "missing calls_without_findings",
    ),
    "the calls list left blank": (
        _setting(("calls_without_findings",), None),
        "calls_without_findings must be a list",
    ),
    "a call listed twice": (
        _setting(("calls_without_findings",), ["CALL-91", "CALL-91"]),
        "lists a call more than once",
    ),
}


def test_clean_traces_pass() -> None:
    """The control for every break below: the unbroken document has no problem."""
    problems = validator.traces_problems(
        _clean_traces(), finding_ids=_FINDING_IDS, entry_ids=_ENTRY_IDS, freeze_sha=_SHA
    )
    assert problems == []


@pytest.mark.parametrize("case", sorted(_TRACE_BREAKS))
def test_each_traces_rule_names_its_break_alone(case: str) -> None:
    """One break, one problem: a missing list is not also reported as every finding unplaced."""
    mutate, phrase = _TRACE_BREAKS[case]
    document = _clean_traces()
    mutate(document)
    problems = validator.traces_problems(
        document, finding_ids=_FINDING_IDS, entry_ids=_ENTRY_IDS, freeze_sha=_SHA
    )
    assert len(problems) == 1, problems
    assert phrase in problems[0], problems


# --------------------------------------------------------------------------
# The copied patterns, held to the harness's
# --------------------------------------------------------------------------

_PORTED_PATTERNS: Final[tuple[str, ...]] = (
    "_EVENT_QUOTE",
    "_EVENT_PLAIN",
    "_RECORD",
    "_SPAN",
    "_FINAL_EVENT",
    "_CROSS_CALL",
    "_GAP_CLAIM",
    "_CONTEXT",
    "_PROSE_EVENT",
)


def _compiled_constant(source: str, name: str) -> re.Pattern[str]:
    """The `re.compile` a module assigns to `name` at its top level, rebuilt without importing it.

    A test module is not an importable interface, which is why every port in this repository
    is a copy, and why the original is read from its syntax tree.
    """
    for node in ast.parse(source).body:
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        else:
            continue
        if value is None or not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        if not (
            isinstance(value, ast.Call) and ast.unparse(value.func) == "re.compile" and value.args
        ):
            raise LookupError(name)
        flags = 0
        named = (*value.args[1:], *(kw.value for kw in value.keywords if kw.arg == "flags"))
        for flag in named:
            for part in ast.unparse(flag).split("|"):
                flags |= getattr(re, part.strip().removeprefix("re."))
        return re.compile(ast.literal_eval(value.args[0]), flags)
    raise LookupError(name)


def _pattern_drift(harness_source: str) -> list[str]:
    """The copied patterns that no longer compile to what the harness's do.

    Takes the harness module's source rather than reading it, so the control below can
    hand it a module in which one pattern has moved.
    """
    problems: list[str] = []
    for name in _PORTED_PATTERNS:
        try:
            theirs = _compiled_constant(harness_source, name)
        except LookupError:
            problems.append(f"{name} is no longer a top-level re.compile in the harness module")
            continue
        mine: re.Pattern[str] = getattr(validator, name)
        if (mine.pattern, mine.flags) != (theirs.pattern, theirs.flags):
            problems.append(f"{name} no longer compiles to the harness's pattern")
    return problems


@requires_harness
def test_the_copied_evidence_patterns_still_match_the_harness() -> None:
    """Held-out findings follow the design set's evidence rules, so the copies may not drift."""
    assert HARNESS is not None
    source = (HARNESS / "tests" / "test_findings_evidence.py").read_text(encoding="utf-8")
    drift = _pattern_drift(source)
    assert not drift, (
        "an evidence pattern copied from the harness has diverged from it, so held-out findings "
        "are being checked by a rule design findings no longer follow:\n  " + "\n  ".join(drift)
    )


def test_the_pattern_comparison_fires_on_a_pattern_that_moved() -> None:
    """The control: identical passes; a changed pattern, flags or name each fail alone."""

    def module(
        patterns: dict[str, str] | None = None,
        flags: dict[str, str] | None = None,
        without: str = "",
    ) -> str:
        lines = ["import re"]
        for name in _PORTED_PATTERNS:
            if name == without:
                continue
            compiled: re.Pattern[str] = getattr(validator, name)
            text = (patterns or {}).get(name, compiled.pattern)
            named = (flags or {}).get(name) or " | ".join(
                f"re.{flag.name}" for flag in (re.DOTALL, re.IGNORECASE) if compiled.flags & flag
            )
            # One annotated assignment, so both shapes are read.
            annotation = ": Final[re.Pattern[str]]" if name == "_CONTEXT" else ""
            lines.append(f"{name}{annotation} = re.compile({text!r}, {named})")
        return "\n".join(lines) + "\n"

    assert not _pattern_drift(module()), "identical patterns were reported as drift"

    moved = _pattern_drift(module(patterns={"_SPAN": validator._SPAN.pattern + "x"}))
    assert len(moved) == 1 and "_SPAN" in moved[0], moved

    reflagged = _pattern_drift(module(flags={"_PROSE_EVENT": "re.DOTALL"}))
    assert len(reflagged) == 1 and "_PROSE_EVENT" in reflagged[0], reflagged

    renamed = _pattern_drift(module(without="_CONTEXT"))
    assert len(renamed) == 1 and "_CONTEXT" in renamed[0], renamed
