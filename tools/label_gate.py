#!/usr/bin/env python3
"""The phase-5 gate: labels, manifest and run logs, checked over what git records.

    python tools/label_gate.py

WHY THIS EXISTS
---------------
`PHASE-5-LABELS.md` §3 and §7. The held-out labels are sealed before the judged
run and revealed after it, and the order of those commits is the whole of what
the chain proves (D21). Kept by care, that order is a promise. This makes it a
check, run over commits rather than over a working tree, so CI turns red on any
step taken out of order. It is merged before anything is sealed (§6 step 0);
until something is, it asserts only that nothing is.

THE STAGES
----------
The stage is read from which admitted paths HEAD tracks, and each stage's checks
include the ones before it.

- S0: nothing under `labels/` or `runs/`, and no label file or salt in any commit.
- S1: `labels/MANIFEST`. Every commit that touched it carries
  `Rubric-Frozen: <F>`, where F is the commit `rubric-frozen-v1` names now, and
  is dated after F. The manifest names F and holds one digest line per sealed file.
- S2: `runs/heldout-*.jsonl`. Each log's header record names, as
  `labels_manifest`, the last commit to touch `labels/MANIFEST` before the log
  was committed. It states the rubric version and prompt-template hash the
  harness computes at F, and it never changes after it is committed.
  `labels/MANIFEST` never changes after a log is committed.
- S3: `labels/findings.yaml`, `labels/traces.yaml`, `labels/severity.json` and
  `labels/SALT`, added once and together by a commit that carries
  `Judged-Run: <C2>`, where C2 added a log that passes S2 and is an ancestor of
  the reveal. All three sealed files recompute to the manifest, the two label
  files and the severity export pass `tools/validate_labels.py`, and none of the
  four changes afterwards.

Anything else under `labels/` or `runs/` fails, whatever it is called.

A MOVED TAG
-----------
F is read from the harness checkout on every run, never from this repository. A
tag moved after sealing no longer matches the trailer and the manifest header
recorded at sealing, so S1 fails, as §9 requires.

THE TEMPLATE HASH AT F
----------------------
`prompt_template_hash` is not a file digest: the harness hashes the two halves
it sends, with comments stripped. So the gate does not reimplement it. It runs
the frozen commit's own code, from an archive of that commit, in a separate
interpreter, and a test checks that this reproduces the hash in the reference
run log the harness had committed at F.

WHAT IT PRINTS
--------------
The stage, and each problem with the commit or path it concerns. Never a label,
and nothing from a run log but its header's identifiers.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_label_worksheet import FREEZE_TAG, REPO_ROOT, freeze_commit, harness_root
from validate_labels import SEVERITY_NAME, validate

if TYPE_CHECKING:  # pragma: no cover - types only
    from collections.abc import Callable

MANIFEST: Final[str] = "labels/MANIFEST"
#: The held-out bands, exported from a `comparative-judgment` store of their own kept
#: outside both repositories (harness O-10). The chain seals its bytes and reads nothing
#: inside it: the bands are labels (D10), and their schema is the harness's to state.
SEVERITY: Final[str] = f"labels/{SEVERITY_NAME}"
SEALED: Final[tuple[str, ...]] = ("labels/findings.yaml", "labels/traces.yaml", SEVERITY)
SALT: Final[str] = "labels/SALT"
PLAINTEXT: Final[tuple[str, ...]] = (*SEALED, SALT)
RUN_LOG: Final[re.Pattern[str]] = re.compile(r"runs/heldout-[A-Za-z0-9._-]+\.jsonl")

RUBRIC_FROZEN: Final[str] = "Rubric-Frozen"
JUDGED_RUN: Final[str] = "Judged-Run"
LABELS_MANIFEST: Final[str] = "labels_manifest"

STAGES: Final[dict[str, str]] = {
    "S0": "nothing sealed",
    "S1": "sealed, no judged run committed",
    "S2": "judged run committed, labels not revealed",
    "S3": "labels revealed",
}

_MANIFEST_HEADER: Final[tuple[str, ...]] = (
    "# held-out label manifest",
    "# algorithm: sha256 over the salt's 64 hex characters, a newline, then the file's exact bytes",
)
_FREEZE_LINE: Final[re.Pattern[str]] = re.compile(rf"# {FREEZE_TAG}: ([0-9a-f]{{40}})")
_DIGEST_LINE: Final[re.Pattern[str]] = re.compile(r"([0-9a-f]{64})  (\S+)")
_COMMIT: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}")
_HEX64: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")

#: Run in a separate interpreter over an archive of the frozen commit, so that the
#: harness it imports is the frozen one and never the checkout's.
_TEMPLATE_PROBE: Final[str] = (
    "import sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import harness\n"
    "from harness.judge.prompt import load_template\n"
    "print(harness.__file__)\n"
    "print(load_template(Path(sys.argv[2])).sha256)\n"
)


class GateError(Exception):
    """A question git could not answer, reported rather than guessed past."""


@dataclass(frozen=True, slots=True)
class Manifest:
    freeze_sha: str
    digests: dict[str, str]


@dataclass(frozen=True, slots=True)
class FrozenHeader:
    """What a run log's header must state to have been judged under the frozen rubric."""

    rubric_version: str
    prompt_template_hash: str


