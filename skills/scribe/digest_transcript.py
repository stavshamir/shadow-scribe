#!/usr/bin/env python3
"""
Deterministically compact a session transcript slice for /scribe's digest step.

Usage:
  python3 digest_transcript.py --uuid UUID [--since N] [--label TEXT] [--stats]

Reads ~/.cursor/projects/<any-workspace>/agent-transcripts/<uuid>/<uuid>.jsonl
(searching across every Cursor workspace, since a session can live in any of
them) from line index N (0-based, default 0 = whole transcript) to EOF, and prints a
compact plaintext stream: full user-query text, full assistant reasoning text,
and one-line summaries for tool calls (path/command only — no file contents,
diffs, or tool output, none of which the digest step needs to see).

This is a pure extraction/compaction pass, not a summarizer: it does not
decide what's a "decision" or a "loose end" — that judgment stays with the
model reading this script's output.

Output contract:
  - Plaintext to stdout: one block per turn, "### USER" / "### ASSISTANT"
    headers, optionally prefixed with "[<label>] " when --label is given.
  - Final line: "WATERMARK=<n>" where n = the number of lines now consumed
    (pass this back as `--since n` on the next call; store it verbatim in
    the registry sidecar's "watermark" field).
  - With --stats, a compaction summary (input/output bytes, ratio) is
    printed to stderr — informational only, never parsed by the caller.

Transcripts have no tool_result blocks: tool outputs are never persisted,
only the call itself (name + input args). The only record of what a tool
returned is the assistant's own subsequent text — so assistant text is never
trimmed here, only tool_use payloads are.
"""
import json, os, re, sys, argparse, glob

PROJECTS_ROOT = os.path.expanduser("~/.cursor/projects")


def find_transcript(uuid):
    """Locate <uuid>.jsonl under any ~/.cursor/projects/<workspace>/agent-transcripts/."""
    matches = glob.glob(os.path.join(PROJECTS_ROOT, "*", "agent-transcripts", uuid, uuid + ".jsonl"))
    return matches[0] if matches else None

# Commands worth keeping in full (up to SHELL_SIGNAL_CHARS) because they are
# themselves the signal a digest needs (PRs, commits, pushes, branch/test
# state) rather than incidental plumbing.
SHELL_SIGNAL_RE = re.compile(
    r"\bgh pr |\bgh issue |\bgit commit|\bgit push|\bgit merge|\bgit tag"
    r"|\bgit checkout -b|\bgit branch"
)
SHELL_TRUNCATE_CHARS = 200
SHELL_SIGNAL_CHARS = 800
TEXT_FALLBACK_CHARS = 2000  # user text with no <user_query> match (rare/malformed)

# Wrapper tags the harness injects around/alongside <user_query> in user
# turns. Stripped only from the no-match fallback path; see find_sessions.py
# preview() for the same list used by the session picker.
INJECTED_TAGS = (
    "manually_attached_skills", "system_reminder", "additional_data",
    "attached_files", "user_info", "agent_transcripts", "rules",
    "agent_skills", "open_and_recently_viewed_files", "timestamp",
)


def truncate(s, limit):
    s = s.strip()
    return s if len(s) <= limit else s[:limit] + f"…[+{len(s) - limit} chars truncated]"


def extract_user_query(text):
    m = re.search(r"<user_query>(.*?)</user_query>", text, re.S)
    if m:
        return m.group(1).strip()
    # Fallback for turns with no <user_query> wrapper (rare): strip known
    # injected tags, then any remaining tags, then truncate.
    cleaned = text
    for tag in INJECTED_TAGS:
        cleaned = re.sub(rf"<{tag}>.*?</{tag}>", " ", cleaned, flags=re.S)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return truncate(" ".join(cleaned.split()), TEXT_FALLBACK_CHARS)


