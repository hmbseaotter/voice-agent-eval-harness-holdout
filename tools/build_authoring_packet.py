#!/usr/bin/env python3
"""Build a curated input packet for a session authoring a held-out transcript.

    python tools/build_authoring_packet.py --harness ../voice-agent-eval-harness

WHY THIS EXISTS
---------------
The held-out set is what a judge's accuracy is measured against. A session
authoring a new transcript for it must not see the design set, because a call
written with a design call in view resembles it, and a judge measured on a
near-twin of the material it was built from scores better than it deserves --
not by cheating, but because the test case looks like the training case.

The mechanism is **modified documents, not instructions about documents.** An
allow-list saying "read these, not those" depends on obedience, exactly as a
`holdout/` directory would have. A packet whose documents no longer contain the
material cannot be disobeyed. That distinction was the correction that made the
first packet work (D83, D86 in the harness's decision record).

WHY THE LEAK SCAN IS THE GUARANTEE AND THE REDACTIONS ARE NOT
------------------------------------------------------------
The redaction list below matches exact strings in the harness's documents, and
those documents change. A pattern that stops matching would silently pass the
material through -- which is the failure this whole apparatus exists to prevent,
appearing inside the tool built to prevent it.

So the redactions are best-effort and **the scan is the gate**: after writing the
packet, every file is searched for design-set call identifiers, and any hit
fails the build with the offending lines named. A stale pattern therefore stops
the build rather than leaking. When that happens, read the reported line, add a
pattern, and run again.

This was not hypothetical on the second run: two of the five original patterns
had already gone stale within a day, because the register was edited twice for
unrelated reasons.

WHAT IT DOES NOT DO
-------------------
It writes no assignment. What the new call must contain is specific to the class
being seeded, and whoever assembles a packet knows the design set's version of
that class -- so supplying a scenario would reintroduce the resemblance the
packet exists to prevent. The README it emits carries the reusable rules and a
placeholder where the assignment goes.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Identifiers belonging to the design set. Derived from the harness's
#: `corpus/DESIGN_SET` at run time rather than hardcoded here -- a list written
#: into this file would go stale the first time the design set grew, which is
#: the defect this tool is built to avoid committing itself.
_HELD_OUT_PATTERN = re.compile(r"\bCALL-\d{2}\b")

#: Passages naming a design call, with what replaces them. Every redaction is a
#: **visible marker**, never a silent rewrite: a reader who cannot tell that
#: something was removed will believe they have the whole document, which is a
#: worse failure than the leak being closed.
#:
#: Asserted to match by `test_every_redaction_still_matches_the_harness`, as an early
#: warning and nothing more: the scan is still the gate. See the module docstring.
MARK = "**[Redacted by the packet builder: {}]**"

REDACTIONS: list[tuple[str, str]] = [
    (
        "**`transfer_to_specialist` was added for CALL-20** and is the only tool",
        "**`transfer_to_specialist`** is the only tool",
    ),
    (
        "**`escalated` was added for CALL-20**, and the gap it fills is worth recording",
        "**`escalated`** fills a gap worth recording",
    ),
    (
        # Re-targeted 2026-09-07. The harness rewrote this sentence at D89 -- it
        # had counted the calls carrying `caller_ani` and counted the wrong
        # population -- and the previous pattern, an exact string, matched
        # nothing from that moment. The leak scan is what would have caught it,
        # at the next build; `test_every_redaction_still_matches_the_harness`
        # now catches it on every run instead.
        (
            "Every design call is matched on `caller_ani` except CALL-18, which is matched on\n"
            "`booking_reference`, because the caller there is not the account holder and the "
            "number they call\nfrom is not on the account. That difference is the whole subject "
            "of that call and closing the\nvocabulary would have made it unstateable."
        ),
        (
            "Every design call is matched on `caller_ani` except one, which is matched on\n"
            "`booking_reference`, because the caller there is not the account holder and the "
            "number they call\nfrom is not on the account. "
            + MARK.format("the rest identified a design transcript and its subject")
        ),
    ),
    (
        (
            "emitted: CALL-12 carries `disclosure_ai_status` in context and no `ai_status` "
            "event, which\nis the defect F-57 states."
        ),
        "emitted. " + MARK.format("the rest identified a design transcript and a seeded finding"),
    ),
]

#: Whole lines to drop when they match, for prose that enumerates the design set
#: rather than merely mentioning one call. Regex, because these lines are edited
#: often and an exact string goes stale faster than a shape does.
LINE_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^Design set: .*$", re.MULTILINE),
        "Design set: " + MARK.format("the design set's call identifiers"),
    ),
    (
        # Re-targeted 2026-09-11. The harness extended this note past the
        # sentence the pattern ended on, so `list\.$` stopped matching and the
        # paragraph, which names a design call, passed through to the scan. It
        # now ends on the declaration line that follows the note rather than on
        # a phrase inside it, because the phrase is the part that gets edited.
        re.compile(
            r"^\*\*`corpus/DESIGN_SET` is the declaration.*?\n(?=Held-out set: )",
            re.MULTILINE | re.DOTALL,
        ),
        MARK.format("a note about the design set's declaration") + "\n",
    ),
    (
        # Not anchored to a line start: this sentence begins mid-line, and the
        # first version of this pattern anchored with `^`, matched nothing, and
        # was caught by the scan rather than by review. Shape-based on the id
        # for the same reason -- a literal identifier goes stale the next time
        # the held-out set grows.
        #
        # Runs to the end of the paragraph since 2026-09-11. It used to end on
        # the sentence about the first shared identifier, and the harness then
        # appended a second sentence about the next design call to the same
        # paragraph, which this left behind with its identifier intact.
        re.compile(r"`CALL-\d{2}` was added on .*?(?=\n[ \t]*\n|\Z)", re.DOTALL),
        MARK.format("a note on how the two sets share one numbering space"),
    ),
    (
        # Added 2026-09-11. The register explains why three kinds of name were
        # declared with an example naming a design transcript and the seeded
        # defects two of those names carry. The declarations themselves stay,
        # because they are vocabulary; only the example goes.
        re.compile(r", and one of them mattered:.*?names the canon had never seen\.", re.DOTALL),
        ". " + MARK.format("an example naming a design transcript and its seeded defects"),
    ),
    (
        # The worked example in the event model names a design transcript. This
        # lived inline in `build()` until 2026-09-07, where the staleness test
        # could not see it -- a redaction outside the list is a redaction
        # nothing checks, which is the same shape as the pattern that had
        # already gone stale.
        re.compile(r"CALL-\d{2} is the worked example.*?anyway\.", re.DOTALL),
        MARK.format("the worked example named a design transcript and its seeded defect"),
    ),
]

README = """# Authoring brief — {assignment_title}