# --------------------------------------------------------------------------
# The manifest
# --------------------------------------------------------------------------


def digest(salt: str, data: bytes) -> str:
    """sha256 over the salt's hex characters, a newline, then the file's exact bytes (§4).

    The salt file holds its 64 characters and no newline of its own, so the `cat` recipe
    in §4 hashes exactly these bytes.
    """
    return hashlib.sha256(salt.encode("ascii") + b"\n" + data).hexdigest()


def valid_salt(text: str) -> bool:
    return _HEX64.fullmatch(text) is not None


def render_manifest(freeze_sha: str, digests: dict[str, str]) -> str:
    lines = [*_MANIFEST_HEADER, f"# {FREEZE_TAG}: {freeze_sha}"]
    lines += [f"{digests[path]}  {path}" for path in SEALED]
    return "\n".join(lines) + "\n"


def parse_manifest(text: str) -> tuple[Manifest | None, list[str]]:
    """The manifest, or every way it departs from the five lines §4 specifies."""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    header = len(_MANIFEST_HEADER)
    if len(lines) != header + 1 + len(SEALED):
        return None, [f"{MANIFEST}: expected three header lines and {len(SEALED)} digest lines"]
    problems: list[str] = []
    if tuple(lines[:header]) != _MANIFEST_HEADER:
        problems.append(f"{MANIFEST}: its first two lines are not the manifest header")
    freeze = _FREEZE_LINE.fullmatch(lines[header])
    if freeze is None:
        problems.append(f"{MANIFEST}: its third line does not name a freeze commit")
    digests: dict[str, str] = {}
    for line in lines[header + 1 :]:
        match = _DIGEST_LINE.fullmatch(line)
        if match is None:
            problems.append(f"{MANIFEST}: a digest line is not a digest, two spaces and a path")
        else:
            digests[match.group(2)] = match.group(1)
    if not problems and sorted(digests) != sorted(SEALED):
        problems.append(f"{MANIFEST}: its digest lines must name {' and '.join(SEALED)}, once each")
    if problems or freeze is None:
        return None, problems
    return Manifest(freeze.group(1), digests), []


# --------------------------------------------------------------------------
# What git records
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise GateError(f"git {args[0]} failed in {repo}: {detail[-1] if detail else 'no message'}")
    return result.stdout


def _lines(repo: Path, *args: str) -> list[str]:
    return [line for line in _git(repo, *args).decode("utf-8").splitlines() if line.strip()]


def tracked(repo: Path) -> list[str]:
    """Every path HEAD tracks under `labels/` or `runs/`: what is committed, not what is on disk."""
    return _lines(repo, "ls-tree", "-r", "--name-only", "HEAD", "--", "labels", "runs")


