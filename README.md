# shadow-scribe

A Cursor agent skill that keeps a developer journal for you. It runs in a
second chat, a *shadow session*, next to the chat where you actually work. It
reads that session's transcript and keeps one structured journal entry up to
date: the goal, the background, what changed, the decisions and the
alternatives that lost, the insights worth keeping, and links to the plans and
scripts the agent produced.

Background and motivation: [LINK TO POST]

## Install

With the [GitHub CLI](https://cli.github.com/manual/gh_skill_install):

```bash
gh skill install stavshamir/shadow-scribe scribe --agent cursor --scope user
```

Or copy the skill folder by hand:

```bash
git clone https://github.com/stavshamir/shadow-scribe
cp -r shadow-scribe/skills/scribe ~/.cursor/skills/
```

Requirements: Cursor, and Python 3.8+ on your `PATH`. The `sqlite3` CLI is
optional; with it, the session picker shows Cursor's chat titles instead of
message previews.

## Usage

1. Work on a task in a normal chat.
2. Open a second chat and run `/scribe @<working-chat>`. Scribe reads the
   transcript so far and writes the first entry.
3. At natural stopping points, type `checkpoint` in the shadow chat. Scribe
   reads the new turns and rewrites the entry.
4. When the task is done, archive both chats. The entry stays.

| Command | What it does |
|---|---|
| `/scribe [@chat]` | Pick a working chat and write its entry |
| `attach [@chat]` | Follow another working chat in the same entry |
| `checkpoint` | Read new turns and rewrite the entry |

You can also tell the shadow chat anything the transcript doesn't show, such
as a decision made in a meeting, and it goes into the entry.

## The vault

Entries live in a single folder, the vault. On first use, Scribe asks where to
create it (`~/memory` by default) and remembers the choice in
`~/.scribe/config.json`. Set `MEMORY_VAULT` to override it.

```text
<vault>/
  journal/     one markdown entry per piece of work
  artifacts/   plans, test plans and scripts copied from the work, per entry
  tags.yaml    the tag vocabulary
  .scribe/     Scribe's bookkeeping; you can ignore it
```

Entries are plain markdown with Obsidian-style wikilinks, so any markdown
reader works. Obsidian works especially well.

## Entry format

Every entry has a Goal, Background and Outcomes. Decisions, Insights, Handoff
(for unfinished work) and References appear when there is something to put in
them. The full format and the rules for what to keep are in
[`skills/scribe/SKILL.md`](skills/scribe/SKILL.md).

Two principles drive those rules:

- **Written for humans and agents alike.** The title, Goal and Outcomes give a
  person the gist in under a minute; labeled **Why** and **Rejected** bullets
  give an agent the reasoning without digging through prose.
- **Keep what is expensive to rediscover.** Reasons, rejected alternatives and
  surprises stay. Commits, PR status and test runs stay in the systems that
  already track them.

## Adapting it

The skill is opinionated. The entry template and the retention rules are plain
instructions in `SKILL.md`; change them to fit how you work.

Only the helper scripts depend on Cursor:

- `find_sessions.py` and `digest_transcript.py` read transcripts from
  `~/.cursor/projects/*/agent-transcripts/`. Other agent harnesses also save
  transcripts, so porting mostly means pointing these scripts at a new location
  and format.
- `find_sessions.py` reads chat titles from Cursor's local state database on
  macOS. The schema is undocumented, so this is best-effort and falls back to
  message previews.

`scribe_state.py` (vault and bookkeeping) is harness-independent.

## Limitations

- Only local chats are supported. Cursor Cloud Agent transcripts are stored on
  Cursor's servers, not on disk.
- Cursor keeps local transcripts for a limited time, so an entry's `session:`
  field is provenance, not a permanent link back to the chat.

## Development

```bash
cd skills/scribe
python3 -m unittest test_scribe_state
```

## License

[MIT](LICENSE)
