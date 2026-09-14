"""The ledger-to-findings generator, `tools/make_label_findings.py`.

Every draft and ruling here is invented for the test, so a failure can print
nothing a label says. Every refusal also asserts that none of the text it was
handed comes back in what it printed.

What wins where is exercised on four drafts: a plain accept, an
accept-with-edits, a reject, and an id that sorts wrongly as text. Each rule of
the ledger is then broken alone. The refusals before the freeze and inside this
repository outside `private/` are exercised too, and so is the renderer's own
check, by a fold planted to lose a word.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest

if TYPE_CHECKING:  # pragma: no cover - types only
    from collections.abc import Callable

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import make_label_findings as generator  # noqa: E402
import make_label_worksheet as worksheet  # noqa: E402

HARNESS: Final[Path | None] = worksheet.harness_root()

if HARNESS is not None:  # pragma: no cover - import plumbing
    with contextlib.suppress(ImportError):
        import harness  # noqa: F401
    if "harness" not in sys.modules:
        sys.path.insert(0, str(HARNESS / "src"))

requires_harness = pytest.mark.skipif(
    HARNESS is None,
    reason="the harness repository was not found, so there is no loader to generate against",
)

Documents = list[dict[str, Any]]

_IDENTITY: Final[dict[str, str]] = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

#: Text planted in the invented documents, and the misspellings the refusals plant. None of it
#: may come back in anything printed.
_PLANTED: Final[tuple[str, ...]] = ("marigold", "rejcet", "owners", "defct")


def _stand_in_harness(root: Path, *, tagged: bool) -> Path:
    """A git repository standing in for the harness: one commit, the freeze tag only if asked."""
    root.mkdir(parents=True)
    (root / "README.md").write_text("stand-in harness\n", encoding="utf-8")
    commands = [["init", "-q"], ["add", "README.md"], ["commit", "-q", "-m", "stand-in"]]
    if tagged:
        commands.append(["tag", worksheet.FREEZE_TAG])
    for command in commands:
        subprocess.run(
            ["git", "-C", str(root), *command],
            check=True,
            env={**os.environ, **_IDENTITY},
            capture_output=True,
        )
    return root


@pytest.fixture(scope="module")
def stand_in(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One tagged stand-in for the module, since every git command is a process to start."""
    return _stand_in_harness(tmp_path_factory.mktemp("stand-in") / "harness", tagged=True)


def _drafts() -> Documents:
    """Four invented drafts, out of order, each carrying "marigold" in its text."""
    return [
        {
            "id": "HF-10",
            "call_ref": "CALL-90",
            "observation": "The tenth invented marigold observation.",
            "evidence": ['event 1 — "marigold"'],
            "consequence": "A marigold consequence ending in the newline a block scalar leaves.\n",
        },
        {
            "id": "HF-02",
            "call_ref": "CALL-90",
            "observation": "The second invented marigold observation.",
            "evidence": ['event 2 — "marigold"', "call record — duration_ms 20000"],
            "consequence": "A marigold consequence whose line breaks\nare content.",
        },
        {
            "id": "HF-01",
            "call_ref": "CALL-91",
            "observation": "The first invented marigold observation.",
            "evidence": ['event 1 — "marigold"'],
            "consequence": "A marigold consequence.",
        },
        {
            "id": "HF-03",
            "call_ref": "CALL-91",
            "observation": "An invented marigold observation the owner rejects.",
            "evidence": ['event 2 — "marigold"'],
            "consequence": "A marigold consequence.",
        },
    ]


def _rulings() -> Documents:
    """One ruling per draft: accept, accept-with-edits, reject, accept."""
    return [
        {
            "id": "HF-01",
            "verdict": "accept",
            "origin": "both",
            "note": "An invented note.",
            "owner": "agent",
            "detectable_by": "judge",
            "tier": "defect",
        },
        {
            "id": "HF-02",
            "verdict": "accept-with-edits",
            "origin": "owner",
            "note": "An invented note.",
            "owner": "data",
            "detectable_by": "assert",
            "tier": "question",
            "observation": "The second marigold observation, as the owner reworded it.",
        },
        {"id": "HF-03", "verdict": "reject", "origin": "reviewer", "note": "An invented note."},
        {
            "id": "HF-10",
            "verdict": "accept",
            "origin": "reviewer",
            "note": "An invented note.",
            "owner": "platform",
            "detectable_by": "human",
            "tier": "defect",
        },
    ]


