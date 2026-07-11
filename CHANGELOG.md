# Changelog

All notable changes to the **ACC Custom Race Engineer** project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.3.0] - 2026-07-11 (Current Update)

This update focuses on making the engineer bi-directional (giving you control back over the radio), stabilizing session transitions, and cleaning up the codebase repository layout for public publication.

### Added
*   **Voice MFD Keyboard Emulator (`mfd_control.py`)**: Intercepts transcribed voice commands (using local regex triggers before hitting the LLM) and simulates Windows keypress inputs directly to the ACC window (`AC2`).
    *   *Fuel control*: `"set fuel to 40"` / `"add 20 liters"`.
    *   *Tires*: `"switch to wet"` / `"dry tyres"`.
    *   *ECU*: `"engine map 3"` / `"brake bias 54.8"`.
*   **In-Game Session Restart Detection**: Recognizes when you pause and select "Restart" in-game by watching the completed laps drop back to 0. Automatically resets state and re-triggers the radio welcome check.
*   **Pre-Race Suppressor**: Silences race notifications (gaps, delta alerts, spots) during grid line-ups and formation laps. State counters sync silently in the background, preparing for a clean, non-spammy wave of the green flag.
*   **Dynamic Driver Swap Tracking**: Monitors driver changes during pit stops by checking surname telemetry. Greets the incoming driver upon exit and updates all future name-injection notifications dynamically.
*   **New Automated Engineer Triggers**:
    *   *Session Countdown*: Alerts at 30, 15, 10, 5, and 1 minute marks.
    *   *Gap Trends*: Evaluates pace trends (closing in or losing time to the car ahead over 4+ laps).
    *   *Lap Consistency*: Congratulates you when running 3 consecutive laps within a `0.3s` spread.
    *   *Leader Gap*: Updates you on your gap to the leader every 5 laps.
    *   *Out-Lap coaching*: Friendly reminders to build tire heat safely after pit exits.
*   **Clean Repository Layout**: Created a `.gitignore` to skip compilation caches, compiled ZIP binaries, and test audio waves. Added an open-source MIT `LICENSE` file.

### Changed
*   **Directory Restructuring**: Tucked all internal Python modules (`config`, `telemetry`, `rules_engine`, etc.) inside a neat `src/` subfolder to clean up the root repository.
*   **Path Resolvers**: Modified `main.py` and `gui_app.py` launcher paths using dynamic `sys.path` injection so no internal module import lines had to be rewritten.
*   **Name Injection Registry**: Switched name-injection loops to rely on the active tracked driver registry (`self._current_driver_surname`) instead of raw static telemetry (which frequently got stuck using the profile owner's name after a driver swap).
*   **Re-written README.md**: Overhauled the documentation in a natural, sim-racing-oriented tone, highlighting voice control parameters and the DSP radio pipeline.

### Removed
*   Obsolete PyInstaller build artifacts (`build/`, `dist/`, `RaceEngineer.spec`) to allow lightweight repository operations.
*   Cleaned out temporary audio output files (`test.wav`) and bloated `.zip` local binaries.

---

## [1.2.0] - 2026-07-09

Migrated the console interface into an interactive desktop environment and introduced a custom radio sound filter.

### Added
*   **CustomTkinter Desktop GUI (`gui_app.py`)**: A dark-themed cockpit panel displaying real-time tire temperatures, brake heat, session timers, and a live voice transcription log.
*   **Radio DSP Audio Pipeline (`voice_queue.py`)**: Custom audio effects processing applied to `edge-tts` voice lines:
    *   *Bandpass Filter*: Limits frequencies to 300Hz-3400Hz (simulating telephone and GT3 headset bandwidth).
    *   *Tanh Saturation*: Adds mild harmonic analogue clipping warmth.
    *   *Background Static*: Quiet white noise overlay.
    *   *Radio Clicks*: Custom sine-wave tone bursts at the beginning and end of transmissions.
*   **Voice Recording (PTT Listener - `voice_input.py`)**: Monitors the `Caps Lock` key via keyboard hooks and records microphone input using `sounddevice`. Pipes files to Groq's Whisper API for fast transcriptions.
*   **Smart Launch Script (`run.bat`)**: Checks for local dependencies and lets you choose between GUI and Console mode. Automatically writes local broadcasting port/passwords to ACC's `broadcasting.json`.

---

## [1.1.0] - 2026-07-05

Introduced multiplayer telemetry capabilities and integrated AI strategic comments.

### Added
*   **Broadcasting Telemetry Client (`telemetry_broadcast.py`)**: Handles UDP connections to ACC's Broadcasting API to fetch competitor positions, real-time gaps, and opponent lap times.
*   **LLM commentator worker (`llm_commentary.py`)**: Runs background threads to fetch strategic advice, driver motivation, or racing commentary from Groq using the Llama model.
*   **Dynamic Name Injection**: Randomly appends your surname to rule notifications (e.g., *"Box this lap, Auer"*).

---

## [1.0.0] - 2026-06-28

Initial release of the rule-based virtual race engineer CLI.

### Added
*   **Shared Memory Telemetry Reader (`telemetry_local.py`)**: Sub-millisecond local reads for physics (tire temps, brake wear, fuel, speed).
*   **Rule Engine Triggers (`rules_engine.py`)**: Basic triggers for tire pressure, brake heat, low fuel warnings, and lap summaries.
*   **Offline TTS queue (`voice_queue.py`)**: Simple prioritised queue (Urgent > Normal > Banter) utilizing Windows SAPI5 voices.
*   **Base Config (`config.py`)** & **Dialogue templates (`personality.py`)**.
