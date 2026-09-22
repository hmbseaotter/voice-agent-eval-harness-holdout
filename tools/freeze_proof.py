"""The harness's published freeze proof, read as objects rather than as a ref.

Why this exists. The gate used to find the freeze commit by resolving the tag
`rubric-frozen-v1` in the harness checkout, and to read the frozen rubric, the frozen
`cli.py` and the frozen `src` tree by asking git for them at that commit. Neither works
against the published harness: it is a snapshot (harness D208), so the freeze commit is
not reachable in its log, and a ref reaching it cannot be pushed without dragging the
private history behind it.

What replaced them is `freeze-proof/` in the harness (harness D209), which publishes the
commit, its annotated tag, the trees on the path to the rubric and the template, and the
whole frozen `src` subtree -- every file named by its own object id, so a file name is a
checksum. This module reads that directory and recomputes every id it uses, under git's
own rule `sha1("<type> <size>\\0" + bytes)`.

That recomputation is the point, and it is stronger than the tag it replaces. A tag is a
name that can be moved; an object id cannot be moved onto different bytes without a SHA-1
second preimage. The holdout's seal commit cites the freeze commit's SHA, and a proof whose
commit object hashes to that SHA is the opening of that commitment -- which is what
discharges O-12.

Nothing here reads the harness's history. A checkout with no history at all, or none that
reaches the freeze, verifies exactly as well as a full clone.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: The directory the harness publishes the proof in, and the object store inside it.
PROOF_DIR: Final[str] = "freeze-proof"
OBJECTS_DIR: Final[str] = "objects"

#: The tag name the proof's tag object must carry. The published snapshot deliberately
#: does not carry a ref by this name -- reusing it for the snapshot's own first commit is
#: what made the freeze appear to postdate the seal -- so this is asserted against the tag
#: object's bytes instead, which is the only place the name is now load-bearing.
FREEZE_TAG: Final[str] = "rubric-frozen-v1"

#: The four files the proof publishes outside its object store, and the object kind each
#: holds. Trees carry NUL bytes and raw 20-byte ids, so they are base64; the commit and the
#: tag are raw bytes a reader can open.
_CORE: Final[dict[str, tuple[str, bool]]] = {
    "freeze-commit.txt": ("commit", False),
    "freeze-tag.txt": ("tag", False),
    "freeze-tree.b64": ("tree", True),
    "freeze-prompts-tree.b64": ("tree", True),
}

_SHA1: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}")
_TREE_LINE: Final[re.Pattern[bytes]] = re.compile(rb"^tree ([0-9a-f]{40})$", re.M)
_TAG_OBJECT: Final[re.Pattern[bytes]] = re.compile(rb"^object ([0-9a-f]{40})$", re.M)
_TAG_NAME: Final[re.Pattern[bytes]] = re.compile(rb"^tag (.+)$", re.M)
_COMMITTER: Final[re.Pattern[bytes]] = re.compile(rb"^committer .*? (\d+) [+-]\d{4}$", re.M)

#: A tree entry's mode for a subdirectory. Git writes it without the leading zero.
_DIR_MODE: Final[str] = "40000"


class ProofError(Exception):
    """A question the published objects could not answer, reported rather than guessed past."""


def object_id(kind: str, data: bytes) -> str:
    """The id git would give `data` as an object of `kind`: sha1 over the header and bytes."""
    return hashlib.sha1(f"{kind} {len(data)}\0".encode() + data, usedforsecurity=False).hexdigest()


def parse_tree(data: bytes) -> list[tuple[str, str, str]]:
    """A tree object's entries as `(mode, name, id)`, in the order git stored them."""
    entries: list[tuple[str, str, str]] = []
    index = 0
    while index < len(data):
        try:
            space = data.index(b" ", index)
            nul = data.index(b"\0", space)
        except ValueError as error:
            raise ProofError("a tree object is truncated") from error
        ident = data[nul + 1 : nul + 21]
        if len(ident) != 20:
            raise ProofError("a tree object ends mid-entry")
        entries.append(
            (
                data[index:space].decode("ascii", "replace"),
                data[space + 1 : nul].decode("utf-8", "replace"),
                ident.hex(),
            )
        )
        index = nul + 21
    return entries