def show(repo: Path, revision: str, path: str) -> bytes:
    return _git(repo, "show", f"{revision}:{path}")


def touching(repo: Path, *paths: str, after: str | None = None) -> list[str]:
    """Commits that changed any of `paths`, newest first; only those after `after` if given."""
    return _lines(repo, "log", "--format=%H", f"{after}..HEAD" if after else "HEAD", "--", *paths)


def adding(repo: Path, path: str) -> list[str]:
    """Commits that added `path`, newest first. More than one means it was deleted and re-added."""
    return _lines(repo, "log", "--diff-filter=A", "--format=%H", "HEAD", "--", path)


def trailer(repo: Path, commit: str, key: str) -> list[str]:
    return _lines(repo, "log", "-1", f"--format=%(trailers:key={key},valueonly)", commit)


def committed_at(repo: Path, commit: str) -> int:
    return int(_git(repo, "log", "-1", "--format=%ct", commit).decode("ascii").strip())


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def manifest_before(repo: Path, commit: str) -> str | None:
    """The last commit to touch the manifest strictly before `commit`, or None."""
    if not _lines(repo, "log", "-1", "--format=%P", commit):
        return None
    found = _lines(repo, "log", "-1", "--format=%H", f"{commit}^", "--", MANIFEST)
    return found[0] if found else None


def run_log_header(data: bytes) -> dict[str, object] | None:
    """The header record a run log begins with, or None when it does not begin with one."""
    for raw in io.BytesIO(data):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if isinstance(record, dict) and record.get("record") == "header":
            return record
        return None
    return None


# --------------------------------------------------------------------------
# The harness at the freeze
# --------------------------------------------------------------------------


def _assigned(source: str, name: str) -> object:
    """The literal a module assigns to `name` at its top level, read without importing it."""
    for node in ast.parse(source).body:
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        else:
            continue
        if value is not None and any(isinstance(t, ast.Name) and t.id == name for t in targets):
            try:
                return ast.literal_eval(value)
            except ValueError as error:
                raise GateError(f"{name} is not a literal in the frozen harness") from error
    raise GateError(f"the frozen harness assigns no {name}")


def frozen_header(harness: Path, freeze_sha: str) -> FrozenHeader:
    """The rubric version and prompt-template hash the harness computes at `freeze_sha`."""
    import yaml

    rubric = yaml.safe_load(show(harness, freeze_sha, "rubric.yaml"))
    version = rubric.get("version") if isinstance(rubric, dict) else None
    if not isinstance(version, str):
        raise GateError(f"rubric.yaml at {freeze_sha[:12]} declares no version")
    cli = show(harness, freeze_sha, "src/harness/cli.py").decode("utf-8")
    template = _assigned(cli, "_DEFAULT_TEMPLATE")
    if not isinstance(template, str):
        raise GateError("the frozen harness's default template is not a path")

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        archive = _git(harness, "archive", "--format=tar", freeze_sha, "src")
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(root, filter="data")
        (root / "template.md").write_bytes(show(harness, freeze_sha, template))
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                _TEMPLATE_PROBE,
                str(root / "src"),
                str(root / "template.md"),
            ],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        output = result.stdout.strip().splitlines()
        if result.returncode != 0 or len(output) < 2:
            reason = result.stderr.strip().splitlines()
            raise GateError(
                f"the harness at {freeze_sha[:12]} could not compute its template hash: "
                f"{reason[-1] if reason else 'no output'}"
            )
        imported, template_hash = output[-2], output[-1]
        if not Path(imported).resolve().is_relative_to((root / "src").resolve()):
            raise GateError("the template hash came from a harness other than the frozen one")
    if _HEX64.fullmatch(template_hash) is None:
        raise GateError(f"the harness at {freeze_sha[:12]} produced no template hash")
    return FrozenHeader(version, template_hash)


# --------------------------------------------------------------------------
# The stages
# --------------------------------------------------------------------------


