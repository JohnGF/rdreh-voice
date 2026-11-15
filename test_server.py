import unittest
from unittest.mock import patch

import server
from server import (
    analyze_for_tts,
    clean_for_tts,
    format_pane_announcement,
    normalize_spoken_targets,
    pane_job_label,
    sanitize_for_speech,
    send_to_pane,
)


class TtsFormattingTests(unittest.TestCase):
    def test_sanitize_removes_non_letter_symbols(self) -> None:
        raw = "● **Updated** `~/git/rdreh-voice/server.py` · 100% pass ✓ → ← ↓ ✻"
        cleaned = sanitize_for_speech(raw)
        self.assertNotIn("●", cleaned)
        self.assertNotIn("*", cleaned)
        self.assertNotIn("`", cleaned)
        self.assertNotIn("/", cleaned)
        self.assertNotIn("~", cleaned)
        self.assertNotIn("·", cleaned)
        self.assertNotIn("✓", cleaned)
        self.assertNotIn("→", cleaned)
        self.assertNotIn("✻", cleaned)
        self.assertIn("Updated", cleaned)
        self.assertIn("100%", cleaned)

    def test_permission_prompt_with_box_and_options(self) -> None:
        raw = """
╭──────────────────────────────────────────╮
│ Bash command                             │
│   rm -rf build/                          │
│ Do you want to proceed?                  │
│ ❯ 1. Yes                                 │
│   2. Yes, and don't ask again            │
│   3. No                                  │
╰──────────────────────────────────────────╯
  Esc to cancel · Tab to add additional instructions
"""
        res = analyze_for_tts(raw)
        self.assertEqual(res["kind"], "action")
        self.assertIn("Do you want to proceed?", res["spoken"])
        self.assertIn("Option 1: Yes.", res["spoken"])
        self.assertIn("Option 2: Yes, and don't ask again.", res["spoken"])
        self.assertIn("Option 3: No.", res["spoken"])
        self.assertNotIn("Esc to cancel", res["spoken"])
        self.assertNotIn("╭", res["spoken"])
        self.assertNotIn("❯", res["spoken"])

    def test_question_with_numbered_options(self) -> None:
        raw = """
I found two ways to store the state.
Which approach do you prefer?
1. SQLite - simple and local
2. JSON file - zero setup
3. In-memory only - fastest

❯
  ⏵⏵ auto mode on · shift+tab to cycle
"""
        res = analyze_for_tts(raw)
        self.assertEqual(res["kind"], "question")
        self.assertIn("Which approach do you prefer?", res["spoken"])
        self.assertIn("Option 1: SQLite, simple and local.", res["spoken"])
        self.assertIn("Option 2: JSON file, zero setup.", res["spoken"])
        self.assertIn("Option 3: In-memory only, fastest.", res["spoken"])
        self.assertNotIn("auto mode on", res["spoken"])

    def test_direct_question_without_options(self) -> None:
        raw = """
● I finished checking the logs. Should I restart the service now?
✻ Baked for 12s · done 12:44
────────────────────────────────────────
❯
"""
        res = analyze_for_tts(raw)
        self.assertEqual(res["kind"], "question")
        self.assertEqual(res["spoken"], "I finished checking the logs. Should I restart the service now?")

    def test_real_pane_action_request_strips_chrome(self) -> None:
        raw = """
  Ran 1 shell command

● Please do this now: unplug the MetroY Pro, plug it back into the same USB port, and start a short scan in Revo Metro for about 20–30 s.

✻ Baked for 2m 58s · done 12:44 · 1 shell still running

────────────────────────────────────────────────────────────────────────
❯ done, replugged and scanned
────────────────────────────────────────────────────────────────────────
  ⏵⏵ auto mode on · 1 shell · ← 1 agent · ↓ to manage
"""
        res = analyze_for_tts(raw)
        self.assertEqual(res["kind"], "action")
        self.assertIn("Please do this now:", res["spoken"])
        self.assertIn("20-30 s.", res["spoken"])
        self.assertNotIn("Baked for", res["spoken"])
        self.assertNotIn("auto mode on", res["spoken"])
        self.assertNotIn("replugged and scanned", res["spoken"])
        self.assertNotIn("Ran 1 shell command", res["spoken"])

    def test_normal_finished_output(self) -> None:
        raw = """
  Edited server.py
● All 12 unit tests passed. The voice assistant now filters TUI chrome cleanly.
✻ Worked for 45s · done 12:45
❯
  Bypass permissions on · esc to interrupt
"""
        res = analyze_for_tts(raw)
        self.assertEqual(res["kind"], "finished")
        self.assertEqual(
            res["spoken"],
            "All 12 unit tests passed. The voice assistant now filters TUI chrome cleanly.",
        )
        self.assertEqual(clean_for_tts(raw), res["spoken"])

    def test_pane_job_label(self) -> None:
        self.assertEqual(
            pane_job_label("/home/john/git/bci_projects/metroY", "~: agy - agy"),
            "in metroY",
        )
        self.assertEqual(
            pane_job_label("/home/john/git/rdreh-voice", "~/git/rdreh-voice - fish"),
            "in rdreh-voice",
        )
        self.assertEqual(
            pane_job_label("/home/john/git/bci_projects", "claude - Fix EEG filter"),
            "in bci projects, Fix EEG filter",
        )

    def test_announcement_formatting(self) -> None:
        self.assertEqual(
            format_pane_announcement(
                "Agent 1",
                "idle",
                {"kind": "question", "spoken": "Which one?"},
                job_label="in metroY",
            ),
            "Agent 1 in metroY is asking a question. Which one?",
        )
        self.assertEqual(
            format_pane_announcement(
                "Agent 2",
                "idle",
                {"kind": "action", "spoken": "Approve?"},
                job_label="in bci projects",
            ),
            "Agent 2 in bci projects needs action. Approve?",
        )
        self.assertEqual(
            format_pane_announcement(
                "Agent 3",
                "idle",
                {"kind": "finished", "spoken": "Tests passed."},
                job_label="in rdreh-voice",
            ),
            "Agent 3 in rdreh-voice finished. Tests passed. What are your actions?",
        )

    def test_normalize_spoken_targets(self) -> None:
        self.assertEqual(normalize_spoken_targets("tell agent one hello"), "tell agent 1 hello")
        self.assertEqual(normalize_spoken_targets("yes to agent two"), "yes to agent 2")
        self.assertEqual(normalize_spoken_targets("window three read pane four"), "window 3 read pane 4")

    def test_send_to_pane_splits_text_and_enter(self) -> None:
        calls: list[list[str]] = []

        def fake_run_rdr(_bin: str, _sess: str | None, args: list[str]) -> str:
            calls.append(args)
            return "ok"

        with patch.object(server, "run_rdr", side_effect=fake_run_rdr), patch.object(server.time, "sleep"):
            send_to_pane("rdr", None, 28, "- option 1", True)

        self.assertEqual(
            calls,
            [
                ["send", "--no-enter", "28", "--", "- option 1"],
                ["send", "28", ""],
            ],
        )

    def test_summarize_git_changes(self) -> None:
        fake_proc = unittest.mock.Mock(returncode=0, stdout=" M server.py\n?? notes.txt\n")
        with patch.object(server.subprocess, "run", return_value=fake_proc):
            out = server.summarize_git_changes("/home/john/git/rdreh-voice")
        self.assertEqual(out, "1 modified, 1 untracked in rdreh-voice: server.py, notes.txt.")

    def test_summarize_tokens(self) -> None:
        with patch.object(server, "run_rdr", return_value='{"today": {"total": 12345}}'):
            out = server.summarize_tokens("rdr")
        self.assertEqual(out, "Today's token usage is 12,345 tokens.")

    def test_new_voice_commands(self) -> None:
        fake_state = {
            "ok": True,
            "panes": [
                {
                    "id": 7,
                    "workspace_index": 1,
                    "pane_index": 0,
                    "agent_num": 1,
                    "agent": True,
                    "state": "idle",
                    "focused": True,
                    "cwd": "/home/john/git/rdreh-voice",
                    "job_label": "rdreh-voice",
                }
            ],
            "workspaces": [{"index": 1, "name": "agents", "active": True, "panes": [7]}],
            "counts": {"total": 1, "busy": 0, "finished": 1},
        }
        with patch.object(server, "fetch_panes", return_value=fake_state):
            rep = server.parse_and_execute_command("rdr", None, "repeat", 7)
            self.assertEqual(rep["action"], "repeat")

            foc = server.parse_and_execute_command("rdr", None, "focus agent one", 7)
            self.assertEqual(foc["action"], "focus")
            self.assertEqual(foc["pane"], 7)

            with patch.object(server, "summarize_tokens", return_value="Today's token usage is 100 tokens."):
                tok = server.parse_and_execute_command("rdr", None, "token usage", 7)
                self.assertEqual(tok["action"], "tokens")

            with patch.object(server, "summarize_git_changes", return_value="Working tree is clean in rdreh-voice."):
                chg = server.parse_and_execute_command("rdr", None, "what changed in agent 1", 7)
                self.assertEqual(chg["action"], "git_status")


if __name__ == "__main__":
    unittest.main()
