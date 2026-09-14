# Phase 5 in this repository: labels, manifest, run log, reveal

**Status: design, decisions recorded 2026-09-12.** Nothing in §5 or §6 starts before
`rubric-frozen-v1` exists in the harness. The tools in §12 refuse to until it does.

**Scope.** What happens in this repository from the moment the freeze tag exists until the plaintext
labels are published. It names what the harness owes as well (§8), without designing that work: this
document was written from the held-out side.

**What this document deliberately does not contain:** no label, no example drawn from a held-out
transcript, and no statement about what the labels will say (D61). Every example is a placeholder.

---

## 1. What the path must satisfy

| Source | Requirement |
|---|---|
| D21 | Strict order: freeze tag → labels authored, citing the freeze commit SHA → hash manifest committed → held-out judged run → plaintext labels published. "The ordering is the mechanism." |
| D26 | Every held-out run-log header names the manifest's **commit SHA**, and that SHA resolves in this repository. A timestamp comparison is corroboration only. |
| Spec, P5 criterion | The held-out label files' first commit is later than `rubric-frozen-v1`, asserted by a script reading git history. |
| Spec, P5 criterion | The manifest matches the published labels, asserted by recomputation. |
| Spec, prior decisions; D10 | Gold-set labels have human provenance: "Model-generated labels would make 'human agreement' measure nothing." |
| D36 | A gold set is secured by not existing until a human has made it. |
| D61 | No statement about the held-out labels appears in either repository before phase 5. |
| D12, D13 | `comparative-judgment` scores severity; D13 plans to use it on the held-out set after the freeze. |
| D14, D29 | `private/` is gitignored and blocked by a fail-closed global pre-commit guard, which was verified installed on the owner's machine on 2026-09-11. |

## 2. Facts that shape the design

1. **The harness cannot read this repository.** None of its three tokens grants read access here, so
   **every check that needs both sides runs here**, which is the same argument that placed O-4's
   cross-corpus check in this repository.
2. **A held-out run log contains held-out transcript text.** The run log stores "the exact prompt
   sent" (D128), and a judged prompt embeds the transcript. That log can **never be committed to the
   harness**. It is committed here.
3. **The run-log header has no manifest field yet.** `RunLogHeader` carries `rubric_version`,
   `prompt_template_hash`, `corpus_version`, `artifact_hash`, `mode` and `started_at`.
4. **CI cannot see the freeze tag today.** Both checkouts use the default `fetch-depth: 1`;
   `fetch-depth: 0` fetches all history and tags (confirmed against the `actions/checkout`
   documentation).
5. **Agreement is scored through the rubric's `traces_to`, and the frozen rubric names design findings
   only.** An entry must fire on the calls its traced findings sit on and stay silent elsewhere (D105,
   D125). A held-out findings file therefore needs its own mapping to the rubric's entries, or it cannot
   be scored.
6. **Session transcripts are searchable from any later session.** Verified 2026-09-12. A labeling
   discussion is readable that way until the reveal.

## 3. The chain of content hashes

```
harness                         this repository
───────                         ───────────────
F  rubric-frozen-v1 ──cited by──▶ C1  labels/MANIFEST          trailer  Rubric-Frozen: <F>
                                   │
                                   │ ancestor of, and cited by the run-log header
                                   ▼
                                  C2  runs/heldout-<stamp>.jsonl  header  labels_manifest: <C1>
                                   │
                                   │ ancestor of, and cited by trailer
                                   ▼
                                  C3  labels/findings.yaml      trailer  Judged-Run: <C2>
                                      labels/traces.yaml
                                      labels/SALT
```

Each link cites a content hash of the one before it, which is the device D21 and D26 chose. Because C1,
C2 and C3 live in **one** repository, their order is also **git ancestry**.

| Property | Secured by |
|---|---|
| (a) rubric not designed against the labels | C1 cites F, and C1's committer date is later than F's (corroboration) |
| (b) labels not tuned after judge output | C2's header cites C1; C1 is an ancestor of C2, and C2 of C3; both label files at C3 recompute to C1's manifest |
| P5 "first commit later than the tag" | C1 is the labels' first appearance in any form, and it cites F |
| D26 | C2's header names C1, which resolves in this repository by construction |

**What the chain cannot prove.** A history can be fabricated in full before it is ever pushed. The
external anchor is **GitHub's record of the C1 push**. Push C1 and let its CI run finish before the
judged run; C2's commit message cites that Actions run ID. Property (a) stays evidence; property (b) is
as strong as the C1 push record.

