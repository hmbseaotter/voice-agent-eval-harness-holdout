"""The phase-5 chain: `tools/label_gate.py`, and the `tools/label_manifest.py` that feeds it.

Every repository here is invented: a stand-in harness whose invented rubric is
frozen by a planted tag, and held-out histories written with `git fast-import`.
Plumbing rather than `git commit`, for two reasons. A control has to be able to
write a commit dated before the freeze, and this machine's global commit hooks
cost seconds a commit while guarding nothing a throwaway repository holds.

A clean chain is walked through all four stages first. Every control after it
is that chain with one step out of order, and each must turn the gate red with
the problem named: the controls `PHASE-5-LABELS.md` §7 lists, and the checks the
gate adds to them. Then seal and reveal run over the same kind of invented
repository, and what they write, committed as §6 says, must pass the gate.
Nothing here prints a label, because nothing here is one.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest

if TYPE_CHECKING:  # pragma: no cover - types only
    from collections.abc import Callable

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import label_gate as chain  # noqa: E402
import label_manifest as manifest_tool  # noqa: E402
import make_label_worksheet as worksheet  # noqa: E402

HARNESS: Final[Path | None] = worksheet.harness_root()

if HARNESS is not None:  # pragma: no cover - import plumbing
    with contextlib.suppress(ImportError):
        import harness  # noqa: F401
    if "harness" not in sys.modules:
        sys.path.insert(0, str(HARNESS / "src"))

requires_harness = pytest.mark.skipif(
    HARNESS is None,
    reason="the harness repository was not found, so revealed labels cannot be validated",
)

_IDENTITY: Final[dict[str, str]] = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

#: The stand-in freeze commit's date, 2027-01-01T00:00:00Z. Every invented commit is dated from it.
FROZEN_AT: Final[int] = 1_798_761_600
DAY: Final[int] = 86_400
SALT: Final[str] = "c" * 64
#: The invented severity export, in the harness's schema 3: four rows in descending theta,
#: and the three cuts anchored on them, which is the smallest shape its loader accepts.
_SEVERITY: Final[bytes] = (
    json.dumps(
        {
            "schema_version": "3",
            "anchor_set_version": "1",
            "comparison_log_hash": "0" * 64,
            "run_id": "invented",
            "calibration": {
                "critical_high": "An invented boundary.",
                "high_medium": "An invented boundary.",
                "medium_low": "An invented boundary.",
            },
            "severities": [
                {
                    "id": "HF-01",
                    "severity": "critical",
                    "theta": 3.0,
                    "content_hash": "a" * 64,
                    "appearances": 10,
                    "informative": 8,
                },
                {
                    "id": "HF-02",
                    "severity": "high",
                    "theta": 1.0,
                    "content_hash": "b" * 64,
                    "appearances": 10,
                    "informative": 8,
                },
                {
                    "id": "HF-03",
                    "severity": "medium",
                    "theta": -1.0,
                    "content_hash": "c" * 64,
                    "appearances": 10,
                    "informative": 8,
                },
                {
                    "id": "HF-04",
                    "severity": "low",
                    "theta": -3.0,
                    "content_hash": "d" * 64,
                    "appearances": 10,
                    "informative": 8,
                },
            ],
            "unplaced": [],
            "cuts": [
                {
                    "name": "critical_high",
                    "above_id": "HF-01",
                    "below_id": "HF-02",
                    "gap": 2.0,
                    "between": [],
                },
                {
                    "name": "high_medium",
                    "above_id": "HF-02",
                    "below_id": "HF-03",
                    "gap": 2.0,
                    "between": [],
                },
                {
                    "name": "medium_low",
                    "above_id": "HF-03",
                    "below_id": "HF-04",
                    "gap": 2.0,
                    "between": [],
                },
            ],
        },
        indent=2,
    )
    + "\n"
).encode()
EXPECTED: Final[chain.FrozenHeader] = chain.FrozenHeader(
    rubric_version="1", prompt_template_hash="a" * 64, rubric_hash="c" * 64
)
#: A committed log name: the harness writes <started_at, colons as hyphens>-<mode>.jsonl, and
#: §6 step 4 commits it under the heldout- prefix the gate admits.
RUN_LOG: Final[str] = "runs/heldout-2027-01-03T10-00-00Z-live.jsonl"

_RUBRIC: Final[str] = "version: '1'\nentries:\n  - id: A-alpha\n  - id: J-beta\n"

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

_CALL_90: Final[str] = """\
  1 |  0:01.000 |  0:09.400 | AGENT       | Thanks for calling, how can I help with the
    |           |           |             | marigold question today?
  2 |  0:10.000 |  0:10.000 | STATE       | long_value := marigold
  3 |  0:11.000 |  0:14.000 | CALLER      | Single line.