**Read this first. This packet is deliberately incomplete, and that is its whole point.**

You are being asked to author **one transcript** for a held-out evaluation set. The packet you have
is a curated subset of a larger project, with specific passages removed. Nothing here is an
oversight
and nothing is being kept from you for secrecy.

---

## Why the packet is cut down

The set you are adding to is what a judge's accuracy will eventually be **measured against**. The
design set — the transcripts the judge is built from — already contains calls of the kind you are
being asked to write. If you read one, or a description of one, the call you write would resemble
it,
and a judge measured on a near-twin of the material it was built from scores better than it
deserves.
Not by cheating; just because the test case would look like the training case.

So the packet withholds the design transcripts and everything that describes them. Where a document
you *do* have said something about a design call, the sentence was removed and replaced with a
visible marker rather than quietly rewritten — you should always be able to tell that something is
missing rather than believe you have the whole document.

**The one thing you must not do is go looking for what was removed.** The originals are on this
machine. If you find yourself wanting them, that wanting is the signal this packet exists to create:
stop and say so rather than continuing.

**In particular, no scenario is supplied.** What the call is *about* is yours to invent. That gap is
deliberate: whoever assembled this packet knows the design set's version of this class and could not
suggest a scenario without handing you the resemblance the packet exists to prevent.

---

## What you have

```
specs/transcript-format.md    the serialization. Governs the file you will write.
specs/event-model.md          the canonical model it serializes. Passages redacted.
reference/entity-canon.md     names, venues, tools, closed vocabularies. Passages redacted.
transcripts/                  the transcripts already in this held-out set.
```

**Read the existing transcripts.** The call you write has to read as a member of that set — same
format, same entity canon, same register. Note that reading them commits this session: a session
that
has read held-out transcripts must not afterwards work on the judge's rubric or the design corpus.

---

## The assignment

{assignment}

## What the transcript must satisfy

**Every value the agent passes to a tool must have a source earlier in the call.** A tool argument
may
trace to a context value, a field of the call record, earlier caller or agent speech, the body of an
earlier event including an earlier tool result, or arithmetic over context values. A value that
first
appears in the result of the call that used it is *not* sourced. The single declared exception is
`fetch_policy(document=…)`, because a document's name is part of the tool's contract.

Two consequences worth knowing before you write rather than after:

- **No bare integer of one or two characters can pass this rule.** The speech and prior-event paths
  require three characters and the arithmetic path adds rather than subtracts. To pass a quantity,
  key the call on something already established instead — a booking reference, an identifier from a
  prior result.
- **If you use `fetch_policy`, it takes a document and no clause.**
Its result names the document and
  its real clause count, and a separate `POLICY` event records the clause the agent *applied*,
quoted
  verbatim. The policy documents are not in this packet, so ask for the clause counts rather than
  inventing one.

**Conventions the register may not state.** Ask if a call-record field's correct value is not
obvious
from the vocabulary alone. The register lists what values exist; it does not always say which one a
given situation takes, and that gap has produced a wrong field before.