## 4. Artifacts and where they live

**Never committed: `private/labels/`**, gitignored and guard-blocked, with an external backup (D14).

| File | Written by | Contents |
|---|---|---|
| `notes-owner.md` | generated by `tools/make_label_worksheet.py`, filled in by the owner | each call in full, then the template (§5 step 1) |
| `notes-reviewer.md` | the independent reviewer, in the review folder | the same document, filled in separately; copied here once saved |
| `drafts.yaml` | AI | rows in the gold-set format, one per merged observation |
| `ledger.yaml` | owner | one ruling per draft: `id`, `verdict`, `owner`, `detectable_by`, `tier`, `origin`, `note` |
| `findings.yaml` | tool | generated from `drafts.yaml` and `ledger.yaml`, as the harness's `make_gold_set.py` does |
| `traces.yaml` | owner | the entry mapping (format below) |
| `SALT` | tool | 32 random bytes as 64 hex characters |

**Committed: `labels/` and `runs/`**, in the order of §3.

| Path | Commit | Contents |
|---|---|---|
| `labels/MANIFEST` | C1 | algorithm, freeze SHA, two digest lines |
| `runs/heldout-<started_at>.jsonl` | C2 | the held-out judged run log, unmodified |
| `labels/findings.yaml`, `labels/traces.yaml`, `labels/SALT` | C3 | byte-identical to what C1 sealed |

**`findings.yaml`** uses the gold-set format exactly, so `harness.core.findings` loads it: eight
required keys and no unknown ones. Held-out ids must not collide with design ids; the id format is
settled against the loader when that tooling is built.

**`traces.yaml`** is the held-out counterpart of the rubric's `traces_to`:

```yaml
rubric-frozen-v1: <40-hex freeze commit SHA>
traces:
  <rubric entry id>: [<held-out finding id>, ...]   # every entry of the frozen rubric; [] allowed
uncovered: [<held-out finding id>, ...]             # findings no entry should catch
```

Two checkable rules: the keys under `traces` equal the entry ids of the rubric **at the freeze commit**,
and every finding appears under at least one entry or in `uncovered`.

**`MANIFEST`** can be recomputed with standard tools and no project code:

```
# held-out label manifest
# algorithm: sha256 over the salt's 64 hex characters, a newline, then the file's exact bytes
# rubric-frozen-v1: <40-hex freeze commit SHA>
<64-hex digest>  labels/findings.yaml
<64-hex digest>  labels/traces.yaml
```

A reader verifies each file with `(cat labels/SALT; printf '\n'; cat labels/findings.yaml) | sha256sum`.
One salt serves both lines. It is cheap, and it keeps the commitment hiding even if a file's shape ever
makes its content guessable.

## 5. The labeling workflow (adopted 2026-09-12)

1. **Owner's worksheet.** `tools/make_label_worksheet.py` writes `private/labels/notes-owner.md`. For
   each call it shows the call record, the context and every event, in order, then an empty template.
   - It refuses before the freeze tag resolves, and records the freeze commit in its header.
   - It refuses to overwrite an existing file, because the owner writes into it.
   - It shows no proposals (D38), and no rubric: noticing comes before mapping.

   The template, with every label defined in the document's header from the harness's own docstrings:
   ```
   CALL-NN · observation <n>
     What went wrong:     (own words)
     Where:               event numbers
     Owner:               agent | platform | data | not sure
     Could be caught by:  assert | judge | human | not sure
     Defect or question:  defect | question | not sure
     Consequence:         (optional)
   ```
2. **Owner review.** The owner fills in `notes-owner.md` for all six calls.
3. **Independent review.** `tools/build_review_folder.py` builds a **review folder**, by default
   `~/holdout-review`. It holds the transcripts, the format specification, the event model and the
   entity canon (both redacted as for the authoring packet, with the same leak scan), a reviewer's copy
   of the worksheet, and `BRIEF.md`. It holds no rubric, no design findings and no seeding manifest.
   - **Where it may be built.** Never inside this repository or the harness checkout, whatever their
     ignore rules say. And never where a git repository would track what the reviewer writes: the
     destination must be outside every repository, or ignored by the one that encloses it. On the
     owner's machine the home directory is itself a repository that ignores `holdout-review`
     (checked 2026-09-12), so the default passes by that second condition.
   - It also refuses before the freeze, and will not overwrite an existing folder.
   - A **fresh Fable 5.1 session** started in that folder fills in `notes-reviewer.md`. Its opening
     message is Appendix A.