def _labels(root: Path, drafts: Documents, rulings: Documents) -> Path:
    """Both inputs, saved as YAML."""
    import yaml

    root.mkdir(parents=True, exist_ok=True)
    for name, document in (
        ("drafts", {"findings": drafts}),
        ("ledger", {"adjudications": rulings}),
    ):
        (root / f"{name}.yaml").write_text(
            yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    return root


def _repeated(printed: str) -> list[str]:
    return [word for word in _PLANTED if word in printed.lower()]


def test_the_generator_refuses_before_the_freeze(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No tag, no findings: held-out findings exist only after the freeze (D21)."""
    untagged = _stand_in_harness(tmp_path / "harness", tagged=False)
    labels = tmp_path / "labels"
    labels.mkdir()
    for name in ("drafts.yaml", "ledger.yaml"):
        (labels / name).write_text("placeholder: true\n", encoding="utf-8")

    assert generator.build(harness=untagged, labels=labels) == 1
    assert not (labels / "findings.yaml").exists()
    assert worksheet.FREEZE_TAG in capsys.readouterr().err


def test_the_generator_refuses_the_repository_outside_private(stand_in: Path) -> None:
    """Inside this repository only `private/` is gitignored, so labels anywhere else are refused."""
    labels = REPO_ROOT / "labels-probe"
    assert not labels.exists()

    assert generator.build(harness=stand_in, labels=labels) == 2
    assert not labels.exists()


@requires_harness
def test_the_findings_are_projected_from_the_drafts_and_the_ledger(
    stand_in: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ruled fields from the ledger, text from the ledger where it has some, rejects dropped.

    The harness's loader refuses any key beyond its eight, so loading the result also shows
    that `verdict`, `origin` and `note` were projected out.
    """
    from harness.core.findings import load_findings

    labels = _labels(tmp_path / "labels", _drafts(), _rulings())
    assert generator.build(harness=stand_in, labels=labels) == 0

    findings = {finding.id: finding for finding in load_findings(labels / "findings.yaml")}
    assert list(findings) == ["HF-01", "HF-02", "HF-10"], "numeric order, and the reject dropped"

    edited = findings["HF-02"]
    ruled = (edited.owner.value, edited.detectable_by.value, edited.tier.value)
    assert ruled == ("data", "assert", "question")
    assert edited.observation == "The second marigold observation, as the owner reworded it."
    assert edited.evidence == ('event 2 — "marigold"', "call record — duration_ms 20000")
    assert edited.consequence == "A marigold consequence whose line breaks\nare content."
    assert findings["HF-10"].consequence == (
        "A marigold consequence ending in the newline a block scalar leaves."
    )

    text = (labels / "findings.yaml").read_text(encoding="utf-8")
    assert f"# {worksheet.FREEZE_TAG}: {worksheet.freeze_commit(stand_in)}\n" in text
    assert "    consequence: |-\n      A marigold consequence whose line breaks\n" in text, (
        "line breaks that are content must render as a literal block (D22)"
    )

    printed = capsys.readouterr()
    assert "3 findings from 4 drafts, 1 rejected" in printed.out
    assert not _repeated(printed.out + printed.err)


@requires_harness
def test_check_holds_the_file_to_its_inputs_byte_for_byte(stand_in: Path, tmp_path: Path) -> None:
    """Absent, current, re-encoded, and stale after a ruling changes: only current passes."""
    labels = _labels(tmp_path / "labels", _drafts(), _rulings())
    out = labels / "findings.yaml"

    assert generator.build(harness=stand_in, labels=labels, check=True) == 1, "not generated yet"
    assert generator.build(harness=stand_in, labels=labels) == 0
    assert generator.build(harness=stand_in, labels=labels, check=True) == 0

    out.write_bytes(out.read_bytes().replace(b"\n", b"\r\n"))
    assert generator.build(harness=stand_in, labels=labels, check=True) == 1, "line endings moved"

    assert generator.build(harness=stand_in, labels=labels) == 0
    rulings = _rulings()
    rulings[3]["tier"] = "question"
    _labels(labels, _drafts(), rulings)
    assert generator.build(harness=stand_in, labels=labels, check=True) == 1, "a ruling changed"


@requires_harness
def test_a_row_that_would_not_read_back_as_written_is_refused(
    stand_in: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control for the renderer's own check: a fold that loses a word must be caught."""

    def lossy(text: str, indent: str) -> str:
        words = str(text).split()
        return indent + " ".join(words[:-1] or words)

    monkeypatch.setattr(generator, "_fold", lossy)
    labels = _labels(tmp_path / "labels", _drafts(), _rulings())

    assert generator.build(harness=stand_in, labels=labels) == 1
    assert not (labels / "findings.yaml").exists()
    assert "would not read back as written" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Every rule of the ledger, broken alone
# --------------------------------------------------------------------------


def _drop_the_last_ruling(documents: dict[str, Documents]) -> None:
    documents["rulings"].pop()


def _rule_on_a_missing_draft(documents: dict[str, Documents]) -> None:
    documents["rulings"].append({**documents["rulings"][0], "id": "HF-11"})


def _rule_twice(documents: dict[str, Documents]) -> None:
    documents["rulings"].append(dict(documents["rulings"][0]))


def _misspell_a_verdict(documents: dict[str, Documents]) -> None:
    documents["rulings"][2]["verdict"] = "rejcet"


def _accept_with_text(documents: dict[str, Documents]) -> None:
    documents["rulings"][0]["observation"] = "A marigold rewrite."


def _reject_with_a_ruling(documents: dict[str, Documents]) -> None:
    documents["rulings"][2]["tier"] = "defect"


def _accept_without_a_tier(documents: dict[str, Documents]) -> None:
    del documents["rulings"][0]["tier"]


def _give_an_unknown_origin(documents: dict[str, Documents]) -> None:
    documents["rulings"][0]["origin"] = "owners"


def _leave_out_the_note(documents: dict[str, Documents]) -> None:
    del documents["rulings"][0]["note"]


def _misspell_a_key(documents: dict[str, Documents]) -> None:
    documents["rulings"][0]["detectible_by"] = "judge"


def _rule_a_value_the_harness_lacks(documents: dict[str, Documents]) -> None:
    documents["rulings"][0]["tier"] = "defct"


def _blank_the_replacement_text(documents: dict[str, Documents]) -> None:
    documents["rulings"][1]["observation"] = "  "


def _classify_in_a_draft(documents: dict[str, Documents]) -> None:
    documents["drafts"][0]["tier"] = "defect"


def _misshape_a_draft_id(documents: dict[str, Documents]) -> None:
    documents["drafts"][0]["id"] = "F-10"


def _reject_everything(documents: dict[str, Documents]) -> None:
    for ruling in documents["rulings"]:
        for key in ("owner", "detectable_by", "tier", "observation"):
            ruling.pop(key, None)
        ruling["verdict"] = "reject"


_REFUSALS: Final[dict[str, tuple[Callable[[dict[str, Documents]], None], str]]] = {
    "a draft with no ruling": (_drop_the_last_ruling, "no ruling on HF-10"),
    "a ruling with no draft": (_rule_on_a_missing_draft, "no draft carries: HF-11"),
    "two rulings on one draft": (_rule_twice, "a second ruling on the same draft"),
    "a misspelled verdict": (_misspell_a_verdict, "verdict must be one of"),
    "an accept carrying text": (_accept_with_text, "use accept-with-edits"),
    "a reject carrying a ruling": (_reject_with_a_ruling, "a reject carries tier"),
    "an accept missing a ruled field": (_accept_without_a_tier, "missing tier"),
    "an unknown origin": (_give_an_unknown_origin, "origin must be one of"),
    "a ruling with no note": (_leave_out_the_note, "note is required"),
    "a misspelled key": (_misspell_a_key, "unknown key(s) detectible_by"),
    "a value the harness does not have": (_rule_a_value_the_harness_lacks, "tier must be one of"),
    "blank replacement text": (_blank_the_replacement_text, "replacement observation must be"),
    "a draft that classifies": (_classify_in_a_draft, "only the owner's ledger states"),
    "a draft id of the wrong shape": (_misshape_a_draft_id, "draft 1: its id is not shaped HF-NN"),
    "every draft rejected": (_reject_everything, "every draft was rejected"),
}


@requires_harness
@pytest.mark.parametrize("case", sorted(_REFUSALS))
def test_each_ledger_rule_refuses_alone_and_writes_nothing(
    stand_in: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    """One broken rule, one problem naming it, no file, and none of the text repeated."""
    mutate, phrase = _REFUSALS[case]
    documents = {"drafts": _drafts(), "rulings": _rulings()}
    mutate(documents)
    labels = _labels(tmp_path / "labels", documents["drafts"], documents["rulings"])

    assert generator.build(harness=stand_in, labels=labels) == 1
    assert not (labels / "findings.yaml").exists()
    printed = capsys.readouterr()
    assert "refused: 1 problem(s)" in printed.err, printed.err
    assert phrase in printed.err, printed.err
    assert not _repeated(printed.out + printed.err)