**Plausibility.** Speech runs 110–185 words per minute with the median between 130 and 160. Event
indices are sequential from 1. Timestamps are monotonic and `duration_ms` is what the platform
reported, not something recomputed from the log.

## What you must not write

**No labels, and no notes about what is wrong with the call.** Whether the transcript contains a
seeded defect, and what it would be, is a later artifact for a human and must not exist anywhere —
not in a file, not in a commit message, not in a comment. This holds even though you will have a
view: write the call, not your view of it. The same applies to how the set is composed.

## When you are done

1. Run the checks in this repository: `python -m pytest tests -q`, with the harness available.
2. The workflow checks this set's membership against `HELDOUT_SET` in the harness, which names
   every held-out call. Adding one turns that step red, correctly, until the declaration names
   the new call as well — the fix is the declaration, never suppressing the step.
3. Expect a **resemblance check** afterwards, run by someone who can see both your call and the
   design set: event count, kind sequence, tool sequence, and where the defect sits. That check is
   what makes this packet's controls worth anything. Write the call you would write; do not try to
   anticipate it.
"""


def build(harness: Path, out: Path, assignment: str, assignment_title: str) -> int:
    design = {
        line.strip()
        for line in (harness / "corpus" / "DESIGN_SET").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    if not design:
        print(
            "error: the harness declares no design set; refusing to build",
            file=sys.stderr,
        )
        return 2

    if out.exists():
        shutil.rmtree(out)
    (out / "specs").mkdir(parents=True)
    (out / "reference").mkdir()
    (out / "transcripts").mkdir()

    shutil.copy2(
        harness / "specs" / "transcript-format.md",
        out / "specs" / "transcript-format.md",
    )

    for source, target in (
        (harness / "specs" / "event-model.md", out / "specs" / "event-model.md"),
        (harness / "corpus" / "entities.md", out / "reference" / "entity-canon.md"),
    ):
        text = source.read_text(encoding="utf-8")
        for old, new in REDACTIONS:
            if old in text:
                text = text.replace(old, new)
        for pattern, replacement in LINE_REDACTIONS:
            text = pattern.sub(replacement, text)
        target.write_text(text, encoding="utf-8")

    transcripts = sorted((REPO_ROOT / "transcripts").glob("CALL-*.txt"))
    for path in transcripts:
        shutil.copy2(path, out / "transcripts" / path.name)

    (out / "README.md").write_text(
        README.format(assignment=assignment, assignment_title=assignment_title),
        encoding="utf-8",
    )

    # The gate. Everything above is best-effort; this is what makes the packet
    # a mechanism rather than a promise.
    leaks: list[str] = []
    for path in sorted(out.rglob("*")):
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for ref in _HELD_OUT_PATTERN.findall(line):
                if ref in design:
                    leaks.append(
                        f"  {path.relative_to(out).as_posix()}:{number}: {line.strip()[:90]}"
                    )

    print(f"packet written to {out}")
    print(f"  {len(transcripts)} held-out transcripts, 3 harness documents, 1 brief")
    if leaks:
        # **Deleted, not just reported.** "Do not hand over this packet" is
        # advice, and this project's whole argument is that advice is not a
        # mechanism: a leaking packet left on disk beside a non-zero exit code
        # is one hurried moment away from being handed over anyway. Removing it
        # means the only packet that can reach an authoring session is one that
        # passed.
        shutil.rmtree(out, ignore_errors=True)
        print("\nLEAK: design-set identifiers survived redaction:", file=sys.stderr)
        print("\n".join(dict.fromkeys(leaks)), file=sys.stderr)
        print(
            "\nA redaction pattern has gone stale. Read the lines above, add a pattern to "
            "REDACTIONS or LINE_REDACTIONS, and run again. **The packet has been deleted** "
            "rather than left for someone to hand over by mistake.",
            file=sys.stderr,
        )
        return 1
    print("  leak scan: no design-set identifier survives")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--harness",
        type=Path,
        default=REPO_ROOT.parent / "voice-agent-eval-harness",
        help="the harness repository, checked out alongside or at .harness",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT.parent / "holdout-authoring-packet",
        help="where to write the packet (deleted and recreated)",
    )
    parser.add_argument(
        "--assignment",
        default=(
            "**Not yet written.** Replace this with what the call must contain — "
            "the class being seeded and the closed-vocabulary values that make it "
            "an instance — and no scenario."
        ),
        help="what the new transcript must contain",
    )
    parser.add_argument("--title", default="one held-out transcript")
    args = parser.parse_args(argv)

    if not (args.harness / "corpus" / "DESIGN_SET").is_file():
        print(f"error: no harness repository at {args.harness}", file=sys.stderr)
        return 2
    return build(args.harness, args.out, args.assignment, args.title)


if __name__ == "__main__":
    raise SystemExit(main())