"""

_CALL_91: Final[str] = """\
  1 |  0:01.000 |  0:02.000 | CALLER      | Second call.
  2 |  0:03.000 |  0:04.000 | AGENT       | Still the second call.
"""

_FINDINGS: Final[str] = """\
findings:
  - id: HF-01
    call_ref: CALL-90
    owner: agent
    observation: An invented observation that cites event 3.
    evidence:
      - 'event 1 — "how can I help with the marigold question"'
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
  - id: HF-03
    call_ref: CALL-90
    owner: data
    observation: A third invented observation.
    evidence:
      - 'event 3 — "Single line."'
    consequence: A third invented consequence.
    detectable_by: human
    tier: defect
  - id: HF-04
    call_ref: CALL-91
    owner: agent
    observation: A fourth invented observation.
    evidence:
      - 'event 1 — "Second call."'
    consequence: A fourth invented consequence.
    detectable_by: judge
    tier: defect
"""


def _traces(freeze: str, *, uncovered: str = "[HF-02]") -> str:
    return (
        f"{worksheet.FREEZE_TAG}: '{freeze}'\n"
        "traces:\n"
        "  A-alpha: [HF-01, HF-03]\n"
        "  J-beta: [HF-04]\n"
        f"uncovered: {uncovered}\n"
        "calls_without_findings: []\n"
    )


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        env={**os.environ, **_IDENTITY, **(env or {})},
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _dated(days: int) -> dict[str, str]:
    stamp = f"{FROZEN_AT + days * DAY} +0000"
    return {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}


def _stand_in_harness(root: Path, *, tagged: bool = True) -> tuple[Path, str]:
    """A stand-in harness repository: one commit, dated `FROZEN_AT`, and tagged if asked."""
    (root / "corpus").mkdir(parents=True)
    (root / "HELDOUT_SET").write_text("CALL-90\nCALL-91\n", encoding="utf-8")
    (root / "corpus" / "findings.yaml").write_text("findings:\n  - id: F-01\n", encoding="utf-8")
    (root / "rubric.yaml").write_text(_RUBRIC, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "frozen", env=_dated(0))
    if tagged:
        _git(root, "tag", worksheet.FREEZE_TAG)
    return root, _git(root, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def stand_in(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """One stand-in harness for the module, since its commit runs the machine's hooks."""
    return _stand_in_harness(tmp_path_factory.mktemp("stand-in") / "harness")


@dataclass(frozen=True)
class Commit:
    """One invented commit: its message, what it writes (None deletes), and its day after F."""

    message: str
    files: dict[str, bytes | None]
    day: int


