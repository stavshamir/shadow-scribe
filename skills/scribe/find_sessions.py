#!/usr/bin/env python3
"""
Find recent agent sessions for the /scribe picker.

Usage:
  python3 find_sessions.py [--self UUID] [--exclude UUID,UUID,...]
                           [--limit N] [--min-turns N] [--pretty]
  python3 find_sessions.py --uuid UUID

Outputs JSON by default (for the agent to build AskQuestion options).
Use --pretty for a human-readable table.

Each session's label prefers Cursor's real chat title (read best-effort from
the local state.vscdb SQLite DB) and falls back to a preview of the first user
message when no title is available.

--uuid resolves a single, already-known session's label the same way, without
listing or excluding anything. Use this when the session was identified
directly from an `@`-mentioned chat transcript path rather than picked from
the recency list — an `@` mention only carries the bare file path, never a
title, so the label still has to be resolved explicitly.

Scans ACROSS every Cursor project workspace (each open folder, plus the
Home/empty-window tab, gets its own `agent-transcripts` dir under
~/.cursor/projects/<project>/), not just the current one — a session relevant
to a scribe chat can live in any of them (e.g. a planning session started from
Cursor's Home tab, or from a different repo's window).
"""
import json, os, re, sys, time, argparse, subprocess, glob

PROJECTS_ROOT = os.path.expanduser("~/.cursor/projects")


def all_transcript_dirs():
    """All existing <project>/agent-transcripts dirs across every workspace."""
    return sorted(glob.glob(os.path.join(PROJECTS_ROOT, "*", "agent-transcripts")))


def iter_transcripts():
    """Yield (uuid, jsonl_path) for every session across every workspace."""
    for base in all_transcript_dirs():
        for d in os.listdir(base):
            f = os.path.join(base, d, d + ".jsonl")
            if os.path.isfile(f):
                yield d, f


def find_transcript(uuid_):
    """Locate a single transcript's jsonl path by UUID across all workspaces.

    Used to resolve an `@`-mentioned session (which only supplies a bare file
    path/UUID, never a title) without paying for a full iter_transcripts()
    scan-and-sort pass over every session.
    """
    for base in all_transcript_dirs():
        f = os.path.join(base, uuid_, uuid_ + ".jsonl")
        if os.path.isfile(f):
            return f
    return None

# Cursor's global UI state DB. Holds chat titles either in a dedicated
# `composerHeaders` table or, on older versions, in ItemTable JSON blobs.
# composerId in these records maps 1:1 to the agent-transcripts UUID.
# NOTE: this is an undocumented, version-fragile schema (it moved in the
# Cursor 3.0 / April 2026 migration, then again to the `composerHeaders`
# table around July 2026). Always treat it as best-effort and let the
# caller fall back to the message preview.
STATE_DB = os.path.expanduser(
    "~/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
)
# Pre-`composerHeaders`-table fallback: 3.0+ key first, then the pre-3.0
# location, both in ItemTable.
TITLE_KEYS = ("composer.composerHeaders", "composer.composerData")


def user_text(ev):
    content = (ev.get("message") or {}).get("content") or []
    return " ".join(
        b.get("text", "")
        for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    )


def preview(path, limit=100):
    """Extract a clean human-readable preview from the first useful user turn."""
    first_text = None
    with open(path) as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("role") != "user":
                continue
            t = user_text(ev)
            if not t:
                continue
            if first_text is None:
                first_text = t
            # Prefer the explicit <user_query> block if present
            m = re.search(r"<user_query>(.*?)</user_query>", t, re.S)
            if m:
                return " ".join(m.group(1).split())[:limit]

    if first_text:
        # Strip known injected wrapper blocks, then all remaining tags
        for tag in ("manually_attached_skills", "system_reminder",
                    "additional_data", "attached_files", "user_info",
                    "agent_transcripts", "rules", "agent_skills"):
            first_text = re.sub(rf"<{tag}>.*?</{tag}>", " ", first_text, flags=re.S)
        cleaned = " ".join(re.sub(r"<[^>]+>", " ", first_text).split())
        return cleaned[:limit] or "(no user text)"

    return "(no user text)"


def count_turns(path):
    """Count user turns in a transcript."""
    n = 0
    with open(path) as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("role") == "user":
                n += 1
    return n


