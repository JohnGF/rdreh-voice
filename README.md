# rdreh-voice

Minimal zero-dependency voice, TTS, and notification PWA companion for [rdreh](https://github.com/JohnGF/rdreh).

## Install

```sh
uv tool install git+https://github.com/JohnGF/rdreh-voice
```

Or run directly from a local checkout:

```fish
uv run /home/john/git/rdreh-voice/server.py --host 127.0.0.1 --port 8765
```

### Systemd user service

A unit template is provided at [systemd/rdreh-voice.service](systemd/rdreh-voice.service):

```sh
mkdir -p ~/.config/systemd/user
cp systemd/rdreh-voice.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now rdreh-voice
```

## Run

```fish
uv run /home/john/git/rdreh-voice/server.py --host 127.0.0.1 --port 8765
```

To access from your phone over WireGuard (`wg0` at `10.0.0.100`):

```fish
env RDR_VOICE_TOKEN=mysecret uv run /home/john/git/rdreh-voice/server.py --host 10.0.0.100 --port 8765
```

Then open `http://10.0.0.100:8765/?token=mysecret` on your phone.

For full PWA install, Wake Lock, and browser Notifications (which Android Chrome only enables on `https://` or `localhost`), keep the server on `127.0.0.1` and forward the port over SSH from Termux:

```sh
ssh -N -L 8765:127.0.0.1:8765 john@10.0.0.100
```

Then open `http://localhost:8765` on your phone.

## How Voice & Alerts Work

When an agent finishes a turn (`working` -> `idle`) or when you tap `Read`:

- **Clean Speech**: Strips ANSI codes, box-drawing, spinners, markdown/path punctuation, and TUI footer chrome (`auto mode on`, `Baked for ...`, `Esc to cancel`, prompt bars) so TTS only reads spoken words.
- **Job Context**: Announces which agent and project/chat finished or needs input (for example, `Agent 1 in rdreh-voice` or `Agent 2 in bci projects, Fix EEG filter`).
- **Questions & Options**: If the agent is asking a question or presenting a numbered menu, it announces `is asking a question` or `needs action` and reads the question plus `Option 1: ... Option 2: ...` so you can reply verbally.
- **Completion Prompt**: When an agent finishes normally, it reads the concluding summary followed by `What are your actions?`.

## Topbar Toggles

- **Auto-Read**: Automatically speaks when an agent transitions from `working` to `idle`.
- **Notify**: Requests browser notification permission and sends a system notification when an agent finishes or needs action.
- **Auto-Send**: Automatically sends the composer text after a short pause in typing/dictation.
- **Wake**: Keeps the phone screen awake via Screen Wake Lock.

## Supported Voice Commands

Spoken numbers (`one` through `ten`) are normalized automatically (e.g. `agent one` -> `agent 1`).

- **Approve / Reject / Control**:
  - `yes to agent 1` / `approve agent 1`
  - `no to agent 2` / `reject agent 2`
  - `cancel agent 1` / `stop agent 1`
  - `enter to agent 1` / `continue agent 1`
- **Read & Status**:
  - `status` / `counts` / `summary`
  - `read agent 1` / `what did agent 1 say`
  - `read all` / `read finished`
  - `repeat` / `say again`
  - `tokens` / `token usage`
  - `what changed` / `what changed in agent 1`
- **Switch Views & Cross-Window**:
  - `agents` / `show agents`
  - `focus agent 1` / `select pane 2`
  - `window 2` / `switch to window 2`
  - Prefix any command with `window <N>` (e.g. `window 2 read pane 1`).
- **Send Message**:
  - `send to agent 1: <message>` / `tell agent 1 <message>` / `agent 1: <message>`
  - Anything else sends directly to the currently selected pane.

## Tests

```fish
uv run python -m unittest -v test_server.py
```

## Android App

A native Kotlin Android client lives in `android/`, adding:

- Persistent foreground SSE monitor (`RdrVoiceService`) over WireGuard
- Actionable notifications with **Approve**, **Reject**, and **Reply** (`RemoteInput`)
- Bluetooth SCO headset mic + TTS routing and media-button PTT (`MediaSessionCompat`)
- Quick Settings Tile (`RdrTileService`) and Android Assistant (`android.intent.action.ASSIST`) launch

Build the debug APK:

```fish
cd android
./gradlew assembleDebug
```