def summarize_tool_use(block, stats):
    name = block.get("name", "?")
    inp = block.get("input") or {}
    stats["tool_bytes_in"] += len(json.dumps(inp).encode())

    if name == "Shell":
        cmd = inp.get("command", "").strip()
        desc = inp.get("description", "")
        cap = SHELL_SIGNAL_CHARS if SHELL_SIGNAL_RE.search(cmd) else SHELL_TRUNCATE_CHARS
        line = f"[ran] {truncate(cmd, cap)}"
        return line + (f"  # {desc}" if desc and len(cmd) > cap else "")
    if name == "Write":
        return f"[wrote] {inp.get('path', '?')}"
    if name == "StrReplace":
        return f"[edited] {inp.get('path', '?')}"
    if name == "Delete":
        return f"[deleted] {inp.get('path', '?')}"
    if name == "Read":
        return f"[read] {inp.get('path', '?')}"
    if name in ("Glob", "Grep"):
        pat = inp.get("glob_pattern") or inp.get("pattern") or ""
        return f"[{name.lower()}] {pat}"
    if name == "WebSearch":
        return f"[web search] {inp.get('search_term', '')}"
    if name == "WebFetch":
        return f"[web fetch] {inp.get('url', '')}"
    if name == "AskQuestion":
        qs = inp.get("questions") or []
        prompts = "; ".join(q.get("prompt", "") for q in qs if isinstance(q, dict))
        return f"[asked] {truncate(prompts, 400)}"
    if name == "SetActiveBranch":
        return f"[branch] {inp.get('branchName', '?')}"
    if name == "TodoWrite":
        return None  # pure bookkeeping — assistant text already narrates progress
    # Unknown/rare tool: name only, no payload (safe default).
    return f"[{name}]"


def digest(path, since, label, stats):
    prefix = f"[{label}] " if label else ""
    out = []
    line_count = 0
    with open(path) as fh:
        for i, raw in enumerate(fh):
            line_count = i + 1
            if i < since:
                continue
            stats["bytes_in"] += len(raw.encode())
            try:
                ev = json.loads(raw)
            except Exception as e:
                print(f"warning: unparseable line {i} in {path}: {e}", file=sys.stderr)
                continue

            role = ev.get("role") or ev.get("type")
            if role == "turn_ended":
                continue

            content = (ev.get("message") or {}).get("content") or []
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]

            if role == "user":
                text = " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
                query = extract_user_query(text)
                if query:
                    out.append(f"### {prefix}USER\n{query}\n")
                continue

            if role == "assistant":
                texts, tool_lines = [], []
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        texts.append(b.get("text", ""))
                    elif b.get("type") == "tool_use":
                        line = summarize_tool_use(b, stats)
                        if line:
                            tool_lines.append(line)
                block = f"### {prefix}ASSISTANT\n"
                if texts:
                    block += "\n".join(t.strip() for t in texts if t.strip()) + "\n"
                if tool_lines:
                    block += "\n".join(tool_lines) + "\n"
                if texts or tool_lines:
                    out.append(block)
                continue

            # Unknown role — keep a trace rather than silently dropping.
            out.append(f"### {prefix}{role or 'UNKNOWN'}\n{truncate(json.dumps(ev), 300)}\n")

    text_out = "\n".join(out)
    stats["bytes_out"] += len(text_out.encode())
    return text_out, line_count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uuid", required=True, help="Session transcript UUID")
    ap.add_argument("--since", type=int, default=0,
                     help="Lines already digested (the sidecar's stored watermark). Default 0 = whole transcript.")
    ap.add_argument("--label", default="", help="Session label, prefixed on each block when multiple sessions are attached")
    ap.add_argument("--stats", action="store_true", help="Print a compaction summary to stderr")
    args = ap.parse_args()

    path = find_transcript(args.uuid)
    if not path:
        print(f"error: transcript not found for uuid {args.uuid} in any "
              f"{PROJECTS_ROOT}/*/agent-transcripts/", file=sys.stderr)
        sys.exit(1)

    stats = {"bytes_in": 0, "bytes_out": 0, "tool_bytes_in": 0}
    text_out, new_watermark = digest(path, args.since, args.label, stats)

    print(text_out)
    print(f"WATERMARK={new_watermark}")

    if args.stats:
        bi, bo = stats["bytes_in"], stats["bytes_out"]
        pct = 100 * bo / bi if bi else 0
        print(
            f"[digest_transcript] lines {args.since}->{new_watermark}  "
            f"input={bi/1024:.1f}KB  output={bo/1024:.1f}KB  "
            f"({pct:.0f}% of input; tool payload stripped from {stats['tool_bytes_in']/1024:.1f}KB)",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