def log_problems(repo: Path, path: str, expected: FrozenHeader) -> tuple[str, list[str]]:
    """The commit that added the run log at `path`, and every way the log breaks S2."""
    added = adding(repo, path)
    commit = added[-1]
    problems: list[str] = []
    if len(added) > 1:
        problems.append(f"{path}: added more than once; a run log is committed once (§4)")
    elif touching(repo, path, after=commit):
        problems.append(f"{path}: changed after {commit[:12]} added it; a run log stays unmodified")
    header = run_log_header(show(repo, commit, path))
    if header is None:
        return commit, [*problems, f"{path}: does not begin with a run-log header record"]

    cited = header.get(LABELS_MANIFEST)
    in_force = manifest_before(repo, commit)
    if in_force is None:
        problems.append(
            f"{path}: added in {commit[:12]}, before any {MANIFEST}; a run is measured only "
            "against labels sealed first (D21)"
        )
    elif cited != in_force:
        named = cited[:12] if isinstance(cited, str) else "nothing"
        problems.append(
            f"{path}: its header cites {named} as {LABELS_MANIFEST}, but the manifest in force "
            f"when it was committed is {in_force[:12]}"
        )
    if header.get("rubric_version") != expected.rubric_version:
        problems.append(f"{path}: its rubric_version is not the rubric's at the freeze commit")
    if header.get("prompt_template_hash") != expected.prompt_template_hash:
        problems.append(
            f"{path}: its prompt_template_hash is not the template's at the freeze commit"
        )
    return commit, problems


def _committed_label_problems(repo: Path, harness: Path, freeze: str) -> list[str]:
    """`tools/validate_labels.py` over the committed labels: its `all` stage, then `severity`."""
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        archive = _git(repo, "archive", "--format=tar", "HEAD", "labels", "transcripts")
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(root, filter="data")
        problems, _ = validate(
            "all",
            harness=harness,
            freeze_sha=freeze,
            labels=root / "labels",
            transcripts=root / "transcripts",
        )
        bands, _ = validate(
            "severity",
            harness=harness,
            freeze_sha=freeze,
            labels=root / "labels",
            transcripts=root / "transcripts",
        )
    return problems + bands


def gate(
    repo: Path,
    harness: Path | None,
    *,
    frozen: Callable[[Path, str], FrozenHeader] = frozen_header,
) -> tuple[str, list[str]]:
    """The stage the chain in `repo` has reached, and every way it breaks §7."""
    try:
        return _gate(repo, harness, frozen)
    except GateError as error:
        return "?", [str(error)]


