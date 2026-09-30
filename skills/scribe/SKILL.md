---
name: scribe
description: >-
  Shadow one or more working sessions from a dedicated scribe chat and keep a
  journal entry current at every checkpoint. Use when the user says /scribe,
  attach, or checkpoint, or asks to start a scribe session, add a session to
  it, or   update its journal entry.
license: MIT
disable-model-invocation: true
---

# /scribe — Incremental Journal Scribe

Runs in its own dedicated chat alongside one or more working sessions. It reads
those sessions' on-disk transcripts and keeps one journal entry current. Every
checkpoint leaves a complete entry; there is no separate publish step.

## Commands

| Command | Description |
|---|---|
| `/scribe [@session]` | Pick a working session and write its entry |
| `attach [@session]` | Add another working session to the entry |
| `checkpoint` | Digest new turns and rewrite the entry |

## Replies

The user sees the journal, not the machinery. After each command, reply with
the vault-relative entry path and at most two short lines on what changed in
it. Never mention registries, watermarks, state files, helper scripts, UUIDs,
slugs, or digest statistics, and never narrate protocol steps. Report a
failure as what the user can do next, not as the internal step that broke.

Ask every question with AskQuestion, never in plain chat text. Scribe asks only
to set up the vault, to pick a session, or to approve tags.

## The vault

The vault is the single folder holding `journal/`, `artifacts/`, `tags.yaml`, and
`.scribe/` state. Every path below is relative to its root.

`<skill-dir>` below means the directory containing this `SKILL.md`; invoke
helpers as `python3 <skill-dir>/<script>`, never from a hardcoded repository.

Before `/scribe`, locate it:

```bash
python3 <skill-dir>/scribe_state.py --resolve-vault
```

The helper checks `$MEMORY_VAULT`, then `~/.scribe/config.json`, then an
enclosing directory containing `.scribe/`. If it reports `"configured": false`,
ask once with AskQuestion where the vault should go. Offer concrete paths:
`~/memory` as the default, an existing Obsidian vault if one is visible on
disk, the current repository when it is clearly a personal notes repo, and a
free-form option. Then create it:

```bash
python3 <skill-dir>/scribe_state.py --init-vault --path "<path>"
```

and continue the original request, keeping any transcript mention it carried.
Ask nothing else during setup. Never set up a vault once one resolves, and never
write entries somewhere else when none does.

## Transcript mechanics

Transcripts are stored under:

```text
~/.cursor/projects/<workspace>/agent-transcripts/<uuid>/<uuid>.jsonl
```

The two transcript helpers search every Cursor workspace. User messages include
injected context; only text inside `<user_query>…</user_query>` is real user
input. Transcript tool results are not stored.

### Session selection

An `@` mention of a past chat inserts its transcript path. Treat any mentioned
path or bare UUID as explicit selection:

1. Extract its UUID using `agent-transcripts/([0-9a-f-]{36})/`.
2. Resolve its label:

   ```bash
   python3 <skill-dir>/find_sessions.py --uuid <uuid>
   ```

3. If found, use it directly. Multiple mentions attach multiple sessions.

Only without a mention, build a recency picker. First find and exclude this
scribe chat:

```bash
SELF=$(python3 <skill-dir>/find_sessions.py --whoami)
python3 <skill-dir>/find_sessions.py --self "$SELF" --exclude <attached-uuids>
```

Use each returned `label` as an AskQuestion option. The self UUID is a strong
hint, not certainty: if the selected transcript is this scribe conversation,
exclude it and re-run the picker.

### Registry state

Scribe tracks each entry's sessions in a registry at:

```text
<vault>/.scribe/state/YYYY-MM-DD-<slug>.json
```

```json
{
  "version": 1,
  "entry": "journal/YYYY-MM-DD-<slug>.md",
  "slug": "<slug>",
  "sessions": {
    "<uuid>": { "watermark": 47, "label": "Session title" }
  }
}
```

`watermark` is the count of transcript lines already digested.

For `attach` and `checkpoint`, use the working-session UUIDs already selected
in this dedicated scribe chat. Find the registry containing those sessions:

