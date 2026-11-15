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

    def test_strips_model_mode_footer_chrome(self) -> None:
        sample = (
            "All 13 tests passed.\n"
            "────────────────────────\n"
            "❯ \n"
            "  auto · Gemini 4 Hydrogen · medium\n"
        )
        res = analyze_for_tts(sample)
        self.assertEqual(res["spoken"], "All 13 tests passed.")

    def test_stt_homophones_and_trailing_target(self) -> None:
        self.assertEqual(server.normalize_spoken_targets("agents tree"), "agent 3")
        self.assertEqual(server.normalize_spoken_targets("testing agent tree"), "testing agent 3")
        self.assertEqual(server.normalize_spoken_targets("read pane to"), "read pane 2")

        fake_state = {
            "ok": True,
            "panes": [
                {
                    "id": 9,
                    "workspace_index": 1,
                    "pane_index": 2,
                    "agent_num": 3,
                    "agent": True,
                    "state": "idle",
                    "focused": False,
                    "cwd": "/tmp",
                    "job_label": "test",
                }
            ],
            "workspaces": [{"index": 1, "name": "agents", "active": True, "panes": [9]}],
            "counts": {"total": 1, "busy": 0, "finished": 1},
        }
        with patch.object(server, "fetch_panes", return_value=fake_state):
            foc = server.parse_and_execute_command("rdr", None, "agents tree", 2)
            self.assertEqual(foc["action"], "focus")
            self.assertEqual(foc["pane"], 9)

            with patch.object(server, "send_to_pane") as mock_send:
                snd = server.parse_and_execute_command("rdr", None, "testing agent tree", 2)
                self.assertEqual(snd["action"], "send")
                self.assertEqual(snd["pane"], 9)
                mock_send.assert_called_once_with("rdr", None, 9, "testing", True)

                cmp = server.parse_and_execute_command("rdr", None, "compact agent tree", 2)
                self.assertEqual(cmp["spoken"], "Compacted agent 3.")
                mock_send.assert_called_with("rdr", None, 9, "/compact", True)

                clr = server.parse_and_execute_command("rdr", None, "clear", 9)
                self.assertEqual(clr["spoken"], "Cleared agent 3.")
                mock_send.assert_called_with("rdr", None, 9, "/clear", True)

                conv = server.parse_and_execute_command(
                    "rdr",
                    None,
                    "okay let's tell agent 3 to maybe try to look for some features that I'm missing",
                    2,
                )
                self.assertEqual(conv["action"], "send")
                self.assertEqual(conv["pane"], 9)
                mock_send.assert_called_with(
                    "rdr",
                    None,
                    9,
                    "maybe try to look for some features that I'm missing",
                    True,
                )

    def test_sanitize_drops_colons_hyphens_and_filename_dots(self) -> None:
        raw = "Updated server.py (http://10.0.0.100:8765) — check test_server.py; 100% pass!"
        out = server.sanitize_for_speech(raw)
        self.assertNotIn(":", out)
        self.assertNotIn(";", out)
        self.assertNotIn("server.py", out)
        self.assertIn("100% pass!", out)

    def test_directory_navigation_commands(self) -> None:
        fake_state = {
            "ok": True,
            "panes": [
                {
                    "id": 9,
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
            "workspaces": [{"index": 1, "name": "agents", "active": True, "panes": [9]}],
            "counts": {"total": 1, "busy": 0, "finished": 1},
        }
        with patch.object(server, "fetch_panes", return_value=fake_state):
            with patch.object(server, "run_rdr", return_value="ok") as mock_rdr:
                res = server.parse_and_execute_command("rdr", None, "open rdreh voice quad", 9)
                self.assertEqual(res["action"], "open_dir")
                self.assertEqual(res["spoken"], "Opened rdreh-voice.")
                mock_rdr.assert_called_once_with("rdr", None, ["add", "/home/john/git/rdreh-voice", "quad"])

            with patch.object(server, "send_to_pane") as mock_send:
                cd_res = server.parse_and_execute_command("rdr", None, "cd rdreh in agent 1", 9)
                self.assertEqual(cd_res["action"], "cd")
                self.assertEqual(cd_res["spoken"], "Changed agent 1 to rdreh.")
                mock_send.assert_called_once_with("rdr", None, 9, "cd '/home/john/git/rdreh'", True)

                wake_res = server.parse_and_execute_command("rdr", None, "r d r tell agent 1 to run tests", 9)
                self.assertEqual(wake_res["action"], "send")
                mock_send.assert_called_with("rdr", None, 9, "run tests", True)

                on_res = server.parse_and_execute_command("rdr", None, "on agent 1 tell it to check features", 2)
                self.assertEqual(on_res["pane"], 9)
                mock_send.assert_called_with("rdr", None, 9, "check features", True)

                stt_res = server.parse_and_execute_command("rdr", None, "patient 1 check for new features", 2)
                self.assertEqual(stt_res["pane"], 9)
                mock_send.assert_called_with("rdr", None, 9, "check for new features", True)

                self.assertEqual(server.normalize_spoken_targets("pageantry"), "agent 3")

    def test_analyze_returns_question_and_options(self) -> None:
        sample = "Which database?\n1. SQLite\n2. Postgres\n3. DuckDB\n4. Redis\n"
        res = analyze_for_tts(sample)
        self.assertEqual(res["question"], "Which database?")
        self.assertEqual(len(res["options"]), 4)
        self.assertEqual(res["options"][2], {"num": 3, "label": "DuckDB"})

    def test_leading_target_prefix_routes_commands_and_messages(self) -> None:
        fake_state = {
            "ok": True,
            "panes": [
                {
                    "id": 9,
                    "workspace_index": 1,
                    "pane_index": 0,
                    "agent_num": 1,
                    "agent": True,
                    "state": "idle",
                    "focused": False,
                    "cwd": "/home/john/git/rdreh",
                    "job_label": "rdreh",
                },
                {
                    "id": 10,
                    "workspace_index": 1,
                    "pane_index": 1,
                    "agent_num": 2,
                    "agent": True,
                    "state": "idle",
                    "focused": True,
                    "cwd": "/home/john/git/rdreh",
                    "job_label": "rdreh",
                },
                {
                    "id": 11,
                    "workspace_index": 1,
                    "pane_index": 2,
                    "agent_num": 3,
                    "agent": True,
                    "state": "idle",
                    "focused": False,
                    "cwd": "/home/john/git/rdreh",
                    "job_label": "rdreh",
                },
            ],
            "workspaces": [{"index": 1, "name": "agents", "active": True, "panes": [9, 10, 11]}],
            "counts": {"total": 3, "busy": 0, "finished": 3},
        }
        with patch.object(server, "fetch_panes", return_value=fake_state):
            with patch.object(server, "send_to_pane") as mock_send:
                r1 = server.parse_and_execute_command("rdr", None, "agent 3 compact", 10)
                self.assertEqual(r1["pane"], 11)
                self.assertEqual(r1["spoken"], "Compacted agent 3.")
                mock_send.assert_called_with("rdr", None, 11, "/compact", True)

                r2 = server.parse_and_execute_command("rdr", None, "agent 2 yes", 9)
                self.assertEqual(r2["pane"], 10)
                self.assertEqual(r2["spoken"], "Sent yes to agent 2.")
                mock_send.assert_called_with("rdr", None, 10, "y", True)

                r3 = server.parse_and_execute_command("rdr", None, "3 check tests", 10)
                self.assertEqual(r3["pane"], 11)
                self.assertEqual(r3["spoken"], "Sent to agent 3.")
                mock_send.assert_called_with("rdr", None, 11, "check tests", True)

                r4 = server.parse_and_execute_command("rdr", None, "one clear", 10)
                self.assertEqual(r4["pane"], 9)
                self.assertEqual(r4["spoken"], "Cleared agent 1.")
                mock_send.assert_called_with("rdr", None, 9, "/clear", True)

            with patch.object(server, "tail_pane", return_value="All tests passed.") as mock_tail:
                r5 = server.parse_and_execute_command("rdr", None, "agent 1 read", 10)
                self.assertEqual(r5["action"], "read")
                self.assertEqual(r5["pane"], 9)
                self.assertIn("Agent 1", r5["spoken"])
                mock_tail.assert_called_with("rdr", None, 9, 40)


if __name__ == "__main__":
    unittest.main()
