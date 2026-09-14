#!/usr/bin/env python3
"""Seal the held-out labels before the judged run, and reveal them after it.

    python tools/label_manifest.py seal
    python tools/label_manifest.py reveal

WHY THIS EXISTS
---------------
`PHASE-5-LABELS.md` §6 steps 1 and 5. Sealing commits to the labels without
publishing them: `labels/MANIFEST` holds a salted digest of each file, while the
files and the salt stay in `private/labels/`. Revealing publishes them once a
committed run log cites that manifest, and only while they still recompute to
it.

Both commands refuse whatever `tools/label_gate.py` would fail. The gate runs in
CI after a push, and by then the push has published it.

SEAL
----
Refuses before the freeze, once a run log is committed (the manifest a run was
measured against never changes), when plaintext is already in `labels/`, and
when the labels do not pass `tools/validate_labels.py`. Generates
`private/labels/SALT` when it is absent: 32 random bytes as 64 lowercase hex
characters and no newline, so §4's `cat` recipe reproduces each digest.
Re-sealing before any run rewrites the manifest, and says so.

REVEAL
------
Refuses unless:
- `labels/MANIFEST` is committed unchanged, and names the commit the tag names now;
- a committed run log cites the last commit to touch it, and passes the gate's
  run-log checks;
- the private labels still validate and recompute to it.

Then it copies the two files and the salt into `labels/`, recomputes from the
copies, and names the commit the reveal's `Judged-Run` trailer must cite. The
private copies stay: publishing does not need them gone, and a move interrupted
halfway could lose the only copy.

WHAT IT PRINTS
--------------
Counts and commit ids, never a label.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent))

from label_gate import (
    JUDGED_RUN,
    MANIFEST,
    PLAINTEXT,
    RUBRIC_FROZEN,
    RUN_LOG,
    SEALED,
    GateError,
    committed_at,
    digest,
    frozen_header,
    log_problems,
    parse_manifest,
    render_manifest,
    show,
    touching,
    tracked,
    valid_salt,
)
from make_label_worksheet import FREEZE_TAG, REPO_ROOT, freeze_commit, harness_root
from validate_labels import LABELS, validate

if TYPE_CHECKING:  # pragma: no cover - types only
    from collections.abc import Callable

    from label_gate import FrozenHeader


def _refuse(message: str, problems: list[str] | None = None) -> int:
    print(f"error: {message}", file=sys.stderr)
    for problem in problems or []:
        print(f"  {problem}", file=sys.stderr)
    return 1


def _private(private: Path, path: str) -> Path:
    """The private copy of a committed path: `labels/SALT` lives at `<private>/SALT`."""
    return private / Path(path).name


def seal(*, repo: Path = REPO_ROOT, harness: Path, private: Path = LABELS) -> int:
    """Write `labels/MANIFEST` over the private labels, or refuse and say why."""
    freeze = freeze_commit(harness)
    if freeze is None:
        return _refuse(
            f"{FREEZE_TAG} does not resolve in {harness}; labels are sealed only after the "
            "freeze (D21)"
        )
    try:
        paths = tracked(repo)
    except GateError as error:
        return _refuse(str(error))
    logs = [path for path in paths if RUN_LOG.fullmatch(path)]
    if logs:
        return _refuse(
            f"{len(logs)} judged run log(s) already committed, and the manifest a run was measured "
            "against never changes (§7). A label error found now goes in an erratum beside the "
            "sealed labels (§9)."
        )
    present = [path for path in PLAINTEXT if path in paths or (repo / path).exists()]
    if present:
        return _refuse(f"{', '.join(present)} already exist; sealing comes before any plaintext")

    problems, summary = validate(
        "all", harness=harness, freeze_sha=freeze, labels=private, transcripts=repo / "transcripts"
    )
    if problems:
        return _refuse(f"the labels in {private} do not validate, so nothing was sealed", problems)

    salt_path = _private(private, "SALT")
    made = not salt_path.exists()
    if made:
        with salt_path.open("xb") as handle:
            handle.write(secrets.token_hex(32).encode("ascii"))
    salt = salt_path.read_bytes().decode("ascii", "replace")
    if not valid_salt(salt):
        return _refuse(f"{salt_path} is not 64 lowercase hex characters without a newline")

    digests = {path: digest(salt, _private(private, path).read_bytes()) for path in SEALED}
    rendered = render_manifest(freeze, digests).encode("utf-8")
    target = repo / MANIFEST
    previous = target.read_bytes() if target.exists() else None
    if previous == rendered:
        print(
            f"{MANIFEST} already seals these labels under {FREEZE_TAG} {freeze[:12]}; "
            "nothing changed"
        )
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rendered)
    verb = "re-sealed" if previous is not None else "sealed"
    salted = ", with a new salt" if made else ""
    print(f"{verb} {MANIFEST} under {FREEZE_TAG} {freeze[:12]}{salted}. {summary}")
    print(
        f"next: commit only {MANIFEST}, with the trailer '{RUBRIC_FROZEN}: {freeze}', push, and "
        "wait for CI before the judged run (§6 step 2)"
    )
    return 0


def reveal(
    *,
    repo: Path = REPO_ROOT,
    harness: Path,
    private: Path = LABELS,
    frozen: Callable[[Path, str], FrozenHeader] = frozen_header,
) -> int:
    """Copy the sealed labels into `labels/` once a committed run cites them, or refuse."""
    freeze = freeze_commit(harness)
    if freeze is None:
        return _refuse(
            f"{FREEZE_TAG} does not resolve in {harness}; nothing is revealed without it"
        )
    try:
        paths = tracked(repo)
        present = [path for path in PLAINTEXT if path in paths or (repo / path).exists()]
        if present:
            return _refuse(f"{', '.join(present)} already exist; the labels are revealed once")
        if MANIFEST not in paths:
            return _refuse(f"{MANIFEST} is not committed; seal, commit it, and commit a run first")
        committed = show(repo, "HEAD", MANIFEST)
        on_disk = repo / MANIFEST
        if not on_disk.is_file() or on_disk.read_bytes() != committed:
            return _refuse(
                f"{MANIFEST} differs from its committed version, which a reveal answers to"
            )
        manifest, malformed = parse_manifest(committed.decode("utf-8", "replace"))
        if manifest is None:
            return _refuse(f"{MANIFEST} is malformed", malformed)
        if manifest.freeze_sha != freeze:
            return _refuse(
                f"{MANIFEST} names {manifest.freeze_sha[:12]}, but {FREEZE_TAG} now names "
                f"{freeze[:12]}; the tag moved after sealing (§9)"
            )
        in_force = touching(repo, MANIFEST)[0]
        citing: list[str] = []
        logs = sorted(path for path in paths if RUN_LOG.fullmatch(path))
        if logs:
            expected = frozen(harness, freeze)
            for path in logs:
                commit, found = log_problems(repo, path, expected)
                if not found and not touching(repo, MANIFEST, after=commit):
                    citing.append(commit)
        if not citing:
            return _refuse(
                f"no committed run log cites the manifest committed in {in_force[:12]} and passes "
                "the gate's run-log checks (§7, S2), so the labels stay sealed"
            )
        judged = max(citing, key=lambda commit: committed_at(repo, commit))
    except GateError as error:
        return _refuse(str(error))

    problems, summary = validate(
        "all", harness=harness, freeze_sha=freeze, labels=private, transcripts=repo / "transcripts"
    )
    if problems:
        return _refuse("the private labels no longer validate, so nothing was revealed", problems)
    salt_path = _private(private, "SALT")
    salt = salt_path.read_bytes().decode("ascii", "replace") if salt_path.is_file() else ""
    if not valid_salt(salt):
        return _refuse(f"{salt_path} is missing, or not 64 lowercase hex characters")
    changed = [
        Path(path).name
        for path in SEALED
        if digest(salt, _private(private, path).read_bytes()) != manifest.digests[path]
    ]
    if changed:
        return _refuse(
            f"{', '.join(changed)} in {private} no longer recompute to {MANIFEST}: the labels "
            "changed after sealing, and only what was sealed is published (§9)"
        )

    written: list[Path] = []
    try:
        (repo / "labels").mkdir(exist_ok=True)
        for path in PLAINTEXT:
            target = repo / path
            with target.open("xb") as handle:
                handle.write(_private(private, path).read_bytes())
            written.append(target)
        copied = (repo / PLAINTEXT[-1]).read_bytes().decode("ascii", "replace")
        for path in SEALED:
            if digest(copied, (repo / path).read_bytes()) != manifest.digests[path]:
                raise OSError(f"the copy of {path} does not recompute to {MANIFEST}")
    except OSError as error:
        for target in written:
            target.unlink(missing_ok=True)
        return _refuse(f"the reveal was undone: {error}")

    print(
        f"revealed {', '.join(PLAINTEXT)}: they recompute to the manifest committed in "
        f"{in_force[:12]}. {summary}"
    )
    print(
        f"next: commit only these three files, with the trailer '{JUDGED_RUN}: {judged}', and "
        "push (§6 step 6)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seal the held-out labels, or reveal them after the judged run."
    )
    parser.add_argument("command", choices=("seal", "reveal"))
    args = parser.parse_args(argv)

    harness = harness_root()
    if harness is None:
        print(
            "error: the harness was not found, and it holds the freeze tag, the loader and the "
            "frozen rubric.\nSet HARNESS_ROOT, check it out to .harness, or clone it alongside "
            "this one.",
            file=sys.stderr,
        )
        return 1
    if args.command == "seal":
        return seal(harness=harness)
    return reveal(harness=harness)


if __name__ == "__main__":
    raise SystemExit(main())
