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
3. **The run-log header names the manifest and the rubric.** `RunLogHeader` carries
   `rubric_version`, `prompt_template_hash`, `corpus_version`, `artifact_hash`, `mode`, `started_at`,
   and, when they are set, `resumed_from`, `labels_manifest` (delivered 2026-09-15, harness D173) and
   `rubric_hash` (delivered 2026-09-16, harness D183). The harness requires `labels_manifest` on a run
   over the calls `HELDOUT_SET` declares, refuses it on any other run, and checks only its shape; it
   writes `rubric_hash` on those same runs and on no other, and refuses a replay or a resume whose log
   names another rubric or none, with no override. That the commit `labels_manifest` names is the
   manifest in force, and that `rubric_hash` is `rubric.yaml`'s at F, are checked here, at S2.
4. **CI could not see the freeze tag.** Both checkouts used the default `fetch-depth: 1` until the gate
   set both to `fetch-depth: 0`, which fetches all history and tags (confirmed against the
   `actions/checkout` documentation).
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
                                                                          rubric_hash: <rubric.yaml at F>
                                   │
                                   │ ancestor of, and cited by trailer
                                   ▼
                                  C3  labels/findings.yaml      trailer  Judged-Run: <C2>
                                      labels/traces.yaml
                                      labels/severity.json
                                      labels/SALT
```

Each link cites a content hash of the one before it, which is the device D21 and D26 chose. Because C1,
C2 and C3 live in **one** repository, their order is also **git ancestry**.

| Property | Secured by |
|---|---|
| (a) rubric not designed against the labels | C1 cites F, and C1's committer date is later than F's (corroboration) |
| (b) labels not tuned after judge output | C2's header cites C1; C1 is an ancestor of C2, and C2 of C3; both label files at C3 recompute to C1's manifest |
| the run judged under the entry text the labels were written against | C2's header carries `rubric_hash`, `rubric.yaml` at F hashed as text (harness D183) |
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
| `drafts.yaml` | AI | one row per merged observation: the gold-set format's text fields (`id`, `call_ref`, `observation`, `evidence`, `consequence`) and no classification, which only the ledger states (D10, D38) |
| `ledger.yaml` | owner | one ruling per draft: `id`, `verdict`, `owner`, `detectable_by`, `tier`, `origin`, `note`, and replacement text only under `accept-with-edits` |
| `findings.yaml` | tool | generated from `drafts.yaml` and `ledger.yaml`, as the harness's `make_gold_set.py` does |
| `traces.yaml` | owner | the entry mapping (format below) |
| `severity.json` | owner | the held-out bands, exported from a `comparative-judgment` store of their own kept outside both repositories (harness O-10); placed before the judged run, sealed with the labels, revealed with them |
| `SALT` | tool | 32 random bytes as 64 lowercase hex characters, with no newline, so the `cat` recipe below reproduces each digest |

**Committed: `labels/` and `runs/`**, in the order of §3.

| Path | Commit | Contents |
|---|---|---|
| `labels/MANIFEST` | C1 | algorithm, freeze SHA, one digest line per sealed file |
| `runs/heldout-<started_at>-<mode>.jsonl` | C2 | the held-out judged run log, unmodified, under the name the harness gave it (harness D184) |
| `labels/findings.yaml`, `labels/traces.yaml`, `labels/severity.json`, `labels/SALT` | C3 | byte-identical to what C1 sealed |

**`CORPUS_VERSION`** sits at the root of this repository, tracked and on the workflow's allowlist. It
holds this set's own version string, which the harness stamps into every held-out run-log header from
`--corpus-version-file` (harness D182). It is not the design corpus's version: a header committed here
unmodified would otherwise describe a corpus that run never read. Bump it if a transcript ever changes,
which would invalidate the labels anyway.

**`findings.yaml`** uses the gold-set format exactly, so `harness.core.findings` loads it: eight
required keys and no unknown ones. **Held-out ids are shaped `HF-NN`**, two digits or more. The loader
accepts any non-empty string, so the shape is this repository's rule: a prefix no design finding
carries makes a collision with the design set's `F-NN` impossible rather than unlikely. `H-` was not
free, since the harness's audit records number their own findings `H-1` onward. The validator checks
against the design ids as well.

**`traces.yaml`** is the held-out counterpart of the rubric's `traces_to`:

```yaml
rubric-frozen-v1: <40-hex freeze commit SHA>
traces:
  <rubric entry id>: [<held-out finding id>, ...]   # every entry of the frozen rubric; [] allowed