def load_titles_from_table():
    """Titles from Cursor's dedicated `composerHeaders` SQL table.

    Cursor migrated composer headers off the `ItemTable` JSON-blob keys (see
    TITLE_KEYS) into a live `composerHeaders` table (one row per composer,
    `value` = the same per-composer JSON `ItemTable` used to bundle) once
    `composer.composerHeaders.tableGateEnabled` flips to true. When that
    happens, the old blob keys freeze in place (stop being updated) rather
    than disappearing, so reading them silently returns stale/incomplete
    data instead of erroring — this must be tried FIRST, not as a fallback.
    Returns {} if the table doesn't exist (pre-migration Cursor versions).
    """
    try:
        out = subprocess.run(
            ["sqlite3", "-readonly", "-json", STATE_DB,
             "SELECT composerId, value FROM composerHeaders;"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return {}
    if not out:
        return {}
    try:
        rows = json.loads(out)
    except Exception:
        return {}
    titles = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = row.get("composerId")
        try:
            val = json.loads(row.get("value") or "{}")
        except Exception:
            continue
        name = val.get("name") or val.get("title")
        if cid and name:
            titles[cid] = name
    return titles


def load_titles():
    """Best-effort map of {composerId/uuid: title} from Cursor's state.vscdb.

    Returns {} on any failure (DB missing, schema changed, sqlite3 absent),
    so the caller can fall back to message previews.
    """
    if not os.path.isfile(STATE_DB):
        return {}

    table_titles = load_titles_from_table()
    if table_titles:
        return table_titles

    # Fallback for pre-migration Cursor versions: headers as one JSON blob
    # under an ItemTable key.
    for key in TITLE_KEYS:
        try:
            out = subprocess.run(
                ["sqlite3", "-readonly", STATE_DB,
                 f"SELECT value FROM ItemTable WHERE key='{key}';"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except Exception:
            continue
        if not out:
            continue
        try:
            data = json.loads(out)
        except Exception:
            continue
        # The records may live directly in a list, or nested under a list-valued
        # field (e.g. "allComposers" pre-3.0). Find the first list of dicts.
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = next(
                (v for v in data.values()
                 if isinstance(v, list) and v and isinstance(v[0], dict)),
                [],
            )
        else:
            items = []
        titles = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            cid = it.get("composerId") or it.get("id")
            name = it.get("name") or it.get("title")
            if cid and name:
                titles[cid] = name
        if titles:
            return titles
    return {}


def age_label(minutes):
    if minutes < 90:
        return f"{minutes}m"
    if minutes < 24 * 60:
        return f"{minutes // 60}h"
    return f"{minutes // (60 * 24)}d"


def whoami():
    """UUID of the most-recently-modified transcript across every workspace.

    This is the scribe's own best-guess UUID (see the Self-identification
    caveat in SKILL.md: it's a strong hint, not a certainty, when other
    Cursor chats are concurrently active).
    """
    newest = max(iter_transcripts(), key=lambda df: os.path.getmtime(df[1]), default=None)
    return newest[0] if newest else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--whoami", action="store_true",
                    help="Print the best-guess self UUID (newest transcript across all workspaces) and exit")
    ap.add_argument("--uuid", dest="lookup_uuid", default=None,
                    help="Resolve a single session's label by UUID (e.g. from an @-mentioned "
                         "transcript path) and exit — skips listing/excluding entirely")
    ap.add_argument("--self", dest="self_uuid", default=None,
                    help="The scribe's own UUID to exclude")
    ap.add_argument("--exclude", default="",
                    help="Comma-separated UUIDs to also exclude (already-attached sessions)")
    ap.add_argument("--limit", type=int, default=10,
                    help="How many sessions to return (default 10)")
    ap.add_argument("--min-turns", type=int, default=1, dest="min_turns",
                    help="Skip sessions with fewer than this many user turns (default 1)")
    ap.add_argument("--pretty", action="store_true",
                    help="Print a human-readable table instead of JSON")
    args = ap.parse_args()

    if args.whoami:
        print(whoami() or "")
        return

    if args.lookup_uuid:
        f = find_transcript(args.lookup_uuid)
        if not f:
            print(json.dumps({"uuid": args.lookup_uuid, "found": False}))
            return
        titles = load_titles()
        title = titles.get(args.lookup_uuid)
        prev = preview(f)
        row = {
            "uuid": args.lookup_uuid,
            "turns": count_turns(f),
            "title": title,
            "preview": prev,
            "label": title or prev,
            "found": True,
        }
        print(json.dumps(row, indent=2))
        return

    excl = {u.strip() for u in args.exclude.split(",") if u.strip()}
    if args.self_uuid:
        excl.add(args.self_uuid)

    titles = load_titles()

    rows = []
    for d, f in iter_transcripts():
        if d in excl:
            continue
        turns = count_turns(f)
        if turns < args.min_turns:
            continue
        mtime = os.path.getmtime(f)
        age_min = int((time.time() - mtime) / 60)
        prev = preview(f)
        title = titles.get(d)
        rows.append({
            "uuid": d,
            "mtime": mtime,
            "age_min": age_min,
            "turns": turns,
            "title": title,
            "preview": prev,
            # Real chat title when available, message preview otherwise.
            "label": title or prev,
        })

    rows.sort(key=lambda r: r["mtime"], reverse=True)
    rows = rows[: args.limit]

    if args.pretty:
        for i, r in enumerate(rows, 1):
            print(f"[{i:>2}] {age_label(r['age_min']):>4} · {r['turns']:>2} turns · "
                  f"{r['label']}")
    else:
        # Drop mtime from JSON output (not useful to the agent)
        for r in rows:
            del r["mtime"]
        print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