@dataclass(frozen=True, slots=True)
class FreezeProof:
    """The published objects, every id already recomputed against the bytes it names."""

    objects: Path
    commit_sha: str
    tag_sha: str
    commit: bytes
    root_tree: bytes
    prompts_tree: bytes

    @property
    def committed_at(self) -> int:
        """The freeze commit's committer timestamp, read out of the commit object itself.

        The gate compares label commits against this. It is a self-asserted field, as every
        git date is, and it is not what secures the ordering: the seal commit citing this
        commit's SHA is. It is read here so that no history has to be present to read it.
        """
        found = _COMMITTER.search(self.commit)
        if found is None:
            raise ProofError("the freeze commit object carries no committer timestamp")
        return int(found.group(1))

    def read(self, ident: str, kind: str) -> bytes:
        """The object `ident`, refused unless its bytes hash back to the id asked for.

        Two trees are published outside the object store, as named files: the frozen root
        tree and the `prompts` tree beneath it. A walk down from the root reaches them by id
        like any other object, so they are answered here rather than made a special case of
        every caller. They are hashed on the way out exactly as a stored object is.
        """
        if _SHA1.fullmatch(ident) is None:
            raise ProofError(f"{ident!r} is not an object id")
        if kind == "tree":
            for published in (self.root_tree, self.prompts_tree):
                if object_id("tree", published) == ident:
                    return published
        path = self.objects / (f"{ident}.b64" if kind == "tree" else ident)
        if not path.is_file():
            raise ProofError(f"{PROOF_DIR}/{OBJECTS_DIR}/ has no {kind} {ident[:12]}")
        data = _decode(path) if kind == "tree" else path.read_bytes()
        if (got := object_id(kind, data)) != ident:
            raise ProofError(f"{path.name}: recomputes to {got[:12]}, not the id it is named by")
        return data

    def entry(self, tree: bytes, name: str) -> tuple[str, str]:
        """The `(mode, id)` a tree gives `name`, or a refusal naming what it does hold."""
        for mode, found, ident in parse_tree(tree):
            if found == name:
                return mode, ident
        held = ", ".join(sorted(entry[1] for entry in parse_tree(tree))) or "nothing"
        raise ProofError(f"the frozen tree names no {name!r}; it holds {held}")

    def blob_at(self, *path: str) -> str:
        """The blob id at `path` under the frozen root tree, walked one tree at a time."""
        tree, walked = self.root_tree, ""
        for name in path[:-1]:
            mode, ident = self.entry(tree, name)
            walked = f"{walked}{name}/"
            if mode != _DIR_MODE:
                raise ProofError(f"{walked.rstrip('/')} is not a directory in the frozen tree")
            tree = self.read(ident, "tree")
        mode, ident = self.entry(tree, path[-1])
        if mode == _DIR_MODE:
            raise ProofError(f"{walked}{path[-1]} is a directory in the frozen tree, not a file")
        return ident

    def materialize(self, tree_id: str, dest: Path) -> int:
        """Write the tree `tree_id` out under `dest`, and answer how many files it held.

        Every object is read through `read`, so a corrupted or substituted byte anywhere in
        the subtree stops the reconstruction rather than producing a tree that merely looks
        right. Modes beyond directory and regular file are refused rather than approximated:
        the frozen `src` holds neither a symlink nor a submodule, and quietly materializing
        one as a plain file would make the reconstruction a different thing from the tree.
        """
        dest.mkdir(parents=True, exist_ok=True)
        written = 0
        for mode, name, ident in parse_tree(self.read(tree_id, "tree")):
            if mode == _DIR_MODE:
                written += self.materialize(ident, dest / name)
            elif mode in {"100644", "100755"}:
                (dest / name).write_bytes(self.read(ident, "blob"))
                written += 1
            else:
                raise ProofError(f"{name}: mode {mode} in the frozen tree is not a plain file")
        return written