uncovered: [<held-out finding id>, ...]             # findings no entry should catch
calls_without_findings: [<held-out call id>, ...]   # held-out calls with nothing wrong; [] allowed
```

Three checkable rules: the keys under `traces` equal the entry ids of the rubric **at the freeze
commit**; every finding appears under at least one entry or in `uncovered`, never both; and every
held-out call is referenced by a finding or listed under `calls_without_findings`, never both.

**Why the last list exists.** Requiring a finding on every held-out call catches a call that was
forgotten, but a call with nothing wrong could then be sealed only by inventing a finding. Listing it
keeps the omission impossible and makes "nothing wrong here" a recorded decision, sealed with the
mapping so it cannot change after the run.

**`severity.json`** is the scoring tool's export, in the harness's schema 3 (harness D181): the top
level carries `schema_version`, `anchor_set_version`, `comparison_log_hash`, `run_id`, `calibration`,
`severities`, `unplaced` and `cuts`; each row carries `id`, `severity`, `theta`, `content_hash`,
`appearances` and `informative`; and all three cuts travel in the same file.
`tools/validate_labels.py severity` reads it with the harness's own loader, which pins the schema and
re-derives every band from the cuts, and checks that every id it names is a finding of this set. It
does **not** require the export to name every finding, which is the scoring tool's design and not an
omission (harness D187): `unplaced` is for findings that were in scope and nobody compared, while a
question-tier entry is excluded before scoring begins, since rating a non-defect would put it in the
anchor set and move every later placement. One field cannot carry both without making an empty
`unplaced` unreadable, so the harness's coverage report names the findings that carry no band instead.
The design set's own export scores 83 of its 90 and lists none unplaced. `content_hash` is the hash
of the finding text a band was placed on, and the harness checks it after the reveal, so a finding's
text must not move after the export: re-export rather than edit either side of it.

**`MANIFEST`** can be recomputed with standard tools and no project code:

```
# held-out label manifest
# algorithm: sha256 over the salt's 64 hex characters, a newline, then the file's exact bytes
# rubric-frozen-v1: <40-hex freeze commit SHA>
<64-hex digest>  labels/findings.yaml
<64-hex digest>  labels/traces.yaml
<64-hex digest>  labels/severity.json
```

A reader verifies each file with `(cat labels/SALT; printf '\n'; cat labels/findings.yaml) | sha256sum`.
One salt serves every line. It is cheap, and it keeps the commitment hiding even if a file's shape ever
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
6. **Formatting.** The AI writes `drafts.yaml` in the gold-set format's text fields: observation,
   verbatim evidence at event numbers, consequence, and no classification. Running
   `tools/validate_labels.py drafts` holds every fragment to the design set's evidence rules.
7. **Adjudication.** The owner rules on every draft in `ledger.yaml`, and
   `tools/make_label_findings.py` builds `findings.yaml` from the drafts and the rulings; `--check`
   says whether the file still agrees with them. This is the design set's route (D36): the ledger
   holds the rulings, and `comparative-judgment` scores severity rather than adjudicating.
8. **Entry mapping.** The owner writes `traces.yaml` with the rubric open. An AI may explain entries
   when asked; the mapping calls are the owner's. What the mapping states, and the reach policy it
   follows, are §13. `tools/validate_labels.py` then checks the findings
   and the mapping together, which is what sealing requires.
9. **Severity.** The owner places the held-out findings in a `comparative-judgment` store of their
   own, kept outside both repositories, and exports the result to `private/labels/severity.json`. It
   happens before the judged run, because afterwards whoever orders the findings can see which ones the
   judge missed, and the export is sealed with the labels and revealed with them (harness O-10, D177).
   `tools/validate_labels.py severity` reads the export with the harness's loader before it is sealed.
10. **Seal, then run, then reveal** (§6).

## 6. Seal, run, reveal

| Step | Who | Action | Refused when |
|---|---|---|---|
| 0 | — | The gate (§7) is merged **before** the tag exists. It is inert until then. | — |
| 1 | tool: `label_manifest.py seal` | Validates `findings.yaml` against the gold-set loader and `traces.yaml` against the rubric at F, and reads `severity.json` with the harness's severity loader. Generates the salt if absent. Writes `labels/MANIFEST`, or rewrites it when re-sealing before any run. Prints counts only. | tag absent; a run log already committed; plaintext already in `labels/`; either label file invalid; the severity export missing, refused by the harness's loader, or naming an id that is not a finding; any `HELDOUT_SET` call neither referenced by a finding nor listed under `calls_without_findings` |
| 2 | owner | Commit **only** `labels/MANIFEST` with trailer `Rubric-Frozen: <F>`. Push and wait for CI. | CI red |
| 3 | harness session | Held-out judged run, from the harness: `harness run --tier judge --mode live`, with `--transcripts` at this repository's transcripts directory, `--run-log-dir` outside the harness checkout and `--corpus-version-file` at this repository's `CORPUS_VERSION`, all absolute, and `--labels-manifest <C1>`. `--policies` stays the harness's, deliberately: both sets read the same policy documents. The header then carries `labels_manifest: <C1>` and `rubric_hash`, over the `rubric.yaml` it judged under. | `--labels-manifest` absent, or not 40 lowercase hex characters; a run mixing declared and undeclared calls; a design-set run given the flag; any of those paths inside the harness checkout; a replay or a resume whose log names another rubric, or none |
| 4 | owner | Commit the log unmodified, under the name the harness gave it: `heldout-<started_at, colons as hyphens>-<mode>.jsonl`, written with that prefix on a held-out run and on no other (harness D184). **Nothing is renamed**, which is what the prefix bought: a rename between a paid-for log and its commit is silent until the gate reads the path. Trailer `Labels-Manifest-CI: <Actions run ID of C1>`. Push. | CI red; a name the gate does not admit |
| 5 | tool: `label_manifest.py reveal` | Copies the three sealed files and the salt to `labels/`, keeping the private copies, and recomputes from the copies. Names the commit the reveal's `Judged-Run` trailer must cite. | no committed run log cites the current manifest and passes the gate's run-log checks; the labels no longer validate; recomputation fails; plaintext already in `labels/` |
| 6 | owner | Commit with trailer `Judged-Run: <C2>`. Push. The plaintext is published. | CI red |
| 7 | harness | Agreement, from this repository and outside the harness checkout: `--held-out-transcripts`, `--held-out-corpus-version-file`, `--held-out-run-log`, `--held-out-findings`, `--held-out-traces`, with `--held-out-policies` optional and defaulting to the harness's own. Coverage reads `labels/severity.json` after the reveal, per band, and names the findings that carry no band (harness D187). A rendered report over these calls is refused an `--out` path inside the harness checkout (harness D185), so it is written here or to stdout. | — |

**No tool ever displays label content.** Tools report counts and pass or fail.

## 7. The gate in CI

**Checkouts.** Both get `fetch-depth: 0`. The freeze commit is
`git -C .harness rev-parse -q --verify refs/tags/rubric-frozen-v1^{commit}`.

**A stage-aware allowlist.** The existing allowlist stays the rule for every other path.

| Stage | Admitted | Asserted over `git log` |
|---|---|---|
| S0, before the freeze | nothing new | `labels/` and `runs/` do not exist. Today's behavior. |
| S1 | `labels/MANIFEST` | tag resolves; every commit touching `MANIFEST` carries `Rubric-Frozen` equal to the tag's commit and is dated after it; the header states the same SHA; one digest line per sealed file, naming `findings.yaml`, `traces.yaml` and `severity.json`; no plaintext exists yet |
| S2 | `runs/heldout-*.jsonl` | each header's `labels_manifest` equals the latest commit touching `MANIFEST` before that log's first commit, and is its ancestor; `rubric_version`, `prompt_template_hash` and `rubric_hash` equal the harness's at F; `MANIFEST` untouched after the first log's commit |
| S3 | `labels/findings.yaml`, `labels/traces.yaml`, `labels/severity.json`, `labels/SALT` | reveal commit carries `Judged-Run` naming a commit that added a valid log, and that commit is an ancestor; all three sealed files recompute to `MANIFEST`; `findings.yaml` loads; `traces.yaml` keys equal the rubric's entries at F, every finding is placed, and every held-out call is referenced or listed; none of the four touched afterwards |

**Controls, all synthetic.** A scratch repository and a scratch "harness" with a planted tag. Each case
must turn the gate red:
- a manifest citing the wrong SHA, or committed before the tag;
- a run log before the manifest, citing a superseded one, or judged under another rubric or none;
- plaintext before a run log, or not recomputing;
- a manifest edited after a run, or labels edited after the reveal;
- a traces file missing an entry, leaving a finding unplaced, or leaving a call neither referenced nor
  listed;
- a moved tag.

**What the gate reads, and what it adds.** `tools/label_gate.py` reads commits, never the working tree.
- **A run log's header** is its first line, the harness's header record (`"record": "header"`). Its
  `labels_manifest` holds the full SHA of the commit that last touched `labels/MANIFEST` (§8, item 1).
- **The frozen template hash** is not a file digest: the harness hashes the halves it sends. So the
  gate runs F's own code, from an archive of F, rather than a copy of it. A test checks the result
  against the header of the reference run log the harness had committed at F.
- **The rubric hash** is `rubric.yaml` at F, read as text and encoded UTF-8, which is how the
  harness hashes the file it judged under (D183). The gate requires one, because a held-out log
  carries it and only a held-out log is committed here: neither `rubric_version` nor the template hash
  moves when an entry's question, criteria or scale text moves. No committed harness log carries one
  to compare with, so a test checks this computation against the harness's own function instead.
- **Added checks:** a run log never changes after the commit that adds it; no label file or salt
  appears in any commit before the reveal, even one deleted since; the sealed files and the salt are
  added once, in one commit; and `Judged-Run` is a full 40-character SHA.

## 8. Owed by the harness (rules only, for a harness session)

**Status, 2026-09-16, at harness `44325dd`. Every item is delivered.** Items 1 to 5 and 7 landed by
`6a0f144`: the header key (D173); the paths refused inside the harness checkout and the absence check
that refuses a held-out run log (D174); agreement over both label files, reporting the two sets apart
(D175); the phase-5 verifier declaring this gate's criteria (D176); the standing rule against searching
these sessions; and a decision entry (D177) with register entries O-9, O-10 and O-11. Item 6 is
decided, and what it decided is below. Items 8 to 11 landed with D181 to D186, the answers to this
repository's four questions and the two decisions the harness took beside them. D187, at specification
0.48.0, answers the question this repository asked back about the export's `unplaced`, and changes
nothing here (§4).

1. `RunLogHeader` gains `labels_manifest`, required on any run over the held-out set (D26): a key of
   the header record holding the manifest commit's full 40-character SHA, where `tools/label_gate.py`
   reads it.
2. A held-out run reads transcripts and writes its log outside the harness tree. `_resolve` already
   accepts absolute paths. `check_holdout_absence` should refuse any run log whose header names the
   held-out corpus.
3. Phase-5 agreement reads `labels/findings.yaml` **and `labels/traces.yaml`** from this repository,
   and reports design and held-out agreement separately, each with its denominator.
4. The P5 "first commit later than the tag" criterion is satisfied by this repository's S1 check; the
   harness verifier should say so.
5. **Harness session prompts forbid searching this repository's labeling sessions before the reveal**
   (§2, fact 6).
6. **Held-out severity: decided (O-10, D177).** The bands are placed in a **separate**
   `comparative-judgment` store kept outside the harness tree, because placing them against the design
   set's cuts moves those cuts (D144), and a person makes every comparison (D10). They are placed
   **before** the judged run, since afterwards whoever orders the findings can see which ones the judge
   missed, and the file is **sealed before that run in a form the gate can check**, then revealed with
   the labels. How it is sealed was this repository's to decide, and the chain has its slot:
   `labels/severity.json`, sealed at C1 with the label files and revealed at C3 (§4).
7. A decision entry recording this chain, and a `HOLDOUT-OBLIGATIONS.md` entry for it.
8. **A rubric hash in the header** (harness D183, D186), which replaces the trailer this document
   proposed: a held-out run's header carries `rubric_hash`, a hash of `rubric.yaml` as text encoded
   UTF-8, and the gate compares it with the same hash of `rubric.yaml` at F. Neither field the gate
   checked before moves when an entry's text moves, and a harness commit that descends from the freeze
   proves nothing about what it judged under. **Delivered 2026-09-16**, with a replay or a resume under
   another rubric refused there and no override, and `rubric.yaml` and the prompt template pinned at
   the harness's HEAD to the commit the tag names.
9. **The `heldout-` prefix on a held-out run's log** (harness D184), keyed on the header carrying a
   labels manifest. **Delivered 2026-09-16**; §6 step 4 renames nothing.
10. **This set's own corpus version** (harness D182): a held-out run takes `--corpus-version-file`, and
    the harness refuses a path resolving inside its own checkout, beside the four paths D174 already
    refused. **Delivered 2026-09-16**; this repository's file is `CORPUS_VERSION` (§4), so a header
    committed here unmodified cannot describe the design corpus.
11. **A report over held-out calls stays out of the harness tree** (harness D185): `harness report`
    refuses an `--out` path inside that checkout over any call `HELDOUT_SET` declares, with stdout and
    outside paths open, and the absence check reads a rendered report as a third shape beside
    transcripts and run logs. Not asked for here, and it closes a route §6 step 7 would otherwise have
    to remember. **Delivered 2026-09-16.**

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
| A held-out call with no finding (2026-09-13) | allowed only when `traces.yaml` lists it under `calls_without_findings`; every held-out call is referenced or listed, never both |

**Provenance facts behind the authorship decision.** The design set's candidates were drafted by
Claude Opus 5, per session metadata for the session that made both drafting commits on 2026-08-29. The
judge is Claude Sonnet 5 per dimension and Claude Opus 5 for synthesis (D16). Of the design set's 90 gold
findings on 2026-09-12, 78 are traced by at least one rubric entry and 12 by none; those 12 are half
`human`-detectable and half `question` tier.

## 11. Still open

Found by the cross-project audit of 2026-09-15, which read both repositories at held-out `5760aa9` and
harness `6a0f144`. Its other finding closed on 2026-09-16: the harness named the header key
`rubric_hash`, and S2 compares it with `rubric.yaml` at F (§7, and §8 item 8).

- **Conventions this set is held to by nothing.** The audit listed thirteen rules the harness enforces
  on the design set with no equivalent here; `tests/test_holdout_conventions.py` records them. Whether
  this set satisfies any of them needs the transcripts, so porting or recording the gap is the
  owner's call.

## 12. Tools in this repository

Built in the order the workflow needs them. Each refuses to act before the freeze.

1. `tools/make_label_worksheet.py`: the owner's worksheet (§5 step 1).
2. `tools/build_review_folder.py`: the review folder and its `BRIEF.md` (§5 step 3).
3. `tools/validate_labels.py`: the label validator, by stage: `drafts`, `findings`, `all`, which adds
   `traces.yaml` against the rubric at F (§5 steps 6 to 8), and `severity`, which reads the export with
   the harness's own loader (§5 step 9). `severity` stands outside `all` because the export arrives
   after the labels do.
4. `tools/make_label_findings.py`: the ledger-to-findings generator, with `--check` (§5 step 7).
5. `tools/label_manifest.py seal | reveal` (§6 steps 1 and 5), tested with the gate in
   `tests/test_label_chain.py`.
6. `tools/label_gate.py`: the CI gate, with its synthetic controls in `tests/test_label_chain.py`,
   merged before the manifest commit.

---

## 13. What the mapping states, and what it does not

**The policy.** `traces.yaml` lists under an entry only findings that entry could catch **as it is
configured at the freeze commit**. Everything else goes to `uncovered`.

**Why, rather than tracing what the rubric arguably ought to catch.** `traces_to` is an expectation
about behavior: an entry must fire on the calls its traced findings sit on and stay silent
elsewhere (D105, D125). This file is sealed and published, and a later reader takes it literally. An
entry traced to something its check cannot reach — a threshold it does not meet, a variable it does
not watch, a phrase it does not know — records a labeling mistake rather than a coverage gap, unless
something beside it explains the intent. Under this policy the sealed file stays literally true, and
the gap is stated in prose, where it can be explained and argued with.

**How reach was established.** By reading, at the freeze commit, each entry's `params` and the check
implementations behind them. **Not by running anything over these transcripts.** A mapping written
with the checks' own output in view would be tuned on it, which is what §3's property (b) exists to
prevent; the deterministic tier costs nothing to run, which makes the temptation worth naming.

**What the reading found, in general.** The deterministic tier is configured around the design set's
own phrasing, variable names and tools: entries carry literal claim phrases, one watches a single
named context variable, one carries a fixed silence threshold in milliseconds, one names an outside
party by name. An entry configured that way has no subject in a corpus written independently of it,
whatever those calls contain. The judged entries carry no such configuration and reach every call,
which is the asymmetry this set was always going to expose.

**What publishes at the reveal, and not before.** How many findings this set holds, how many the
mapping traces and which, are facts about the labels (D61), so they publish with the plaintext at
C3. The reach analysis they rest on is kept in `private/labels/entry-reach.md` until then, and the
agreement measurement at §6 step 7 reports over what the mapping traces.

**One expectation recorded before the run, because a prediction made afterwards is worth less.**
`A-irreversible-action-without-confirmation` is configured for `change_holder_name` with the confirm
phrases "can you confirm that's right" and "before i change it". The transcripts are public, and
CALL-15 event 15 reads *"That's a single character, so it stays a correction rather than a transfer
— no deadline attached to it. Can I read it back? K, R-A-V-E-N-S-B-O-U-R-N."* — a confirmation in
words the check does not know. The check is therefore expected to fire on that call. Whether that
firing is a false alarm is a question only the labels answer, at the reveal.

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