4. **Both lists are saved before either side sees the other.** The reviewer's file is then copied into
   `private/labels/`.
5. **Comparison and discussion.** A merged list, with every item tagged `origin: owner`, `reviewer` or
   `both`. The tag lives in the ledger, not the findings file, so phase 5 can report agreement with and
   without reviewer-only items.
6. **Formatting.** The AI writes `drafts.yaml` in the gold-set format: observation, verbatim evidence at
   event numbers, consequence. A validator checks every quote against the event it cites.
7. **Adjudication.** The owner rules on every draft in `ledger.yaml`, and a generator builds
   `findings.yaml`. This is the design set's route (D36): the ledger holds the rulings, and
   `comparative-judgment` scores severity rather than adjudicating.
8. **Entry mapping.** The owner writes `traces.yaml` with the rubric open. An AI may explain entries
   when asked; the mapping calls are the owner's.
9. **Seal, then run, then reveal** (§6).

## 6. Seal, run, reveal

| Step | Who | Action | Refused when |
|---|---|---|---|
| 0 | — | The gate (§7) is merged **before** the tag exists. It is inert until then. | — |
| 1 | tool: `label_manifest.py seal` | Validates `findings.yaml` against the gold-set loader and `traces.yaml` against the rubric at F. Generates the salt if absent. Writes `labels/MANIFEST`. Prints counts only. | tag absent; either file invalid; any `HELDOUT_SET` call unreferenced |
| 2 | owner | Commit **only** `labels/MANIFEST` with trailer `Rubric-Frozen: <F>`. Push and wait for CI. | CI red |
| 3 | harness session | Held-out judged run with header `labels_manifest: <C1>`; the log is written outside the harness tree. | header field missing; manifest commit not found |
| 4 | owner | Commit the log to `runs/` with trailer `Labels-Manifest-CI: <Actions run ID of C1>`. Push. | CI red |
| 5 | tool: `label_manifest.py reveal` | Moves both files and the salt to `labels/` and recomputes. | no committed run log cites the current manifest; recomputation fails |
| 6 | owner | Commit with trailer `Judged-Run: <C2>`. Push. The plaintext is published. | CI red |
| 7 | harness | Agreement and coverage, from `labels/` and `runs/` in this repository. | — |

**No tool ever displays label content.** Tools report counts and pass or fail.

## 7. The gate in CI

**Checkouts.** Both get `fetch-depth: 0`. The freeze commit is
`git -C .harness rev-parse -q --verify refs/tags/rubric-frozen-v1^{commit}`.

**A stage-aware allowlist.** The existing allowlist stays the rule for every other path.

| Stage | Admitted | Asserted over `git log` |
|---|---|---|
| S0, before the freeze | nothing new | `labels/` and `runs/` do not exist. Today's behavior. |
| S1 | `labels/MANIFEST` | tag resolves; every commit touching `MANIFEST` carries `Rubric-Frozen` equal to the tag's commit and is dated after it; the header states the same SHA; exactly two digest lines, for `findings.yaml` and `traces.yaml`; no plaintext exists yet |
| S2 | `runs/heldout-*.jsonl` | each header's `labels_manifest` equals the latest commit touching `MANIFEST` before that log's first commit, and is its ancestor; `rubric_version` and `prompt_template_hash` equal the harness's at F; `MANIFEST` untouched after the first log's commit |
| S3 | `labels/findings.yaml`, `labels/traces.yaml`, `labels/SALT` | reveal commit carries `Judged-Run` naming a commit that added a valid log, and that commit is an ancestor; both files recompute to `MANIFEST`; `findings.yaml` loads; `traces.yaml` keys equal the rubric's entries at F and every finding is placed; none of the three touched afterwards |

**Controls, all synthetic.** A scratch repository and a scratch "harness" with a planted tag. Each case
must turn the gate red:
- a manifest citing the wrong SHA, or committed before the tag;
- a run log before the manifest, or citing a superseded one;
- plaintext before a run log, or not recomputing;
- a manifest edited after a run, or labels edited after the reveal;
- a traces file missing an entry, or leaving a finding unplaced;
- a moved tag.

## 8. Owed by the harness (rules only, for a harness session)

1. `RunLogHeader` gains `labels_manifest`, required on any run over the held-out set (D26).
2. A held-out run reads transcripts and writes its log outside the harness tree. `_resolve` already
   accepts absolute paths. `check_holdout_absence` should refuse any run log whose header names the
   held-out corpus.
