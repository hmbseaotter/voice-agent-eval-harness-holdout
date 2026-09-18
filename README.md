# voice-agent-eval-harness-holdout

The held-out corpus for [`voice-agent-eval-harness`](https://github.com/hmbseaotter/voice-agent-eval-harness).
Six transcripts, and their ground-truth labels, published on 2026-09-18 after the judged run they
had been sealed against.

## Why this is a separate repository

"Held out" here means *held out from the design process*, not secret. The transcripts are public from
the day they are written; what was withheld, until a judged run had been committed against them, is
their ground-truth labels.

The separation is physical rather than procedural. Any session working on the harness can read
anything in the harness repository, and a rule saying "do not look at the held-out set" is a rule that
depends on obedience. A different repository is a mechanism that does not. That is the whole reason
this repository exists rather than a `holdout/` directory.

The prefix-matched name is deliberate too: the two repositories sort adjacently, so the pairing needs
no explanation.

## What is here

| | |
|---|---|
| **Transcripts** | Six, `CALL-13` … `CALL-17` and `CALL-21`, in the format specified by [`specs/transcript-format.md`](https://github.com/hmbseaotter/voice-agent-eval-harness/blob/main/specs/transcript-format.md) in the main repository. |
| **Labels** | `labels/`: the findings, the entry mapping, the severity export and the salt, revealed in `19673ca` and byte-identical to what `labels/MANIFEST` committed to in `e8dcc27`, before any judged run existed. [`PHASE-5-LABELS.md`](PHASE-5-LABELS.md) §13 says what they hold, and what the mapping traces and does not. |
| **The judged run** | `runs/heldout-2026-09-18T03-18-15Z-live.jsonl`, the harness's live run over the six calls, committed unmodified in `49655ca`. The agreement measurement is the harness's, reading these files in place. |

**The order is the mechanism, and it is not negotiable.** Two distinct properties are secured by two
distinct means, at two distinct moments:

**(a) The rubric was not designed against these labels.** Secured by the labels not existing until
after the `rubric-frozen-v1` tag in the main repository, with their commit message citing that
freeze commit's SHA. A SHA is a content hash, so citing it demonstrates knowledge of a specific prior
state far more strongly than two timestamps across two repositories, which are forgeable.

**(b) The labels were not tuned once judge output was visible.** Secured by a hash manifest committed
after the labels are authored but **before any held-out judged run**, with the plaintext published
afterwards. A reader can recompute the hash and confirm the labels did not move.

Property (a) is evidence. Property (b) is checkable by recomputation. They are not the same claim and
they are not secured the same way.

Both are now on the record. The freeze, the manifest, the run and the reveal are four commits, each
citing the one before it, and every digest in `labels/MANIFEST` recomputes from the published files
with nothing but `cat` and `sha256sum` — `PHASE-5-LABELS.md` §4 gives the recipe and §13 the commits.

## Reading these transcripts

They are authored to the same format and from the same entity canon as the design set, so nothing
about their surface distinguishes them. That is intentional: a held-out set a judge could recognize
as held-out would measure the wrong thing.

**The set's composition, as it was claimed before the labels existed.** This README stated it from
the first commit and withdrew it in `a83c172`, before phase 5; the sentence is restated here verbatim:

> The set deliberately includes at least one call with no seeded defect. A validation set where every
> call is defective would let a judge that reports problems everywhere score well by default, and the
> agreement figure would be meaningless.

It was written over the first five calls; CALL-21 came later. No record in either repository names
which call was authored without a seeded defect, so the claim publishes as it stood: an authoring
intent, not a label.

**What the labels say about it.** They were written blind to that intent, by the owner and an
independent reviewer, and they find something on all six calls: `calls_without_findings` is empty.
That does not refute the claim so far as it can be checked. A call authored without a seeded defect
still collects what any call here collects — an unexplained silence before the hang-up, an
authorization resting on one ZIP code, a disposition or a state the platform never records — and
those are recorded findings, not seeded ones. What the claim was *for* holds, in the form the
measurement takes. Agreement is scored per rubric entry: an entry must fire on the calls its traced
findings sit on and stay silent on the rest. No entry is traced on more than two calls, and CALL-13
and CALL-15 carry no traced finding at all, so on those two every one of the 44 entries is expected
to stay silent, and an entry that fires there is charged a false alarm. A judge that reports problems
everywhere does not score well here by default.

**Why it was withheld until the reveal.** D21 secured property (a) by the labels **not existing**
before `rubric-frozen-v1` — a mechanism that guards files. A sentence describing the labels is not a
file, and it would not have been caught if it travelled: the main repository's held-out scan must
leave prose that merely mentions this set alone (D37), since a check that fired on ordinary README
text would be switched off within a week. So nothing but an editorial decision stood between a
composition claim and the design context this repository exists to stay out of. That decision is
**D61** in the main repository, which deliberately does not restate what was removed: a decision
record made of the labels it reasons about belongs on neither side of the split.

## What is checked here

`.github/workflows/checks.yml` asserts, in its own steps, that the transcripts here are exactly the
ones the harness's `HELDOUT_SET` declares, that every transcript parses under the harness's current
adapter with a zero unparsed-line count, and that **nothing is tracked outside an allowlist** — so no
labels file can exist, whatever it is called or wherever it sits, except under `labels/` and `runs/`.
Those two hold phase 5's sealed labels and judged run, and `tools/label_gate.py` checks them over git
history in the order `PHASE-5-LABELS.md` §7 sets: nothing before the freeze, the manifest before the
run, the run before the plaintext. The allowlist and the gate are the checks that matter.
D21 withholds the labels until after `rubric-frozen-v1`, and until now "they do not exist yet" was a
promise rather than a check — a promise about a repository nobody was running anything against, since
this one had no tests, no CI and no linter of any kind while the harness's own verifier carried a
caveat saying its contents were *"asserted there"*.

Every step that reads a transcript is conditional on the harness repository being checked out
alongside, and **the build fails when it is not.** That was a warning until 2026-09-06, and the
warning is why this section was describing checks that had never run. The harness is private, the
default `GITHUB_TOKEN` is scoped to this repository alone, and so the checkout failed on every run
from the day the workflow was added — silently, because `continue-on-error` swallowed it. The build
stayed green while asserting that five files existed and nothing at all about what was in them. The
workflow said so every time, in a warning nobody read.

`HARNESS_READ_TOKEN` — a fine-grained token carrying `Contents: read` on the harness repository and
nothing else — is what makes the checkout work. It also expires, and on the day it does these checks
would go quiet again; the failing step is what turns that reversion into a red build instead of a
green one. This is the difference the repository keeps rediscovering, between a promise and a check.

`tests/test_holdout_conventions.py` ports conventions the harness enforces over its own corpus and
could not enforce over this one, because the harness's own suite globs `corpus/transcripts/` and so
never reaches this set. The first two were that **no tool-call argument enters a call from nowhere
the transcript records**, and that **policy retrieval returns a whole document whose stated clause
count is real** — both settled in the harness on 2026-09-01, after the first five were written. The
rest arrived as audits and `HOLDOUT-OBLIGATIONS.md` in the harness found conventions it checked and
this set was held to by nothing; each test's docstring says what it holds and why.

The provenance rule is a **copy**, not an import — it is a private helper in the harness's test tree,
and two copies of a rule are two things that can disagree. That weakness is stated in the module's
docstring rather than left to be discovered, and the fix, if anyone wants it, is for the rule to move
into the `harness` package so both repositories import one implementation.

## Replacing the token

`HARNESS_READ_TOKEN` is the only secret this repository holds: `Contents: Read-only` on
`voice-agent-eval-harness`, and nothing else. The paragraph above says what it is for.

**Making or replacing it** follows the harness's README, under *Access: three fine-grained tokens*,
which walks through all three tokens these repositories use: creating one at
<https://github.com/settings/personal-access-tokens/new>, installing it here as a repository secret
named exactly `HARNESS_READ_TOKEN`, and running this repository's workflow by hand to see the harness
checkout succeed. The steps are written there once rather than in each repository, so they cannot
drift apart.

**The token installed now expires on 2026-11-05.** It was installed on 2026-09-06 with a 60-day
lifetime. Whoever replaces it updates this date.

**On the day it expires** the harness checkout fails, every step that reads a transcript fails with
it, and the build goes red naming what is missing. That is the intended behavior rather than a
regression — the alternative is the one this repository shipped until 2026-09-06, a green build that
checked nothing.

## What this repository depends on

| | |
|---|---|
| [`voice-agent-eval-harness`](https://github.com/hmbseaotter/voice-agent-eval-harness) | the transcript format and the adapter these transcripts are parsed by; the conventions `tests/test_holdout_conventions.py` ports, and the patterns and constants those ports are compared with; `HELDOUT_SET`, which names this set's call identifiers over there because nothing over there can discover them; the tag `rubric-frozen-v1`, without which every phase-5 tool refuses to run; `harness.core.findings`, the gold-set schema its labels are written in; `harness.core.severity`, which reads the sealed severity export; `harness.core.rubric.rubric_hash`, the definition a test holds the gate's own hash of the frozen `rubric.yaml` to; the frozen commit's own `_DEFAULT_TEMPLATE` and `harness.judge.prompt.load_template`, which the gate runs from a `git archive` of that commit; `corpus/findings.yaml` and `corpus/DESIGN_SET`; and the two specifications and the entity register the authoring packet and the review folder redact |
| [`comparative-judgment`](https://github.com/hmbseaotter/comparative-judgment) | nothing today: it scores the *design* set's findings. Held-out severity bands are to be placed in a separate store of its own, kept outside both trees (harness O-10), and its sealed export is `labels/severity.json`, in the harness's schema 3, validated before sealing and revealed with the labels (`PHASE-5-LABELS.md` §4) |

Every one of those is a dependency **this repository's own suite cannot check**. That is what
`HOLDOUT-OBLIGATIONS.md` in the harness is for: a convention can change there and leave this set out
of step, with a green build on both sides.

**Three repositories share three tokens, and the map of which grants what lives in the harness's
README**, under *Access: three fine-grained tokens*. It is there rather than here because the harness
is the hub — the only one of the three that talks to both others.

## Committing to this repository

The `.gitignore` above calls the global pre-commit secret guard "the backstop" and this file "the
primary control". **The guard is not shipped here.** Install it from the main repository —
`hooks/README.md` in `voice-agent-eval-harness` — before committing anything to this tree. A clone
that takes the ignore rules and none of the enforcement is exactly the hazard D29 names, and this
repository had it unmitigated.

## License

Corpus content is CC BY 4.0, matching the main repository's corpus tree.