def _decode(path: Path) -> bytes:
    """A published tree object, from the base64 the harness wraps at 76 columns.

    The line breaks are stripped before decoding rather than tolerated by it: `validate=True`
    is what refuses a file with stray characters in it, and it counts a newline as one, so
    decoding the wrapped bytes directly would mean giving up the check to keep the wrapping.
    """
    packed = b"".join(path.read_bytes().split())
    try:
        return base64.b64decode(packed, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ProofError(f"{path.name}: not the base64 a tree object is published as") from error


def _show(harness: Path, revision: str, path: str) -> bytes:
    """`git show <revision>:<path>` in `harness`, as committed bytes rather than as a file."""
    result = subprocess.run(
        ["git", "-C", str(harness), "show", f"{revision}:{path}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ProofError(
            f"git show {revision[:12]}:{path} failed in {harness}: "
            f"{detail[-1] if detail else 'no message'}"
        )
    return result.stdout


def frozen_bytes(harness: Path, freeze_sha: str, path: str) -> bytes:
    """The bytes `path` held at the freeze, proved however this harness checkout can prove it.

    Two checkouts have to work. A clone of the private working repository still reaches the
    freeze commit, so git answers directly. The published snapshot does not, so the bytes are
    taken from its HEAD and held to the blob id the frozen tree names -- which fails loudly if
    the file has moved since the freeze, rather than quietly reading today's version.

    Read out of git in both cases, never off disk: a CRLF checkout hashes differently, and the
    id being compared is of committed bytes.
    """
    proof = load(harness)
    if proof is None:
        return _show(harness, freeze_sha, path)
    if proof.commit_sha != freeze_sha:
        raise ProofError(f"the freeze proof opens {proof.commit_sha[:12]}, not {freeze_sha[:12]}")
    want = proof.blob_at(*path.split("/"))
    data = _show(harness, "HEAD", path)
    if (got := object_id("blob", data)) != want:
        raise ProofError(
            f"{path} at the harness's HEAD is blob {got[:12]}, but the frozen tree names "
            f"{want[:12]}; it is not the file the labels were scored against"
        )
    return data


def load(harness: Path) -> FreezeProof | None:
    """The proof in `harness`, or None when that checkout publishes none.

    None is the answer for a harness predating the proof, and the caller reports it the way
    it once reported a tag that did not resolve. Bytes that are present but do not verify are
    a `ProofError` instead: absent evidence and broken evidence are not the same finding.
    """
    root = harness / PROOF_DIR
    if not root.is_dir():
        return None
    missing = [name for name in _CORE if not (root / name).is_file()]
    if missing:
        raise ProofError(f"{PROOF_DIR}/ is present but incomplete: no {', '.join(sorted(missing))}")

    read: dict[str, tuple[bytes, str]] = {}
    for name, (kind, encoded) in _CORE.items():
        path = root / name
        data = _decode(path) if encoded else path.read_bytes()
        read[name] = (data, object_id(kind, data))

    commit, commit_sha = read["freeze-commit.txt"]
    tag, tag_sha = read["freeze-tag.txt"]
    root_tree, root_tree_id = read["freeze-tree.b64"]
    prompts_tree, prompts_tree_id = read["freeze-prompts-tree.b64"]

    named = _TAG_OBJECT.search(tag)
    if named is None or named.group(1).decode() != commit_sha:
        raise ProofError("the tag object does not name the published freeze commit")
    tag_name = _TAG_NAME.search(tag)
    if tag_name is None or tag_name.group(1).decode() != FREEZE_TAG:
        raise ProofError(f"the tag object is not {FREEZE_TAG}")
    tree_line = _TREE_LINE.search(commit)
    if tree_line is None or tree_line.group(1).decode() != root_tree_id:
        raise ProofError("the freeze commit does not name the published root tree")

    proof = FreezeProof(
        objects=root / OBJECTS_DIR,
        commit_sha=commit_sha,
        tag_sha=tag_sha,
        commit=commit,
        root_tree=root_tree,
        prompts_tree=prompts_tree,
    )
    _, prompts_id = proof.entry(root_tree, "prompts")
    if prompts_id != prompts_tree_id:
        raise ProofError("the root tree does not name the published prompts tree")
    return proof
