# voice-agent-eval-harness-holdout

The held-out corpus for [`voice-agent-eval-harness`](https://github.com/hmbseaotter/voice-agent-eval-harness).
Five transcripts. **No labels yet, deliberately.**

## Why this is a separate repository

"Held out" here means *held out from the design process*, not secret. The transcripts are public from
the day they are written; what is withheld is their ground-truth labels.

The separation is physical rather than procedural. Any session working on the harness can read
anything in the harness repository, and a rule saying "do not look at the held-out set" is a rule that
depends on obedience. A different repository is a mechanism that does not. That is the whole reason
this repository exists rather than a `holdout/` directory.

The prefix-matched name is deliberate too: the two repositories sort adjacently, so the pairing needs
no explanation.

## What is here, and what is coming

| | |
|---|---|
| **Now** | Five transcripts, `CALL-13` … `CALL-17`, in the format specified by [`specs/transcript-format.md`](https://github.com/hmbseaotter/voice-agent-eval-harness/blob/main/specs/transcript-format.md) in the main repository. |
| **Phase 5** | Human-authored labels for those transcripts, then a hash manifest of them, then the judged run, then published plaintext labels and an agreement measurement. |

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

## Reading these transcripts

They are authored to the same format and from the same entity canon as the design set, so nothing
about their surface distinguishes them. That is intentional: a held-out set a judge could recognize
as held-out would measure the wrong thing.

**The set's composition is not stated here.** How many of the five carry a seeded defect, and which,
is a fact about the labels, and the labels are what this repository withholds until phase 5. The
transcripts themselves are readable, so a reader can form their own view; what is withheld is this
repository asserting one.

That omission is load-bearing rather than tidy. D21 secures property (a) by the labels **not
existing** before `rubric-frozen-v1` — a mechanism that guards files. A sentence describing the
labels is not a file, and it would not be caught if it travelled: the main repository's held-out
scan reads every file in its tree looking for transcripts, and D37 requires it to leave prose that
merely mentions this set alone, since a check that fired on ordinary README text would be switched
off within a week. So nothing but an editorial decision separates a composition claim from the
design context this repository exists to stay out of. That decision is recorded as **D61** in the
main repository, which deliberately does not restate what was removed — a decision record made of
the labels it reasons about belongs on neither side of the split. The claim and the reasoning behind
it publish here, with the plaintext labels, at phase 5.

## What is checked here

`.github/workflows/checks.yml` asserts three things itself: that the set is exactly `CALL-13`…`CALL-17`,
that every transcript parses under the harness's current adapter with a zero unparsed-line count, and
that **no labels-shaped file exists**. The last is the one that matters. D21 withholds the labels
until after `rubric-frozen-v1`, and until now "they do not exist yet" was a promise rather than a
check — a promise about a repository nobody was running anything against, since this one had no
tests, no CI and no linter of any kind while the harness's own verifier carried a caveat saying its
contents were *"asserted there"*.

The parse step is conditional on the harness repository being checked out alongside, and says so with
a warning when it is not. A held-out set that could not be validated without a second repository
being public would be a worse trade.

`tests/test_holdout_conventions.py` adds two conventions the harness enforces and this repository
could not, because the harness's own suite globs `corpus/transcripts/` and so never reached these
five: that **no tool-call argument enters a call from nowhere the transcript records**, and that
**policy retrieval returns a whole document whose stated clause count is real**. Both were settled in
the harness on 2026-09-01, after these transcripts were written; `HOLDOUT-OBLIGATIONS.md` there exists
precisely because nothing on either side could detect the gap.

The provenance rule is a **copy**, not an import — it is a private helper in the harness's test tree,
and two copies of a rule are two things that can disagree. That weakness is stated in the module's
docstring rather than left to be discovered, and the fix, if anyone wants it, is for the rule to move
into the `harness` package so both repositories import one implementation.

## Committing to this repository

The `.gitignore` above calls the global pre-commit secret guard "the backstop" and this file "the
primary control". **The guard is not shipped here.** Install it from the main repository —
`hooks/README.md` in `voice-agent-eval-harness` — before committing anything to this tree. A clone
that takes the ignore rules and none of the enforcement is exactly the hazard D29 names, and this
repository had it unmitigated.

## License

Corpus content is CC BY 4.0, matching the main repository's corpus tree.
