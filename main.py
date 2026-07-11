"""
Race Engineer Bawel buat ACC.

Jalankan ini SETELAH ACC sudah kebuka (main menu boleh, atau udah masuk
sesi). Pastikan broadcasting.json sudah diisi (lihat README.md).

    python main.py
"""

import sys
import os

# Insert src directory into sys.path to find core modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

import time
import ctypes

import config
import personality as p
from rules_engine import RulesEngine, Message
from telemetry_local import LocalTelemetryReader
from telemetry_broadcast import BroadcastReader
from voice_queue import VoiceQueue
from llm_commentary import LlmBanterWorker
from voice_input import PttListener


def _disable_quickedit():
    """Disable Windows Console QuickEdit mode.

    QuickEdit causes print() to BLOCK when the console is behind a
    fullscreen app (like ACC).  Disabling it ensures background threads
    (voice input, TTS, LLM) never stall waiting on console output.
    """
    try:
        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        ENABLE_QUICK_EDIT = 0x0040
        ENABLE_EXTENDED_FLAGS = 0x0080
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        new_mode = (mode.value | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT
        kernel32.SetConsoleMode(handle, new_mode)
    except Exception:
        pass  # non-Windows or no console attached — ignore silently


def main():
    _disable_quickedit()
    print("=== Race Engineer Bawel - starting up ===")

    voice = VoiceQueue()
    voice.start()

    local_reader = LocalTelemetryReader()
    broadcast = BroadcastReader()

    print("Connecting to ACC Broadcasting API...")
    ok = broadcast.connect(timeout_sec=5.0)
    if ok:
        print("Broadcasting API connected. Rival data active.")
    else:
        print("Broadcasting API not available yet — will retry every 30s.")

    _last_broadcast_retry = time.time()

    rules = RulesEngine()

    # shared state buat LLM banter thread baca kondisi terakhir
    last_state = {"connected": False}

    def on_banter(text: str):
        voice.say(text, priority=2)

    def get_state():
        return last_state

    banter = LlmBanterWorker(on_message=on_banter, get_state=get_state)
    banter.start()

    # Start Voice Input (Push-To-Talk)
    ptt = PttListener(on_audio_ready=banter.handle_voice_command)
    ptt.start()

    player_identified = False
    consecutive_idle = 0

    try:
        while True:
            snap = local_reader.read()

            if snap is None:
                consecutive_idle += 1
                if consecutive_idle % 20 == 0:
                    print("Waiting for ACC data... (open game & get on track)")
                    # Retry broadcast connection if not yet connected
                    if not broadcast._connected.is_set() and time.time() - _last_broadcast_retry > 30:
                        _last_broadcast_retry = time.time()
                        print("Retrying Broadcasting API connection...")
                        if broadcast.connect(timeout_sec=5.0):
                            print("Broadcasting API connected!")
                time.sleep(config.POLL_INTERVAL_SEC)
                continue
            consecutive_idle = 0

            # cocokkan carIndex kita di broadcast API (sekali aja, pas nama udah kebaca)
            if not player_identified:
                idx = broadcast.identify_player_car(snap.player_full_name)
                if idx is not None:
                    player_identified = True

            # Tyre average temp (just the two fronts for brevity)
            tyre = snap.tyre_temp
            tyre_avg = sum(tyre) / len(tyre) if any(tyre) else 0
            compound = "wet" if snap.rain_tyres else "dry"

            # Gap values (ms → seconds, None if zero/unavailable)
            gap_ahead  = round(abs(snap.gap_ahead_ms)  / 1000.0, 1) if snap.gap_ahead_ms  else None
            gap_behind = round(abs(snap.gap_behind_ms) / 1000.0, 1) if snap.gap_behind_ms else None

            last_state.update({
                "connected":    True,
                "lap":          snap.completed_laps,
                "position":     snap.position,
                "speed":        snap.speed_kmh,
                "fuel_laps":    snap.fuel_estimated_laps,
                "fuel_liters":  snap.fuel_liters,
                "track":        snap.track,
                "rain":         snap.rain_intensity,
                "tyre_avg":     tyre_avg,
                "tyre_fl":      tyre[0],
                "tyre_fr":      tyre[1],
                "tyre_rl":      tyre[2],
                "tyre_rr":      tyre[3],
                "compound":     compound,
                "delta":        snap.delta_ms / 1000.0 if snap.delta_ms else 0,
                "best_lap":     _fmt_laptime(snap.best_lap_ms),
                "last_lap":     _fmt_laptime(snap.last_lap_ms),
                "gap_ahead":    gap_ahead,
                "gap_behind":   gap_behind,
                "is_in_pit":    snap.is_in_pit or snap.is_in_pit_lane,
                "valid_lap":    snap.is_valid_lap,
                "flag":         snap.flag,
                "session":      snap.session_type,
                "car_model":    snap.car_model,
                "driver_name":  snap.player_full_name,
                "driver_surname": snap.player_surname,
                "tc":           snap.tc_level,
                "abs":          snap.abs_level,
                "engine_map":   snap.engine_map,
                "brake_bias":   snap.brake_bias,
                "session_time_left": snap.session_time_left,
                # Pit fuel math
                "fuel_per_lap": snap.fuel_per_lap,
                "laps_remaining_estimate": snap.session_time_left / snap.last_lap_ms if snap.last_lap_ms and snap.last_lap_ms > 0 else 0,
                "fuel_to_end": ((snap.session_time_left / snap.last_lap_ms + 1.5) * snap.fuel_per_lap) if (snap.last_lap_ms and snap.last_lap_ms > 0 and snap.fuel_per_lap > 0) else 0,
                "fuel_to_add_at_pit": max(0, ((snap.session_time_left / snap.last_lap_ms + 1.5) * snap.fuel_per_lap) - snap.fuel_liters) if (snap.last_lap_ms and snap.last_lap_ms > 0 and snap.fuel_per_lap > 0) else 0,
                "pit_window_start": snap.pit_window_start,
                "pit_window_end": snap.pit_window_end,
                "penalty": snap.penalty_type,
                "track_grip": snap.track_grip_status,
                "air_temp": snap.air_temp,
                "road_temp": snap.road_temp,
            })

            msgs: list[Message] = rules.evaluate(local=snap)

            ahead, behind = broadcast.car_ahead_behind()
            if ahead is not None:
                gap_ahead_sec = abs(snap.gap_ahead_ms) / 1000.0 if snap.gap_ahead_ms else None
                if gap_ahead_sec is not None:
                    m = rules.rival_close_ahead(gap_ahead_sec, ahead)
                    if m:
                        msgs.append(m)
            if behind is not None:
                gap_behind_sec = abs(snap.gap_behind_ms) / 1000.0 if snap.gap_behind_ms else None
                if gap_behind_sec is not None:
                    m = rules.rival_close_behind(gap_behind_sec, behind)
                    if m:
                        msgs.append(m)

            for m in sorted(msgs, key=lambda x: x.priority):
                voice.say(m.text, priority=m.priority)

            time.sleep(config.POLL_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        banter.stop()
        broadcast.close()
        local_reader.close()
        voice.stop()

def _fmt_laptime(ms: int) -> str:
    if not ms:
        return "-"
    total_sec = ms / 1000.0
    minutes = int(total_sec // 60)
    seconds = total_sec - minutes * 60
    return f"{minutes}:{seconds:06.3f}"

if __name__ == "__main__":
    main()