def _repository(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    return root


def _extend(repo: Path, *commits: Commit) -> list[str]:
    """Append `commits` to `main` in one fast-import, and return their ids, oldest first."""
    tip = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "-q", "--verify", "refs/heads/main"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    stream = bytearray()
    for mark, commit in enumerate(commits, start=1):
        when = FROZEN_AT + commit.day * DAY
        message = commit.message.encode("utf-8")
        stream += f"commit refs/heads/main\nmark :{mark}\n".encode()
        stream += f"author test <test@example.com> {when} +0000\n".encode()
        stream += f"committer test <test@example.com> {when} +0000\n".encode()
        stream += f"data {len(message)}\n".encode() + message + b"\n"
        parent = f":{mark - 1}" if mark > 1 else tip
        if parent:
            stream += f"from {parent}\n".encode()
        for path, content in commit.files.items():
            if content is None:
                stream += f"D {path}\n".encode()
            else:
                stream += f"M 100644 inline {path}\ndata {len(content)}\n".encode()
                stream += content + b"\n"
        stream += b"\n"
    subprocess.run(
        ["git", "-C", str(repo), "fast-import", "--quiet"],
        input=bytes(stream),
        check=True,
        capture_output=True,
    )
    return _git(repo, "rev-list", "--reverse", f"-n{len(commits)}", "refs/heads/main").split()


def _base() -> Commit:
    files: dict[str, bytes | None] = {"README.md": b"invented\n"}
    for call_id, events in (("CALL-90", _CALL_90), ("CALL-91", _CALL_91)):
        files[f"transcripts/{call_id}.txt"] = (_HEADER.format(call_id=call_id) + events).encode()
    return Commit("Add the invented calls", files, day=-30)


def _labels(freeze: str) -> tuple[bytes, bytes]:
    return _FINDINGS.encode(), _traces(freeze).encode()


def _seal(
    freeze: str,
    findings: bytes,
    traces: bytes,
    *,
    severity: bytes = _SEVERITY,
    day: int = 1,
    trailer: str | None = None,
    names: str | None = None,
) -> Commit:
    """The manifest over the three sealed files, with its `Rubric-Frozen` trailer."""
    digests = {
        chain.SEALED[0]: chain.digest(SALT, findings),
        chain.SEALED[1]: chain.digest(SALT, traces),
        chain.SEALED[2]: chain.digest(SALT, severity),
    }
    manifest = chain.render_manifest(names or freeze, digests).encode()
    message = f"Seal the held-out labels\n\n{chain.RUBRIC_FROZEN}: {trailer or freeze}\n"
    return Commit(message, {chain.MANIFEST: manifest}, day)


def _log(
    cites: str,
    *,
    day: int = 2,
    template_hash: str = EXPECTED.prompt_template_hash,
    rubric_hash: str | None = EXPECTED.rubric_hash,
) -> Commit:
    """A judged run's log: a header record citing `cites`, then one invented record.

    `rubric_hash=None` leaves the key out, which is every log a harness before D183 wrote.
    """
    header = {
        "record": "header",
        "rubric_version": EXPECTED.rubric_version,
        "prompt_template_hash": template_hash,
        "corpus_version": "0.0.0",
        "artifact_hash": "b" * 64,
        "mode": "live",
        "started_at": "2027-01-03T00:00:00Z",
        chain.LABELS_MANIFEST: cites,
    }
    if rubric_hash is not None:
        header[chain.RUBRIC_HASH] = rubric_hash
    body = json.dumps(header) + "\n" + json.dumps({"record": "invented"}) + "\n"
    return Commit("Add the held-out judged run", {RUN_LOG: body.encode()}, day)


def _reveal(
    judged: str | None,
    findings: bytes,
    traces: bytes,
    *,
    severity: bytes = _SEVERITY,
    day: int = 3,
) -> Commit:
    trailer = f"\n\n{chain.JUDGED_RUN}: {judged}" if judged else ""
    files: dict[str, bytes | None] = {
        chain.SEALED[0]: findings,
        chain.SEALED[1]: traces,
        chain.SEALED[2]: severity,
        chain.SALT: SALT.encode(),
    }
    return Commit(f"Reveal the held-out labels{trailer}\n", files, day)


def _severity_document() -> dict[str, Any]:
    """The invented export as a mapping, for a control to break one field of."""
    document: dict[str, Any] = json.loads(_SEVERITY)
    return document


def _severity_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _expected(_harness: Path, _freeze: str) -> chain.FrozenHeader:
    return EXPECTED


def _gate(repo: Path, harness: Path) -> tuple[str, list[str]]:
    return chain.gate(repo, harness, frozen=_expected)


# --------------------------------------------------------------------------
# A clean chain, and nothing at all
# --------------------------------------------------------------------------


@requires_harness
def test_a_clean_chain_holds_at_every_stage(stand_in: tuple[Path, str], tmp_path: Path) -> None:
    """S0 to S3, each checked as it is reached: the baseline every control breaks one step of."""
    harness, freeze = stand_in
    findings, traces = _labels(freeze)
    repo = _repository(tmp_path / "repo")

    _extend(repo, _base())
    assert _gate(repo, harness) == ("S0", [])
    (sealed,) = _extend(repo, _seal(freeze, findings, traces))
    assert _gate(repo, harness) == ("S1", [])
    (judged,) = _extend(repo, _log(sealed))
    assert _gate(repo, harness) == ("S2", [])
    _extend(repo, _reveal(judged, findings, traces))
    assert _gate(repo, harness) == ("S3", [])


def test_nothing_sealed_holds_even_without_a_harness(tmp_path: Path) -> None:
    """S0 asks nothing of the harness, so a missing checkout cannot make it fail."""
    repo = _repository(tmp_path / "repo")
    _extend(repo, _base())
    assert chain.gate(repo, None) == ("S0", [])


def test_anything_sealed_without_the_tag_is_red(tmp_path: Path) -> None:
    """A manifest with no resolvable freeze behind it is a label before the freeze (D21)."""
    repo = _repository(tmp_path / "repo")
    _extend(repo, _base(), _seal("e" * 40, b"findings\n", b"traces\n"))
    stage, problems = chain.gate(repo, None)
    assert stage == "S1"
    assert any("does not resolve" in problem for problem in problems), problems


# --------------------------------------------------------------------------
# One step out of order at a time
# --------------------------------------------------------------------------


def _trailer_names_another_commit(repo: Path, freeze: str) -> None:
    _extend(repo, _base(), _seal(freeze, *_labels(freeze), trailer="0" * 40))


def _manifest_names_another_commit(repo: Path, freeze: str) -> None:
    _extend(repo, _base(), _seal(freeze, *_labels(freeze), names="0" * 40))


def _sealed_before_the_freeze(repo: Path, freeze: str) -> None:
    _extend(repo, _base(), _seal(freeze, *_labels(freeze), day=-1))


def _run_before_the_manifest(repo: Path, freeze: str) -> None:
    _extend(repo, _base(), _log("0" * 40, day=1), _seal(freeze, *_labels(freeze), day=2))


def _run_citing_a_superseded_manifest(repo: Path, freeze: str) -> None:
    findings, traces = _labels(freeze)
    sealed = _extend(repo, _base(), _seal(freeze, findings, traces))[1]
    _extend(repo, _seal(freeze, findings, traces + b"# re-sealed\n", day=2))
    _extend(repo, _log(sealed, day=3))


def _run_under_another_template(repo: Path, freeze: str) -> None:
    sealed = _extend(repo, _base(), _seal(freeze, *_labels(freeze)))[1]
    _extend(repo, _log(sealed, template_hash="d" * 64))


def _run_under_another_rubric(repo: Path, freeze: str) -> None:
    sealed = _extend(repo, _base(), _seal(freeze, *_labels(freeze)))[1]
    _extend(repo, _log(sealed, rubric_hash="e" * 64))


def _run_naming_no_rubric(repo: Path, freeze: str) -> None:
    sealed = _extend(repo, _base(), _seal(freeze, *_labels(freeze)))[1]
    _extend(repo, _log(sealed, rubric_hash=None))


def _manifest_edited_after_the_run(repo: Path, freeze: str) -> None:
    findings, traces = _labels(freeze)
    sealed = _extend(repo, _base(), _seal(freeze, findings, traces))[1]
    _extend(repo, _log(sealed))
    _extend(repo, _seal(freeze, findings, traces + b"# edited\n", day=3))


def _a_path_the_chain_does_not_admit(repo: Path, _freeze: str) -> None:
    _extend(repo, _base(), Commit("Add notes", {"labels/notes.md": b"invented\n"}, day=1))


def _plaintext_committed_then_deleted(repo: Path, freeze: str) -> None:
    findings, _ = _labels(freeze)
    _extend(
        repo,
        _base(),
        Commit("Add the findings", {chain.SEALED[0]: findings}, day=1),
        Commit("Remove the findings", {chain.SEALED[0]: None}, day=2),
    )


_BEFORE_THE_REVEAL: Final[dict[str, tuple[Callable[[Path, str], None], str]]] = {
    "a manifest whose trailer names another commit": (
        _trailer_names_another_commit,
        "without exactly the trailer",
    ),
    "a manifest naming another commit": (_manifest_names_another_commit, "as the freeze commit"),
    "a manifest committed before the freeze": (
        _sealed_before_the_freeze,
        "dated no later than the freeze commit",
    ),
    "a run log before the manifest": (_run_before_the_manifest, "before any labels/MANIFEST"),
    "a run log citing a superseded manifest": (
        _run_citing_a_superseded_manifest,
        "the manifest in force when it was committed",
    ),
    "a run log under another template": (
        _run_under_another_template,
        "prompt_template_hash is not the template's",
    ),
    "a run log under another rubric": (
        _run_under_another_rubric,
        "rubric_hash is not rubric.yaml's",
    ),
    "a run log naming no rubric": (_run_naming_no_rubric, "names no rubric_hash"),
    "a manifest edited after a run": (
        _manifest_edited_after_the_run,
        f"after {RUN_LOG} was committed",
    ),
    "a path the chain does not admit": (
        _a_path_the_chain_does_not_admit,
        "not a path the phase-5 chain admits",
    ),
    "plaintext committed and deleted before sealing": (
        _plaintext_committed_then_deleted,
        "before any reveal",
    ),
}


@pytest.mark.parametrize("case", sorted(_BEFORE_THE_REVEAL))
def test_each_step_out_of_order_before_the_reveal_turns_the_gate_red(
    stand_in: tuple[Path, str], tmp_path: Path, case: str
) -> None:
    """§7's controls up to the run log, each built on a clean chain with one step broken."""
    harness, freeze = stand_in
    build, phrase = _BEFORE_THE_REVEAL[case]
    repo = _repository(tmp_path / "repo")
    build(repo, freeze)

    _, problems = _gate(repo, harness)
    assert any(phrase in problem for problem in problems), problems


def _plaintext_before_a_run(repo: Path, freeze: str) -> None:
    findings, traces = _labels(freeze)
    sealed = _extend(repo, _base(), _seal(freeze, findings, traces))[1]
    _extend(repo, _reveal(sealed, findings, traces, day=2))


def _plaintext_that_does_not_recompute(repo: Path, freeze: str) -> None:
    findings, traces = _labels(freeze)
    sealed = _extend(repo, _base(), _seal(freeze, findings, traces))[1]
    (judged,) = _extend(repo, _log(sealed))
    _extend(repo, _reveal(judged, findings + b"# edited\n", traces))


def _labels_edited_after_the_reveal(repo: Path, freeze: str) -> None:
    findings, traces = _labels(freeze)
    sealed = _extend(repo, _base(), _seal(freeze, findings, traces))[1]
    (judged,) = _extend(repo, _log(sealed))
    _extend(
        repo,
        _reveal(judged, findings, traces),
        Commit("Edit the findings", {chain.SEALED[0]: findings + b"# edited\n"}, day=4),
    )


def _a_call_left_unaccounted_for(repo: Path, freeze: str) -> None:
    findings = _FINDINGS.split("  - id: HF-02")[0].encode()
    traces = _traces(freeze, uncovered="[]").encode()
    sealed = _extend(repo, _base(), _seal(freeze, findings, traces))[1]
    (judged,) = _extend(repo, _log(sealed))
    _extend(repo, _reveal(judged, findings, traces))


def _a_reveal_without_its_trailer(repo: Path, freeze: str) -> None:
    findings, traces = _labels(freeze)
    sealed = _extend(repo, _base(), _seal(freeze, findings, traces))[1]
    _extend(repo, _log(sealed))
    _extend(repo, _reveal(None, findings, traces))


def _severity_that_does_not_recompute(repo: Path, freeze: str) -> None:
    findings, traces = _labels(freeze)
    sealed = _extend(repo, _base(), _seal(freeze, findings, traces))[1]
    (judged,) = _extend(repo, _log(sealed))
    _extend(repo, _reveal(judged, findings, traces, severity=_SEVERITY + b"{}\n"))


_AT_THE_REVEAL: Final[dict[str, tuple[Callable[[Path, str], None], str]]] = {
    "plaintext before a run log": (
        _plaintext_before_a_run,
        "which is not an earlier commit adding a run log",
    ),
    "plaintext that does not recompute": (
        _plaintext_that_does_not_recompute,
        "labels/findings.yaml: does not recompute",
    ),
    "severity that does not recompute": (
        _severity_that_does_not_recompute,
        "labels/severity.json: does not recompute",
    ),
    "labels edited after the reveal": (_labels_edited_after_the_reveal, "after the reveal"),
    "a call neither referenced nor listed": (
        _a_call_left_unaccounted_for,
        "labels: CALL-91: no finding references this held-out call",
    ),
    "a reveal without its Judged-Run trailer": (
        _a_reveal_without_its_trailer,
        "without exactly one 'Judged-Run",
    ),
}


@requires_harness
@pytest.mark.parametrize("case", sorted(_AT_THE_REVEAL))
def test_each_step_out_of_order_at_the_reveal_turns_the_gate_red(
    stand_in: tuple[Path, str], tmp_path: Path, case: str
) -> None:
    """§7's controls from the reveal on, where the committed labels are validated as well."""
    harness, freeze = stand_in
    build, phrase = _AT_THE_REVEAL[case]
    repo = _repository(tmp_path / "repo")
    build(repo, freeze)

    stage, problems = _gate(repo, harness)
    assert stage == "S3"
    assert any(phrase in problem for problem in problems), problems


def test_a_moved_tag_turns_the_gate_red(tmp_path: Path) -> None:
    """A tag moved after sealing breaks the trailer and the header both (§9)."""
    harness, freeze = _stand_in_harness(tmp_path / "harness")
    repo = _repository(tmp_path / "repo")
    _extend(repo, _base(), _seal(freeze, *_labels(freeze)))
    assert _gate(repo, harness) == ("S1", [])

    (harness / "rubric.yaml").write_text(_RUBRIC + "  - id: A-gamma\n", encoding="utf-8")
    _git(harness, "commit", "-q", "-a", "-m", "an entry after the freeze", env=_dated(5))
    _git(harness, "tag", "-f", worksheet.FREEZE_TAG)

    stage, problems = _gate(repo, harness)
    assert stage == "S1"
    assert any("a tag moved after sealing" in problem for problem in problems), problems
    assert any("without exactly the trailer" in problem for problem in problems), problems


# --------------------------------------------------------------------------
# The pieces the gate is built from
# --------------------------------------------------------------------------


@requires_harness
def test_the_frozen_template_hash_is_the_one_the_harness_recorded_at_its_freeze() -> None:
    """Computed by the frozen commit's own code, it matches a run log the harness had committed.

    The reference run log in the harness at F was recorded by F's harness, so its header is
    independent evidence of what the frozen template hashes to.
    """
    assert HARNESS is not None
    freeze = worksheet.freeze_commit(HARNESS)
    if freeze is None:
        pytest.skip(f"{worksheet.FREEZE_TAG} is not fetched into this harness checkout")
    listed = _git(HARNESS, "ls-tree", "-r", "--name-only", freeze, "--", "runs").splitlines()
    references = [path for path in listed if re.fullmatch(r"runs/reference-[^/]+\.jsonl", path)]
    if not references:
        pytest.skip("the harness had committed no reference run log at its freeze")

    recorded = chain.run_log_header(chain.show(HARNESS, freeze, references[0]))
    assert recorded is not None
    computed = chain.frozen_header(HARNESS, freeze)
    assert computed.rubric_version == recorded["rubric_version"]
    assert computed.prompt_template_hash == recorded["prompt_template_hash"]


@requires_harness
def test_the_frozen_rubric_hash_agrees_with_the_harness_s_own_function(tmp_path: Path) -> None:
    """The gate hashes a blob and the harness hashes a file; the two must agree (D186).

    The reference run log at F cannot settle this one, the way it settles the template hash:
    `rubric_hash` is written on a held-out run and on no other, so no log the harness has
    committed carries one. Its own function is the evidence available, and a copy of the rule
    would be two things that can disagree.
    """
    assert HARNESS is not None
    freeze = worksheet.freeze_commit(HARNESS)
    if freeze is None:
        pytest.skip(f"{worksheet.FREEZE_TAG} is not fetched into this harness checkout")
    try:
        from harness.core.rubric import rubric_hash
    except ImportError:
        pytest.skip("this harness checkout is older than the rubric hash")

    blob = chain.show(HARNESS, freeze, "rubric.yaml")
    written = tmp_path / "rubric.yaml"
    written.write_bytes(blob)

    assert chain.rubric_digest(blob) == rubric_hash(written)


def test_the_corpus_version_is_one_line_with_no_blanks() -> None:
    """The harness stamps it into every held-out header, committed here unmodified (D182)."""
    text = (REPO_ROOT / "CORPUS_VERSION").read_text(encoding="utf-8")
    lines = text.splitlines()

    assert text.endswith("\n")
    assert len(lines) == 1, "one line, so what the header carries is unambiguous"
    assert lines[0] != "", "the harness refuses a blank corpus version"
    assert lines[0] == lines[0].strip()
    assert " " not in lines[0]


def test_a_rendered_manifest_parses_back_and_a_malformed_one_does_not() -> None:
    """The five lines §4 specifies, and nothing that merely resembles them."""
    digests = {path: "d" * 64 for path in chain.SEALED}
    rendered = chain.render_manifest("f" * 40, digests)
    assert chain.parse_manifest(rendered) == (chain.Manifest("f" * 40, digests), [])

    malformed = (
        rendered.replace("\n", "\r\n"),
        rendered + "an extra line\n",
        rendered.replace(chain.SEALED[1], chain.SEALED[0]),
        rendered.replace("f" * 40, "f" * 39),
    )
    for text in malformed:
        manifest, problems = chain.parse_manifest(text)
        assert manifest is None
        assert problems


def test_the_digest_is_the_one_the_manifest_recipe_computes(tmp_path: Path) -> None:
    """§4 says a reader can verify with `cat` and `sha256sum`; this runs that recipe."""
    shell, sha256sum = shutil.which("sh"), shutil.which("sha256sum")
    if shell is None or sha256sum is None:
        pytest.skip("no sh and sha256sum to run the recipe with")
    data = b"findings: []\n"
    (tmp_path / "SALT").write_bytes(SALT.encode())
    (tmp_path / "findings.yaml").write_bytes(data)

    result = subprocess.run(
        [shell, "-c", "(cat SALT; echo; cat findings.yaml) | sha256sum"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.split()[0] == chain.digest(SALT, data)


# --------------------------------------------------------------------------
# Seal and reveal, run for real
# --------------------------------------------------------------------------


def _checked_out(repo: Path) -> Path:
    """The working tree brought to HEAD without a hook, because seal and reveal read files."""
    _git(repo, "read-tree", "-u", "--reset", "HEAD")
    return repo


def _held_out(root: Path) -> Path:
    repo = _repository(root)
    _extend(repo, _base())
    return _checked_out(repo)


def _private_labels(
    root: Path, freeze: str, *, traces: str | None = None, severity: bytes | None = _SEVERITY
) -> Path:
    root.mkdir(parents=True)
    (root / "findings.yaml").write_text(_FINDINGS, encoding="utf-8", newline="\n")
    written = traces if traces is not None else _traces(freeze)
    (root / "traces.yaml").write_text(written, encoding="utf-8", newline="\n")
    if severity is not None:
        (root / "severity.json").write_bytes(severity)
    return root


def _commit_the_manifest(repo: Path, freeze: str, *, day: int = 1) -> str:
    """What seal wrote, committed as §6 step 2 says: alone, with its trailer."""
    message = f"Seal the held-out labels\n\n{chain.RUBRIC_FROZEN}: {freeze}\n"
    (sealed,) = _extend(
        repo, Commit(message, {chain.MANIFEST: (repo / chain.MANIFEST).read_bytes()}, day)
    )
    return sealed


def test_seal_refuses_before_the_freeze(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No tag, no manifest (D21)."""
    untagged, _ = _stand_in_harness(tmp_path / "harness", tagged=False)
    repo = _repository(tmp_path / "repo")
    _extend(repo, _base())

    assert manifest_tool.seal(repo=repo, harness=untagged, private=tmp_path / "private") == 1
    assert not (repo / chain.MANIFEST).exists()
    assert worksheet.FREEZE_TAG in capsys.readouterr().err


@requires_harness
def test_seal_refuses_labels_that_do_not_validate(
    stand_in: tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Invalid labels get no manifest, and no salt is made for them either."""
    harness, freeze = stand_in
    repo = _held_out(tmp_path / "repo")
    broken = _traces(freeze).replace("  J-beta: [HF-04]\n", "")
    private = _private_labels(tmp_path / "private", freeze, traces=broken)

    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 1
    assert not (repo / chain.MANIFEST).exists()
    assert not (private / "SALT").exists(), "a salt was made for labels that were never sealed"
    assert "absent: J-beta" in capsys.readouterr().err


@requires_harness
def test_seal_refuses_without_the_severity_export(
    stand_in: tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The bands are sealed with the labels (O-10), or nothing is sealed at all."""
    harness, freeze = stand_in
    repo = _held_out(tmp_path / "repo")
    private = _private_labels(tmp_path / "private", freeze, severity=None)

    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 1
    assert not (repo / chain.MANIFEST).exists()
    assert "does not exist" in capsys.readouterr().err

    (private / "severity.json").write_bytes(b"bands, but not JSON\n")
    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 1
    assert not (repo / chain.MANIFEST).exists()
    assert "not JSON" in capsys.readouterr().err


@requires_harness
def test_seal_refuses_an_export_the_harness_would_not_read(
    stand_in: tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Schema 3 and the ids are the harness's rules, checked by its own loader (harness D181)."""
    harness, freeze = stand_in
    repo = _held_out(tmp_path / "repo")

    older = _severity_document()
    older["schema_version"] = "1"
    private = _private_labels(tmp_path / "old", freeze, severity=_severity_bytes(older))
    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 1
    assert "refuses it" in capsys.readouterr().err

    stranger = _severity_document()
    stranger["severities"][0]["id"] = "HF-99"
    stranger["cuts"][0]["above_id"] = "HF-99"
    private = _private_labels(tmp_path / "stranger", freeze, severity=_severity_bytes(stranger))
    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 1
    assert "are not findings of this set: HF-99" in capsys.readouterr().err
    assert not (repo / chain.MANIFEST).exists()


@requires_harness
def test_seal_writes_a_salt_and_a_manifest_that_recompute(
    stand_in: tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A salt of 64 hex characters and no newline, digests that recompute, an honest re-seal."""
    harness, freeze = stand_in
    repo = _held_out(tmp_path / "repo")
    private = _private_labels(tmp_path / "private", freeze)

    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 0
    salt = (private / "SALT").read_bytes().decode("ascii")
    assert chain.valid_salt(salt)
    manifest, problems = chain.parse_manifest((repo / chain.MANIFEST).read_text(encoding="utf-8"))
    assert problems == []
    assert manifest is not None
    assert manifest.freeze_sha == freeze
    for path in chain.SEALED:
        assert manifest.digests[path] == chain.digest(
            salt, (private / Path(path).name).read_bytes()
        )

    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 0
    assert "nothing changed" in capsys.readouterr().out

    first = (repo / chain.MANIFEST).read_bytes()
    extended = _traces(freeze) + "# re-sealed\n"
    (private / "traces.yaml").write_text(extended, encoding="utf-8", newline="\n")
    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 0
    assert (repo / chain.MANIFEST).read_bytes() != first
    assert (private / "SALT").read_bytes().decode("ascii") == salt, "re-sealing replaced the salt"
    assert "re-sealed" in capsys.readouterr().out


@requires_harness
def test_seal_refuses_once_a_run_is_committed(
    stand_in: tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The manifest a run was measured against never changes, so there is no re-seal after one."""
    harness, freeze = stand_in
    repo = _held_out(tmp_path / "repo")
    private = _private_labels(tmp_path / "private", freeze)
    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 0
    _extend(repo, _log(_commit_the_manifest(repo, freeze)))

    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 1
    assert "never changes" in capsys.readouterr().err


@requires_harness
def test_reveal_waits_for_a_committed_run_citing_the_current_manifest(
    stand_in: tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing sealed, sealed with no run, and a run citing a superseded manifest: all refused."""
    harness, freeze = stand_in
    repo = _held_out(tmp_path / "repo")
    private = _private_labels(tmp_path / "private", freeze)

    def reveal() -> int:
        return manifest_tool.reveal(repo=repo, harness=harness, private=private, frozen=_expected)

    assert reveal() == 1, "nothing is sealed"
    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 0
    first = _commit_the_manifest(repo, freeze)
    assert reveal() == 1, "sealed, but no run is committed"

    extended = _traces(freeze) + "# re-sealed\n"
    (private / "traces.yaml").write_text(extended, encoding="utf-8", newline="\n")
    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 0
    _commit_the_manifest(repo, freeze, day=2)
    _extend(repo, _log(first, day=3))
    assert reveal() == 1, "the only run cites a superseded manifest"

    assert not any((repo / path).exists() for path in chain.PLAINTEXT)
    assert "no committed run log cites" in capsys.readouterr().err


@requires_harness
def test_reveal_refuses_labels_changed_since_sealing(
    stand_in: tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only what was sealed is published: an edit after sealing stops the reveal (§9)."""
    harness, freeze = stand_in
    repo = _held_out(tmp_path / "repo")
    private = _private_labels(tmp_path / "private", freeze)
    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 0
    _extend(repo, _log(_commit_the_manifest(repo, freeze)))

    (private / "findings.yaml").write_text(
        _FINDINGS + "# changed\n", encoding="utf-8", newline="\n"
    )
    revealed = manifest_tool.reveal(repo=repo, harness=harness, private=private, frozen=_expected)
    assert revealed == 1
    assert not any((repo / path).exists() for path in chain.PLAINTEXT)
    assert "no longer recompute" in capsys.readouterr().err


@requires_harness
def test_seal_and_reveal_write_a_chain_the_gate_accepts(
    stand_in: tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """What the two commands write, committed as §6 says, holds at every stage, and only once."""
    harness, freeze = stand_in
    repo = _held_out(tmp_path / "repo")
    private = _private_labels(tmp_path / "private", freeze)

    assert manifest_tool.seal(repo=repo, harness=harness, private=private) == 0
    sealed = _commit_the_manifest(repo, freeze)
    assert _gate(repo, harness) == ("S1", [])
    (judged,) = _extend(repo, _log(sealed))
    assert _gate(repo, harness) == ("S2", [])

    revealed = manifest_tool.reveal(repo=repo, harness=harness, private=private, frozen=_expected)
    assert revealed == 0
    assert f"{chain.JUDGED_RUN}: {judged}" in capsys.readouterr().out
    files: dict[str, bytes | None] = {path: (repo / path).read_bytes() for path in chain.PLAINTEXT}
    message = f"Reveal the held-out labels\n\n{chain.JUDGED_RUN}: {judged}\n"
    _extend(repo, Commit(message, files, day=3))
    assert _gate(repo, harness) == ("S3", [])

    again = manifest_tool.reveal(repo=repo, harness=harness, private=private, frozen=_expected)
    assert again == 1, "the labels were revealed a second time"