def _gate(
    repo: Path, harness: Path | None, frozen: Callable[[Path, str], FrozenHeader]
) -> tuple[str, list[str]]:
    paths = tracked(repo)
    logs = sorted(path for path in paths if RUN_LOG.fullmatch(path))
    revealed = [path for path in PLAINTEXT if path in paths]
    stage = "S3" if revealed else "S2" if logs else "S1" if MANIFEST in paths else "S0"

    problems = [
        f"{path}: not a path the phase-5 chain admits under labels/ or runs/"
        for path in paths
        if path != MANIFEST and path not in PLAINTEXT and not RUN_LOG.fullmatch(path)
    ]
    added = {path: adding(repo, path) for path in PLAINTEXT}
    if stage != "S3" and any(added.values()):
        early = sorted({commit[:12] for found in added.values() for commit in found})
        problems.append(
            f"a label file or the salt was committed in {', '.join(early)} before any reveal, "
            "which published it (§9)"
        )
    if stage == "S0":
        return stage, problems

    freeze = freeze_commit(harness) if harness is not None else None
    if harness is None or freeze is None:
        problems.append(
            f"labels/ or runs/ hold files, but {FREEZE_TAG} does not resolve in the harness "
            "checkout; nothing is sealed before the freeze (D21)"
        )
        return stage, problems
    if MANIFEST not in paths:
        problems.append(
            f"{', '.join(logs + revealed)} exist without {MANIFEST}, which every later step "
            "is measured against"
        )
        return stage, problems

    manifest, malformed = parse_manifest(show(repo, "HEAD", MANIFEST).decode("utf-8", "replace"))
    problems += malformed
    if manifest is not None and manifest.freeze_sha != freeze:
        problems.append(
            f"{MANIFEST}: names {manifest.freeze_sha[:12]} as the freeze commit, but {FREEZE_TAG} "
            f"names {freeze[:12]}; a tag moved after sealing breaks every citation (§9)"
        )
    frozen_at = committed_at(harness, freeze)
    for commit in touching(repo, MANIFEST):
        if trailer(repo, commit, RUBRIC_FROZEN) != [freeze]:
            problems.append(
                f"{commit[:12]}: touches {MANIFEST} without exactly the trailer "
                f"'{RUBRIC_FROZEN}: {freeze}'"
            )
        if committed_at(repo, commit) <= frozen_at:
            problems.append(
                f"{commit[:12]}: touches {MANIFEST} but is dated no later than the freeze commit"
            )
    if stage == "S1":
        return stage, problems

    passing: set[str] = set()
    if logs:
        expected = frozen(harness, freeze)
        for path in logs:
            commit, found = log_problems(repo, path, expected)
            problems += found
            if not found:
                passing.add(commit)
            later = touching(repo, MANIFEST, after=commit)
            if later:
                problems.append(
                    f"{MANIFEST}: changed in {later[-1][:12]}, after {path} was committed; the "
                    "manifest a run was measured against never changes (§7)"
                )
    if stage == "S2":
        return stage, problems

    missing = [path for path in PLAINTEXT if path not in paths]
    if missing:
        problems.append(
            f"{', '.join(missing)}: missing; the reveal publishes both label files and the salt"
        )
    reveals = {commit for path in revealed for commit in added[path]}
    if len(reveals) != 1 or any(len(added[path]) != 1 for path in revealed):
        problems.append("the label files and the salt were not added once, together, in one commit")
    else:
        reveal = next(iter(reveals))
        later = touching(repo, *PLAINTEXT, after=reveal)
        if later:
            problems.append(
                f"the revealed files changed in {later[-1][:12]}, after the reveal; sealed labels "
                "are never edited, and an erratum goes beside them (§9)"
            )
        judged = trailer(repo, reveal, JUDGED_RUN)
        if len(judged) != 1 or _COMMIT.fullmatch(judged[0]) is None:
            problems.append(
                f"{reveal[:12]}: reveals the labels without exactly one "
                f"'{JUDGED_RUN}: <40-character commit>' trailer"
            )
        elif judged[0] not in passing or judged[0] == reveal:
            problems.append(
                f"{reveal[:12]}: its {JUDGED_RUN} names {judged[0][:12]}, which is not an earlier "
                "commit adding a run log that passes S2"
            )
        elif not is_ancestor(repo, judged[0], reveal):
            problems.append(f"{reveal[:12]}: the judged run it names is not among its ancestors")

    if manifest is not None and not missing:
        salt = show(repo, "HEAD", SALT).decode("ascii", "replace")
        if not valid_salt(salt):
            problems.append(f"{SALT}: not 64 lowercase hex characters without a newline")
        else:
            problems += [
                f"{path}: does not recompute to {MANIFEST}"
                for path in SEALED
                if digest(salt, show(repo, "HEAD", path)) != manifest.digests[path]
            ]
        problems += [
            f"labels: {found}" for found in _committed_label_problems(repo, harness, freeze)
        ]
    return stage, problems


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description="Check the phase-5 label chain over this repository's history."
    ).parse_args(argv)

    stage, problems = gate(REPO_ROOT, harness_root())
    described = STAGES.get(stage, "unknown")
    if problems:
        print(
            f"phase-5 chain at {stage} ({described}): {len(problems)} problem(s)", file=sys.stderr
        )
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"phase-5 chain at {stage} ({described}): holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