3. Phase-5 agreement reads `labels/findings.yaml` **and `labels/traces.yaml`** from this repository,
   and reports design and held-out agreement separately, each with its denominator.
4. The P5 "first commit later than the tag" criterion is satisfied by this repository's S1 check; the
   harness verifier should say so.
5. **Harness session prompts forbid searching this repository's labeling sessions before the reveal**
   (§2, fact 6).
6. **Decide whether phase 5 needs held-out severity.** If it does, score it in a **separate**
   `comparative-judgment` store: placing findings against the design set's cuts moves those cuts (D144).
   Severities are labels (D10), so they stay in `private/` and are sealed or scored after the reveal.
7. A decision entry recording this chain, and a `HOLDOUT-OBLIGATIONS.md` entry for it.

## 9. Failure modes and what they cost

| Failure | Consequence | Mitigation |
|---|---|---|
| `private/labels/` lost before reveal | the sealed labels can never be verified | external backup (D14); re-seal voids any run against the old manifest |
| Reviewer session reads the rubric or design findings | its list is no longer independent | the folder holds neither, and Appendix A tells it to stay inside; if it happens anyway, record it in the ledger and read its items as dependent |
| Either list seen before the other is saved | the comparison anchors | save both first (§5 step 4) |
| Label error found **before** any run | fixable | re-seal; S2 binds a run to the latest manifest |
| Label error found **after** a run | the sealed labels are what agreement is measured on | publish an erratum beside them; never edit the sealed files |
| Plaintext committed early | published before the run; CI red but cannot unpublish | `reveal` is the only sanctioned route; while private, an early push is not public |
| Tag moved or deleted | citations stop matching | S1 fails loudly |
| `HARNESS_READ_TOKEN` expires mid-phase | the gate cannot see the tag | the existing failure step turns it red |

## 10. Decisions recorded 2026-09-12

| Question | Decision |
|---|---|
| Reveal model | salted manifest before the judged run; labels, traces and salt after it |
| Labels file | one `findings.yaml` in the gold-set format |
| Entry mapping | a separate `traces.yaml`, sealed with the findings |
| Held-out run log | committed in this repository |
| Authorship | §5: owner and a fresh Fable 5.1 reviewer work independently, compare with origin tags, AI formats, owner adjudicates and maps |
| This document | committed here |

**Provenance facts behind the authorship decision.** The design set's candidates were drafted by
Claude Opus 5, per session metadata for the session that made both drafting commits on 2026-08-29. The
judge is Claude Sonnet 5 per dimension and Claude Opus 5 for synthesis (D16). Of the design set's 90 gold
findings on 2026-09-12, 78 are traced by at least one rubric entry and 12 by none; those 12 are half
`human`-detectable and half `question` tier.

## 11. Still open

- Whether phase 5 needs held-out severity, and in which store (§8, item 6).
- The id format for held-out findings, settled against the loader when that tooling is built.

## 12. Tools in this repository

Built in the order the workflow needs them. Each refuses to act before the freeze.

1. `tools/make_label_worksheet.py`: the owner's worksheet (§5 step 1).
2. `tools/build_review_folder.py`: the review folder and its `BRIEF.md` (§5 step 3).
3. A label validator: format, verbatim quotes, traces keys against the rubric at F.
4. The ledger-to-findings generator.
5. `label_manifest.py seal | reveal`.
6. The CI gate with its synthetic controls, merged before the manifest commit.

---

## Appendix A — opening message for the reviewer session

*For the owner: once `tools/build_review_folder.py` has run, start a new session whose folder is the
review folder, on **Claude Fable 5.1** at effort **max**, and paste the block below as its first
message.*

*Why Fable 5.1: the judge is Claude Sonnet 5 per dimension and Claude Opus 5 for synthesis, and the design
set's findings were drafted on Opus 5, so a different model adds a second axis of independence. Why
`max`: a review's failure mode is missing something, which is what reasoning depth buys.*

```
You are an independent reviewer of six recorded voice-support calls. The project's owner is
reviewing the same six calls separately; the two lists are compared afterwards, and the result
becomes human-adjudicated ground truth for measuring an automated judge.

Read BRIEF.md in this folder before anything else, and follow it. It says what is here, what was
left out on purpose and why, the template you fill in, and the rules.

Work only inside this folder. If you find yourself wanting anything outside it, stop and ask me
instead of looking.

Your output is notes-reviewer.md in this folder, filled in for all six calls. Keep your
observations in that file rather than in chat, and tell me when it is complete.
```