```bash
python3 <skill-dir>/scribe_state.py --find-by-sessions \
  --session-uuids <initial-working-session-uuid>
```

The initial working-session UUID is the normal lookup key; it remains present
even after later `attach` operations. Exactly one match is required. Never
show the user a registry picker or choose by modification time. If the lookup
is not unique, stop without changing files and tell the user this chat cannot
safely update its entry.

### Digest procedure

For each attached session, in attachment order:

```bash
python3 <skill-dir>/digest_transcript.py --uuid <uuid> --since <watermark> \
  --label "<label>"
```

Omit `--label` for a single session. The final `WATERMARK=<n>` line is the
new stored watermark. Never hand-parse raw JSONL. Semantically digest the
compact stream into the session goal, the prior state and trigger it started
from, durable outcomes, decision candidates, insights, open threads, and
literal reference links. Merge sessions in attachment order.

Track goal evolution rather than freezing the opening request. When later turns
establish a different governing deliverable, use that latest explicit purpose
as the Goal. Preserve the pivot itself only when it explains the resulting
scope or decisions.

Do not treat the compact stream as the journal voice. Drop
[delivery state and execution mechanics](#delivery-state-and-execution-mechanics).

Treat explicit user corrections, surprises, changed assumptions, and
relationships synthesized across multiple flows or systems as strong Insight
candidates. “Reconstructable from code” does not mean disposable when recovering
the relationship would require repeating meaningful investigation.

## Protocols

### `/scribe`

1. Resolve the vault, setting it up first if it is not configured.
2. Select the first working session using the mention-first flow above. Keep
   its UUID as the initial working-session UUID for all later registry lookups
   in this dedicated scribe chat.
3. Choose a 2–5 word kebab-case slug. `YYYY-MM-DD` throughout is the date the
   working session ran, not today's date, so scribing an older chat keeps its
   own day. Write the registry to
   `<vault>/.scribe/state/YYYY-MM-DD-<slug>.json`, starting at watermark 0.
4. Run the `checkpoint` protocol with the registry just written, which writes
   `journal/YYYY-MM-DD-<slug>.md`.

### `attach`

1. Load the registry.
2. Select one or more new sessions via mention or picker; never attach without
   explicit user selection.
3. Add each session to the registry at watermark 0 and to the entry's session
   frontmatter, switching `session:` to a `sessions:` list when there are
   several.

### `checkpoint`

1. Load the registry and digest every session.
2. Rewrite the whole entry in the [Entry format](#entry-format), creating
   `journal/` if needed. Preserve established facts, not prior wording:
   consolidate repetition, replace stale intermediate state, and remove
   execution diary detail. Set Goal from the latest governing purpose or
   deliverable, not automatically from the opening request; the situation that
   prompted it belongs in Background. Handoff states what is open now and is
   omitted once the work is done.
3. Collect issue keys literally mentioned in the digested turns (Jira-style,
   such as `ABC-123`) into a sorted `tickets:` list. Omit the field when there
   are none.
4. Copy durable artifacts the work sessions created into
   `<vault>/artifacts/YYYY-MM-DD-<slug>/`, re-copying them at every checkpoint so
   the copies stay current: plans (saved as `plan.md`), test plans with their
   specs, collections, and run reports, one-off verification scripts, and
   handoff or design documents. Code that lives in a repository is not an
   artifact, and neither is a document handed to the session as input: link
   inputs from References instead of copying them. Create the directory only
   when there is something to copy.
5. Add the primary artifact produced by the work, when one exists, plus literal
   PR URLs, artifact links, and relevant vault-note wikilinks to References. A
   primary artifact is not a file inventory: keep the plan, design, report, or
   other deliverable that a future reader should open first.
6. Choose tags as described in [Tags](#tags).
7. Verify the [checklist](#before-writing), then write the entry.
8. Only after the entry is written, advance every watermark using the helper
   output.
9. Reply as described in [Replies](#replies).

## Tags

`<vault>/tags.yaml` is the tag vocabulary: a flat YAML list, one tag per line,
sorted.

```yaml
- aws
- datadog
```

Infer 2–5 lowercase kebab-case topical tags, preferring names already in
`tags.yaml`. Issue keys are tickets, never tags.

The entry's current `tags:` is the approved set. When the proposed set is the
same, keep it without asking. Otherwise ask once with AskQuestion, offering the
proposed set as the recommended option and, when the entry already has tags,
the current set as an alternative; a new entry has no approved set, so its
first checkpoint always asks. Mark any
tag not yet in `tags.yaml` as “(new)” in the options: approving a set that
contains it is approval to add it. Append approved new tags to `tags.yaml`,
keeping it sorted. Never add a tag to `tags.yaml` without that approval; if the
user declines a set, keep the current one.

## Anti-instructions

- Never digest this scribe chat or attach a session without explicit selection.
- Preserve established facts across checkpoints, not accumulated prose. Rewrite
  and consolidate prior content whenever it improves accuracy or retrieval.
- Never invent PRs or tickets; only reference ones literally present in
  digested turns.
- Never expand a decision merely because its implementation was complicated.
  Package bumps, migration steps, and delivery sequencing are not durable
  decisions unless they expose a reusable constraint.
- Never hardcode a vault path, repository, remote, branch, or publishing action
  in this skill.

## Entry format

The audience is a future agent or teammate resuming related work. The entry is
not a session summary. State the goal, the situation it started from, and the
durable outcome, then retain only reasoning and insights that could change a
future action.

```markdown
---
date: YYYY-MM-DD
tags:
  - inferred-tag-1
  - inferred-tag-2
tickets:
  - ABC-123
session: <uuid> # use sessions: [uuidA, uuidB] for multiple sources
---

# [Short title]

## Goal

[One sentence: the question to answer or the deliverable to produce, plus a
short "so that …" clause when the work has a stated purpose.]

## Background

- [What was true, believed, or broken before the work started.]
- [What triggered it.]
- [[YYYY-MM-DD-prior-entry]] when an earlier entry already holds the context.

## Outcomes

- [Durable result or newly established fact.]

## Decisions

- **[Decision headline]** — [One-line choice and rationale.]
  - **Why:** [Non-obvious constraint.]
  - **Rejected:** [Plausible alternative and why it lost.]
  - **Consequence:** [Important cost or behavior.]
  - **Revisit if:** [Condition that invalidates the original reasoning.]

## Insights

- **[Insight]** — [Evidence and implication for future work.]

## Handoff

- [What is still open: the blocker, risk, or unresolved question someone would
  need to resume. Omit the section once the work is done.]

## References

- Primary artifact: [<name>](<path-or-url>)
- Related entry: [[YYYY-MM-DD-related-entry|Why it is relevant]]
- Plan: [../artifacts/YYYY-MM-DD-<slug>/plan.md](../artifacts/YYYY-MM-DD-<slug>/plan.md)
- PRs: [<repo>#<number>](<pr-url>)
```

`## Goal`, `## Background`, and `## Outcomes` are required. Omit `tickets:`,
Decisions, Insights, Handoff, or References when empty. Use a short
outcome-oriented title; the title, Goal, and Outcomes should give a complete
15–30 second scan.

### Background

Background carries the situation; Goal carries the objective. Strip the trigger
narrative out of Goal — "the channel had become hard to follow", "the report
surfaced 101 stuck sessions" — and put it here. A "so that …" purpose clause is
not situation and stays in Goal.

Record what was true, believed, or broken before the work started, and what
triggered it. A prior belief that the work overturned belongs here even when
the correction appears in Outcomes: without it, a future reader cannot tell
which assumption was tested.

There is no length target. Include the orienting facts a reader needs in order
to follow the Decisions; that scope, not a word count, is what keeps a brief
system description from growing into reconstructable architecture narration. Do
not trim a genuine prior state to keep the section short. When an earlier entry
already holds the context, link it with a wikilink instead of restating it; a
single pointer bullet is a complete Background.

Background is prior state, not lessons learned. A fact that changes future
diagnosis is an Insight; a fact that merely lets the reader follow this entry
is Background.

### Retention test

Always state the concise goal, background, and outcome. For every supporting
detail, decision sub-bullet, and insight, keep it when it could change a future
action and at least one of these is true:

1. It is non-obvious from any single source.
2. It synthesizes a relationship distributed across files, services, flows, or
   external observations.
3. Recovering it would require repeating meaningful investigation.

“Could change a future action” includes preventing an incorrect choice, a
repeated failed approach, or a misunderstanding of an important constraint.
Being technically reconstructable is not sufficient reason to omit expensive
code archaeology or cross-system synthesis.

Classify candidate material before writing:

- **Background:** prior state, prior belief, or the trigger — context a reader
  needs to follow the rest of the entry. It describes the situation the work
  started from, not anything the work established.
- **Decision:** a meaningful choice among plausible alternatives. Keep when the
  alternative may resurface, the choice is hard to reverse, several non-obvious
  constraints drove it, or its revisit boundary matters.
- **Insight:** a surprising fact, corrected assumption, asymmetry, failure mode,
  flow relationship, or semantic distinction that changes future diagnosis or
  behavior.
- **Delivery state or execution mechanic:** omit, as described below.

### Delivery state and execution mechanics

Delivery state — branch names, commit hashes, pushes, merges, and the status of
PRs, tests, releases, or deployments — and execution mechanics — file
inventories, routine test runs, release sequencing, conflict resolution, and
agent or session drama — belong to their source systems, which stay current
while an entry does not. Omit them from every section, even when the work was
difficult. A PR or issue URL is durable and belongs in References without a
status word. A branch name or commit hash may appear in a Decision or Insight
only as evidence for a constraint that outlives the branch.

Unwrap rather than delete when delivery state is wrapping a real fact. "PR
still open; the only remaining blocker is that the CI service account lacks
read access to the artifact registry — five builds all fail identically at
`GET /v2/packages`" becomes "The CI service account lacks read access to the
artifact registry; five builds fail identically at `GET /v2/packages`."

### Decision capsules

Start every decision with a standalone headline and one-line rationale. Add
only the labeled sub-bullets that preserve consequential reasoning; do not fill
every label. Detailed reasoning is justified when a rejected alternative is
likely to recur, the choice is expensive to reverse, multiple hidden
constraints drove it, or a future revisit condition matters.

Prefer visible labeled sub-bullets for agent retrieval. A long capsule may put
its supporting bullets in `<details><summary>Reasoning</summary>…</details>`
when the vault renders HTML and collapsing it materially improves human
scanning. Never hide the decision headline or one-line rationale.

There is no hard word target. Use the shortest entry that passes the retention
test; do not compress away concrete constraints merely to meet a size goal.

For notes in the same vault, use Obsidian wikilinks so the vault can derive
backlinks: `[[YYYY-MM-DD-entry]]`, or
`[[YYYY-MM-DD-entry|descriptive label]]` when prose needs a label. Do not use
Markdown relative links for vault notes. Keep conventional Markdown links for
external URLs, PRs, and artifacts or other files.

### Before writing

Verify at every checkpoint:

- Goal reflects the latest governing deliverable and carries no trigger
  narrative; Outcomes state the durable end-state without chronology.
- Background states the prior state and trigger, including any belief the work
  overturned, and links rather than restates context an earlier entry already
  holds.
- Every decision capsule and insight passes the retention test.
- Explicit user corrections, surprises, goal pivots, and cross-flow/system
  relationships are represented as Outcomes, Decisions, or Insights, or were
  intentionally omitted after applying the retention test.
- No section carries delivery state or execution mechanics.
- Handoff lists only what is still open, or is absent when the work is done.
- References include the primary artifact and other durable pointers, not a
  file inventory.
- Empty optional sections are absent.

Include a Mermaid diagram only when a flow, sequence, state transition, or
architecture relationship is materially clearer than prose and the relationship
itself is durable. Keep node IDs space-free and avoid explicit styles.

Artifacts use `<vault>/artifacts/YYYY-MM-DD-<slug>/`; files use short
descriptive names and journal links are `../artifacts/YYYY-MM-DD-<slug>/<file>`. Reused
artifacts remain in their originating entry directory and are cross-linked.
