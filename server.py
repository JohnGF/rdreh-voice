#!/usr/bin/env python3
"""Minimal zero-dependency HTTP bridge and voice-command router for rdreh."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
DEFAULT_LOCAL_RDR = Path("/home/john/git/rdreh/target/release/rdr")

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
BOX_RE = re.compile(r"[─│┌┐└┘├┤┬┴┼╭╮╰╯═║╔╗╚╝╠╣╦╩╬▀▄█▌▐░▒▓]+")

# TUI footer / status / chrome lines that should never be spoken aloud
TUI_CHROME_RE = re.compile(
    r"(?i)^(?:"
    r".*(?:auto mode on|bypass permissions|shift\+tab|esc to interrupt|esc to cancel|"
    r"enter to select|enter to confirm|to navigate|to manage|ctrl\+[a-z] to|"
    r"type a message|type your message|send a message).*|"
    r"(?:auto|plan|ask|edit|normal|yolo|bypass|default)\s+·\s+.*|"
    r".*\s+·\s+(?:low|medium|high|max|fast|minimal)(?:\s+·\s+.*)?|"
    r"(?:baked|churned|cooked|worked|thought|brewed|ran)\s+for\s+\d+[hms].*|"
    r"(?:ran|read|edited|wrote|created|deleted|searched|listed|fetched)\s+\d+\s+(?:shell|command|file|match|line).*|"
    r"(?:loading|thinking|working|streaming)\.{0,3}"
    r")$"
)

ACTION_PROMPT_RE = re.compile(
    r"(?i)(?:"
    r"\[[yn]/[yn]\]|\([yn]/[yn]\)|\(yes/no\)|"
    r"\b(?:do you want to|would you like to)\b|"
    r"\b(?:please confirm|waiting for (?:approval|confirmation|input|user)|permission required|"
    r"approve this|allow this|select an option|choose an option|please do this now)\b"
    r")"
)

NUMBERED_OPT_RE = re.compile(r"^\s*(?:[❯›▸▹►•\-*]\s*)?(\d{1,2})[.)]\s+(.+)$")
PROMPT_INPUT_RE = re.compile(r"^\s*[❯›$%#]\s*(.*)$")
LEADING_SYMBOL_RE = re.compile(r"^[\s●○◉◎◆◇▪▫▸▹►◄▲▼❯›»«✓✔✗✘⚠⚡✻✽✶✳✢⏵⏸⏹⏎←→↑↓↔↕↩↪·•‣⁃⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏\-*]+")


def resolve_rdr_bin() -> str:
    env_bin = os.environ.get("RDR_BIN")
    if env_bin:
        return env_bin
    if DEFAULT_LOCAL_RDR.exists() and os.access(DEFAULT_LOCAL_RDR, os.X_OK):
        return str(DEFAULT_LOCAL_RDR)
    found = shutil.which("rdr")
    if found:
        return found
    raise RuntimeError("Could not find `rdr` binary. Set RDR_BIN or build rdreh.")


def run_rdr(rdr_bin: str, session: str | None, args: list[str]) -> str:
    cmd = [rdr_bin]
    if session:
        cmd.extend(["--session", session])
    cmd.extend(args)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip() or f"rdr exited with {proc.returncode}"
        raise RuntimeError(err)
    return proc.stdout


def sanitize_for_speech(text: str) -> str:
    """Keep only spoken words, digits, and natural pause/sentence punctuation."""
    s = ANSI_RE.sub("", text)
    s = BOX_RE.sub(" ", s)
    # Normalize common typographic punctuation before stripping symbols
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", " ").replace("\u201d", " ")
    s = s.replace("\u2013", "-").replace("\u2014", ", ")
    s = s.replace("&", " and ")
    # Convert semicolons and non-prose colons (e.g. :8765) to soft pauses/spaces
    s = s.replace(";", ", ")
    s = re.sub(r":(?!\s)", " ", s)
    # Remove markdown emphasis/code ticks, paths, brackets, and operators
    s = re.sub(r"[`*_~#|\\/<>\[\]{}=+$@^]+", " ", s)
    # Replace parentheses with soft pauses
    s = s.replace("(", ", ").replace(")", ", ")
    # Remove dots inside filenames/IPs/versions (e.g. server.py, 10.0.0.100)
    s = re.sub(r"(?<=\w)\.(?=\w)", " ", s)
    # Keep apostrophes only inside contractions/possessives (e.g. don't, agent's)
    s = re.sub(r"(?<![A-Za-z])'|'(?![A-Za-z])", " ", s)
    # Keep % only immediately after digits (e.g. 50%)
    s = re.sub(r"(?<!\d)%", " ", s)
    # Strip any remaining non-letter/non-digit characters except basic sentence punctuation
    s = re.sub(r"[^A-Za-z0-9.,?!:'\-\s%]", " ", s)
    # Convert spaced dashes into comma pauses, keeping intra-word hyphens (e.g. rdreh-voice, 20-30)
    s = re.sub(r"\s+-+\s+", ", ", s)
    s = re.sub(r"(?<!\w)-+|-(?!\w)", " ", s)
    # Clean up punctuation spacing and repeated punctuation
    s = re.sub(r"\s+([.,?!:])", r"\1", s)
    s = re.sub(r"([.,?!:]){2,}", r"\1", s)
    s = re.sub(r"(?:(?<=^)|(?<=\s))[.,?!:]+(?=\s|$)", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" ,:-")


def _extract_clean_lines(text: str) -> list[str]:
    stripped = ANSI_RE.sub("", text)
    stripped = BOX_RE.sub(" ", stripped)
    raw_lines = [re.sub(r"\s+", " ", ln).strip() for ln in stripped.splitlines()]

    cleaned: list[str] = []
    for ln in raw_lines:
        if not ln:
            continue
        # Preserve numbered option lines even if prefixed by cursor marker (e.g. "❯ 1. Yes")
        if NUMBERED_OPT_RE.match(ln):
            cleaned.append(ln)
            continue
        # Drop bottom prompt input lines ("❯", "❯ some typed text")
        if PROMPT_INPUT_RE.match(ln):
            continue
        # Drop lines with no alphanumeric content (pure dividers/spinners/symbols)
        if not re.search(r"[A-Za-z0-9]", ln):
            continue
        no_marker = LEADING_SYMBOL_RE.sub("", ln).strip()
        if not no_marker or not re.search(r"[A-Za-z0-9]", no_marker):
            continue
        if TUI_CHROME_RE.match(no_marker):
            continue
        cleaned.append(ln)
    return cleaned


def _format_options_block(lines: list[str]) -> tuple[str, int] | None:
    """If recent lines contain a numbered option list, return (spoken_text, start_idx)."""
    opt_indices = [i for i, ln in enumerate(lines) if NUMBERED_OPT_RE.match(ln)]
    if len(opt_indices) < 2:
        return None
    # Focus on the last contiguous/near-contiguous group of options
    last_group: list[int] = [opt_indices[-1]]
    for idx in reversed(opt_indices[:-1]):
        if last_group[-1] - idx <= 3:
            last_group.append(idx)
        else:
            break
    last_group.reverse()
    if len(last_group) < 2:
        return None

    first_opt = last_group[0]
    # Include up to 3 context/question lines right above the first option
    ctx_start = max(0, first_opt - 3)
    ctx_lines = [LEADING_SYMBOL_RE.sub("", ln).strip() for ln in lines[ctx_start:first_opt]]
    ctx_lines = [c for c in ctx_lines if c]

    parts: list[str] = []
    if ctx_lines:
        parts.append(" ".join(ctx_lines))
    for i in range(first_opt, last_group[-1] + 1):
        m = NUMBERED_OPT_RE.match(lines[i])
        if m:
            num, opt_text = m.group(1), m.group(2).strip()
            parts.append(f"Option {num}: {opt_text}.")
    return " ".join(parts), ctx_start


def _truncate_spoken(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + "." if cut and cut[-1] not in ".?!" else cut


def analyze_for_tts(text: str, *, max_chars: int = 480) -> dict[str, str]:
    """Extract only relevant spoken content and classify whether user action is needed."""
    lines = _extract_clean_lines(text)
    if not lines:
        return {"kind": "finished", "spoken": ""}

    # 1. Check for numbered options / choices (e.g. permission menu or multi-choice question)
    opts = _format_options_block(lines[-20:])
    if opts is not None:
        raw_spoken, _ = opts
        spoken = sanitize_for_speech(raw_spoken)
        kind = "action" if ACTION_PROMPT_RE.search(raw_spoken) else "question"
        return {"kind": kind, "spoken": _truncate_spoken(spoken, max_chars)}

    # 2. Check recent lines for explicit action/permission prompt or a direct question
    recent = [LEADING_SYMBOL_RE.sub("", ln).strip() for ln in lines[-10:]]
    recent = [ln for ln in recent if ln]
    joined_recent = " ".join(recent)

    if ACTION_PROMPT_RE.search(joined_recent):
        # Take from the line that triggered the action prompt through the end
        start = 0
        for i, ln in enumerate(recent):
            if ACTION_PROMPT_RE.search(ln):
                start = max(0, i - 1)
                break
        spoken = sanitize_for_speech(" ".join(recent[start:]))
        return {"kind": "action", "spoken": _truncate_spoken(spoken, max_chars)}

    # Direct question (line ending with '?' in the last few lines)
    q_idx = next((i for i in range(len(recent) - 1, -1, -1) if recent[i].rstrip().endswith("?")), None)
    if q_idx is not None:
        start = max(0, q_idx - 2)
        spoken = sanitize_for_speech(" ".join(recent[start:]))
        return {"kind": "question", "spoken": _truncate_spoken(spoken, max_chars)}

    # 3. Normal completion: read the concluding prose (skipping code/noise if possible)
    prose = [ln for ln in recent if len(ln.split()) >= 3]
    chosen = prose[-4:] if prose else recent[-3:]
    spoken = sanitize_for_speech(" ".join(chosen))
    return {"kind": "finished", "spoken": _truncate_spoken(spoken, max_chars)}


def clean_for_tts(text: str, max_lines: int = 6, max_chars: int = 420) -> str:
    del max_lines  # Kept for signature compatibility
    return analyze_for_tts(text, max_chars=max_chars)["spoken"] or "No recent output."


GENERIC_SHELL_NAMES = {
    "fish",
    "bash",
    "zsh",
    "sh",
    "agy",
    "claude",
    "opencode",
    "codex",
    "env",
    "uv",
    "python",
    "python3",
    "node",
}


def pane_job_label(cwd: str, title: str) -> str:
    """Build a short spoken identifier from the pane directory and/or chat title."""
    cwd_clean = (cwd or "").strip().rstrip("/")
    home_dir = str(Path.home()).rstrip("/")
    dir_name = ""
    if cwd_clean and cwd_clean != home_dir:
        dir_name = sanitize_for_speech(Path(cwd_clean).name)

    chat = (title or "").strip()
    # Strip trailing " - fish", " - agy", etc.
    chat = re.sub(r"\s+-\s+(?:fish|bash|zsh|sh|agy|claude|opencode|codex|env)\s*$", "", chat, flags=re.IGNORECASE)
    # Strip leading path prefix like "~/git/proj: " or "~: "
    chat = re.sub(r"^(?:~|/[A-Za-z0-9_.\-/]+)\s*[:\-]\s*", "", chat)
    # If the remaining title is just a filesystem path (e.g. "~/git/rdreh-voice"), ignore it
    if re.match(r"^(?:~(?:/.*)?|/[A-Za-z0-9_.\-/]*)$", chat):
        chat = ""
    # Strip leading "claude - " or "agy - " prefix if a descriptive title follows
    chat = re.sub(r"^(?:agy|claude|opencode|codex)\s+-\s+", "", chat, flags=re.IGNORECASE)
    chat_clean = sanitize_for_speech(chat)

    if chat_clean.lower() in GENERIC_SHELL_NAMES or chat_clean in {"", "~"}:
        chat_clean = ""
    if dir_name and chat_clean and chat_clean.lower() == dir_name.lower():
        chat_clean = ""

    if dir_name and chat_clean:
        return f"in {dir_name}, {chat_clean}"
    if dir_name:
        return f"in {dir_name}"
    if chat_clean:
        return f"on {chat_clean}"
    return ""


def format_pane_announcement(
    who: str,
    state: str,
    analysis: dict[str, str],
    *,
    job_label: str = "",
) -> str:
    kind = analysis.get("kind", "finished")
    spoken = analysis.get("spoken", "")
    subject = f"{who} {job_label}".strip() if job_label else who
    if kind == "question":
        lead = f"{subject} is asking a question."
        return f"{lead} {spoken}".strip() if spoken else lead
    if kind == "action":
        lead = f"{subject} needs action."
        return f"{lead} {spoken}".strip() if spoken else lead
    if state == "working":
        lead = f"{subject} is working."
        return f"{lead} {spoken}".strip() if spoken else lead
    lead = f"{subject} finished."
    parts = [lead]
    if spoken:
        parts.append(spoken)
    parts.append("What are your actions?")
    return " ".join(parts)


def fetch_panes(rdr_bin: str, session: str | None) -> dict[str, Any]:
    raw_list = json.loads(run_rdr(rdr_bin, session, ["list"]))
    counts_raw = run_rdr(rdr_bin, session, ["counts"]).strip().split()
    counts = {
        "total": int(counts_raw[0]) if len(counts_raw) > 0 else 0,
        "busy": int(counts_raw[1]) if len(counts_raw) > 1 else 0,
        "finished": int(counts_raw[2]) if len(counts_raw) > 2 else 0,
    }

    flat_panes: list[dict[str, Any]] = []
    workspaces: list[dict[str, Any]] = []
    global_num = 1
    agent_num = 1
    for ws in raw_list.get("workspaces", []):
        ws_idx = ws.get("index")
        ws_name = ws.get("name") or f"ws-{ws_idx}"
        ws_panes: list[dict[str, Any]] = []
        for ws_pane_idx, pane in enumerate(ws.get("panes", []), start=1):
            state_raw = str(pane.get("state") or "unknown").lower()
            is_agent = bool(pane.get("agent"))
            assigned_agent_num = agent_num if is_agent else None
            if is_agent:
                agent_num += 1
            item = {
                "global_num": global_num,
                "ws_pane_num": ws_pane_idx,
                "agent_num": assigned_agent_num,
                "id": pane["id"],
                "workspace_index": ws_idx,
                "workspace_name": ws_name,
                "focused": bool(pane.get("focused")),
                "command": pane.get("command") or "",
                "title": pane.get("title") or "",
                "agent": is_agent,
                "state": state_raw,
                "cwd": pane.get("cwd") or "",
                "job_label": pane_job_label(pane.get("cwd") or "", pane.get("title") or ""),
            }
            flat_panes.append(item)
            ws_panes.append(item)
            global_num += 1

        workspaces.append(
            {
                "index": ws_idx,
                "name": ws_name,
                "layout": ws.get("layout") or "",
                "active": bool(ws.get("active")),
                "panes": ws_panes,
            }
        )

    return {"ok": True, "counts": counts, "workspaces": workspaces, "panes": flat_panes}


def resolve_target_pane(
    panes: list[dict[str, Any]],
    ref: int | None,
    *,
    view_mode: str = "agents",
    active_workspace: int | None = None,
    ws_ref: int | None = None,
) -> dict[str, Any] | None:
    if ref is None:
        if active_workspace is not None:
            ws_focused = next(
                (p for p in panes if p["workspace_index"] == active_workspace and p["focused"]),
                None,
            )
            if ws_focused:
                return ws_focused
        return next((p for p in panes if p["focused"]), panes[0] if panes else None)

    if ws_ref is not None:
        by_ws_pane = next(
            (p for p in panes if p["workspace_index"] == ws_ref and p["ws_pane_num"] == ref),
            None,
        )
        if by_ws_pane:
            return by_ws_pane

    if view_mode == "agents":
        by_agent = next((p for p in panes if p["agent_num"] == ref), None)
        if by_agent:
            return by_agent

    if view_mode == "workspace" and active_workspace is not None:
        by_ws = next(
            (p for p in panes if p["workspace_index"] == active_workspace and p["ws_pane_num"] == ref),
            None,
        )
        if by_ws:
            return by_ws

    by_global = next((p for p in panes if p["global_num"] == ref), None)
    if by_global:
        return by_global
    return next((p for p in panes if p["id"] == ref), None)


def pane_label_num(pane: dict[str, Any], view_mode: str = "agents") -> int:
    if view_mode == "agents" and pane.get("agent_num") is not None:
        return int(pane["agent_num"])
    if view_mode == "workspace" and pane.get("ws_pane_num") is not None:
        return int(pane["ws_pane_num"])
    return int(pane.get("global_num") or pane["id"])


def send_to_pane(rdr_bin: str, session: str | None, pane_id: int, text: str, enter: bool) -> None:
    if text:
        run_rdr(rdr_bin, session, ["send", "--no-enter", str(pane_id), "--", text])
        if enter:
            time.sleep(0.06)
            run_rdr(rdr_bin, session, ["send", str(pane_id), ""])
    elif enter:
        run_rdr(rdr_bin, session, ["send", str(pane_id), ""])


SPOKEN_NUMS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "tree": "3",
    "free": "3",
    "four": "4",
    "for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "ate": "8",
    "nine": "9",
    "ten": "10",
    "won": "1",
    "to": "2",
    "too": "2",
}


def normalize_spoken_targets(text: str) -> str:
    """Convert spoken target numbers and STT homophones like 'agents tree' -> 'agent 3'."""
    words = "|".join(SPOKEN_NUMS.keys())
    pattern = re.compile(
        rf"\b(agents?|panes?|windows?|workspaces?|tabs?)\s+({words}|\d+)\b",
        re.IGNORECASE,
    )

    def _repl(m: re.Match[str]) -> str:
        noun = m.group(1).lower().rstrip("s")
        raw_num = m.group(2).lower()
        num = SPOKEN_NUMS.get(raw_num, raw_num)
        return f"{noun} {num}"

    return pattern.sub(_repl, text)


def tail_pane(rdr_bin: str, session: str | None, pane_id: int, lines: int = 40) -> str:
    out = run_rdr(rdr_bin, session, ["tail", str(pane_id), "-n", str(lines), "--json"])
    data = json.loads(out)
    return str(data.get("text") or "")


def _norm_dir_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _search_roots(panes: list[dict[str, Any]] | None = None) -> list[Path]:
    roots: list[Path] = []
    for cand in [Path.home() / "git", Path.home()]:
        if cand.is_dir() and cand not in roots:
            roots.append(cand)
    for p in panes or []:
        cwd = p.get("cwd")
        if cwd:
            path = Path(cwd)
            if path.is_dir() and path not in roots:
                roots.append(path)
    return roots


def resolve_spoken_directory(query: str, panes: list[dict[str, Any]] | None = None) -> Path | None:
    """Resolve a spoken folder name or path against ~/git, ~, and open pane directories."""
    cleaned = query.strip().strip("\"'.,!?")
    if not cleaned:
        return None
    direct = Path(cleaned).expanduser()
    if direct.is_dir():
        return direct

    # Support "<sub_dir> in <parent_dir>"
    in_match = re.match(r"^(.+?)\s+in\s+(.+)$", cleaned, re.IGNORECASE)
    if in_match:
        parent = resolve_spoken_directory(in_match.group(2), panes)
        if parent:
            child = resolve_spoken_directory(in_match.group(1), [{"cwd": str(parent)}])
            if child:
                return child

    q_norm = _norm_dir_name(cleaned)
    if not q_norm:
        return None

    candidates: list[tuple[int, Path]] = []
    seen: set[Path] = set()
    for root in _search_roots(panes):
        for depth_path in [root, *(d for d in root.iterdir() if d.is_dir() and not d.name.startswith("."))]:
            if depth_path in seen:
                continue
            seen.add(depth_path)
            name_norm = _norm_dir_name(depth_path.name)
            if name_norm == q_norm:
                candidates.append((0, depth_path))
            elif name_norm.startswith(q_norm):
                candidates.append((1, depth_path))
            elif q_norm in name_norm:
                candidates.append((2, depth_path))
        # Also check 2nd-level directories under ~/git (e.g. ~/git/bci_projects/galaxy_watch_lsl)
        if root == Path.home() / "git":
            for sub in root.iterdir():
                if not sub.is_dir() or sub.name.startswith("."):
                    continue
                for leaf in sub.iterdir():
                    if not leaf.is_dir() or leaf.name.startswith(".") or leaf in seen:
                        continue
                    seen.add(leaf)
                    name_norm = _norm_dir_name(leaf.name)
                    if name_norm == q_norm:
                        candidates.append((3, leaf))
                    elif name_norm.startswith(q_norm):
                        candidates.append((4, leaf))
                    elif q_norm in name_norm:
                        candidates.append((5, leaf))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], len(item[1].name)))
    return candidates[0][1]


def list_spoken_directories(parent_query: str | None = None, panes: list[dict[str, Any]] | None = None) -> list[str]:
    base = resolve_spoken_directory(parent_query, panes) if parent_query else (Path.home() / "git")
    if base is None or not base.is_dir():
        base = Path.home()
    return sorted(d.name for d in base.iterdir() if d.is_dir() and not d.name.startswith("."))


def summarize_git_changes(cwd: str) -> str:
    """Return a concise spoken summary of git working-tree changes in `cwd`."""
    if not cwd:
        return "No working directory for that pane."
    label = Path(cwd).name or cwd
    proc = subprocess.run(
        ["git", "-C", cwd, "status", "--short"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if proc.returncode != 0:
        return f"Not a git repository in {label}."
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        return f"Working tree is clean in {label}."
    modified = sum(1 for ln in lines if not ln.startswith("??"))
    untracked = sum(1 for ln in lines if ln.startswith("??"))
    names = [Path(ln[3:].split(" -> ")[-1].strip()).name for ln in lines[:4]]
    parts = []
    if modified:
        parts.append(f"{modified} modified")
    if untracked:
        parts.append(f"{untracked} untracked")
    file_list = ", ".join(names)
    more = f", and {len(lines) - 4} more" if len(lines) > 4 else ""
    return f"{', '.join(parts)} in {label}: {file_list}{more}."


def summarize_tokens(rdr_bin: str) -> str:
    """Return a concise spoken summary from `rdr tokens --json`."""
    try:
        raw = run_rdr(rdr_bin, None, ["tokens", "--json"])
        data = json.loads(raw)
    except Exception as exc:
        return f"Could not read token usage: {exc}"
    if isinstance(data, dict):
        today = data.get("today") or data.get("Today") or {}
        if isinstance(today, dict) and today:
            total = today.get("total") or today.get("tokens") or sum(
                v for v in today.values() if isinstance(v, (int, float))
            )
            return f"Today's token usage is {int(total):,} tokens."
        if "total" in data and isinstance(data["total"], (int, float)):
            return f"Total token usage is {int(data['total']):,} tokens."
    return "Token telemetry is available, but no summary count was found."


def parse_and_execute_command(
    rdr_bin: str,
    session: str | None,
    transcript: str,
    default_pane: int | None,
    *,
    active_workspace: int | None = None,
    view_mode: str = "agents",
) -> dict[str, Any]:
    raw = normalize_spoken_targets(transcript.strip())
    if not raw:
        return {"ok": False, "error": "Empty command", "spoken": "Nothing heard."}

    state = fetch_panes(rdr_bin, session)
    panes = state["panes"]
    workspaces = state["workspaces"]

    # Optional leading "window N" / "workspace N" scope for cross-window commands
    ws_ref: int | None = None
    scoped_raw = raw
    ws_prefix = re.match(r"^(?:window|workspace|tab)\s+(\d+)\s*[:,]?\s+(.+)$", raw, re.IGNORECASE | re.DOTALL)
    if ws_prefix:
        ws_ref = int(ws_prefix.group(1))
        scoped_raw = ws_prefix.group(2).strip()

    lower = scoped_raw.lower().strip(" .!?")

    # View / window switching
    if lower in {"agents", "agents tab", "agent tab", "show agents", "all agents"}:
        agent_count = sum(1 for p in panes if p["agent"])
        return {
            "ok": True,
            "action": "switch_view",
            "view_mode": "agents",
            "spoken": f"Agents tab, {agent_count} agents.",
        }

    m = re.match(r"^(?:switch\s+to\s+|show\s+|open\s+)?(?:window|workspace|tab)\s+(\d+)$", lower)
    if m:
        idx = int(m.group(1))
        ws = next((w for w in workspaces if w["index"] == idx), None)
        if not ws:
            return {"ok": False, "error": f"Unknown window {idx}", "spoken": f"Window {idx} not found."}
        return {
            "ok": True,
            "action": "switch_view",
            "view_mode": "workspace",
            "workspace_index": idx,
            "spoken": f"Window {idx}, {ws['name']}, {len(ws['panes'])} panes.",
        }

    # Status / counts
    if lower in {"status", "counts", "report", "summary"}:
        c = state["counts"]
        spoken = f"{c['total']} agents total: {c['busy']} working, {c['finished']} finished."
        return {"ok": True, "action": "status", "spoken": spoken, "counts": c}

    # Repeat last spoken announcement
    if lower in {"repeat", "say again", "what did you say", "pardon"}:
        return {"ok": True, "action": "repeat", "spoken": ""}

    # Token usage summary
    if lower in {"tokens", "token usage", "usage", "spend", "how many tokens"}:
        return {"ok": True, "action": "tokens", "spoken": summarize_tokens(rdr_bin)}

    # List directories ("list projects", "list directories in bci projects")
    m = re.match(
        r"^(?:list|show|what)\s+(?:projects|directories|folders|repos)(?:\s+in\s+(.+))?$",
        lower,
    )
    if m:
        parent_q = m.group(1)
        dirs = list_spoken_directories(parent_q, panes)
        if not dirs:
            return {"ok": True, "action": "list_dirs", "spoken": "No folders found."}
        preview = ", ".join(dirs[:8])
        more = f", and {len(dirs) - 8} more" if len(dirs) > 8 else ""
        return {"ok": True, "action": "list_dirs", "dirs": dirs, "spoken": f"Folders: {preview}{more}."}

    # Open directory as a new workspace ("open project rdreh", "open directory dotfiles", "open rdreh quad")
    m = re.match(
        r"^(?:open|add)\s+(?:(?:project|directory|folder|workspace)\s+)?(.+?)(?:\s+(?:with\s+|in\s+)?(single|dual|tri|quad|rows)\s*(?:layout)?)?$",
        scoped_raw.strip(" .!?"),
        re.IGNORECASE,
    )
    if m and not re.match(r"^(?:window|workspace|tab)\s+\d+$", lower):
        dir_query = m.group(1).strip()
        layout = m.group(2).lower() if m.group(2) else None
        resolved = resolve_spoken_directory(dir_query, panes)
        if not resolved:
            return {
                "ok": False,
                "error": f"Directory not found: {dir_query}",
                "spoken": f"Could not find folder {dir_query}.",
            }
        args = ["add", str(resolved)]
        if layout:
            args.append(layout)
        run_rdr(rdr_bin, session, args)
        return {
            "ok": True,
            "action": "open_dir",
            "path": str(resolved),
            "spoken": f"Opened {resolved.name}.",
        }

    # Change directory in target pane ("cd rdreh", "go to dotfiles in agent 1")
    m = re.match(
        r"^(?:cd|go\s+to|switch\s+directory\s+to)\s+(.+?)(?:\s+(?:in|on)\s+(?:agent\s+|pane\s+)?(\d+))?$",
        scoped_raw.strip(" .!?"),
        re.IGNORECASE,
    )
    if m:
        dir_query = m.group(1).strip()
        num = int(m.group(2)) if m.group(2) else None
        resolved = resolve_spoken_directory(dir_query, panes)
        if not resolved:
            return {
                "ok": False,
                "error": f"Directory not found: {dir_query}",
                "spoken": f"Could not find folder {dir_query}.",
            }
        target = (
            resolve_target_pane(
                panes, num, view_mode=view_mode, active_workspace=active_workspace, ws_ref=ws_ref
            )
            if num is not None
            else (
                next((p for p in panes if p["id"] == default_pane), None)
                or resolve_target_pane(
                    panes, None, view_mode=view_mode, active_workspace=active_workspace
                )
            )
        )
        if not target:
            return {"ok": False, "error": "No target pane available", "spoken": "No pane found."}
        send_to_pane(rdr_bin, session, target["id"], f"cd '{resolved}'", True)
        lnum = pane_label_num(target, "workspace" if ws_ref is not None else view_mode)
        noun = "agent" if (ws_ref is None and view_mode == "agents" and target.get("agent_num") is not None) else "pane"
        return {
            "ok": True,
            "action": "cd",
            "pane": target["id"],
            "path": str(resolved),
            "spoken": f"Changed {noun} {lnum} to {resolved.name}.",
        }

    # Git diff / working tree summary ("what changed", "what changed in agent 1")
    m = re.match(
        r"^(?:what changed|changes|git status)(?:\s+(?:in|for|on)\s+(?:agent\s+|pane\s+)?(\d+))?$",
        lower,
    )
    if m:
        num = int(m.group(1)) if m.group(1) else None
        target = (
            resolve_target_pane(panes, num, view_mode=view_mode, active_workspace=active_workspace, ws_ref=ws_ref)
            if num is not None
            else (
                next((p for p in panes if p["id"] == default_pane), None)
                or resolve_target_pane(panes, None, view_mode=view_mode, active_workspace=active_workspace, ws_ref=ws_ref)
            )
        )
        if not target:
            return {"ok": False, "error": "No target pane available", "spoken": "No pane found."}
        return {
            "ok": True,
            "action": "git_status",
            "pane": target["id"],
            "spoken": summarize_git_changes(target.get("cwd", "")),
        }

    # Focus / select pane ("focus agent 1", "select pane 2", or bare "agent 3")
    m = re.match(r"^(?:(?:focus|select|switch\s+to)\s+)?(?:agent|pane)\s+(\d+)$", lower)
    if m:
        num = int(m.group(1))
        target = resolve_target_pane(
            panes, num, view_mode=view_mode, active_workspace=active_workspace, ws_ref=ws_ref
        )
        if not target:
            return {"ok": False, "error": f"Unknown target {num}", "spoken": f"Target {num} not found."}
        lnum = pane_label_num(target, "workspace" if ws_ref is not None else view_mode)
        noun = "agent" if (ws_ref is None and view_mode == "agents" and target.get("agent_num") is not None) else "pane"
        return {
            "ok": True,
            "action": "focus",
            "pane": target["id"],
            "spoken": f"Focused {noun} {lnum}.",
        }

    # Read all finished / active agents
    if lower in {"read all", "read finished", "read agents"}:
        targets = [p for p in panes if p["agent"]] or panes
        if view_mode == "workspace" and active_workspace is not None:
            targets = [p for p in panes if p["workspace_index"] == active_workspace] or targets
        snippets = []
        for p in targets[:4]:
            num = pane_label_num(p, view_mode)
            prefix = "Agent" if view_mode == "agents" else "Pane"
            text = tail_pane(rdr_bin, session, p["id"], 30)
            analysis = analyze_for_tts(text, max_chars=220)
            snippets.append(
                format_pane_announcement(f"{prefix} {num}", p["state"], analysis, job_label=p.get("job_label", ""))
            )
        return {"ok": True, "action": "read_all", "spoken": " ".join(snippets) if snippets else "No panes."}

    def _resolve(num: int) -> dict[str, Any] | None:
        return resolve_target_pane(
            panes,
            num,
            view_mode=view_mode,
            active_workspace=active_workspace,
            ws_ref=ws_ref,
        )

    def _label(target: dict[str, Any]) -> tuple[int, str]:
        num = pane_label_num(target, "workspace" if ws_ref is not None else view_mode)
        noun = "agent" if (ws_ref is None and view_mode == "agents" and target.get("agent_num") is not None) else "pane"
        return num, noun

    # "compact", "compact agent 1", "clear", "clear agent 1", "new chat"
    m = re.match(
        r"^(compact|clear|reset|new\s+chat)(?:\s+(?:for\s+|on\s+)?(?:agent\s+|pane\s+)?(\d+))?$",
        lower,
    )
    if m:
        verb = m.group(1)
        slash_cmd = "/compact" if verb == "compact" else "/clear"
        num = int(m.group(2)) if m.group(2) else None
        target = (
            _resolve(num)
            if num is not None
            else (
                next((p for p in panes if p["id"] == default_pane), None)
                or resolve_target_pane(
                    panes, None, view_mode=view_mode, active_workspace=active_workspace
                )
            )
        )
        if not target:
            return {"ok": False, "error": "No target pane available", "spoken": "No pane found."}
        send_to_pane(rdr_bin, session, target["id"], slash_cmd, True)
        lnum, noun = _label(target)
        past = "Compacted" if slash_cmd == "/compact" else "Cleared"
        return {
            "ok": True,
            "action": "send",
            "pane": target["id"],
            "spoken": f"{past} {noun} {lnum}.",
        }

    # "yes to agent 1", "approve agent 2", "yes 1"
    m = re.match(r"^(yes|yep|yeah|approve|confirm|ok)\s+(?:to\s+)?(?:agent\s+|pane\s+)?(\d+)$", lower)
    if m:
        num = int(m.group(2))
        target = _resolve(num)
        if not target:
            return {"ok": False, "error": f"Unknown target {num}", "spoken": f"Target {num} not found."}
        send_to_pane(rdr_bin, session, target["id"], "y", True)
        lnum, noun = _label(target)
        return {
            "ok": True,
            "action": "send",
            "pane": target["id"],
            "spoken": f"Sent yes to {noun} {lnum}.",
        }

    # "no to agent 1", "reject agent 2", "no 2"
    m = re.match(r"^(no|nope|reject|deny)\s+(?:to\s+)?(?:agent\s+|pane\s+)?(\d+)$", lower)
    if m:
        num = int(m.group(2))
        target = _resolve(num)
        if not target:
            return {"ok": False, "error": f"Unknown target {num}", "spoken": f"Target {num} not found."}
        send_to_pane(rdr_bin, session, target["id"], "n", True)
        lnum, noun = _label(target)
        return {
            "ok": True,
            "action": "send",
            "pane": target["id"],
            "spoken": f"Sent no to {noun} {lnum}.",
        }

    # "cancel agent 1", "stop agent 1"
    m = re.match(r"^(cancel|stop|abort|interrupt)\s+(?:agent\s+|pane\s+)?(\d+)$", lower)
    if m:
        num = int(m.group(2))
        target = _resolve(num)
        if not target:
            return {"ok": False, "error": f"Unknown target {num}", "spoken": f"Target {num} not found."}
        send_to_pane(rdr_bin, session, target["id"], "\x03", False)
        lnum, noun = _label(target)
        return {
            "ok": True,
            "action": "send",
            "pane": target["id"],
            "spoken": f"Cancelled {noun} {lnum}.",
        }

    # "enter to agent 1", "continue agent 1"
    m = re.match(r"^(enter|continue|submit)\s+(?:to\s+)?(?:agent\s+|pane\s+)?(\d+)$", lower)
    if m:
        num = int(m.group(2))
        target = _resolve(num)
        if not target:
            return {"ok": False, "error": f"Unknown target {num}", "spoken": f"Target {num} not found."}
        send_to_pane(rdr_bin, session, target["id"], "", True)
        lnum, noun = _label(target)
        return {
            "ok": True,
            "action": "send",
            "pane": target["id"],
            "spoken": f"Pressed enter on {noun} {lnum}.",
        }

    # "read agent 1", "what did agent 1 say"
    m = re.match(r"^(?:read|check|what did)\s+(?:agent\s+|pane\s+)?(\d+)(?:\s+say)?$", lower)
    if m:
        num = int(m.group(1))
        target = _resolve(num)
        if not target:
            return {"ok": False, "error": f"Unknown target {num}", "spoken": f"Target {num} not found."}
        text = tail_pane(rdr_bin, session, target["id"], 40)
        lnum, noun = _label(target)
        analysis = analyze_for_tts(text)
        spoken = format_pane_announcement(
            f"{noun.capitalize()} {lnum}",
            target["state"],
            analysis,
            job_label=target.get("job_label", ""),
        )
        return {
            "ok": True,
            "action": "read",
            "pane": target["id"],
            "text": text,
            "kind": analysis["kind"],
            "spoken": spoken,
        }

    # "send to agent 1: <msg>", "tell agent 1 <msg>", "agent 1: <msg>"
    m = re.match(
        r"^(?:(?:send(?:\s+this(?:\s+message)?)?\s+to|tell|ask)\s+)?(?:agent|pane)\s+(\d+)\s*[:,]?\s+(.+)$",
        scoped_raw,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        # Trailing target: "<msg> agent 3" or "<msg> to agent 3"
        m_tail = re.match(
            r"^(.+?)\s+(?:(?:send\s+)?to\s+|on\s+)?(?:agent|pane)\s+(\d+)$",
            scoped_raw,
            re.IGNORECASE | re.DOTALL,
        )
        if m_tail:
            num = int(m_tail.group(2))
            msg = m_tail.group(1).strip(" ,:")
            target = _resolve(num)
            if not target:
                return {"ok": False, "error": f"Unknown target {num}", "spoken": f"Target {num} not found."}
            send_to_pane(rdr_bin, session, target["id"], msg, True)
            lnum, noun = _label(target)
            return {
                "ok": True,
                "action": "send",
                "pane": target["id"],
                "spoken": f"Sent to {noun} {lnum}.",
            }
    if m:
        num = int(m.group(1))
        msg = m.group(2).strip()
        target = _resolve(num)
        if not target:
            return {"ok": False, "error": f"Unknown target {num}", "spoken": f"Target {num} not found."}
        send_to_pane(rdr_bin, session, target["id"], msg, True)
        lnum, noun = _label(target)
        return {
            "ok": True,
            "action": "send",
            "pane": target["id"],
            "spoken": f"Sent to {noun} {lnum}.",
        }

    # Fallback: send raw transcript to default_pane (by exact pane id) or focused pane
    target = (
        next((p for p in panes if p["id"] == default_pane), None)
        if default_pane is not None
        else resolve_target_pane(panes, None, view_mode=view_mode, active_workspace=active_workspace)
    )
    if not target:
        return {"ok": False, "error": "No target pane available", "spoken": "No pane found."}
    send_to_pane(rdr_bin, session, target["id"], scoped_raw, True)
    lnum, noun = _label(target)
    return {
        "ok": True,
        "action": "send",
        "pane": target["id"],
        "spoken": f"Sent to {noun} {lnum}.",
    }


def make_handler(rdr_bin: str, session: str | None, token: str | None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def _authorized(self, query: dict[str, list[str]]) -> bool:
            if not token:
                return True
            auth = self.headers.get("Authorization", "")
            if auth == f"Bearer {token}":
                return True
            return query.get("token", [None])[0] == token

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str) -> None:
            if not path.exists():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            return json.loads(raw.decode("utf-8"))

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            if parsed.path == "/":
                self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
                return
            if parsed.path == "/manifest.webmanifest":
                self._send_file(STATIC_DIR / "manifest.webmanifest", "application/manifest+json")
                return
            if parsed.path == "/sw.js":
                self._send_file(STATIC_DIR / "sw.js", "application/javascript; charset=utf-8")
                return

            if not self._authorized(query):
                self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return

            try:
                if parsed.path == "/api/panes":
                    self._send_json(HTTPStatus.OK, fetch_panes(rdr_bin, session))
                elif parsed.path == "/api/events":
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    last_payload: str | None = None
                    ticks = 0
                    try:
                        while True:
                            try:
                                payload = json.dumps(fetch_panes(rdr_bin, session))
                                if payload != last_payload:
                                    self.wfile.write(f"event: panes\ndata: {payload}\n\n".encode("utf-8"))
                                    self.wfile.flush()
                                    last_payload = payload
                                    ticks = 0
                                elif ticks >= 15:
                                    self.wfile.write(b": ping\n\n")
                                    self.wfile.flush()
                                    ticks = 0
                            except Exception as exc:
                                err_payload = json.dumps({"ok": False, "error": str(exc)})
                                if err_payload != last_payload:
                                    self.wfile.write(f"event: panes\ndata: {err_payload}\n\n".encode("utf-8"))
                                    self.wfile.flush()
                                    last_payload = err_payload
                            time.sleep(1.0)
                            ticks += 1
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
                elif parsed.path == "/api/tail":
                    pane_id = int(query["pane"][0])
                    lines = int(query.get("lines", ["40"])[0])
                    text = tail_pane(rdr_bin, session, pane_id, lines)
                    analysis = analyze_for_tts(text)
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "pane": pane_id,
                            "text": text,
                            "kind": analysis["kind"],
                            "spoken": analysis["spoken"],
                        },
                    )
                elif parsed.path == "/api/tails":
                    raw_ids = query.get("panes", [""])[0]
                    pane_ids = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()]
                    lines = int(query.get("lines", ["24"])[0])
                    tails: dict[str, dict[str, str]] = {}
                    for pid in pane_ids[:16]:
                        try:
                            text = tail_pane(rdr_bin, session, pid, lines)
                            analysis = analyze_for_tts(text)
                            tails[str(pid)] = {
                                "text": text,
                                "kind": analysis["kind"],
                                "spoken": analysis["spoken"],
                            }
                        except Exception as exc:
                            tails[str(pid)] = {"text": f"[error: {exc}]", "kind": "finished", "spoken": ""}
                    self._send_json(HTTPStatus.OK, {"ok": True, "tails": tails})
                else:
                    self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if not self._authorized(query):
                self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return

            try:
                body = self._read_json_body()
                if parsed.path == "/api/send":
                    pane_id = int(body["pane"])
                    text = str(body.get("text", ""))
                    enter = bool(body.get("enter", True))
                    send_to_pane(rdr_bin, session, pane_id, text, enter)
                    print(f"[send] pane={pane_id} enter={enter} len={len(text)}", flush=True)
                    self._send_json(HTTPStatus.OK, {"ok": True, "pane": pane_id})
                elif parsed.path == "/api/command":
                    transcript = str(body.get("transcript", ""))
                    default_pane = body.get("default_pane")
                    default_num = int(default_pane) if default_pane is not None else None
                    active_ws = body.get("active_workspace")
                    active_ws_idx = int(active_ws) if active_ws is not None else None
                    view_mode = str(body.get("view_mode") or "agents")
                    res = parse_and_execute_command(
                        rdr_bin,
                        session,
                        transcript,
                        default_num,
                        active_workspace=active_ws_idx,
                        view_mode=view_mode,
                    )
                    print(
                        f"[cmd] ok={res.get('ok')} action={res.get('action')} pane={res.get('pane')} text={transcript!r}",
                        flush=True,
                    )
                    self._send_json(HTTPStatus.OK if res.get("ok") else HTTPStatus.BAD_REQUEST, res)
                else:
                    self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="rdreh voice companion server")
    parser.add_argument("--host", default=os.environ.get("RDR_VOICE_HOST", "127.0.0.1"), help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("RDR_VOICE_PORT", "8765")), help="Bind port (default: 8765)")
    parser.add_argument("--session", default=os.environ.get("RDR_SESSION"), help="rdreh session name")
    parser.add_argument("--tls-cert", default=os.environ.get("RDR_VOICE_TLS_CERT"), help="Path to TLS certificate PEM")
    parser.add_argument("--tls-key", default=os.environ.get("RDR_VOICE_TLS_KEY"), help="Path to TLS private key PEM")
    args = parser.parse_args()

    rdr_bin = resolve_rdr_bin()
    token = os.environ.get("RDR_VOICE_TOKEN") or None
    server = ThreadingHTTPServer((args.host, args.port), make_handler(rdr_bin, args.session, token))
    scheme = "http"
    if args.tls_cert and args.tls_key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=args.tls_cert, keyfile=args.tls_key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    print(f"rdreh-voice listening on {scheme}://{args.host}:{args.port} (using {rdr_bin})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
