#!/usr/bin/env python3
"""Write the names this set uses and the harness register does not declare into `NAMES`.

    python tools/declare_names.py            # write NAMES
    python tools/declare_names.py --check    # fail if it is out of date

WHY THIS EXISTS
---------------
D101 extended the harness's rule, *used implies declared*, to every kind of name
the corpus uses -- nine kinds, each held to its own category of
`corpus/entities.md`, with no kind exempted. Ported here, the rule found names
this set uses that the register does not declare under their kind: vocabulary
the held-out set introduced, not misspellings of declared names.

The owner decided on 2026-09-11 that they are declared on this side, as the agent
personas are (O-8). The register is a design-side document every design session
reads, and the held-out side owns its own vocabulary. So the check accepts a name
declared in its category of the register *or* in `NAMES`.

WHY IT IS A GENERATOR
---------------------
For the reason `declare_personas.py` is one: extraction is deterministic, so a
program writes the file and nobody reads a transcript to produce it. CI re-runs
it with --check, so a new undeclared name fails the build until the file is
regenerated and the addition committed -- the deliberate act D101 requires of a
new name, rather than a name arriving unnoticed. A name the register later
declares drops out of the file the same way.

WHAT IS COPIED, AND HOW IT IS HELD
----------------------------------
`_REGISTER_CATEGORIES` and `_declared_names` are copies of the harness's, from
`tests/test_corpus_hygiene.py`, verbatim down to their names apart from the root
the register is read from. `names_used` rewrites that check's inline loop, so
only the two patterns it reads names with are held.
`test_the_register_extractor_is_the_same_code_as_the_harness_one` holds all three.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Final

REPO_ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS = REPO_ROOT / "transcripts"
DECLARATION = REPO_ROOT / "NAMES"


def _harness_root() -> Path | None:
    for candidate in (
        Path(value) if (value := os.environ.get("HARNESS_ROOT")) else None,
        REPO_ROOT / ".harness",
        REPO_ROOT.parent / "voice-agent-eval-harness",
    ):
        if candidate is not None and (candidate / "corpus" / "policies").is_dir():
            return candidate
    return None


#: Where `_declared_names` reads the register. The harness whenever one is found.
#: When none is, `main` refuses before anything reads it and the tests that call
#: it skip, so the fallback is never read: it exists so that `_declared_names` can
#: be the harness's function with one name changed.
_REGISTER_ROOT: Path = _harness_root() or REPO_ROOT

#: The register's category headings, in the order they appear. Copied from the
#: harness, where the comment on this tuple explains why the boundary is a list.
_REGISTER_CATEGORIES: Final[tuple[str, ...]] = (
    "**Tools.**",
    "**Context variables**",
    "**State variables**",
    "**Disclosure names.**",
    "**Outcomes.**",
    "**Outcome reasons.**",
    "**System event names.**",
    "**Tool arguments.**",
    "**Tool-result detail keys.**",
)


def _declared_names(heading: str) -> set[str]:
    """Every backticked identifier declared under `heading` in the register.

    Bounded at the next category, with a dot allowed in a name: the two things
    D101 fixed in the harness's copy of this function, which this one follows
    statement for statement.
    """
    assert heading in _REGISTER_CATEGORIES, f"{heading!r} is not a register category"
    register = (_REGISTER_ROOT / "corpus" / "entities.md").read_text(encoding="utf-8")
    start = register.index(heading)
    rest = register[start + len(heading) :]

    cuts = [rest.index(other) for other in _REGISTER_CATEGORIES if other in rest]
    section = rest[: min(cuts)] if cuts else rest
    return set(re.findall(r"`([a-z_][a-z0-9_.]*)`", section))


#: How the harness's check reads a tool argument's name and a result detail's key.
ARGUMENT_NAME: Final[re.Pattern[str]] = re.compile(r"(\w+)\s*=")
DETAIL_KEY: Final[re.Pattern[str]] = re.compile(r"(\w+)=")


def names_used() -> dict[str, set[str]]:
    """`{register category: names of that kind this set uses}`, for all nine kinds."""
    harness = _harness_root()
    if harness is not None and str(harness / "src") not in sys.path:
        sys.path.insert(0, str(harness / "src"))
    from harness.core.events import (
        DisclosureEvent,
        StateEvent,
        SystemEvent,
        ToolCallEvent,
        ToolResultEvent,
    )
    from harness.corpus.text_adapter import parse_call

    used: dict[str, set[str]] = {heading: set() for heading in _REGISTER_CATEGORIES}
    for path in sorted(TRANSCRIPTS.glob("CALL-*.txt")):
        call = parse_call(path)
        used["**Context variables**"].update(name for name, _ in call.context)
        used["**Outcomes.**"].add(call.record.outcome.value)
        used["**Outcome reasons.**"].add(call.record.outcome_reason)
        for event in call.events:
            if isinstance(event, StateEvent):
                used["**State variables**"].add(event.name)
            elif isinstance(event, ToolCallEvent):
                used["**Tools.**"].add(event.name)
            elif isinstance(event, DisclosureEvent):
                used["**Disclosure names.**"].add(event.name)
            elif isinstance(event, SystemEvent):
                used["**System event names.**"].add(event.name)
            if isinstance(event, ToolCallEvent):
                used["**Tool arguments.**"].update(ARGUMENT_NAME.findall(event.arguments or ""))
            elif isinstance(event, ToolResultEvent) and event.detail:
                used["**Tool-result detail keys.**"].update(DETAIL_KEY.findall(event.detail))
    return used


def undeclared(used: dict[str, set[str]]) -> dict[str, list[str]]:
    """The names in `used` that their own category of the register does not declare."""
    found: dict[str, list[str]] = {}
    for heading, names in used.items():
        missing = sorted(names - _declared_names(heading))
        if missing:
            found[heading] = missing
    return found


HEADER = """# Names this set uses that the harness's entity register does not declare under
# their kind, one per line: the register's category heading, then the name.
#
# Generated by `tools/declare_names.py`, not written by hand. Regenerate with that
# tool and commit the result; CI re-runs it with --check, so a name this set starts
# using that the register lacks fails the build until it is declared here.
#
# Declared here rather than in the register for the reason `PERSONAS` is: it keeps
# held-out-derived names on the held-out side of the split.
"""


def render(found: dict[str, list[str]]) -> str:
    lines = [
        f"{heading} {name}" for heading in _REGISTER_CATEGORIES for name in found.get(heading, [])
    ]
    return HEADER + "\n" + "\n".join(lines) + "\n"


def read_declaration(text: str) -> dict[str, set[str]]:
    """`{category: names}` from the text of a `NAMES` file.

    A line that starts with no category is refused rather than skipped: a
    declaration the check silently ignores is an undeclared name with a file
    beside it.
    """
    declared: dict[str, set[str]] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        heading = next((h for h in _REGISTER_CATEGORIES if line.startswith(f"{h} ")), None)
        if heading is None:
            raise ValueError(f"a NAMES line names no register category: {line!r}")
        declared.setdefault(heading, set()).add(line[len(heading) :].strip())
    return declared


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit non-zero if NAMES is missing or out of date",
    )
    args = parser.parse_args(argv)

    if _harness_root() is None:
        print(
            "error: the harness was not found, and it holds both the parser and the register.\n"
            "Set HARNESS_ROOT, check it out to .harness, or clone it alongside this one.",
            file=sys.stderr,
        )
        return 1

    used = names_used()
    if not any(used.values()):
        print(
            "error: no names of any kind were read from this set. The parser or the set has "
            "changed; do not commit a declaration built on nothing.",
            file=sys.stderr,
        )
        return 1

    found = undeclared(used)
    rendered = render(found)
    summary = (
        f"{sum(len(names) for names in found.values())} undeclared in the register, "
        f"in {len(found)} of its {len(_REGISTER_CATEGORIES)} categories"
    )
    if args.check:
        if not DECLARATION.is_file():
            print("error: NAMES does not exist. Run this tool without --check.", file=sys.stderr)
            return 1
        if DECLARATION.read_text(encoding="utf-8") != rendered:
            print("error: NAMES is out of date. Re-run this tool and commit.", file=sys.stderr)
            return 1
        print(f"NAMES is current: {summary}")
        return 0

    DECLARATION.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote NAMES: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
