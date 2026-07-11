"""
ACC Custom Race Engineer - Desktop GUI (Compact Widget Edition)
Gunakan ini sebagai antarmuka desktop yang ringkas dan informatif.
    python gui_app.py
"""

import sys
import os

# Masukkan folder src ke path agar modul-modul core bisa di-import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

import threading
import time
import queue
import tkinter as tk
import customtkinter as ctk
from datetime import datetime

import config
import personality as p
from rules_engine import RulesEngine, Message
from telemetry_local import LocalTelemetryReader
from telemetry_broadcast import BroadcastReader
from voice_queue import VoiceQueue
from llm_commentary import LlmBanterWorker
from voice_input import PttListener


# ─── Theme & Colors ──────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

C_BG        = "#0A0B0E"
C_PANEL     = "#101216"
C_CARD      = "#161920"
C_BORDER    = "#222630"
C_ACCENT    = "#E8352A"
C_GREEN     = "#27D48A"
C_BLUE      = "#3B8BEB"
C_TEXT      = "#E8EAF0"
C_MUTED     = "#6B7280"
C_URGENT    = "#FF4444"
C_WARNING   = "#F5A623"
C_NORMAL    = "#E8EAF0"
C_BANTER    = "#7C9FD4"

EVT_LOG       = "log"
EVT_TELEMETRY = "telemetry"
EVT_STATUS    = "status"
EVT_PTT       = "ptt"


class RaceEngineerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ACC Engineer")
        self.geometry("440x590")
        self.minsize(400, 520)
        self.configure(fg_color=C_BG)
        self.resizable(True, True)

        self._ui_queue: queue.Queue = queue.Queue()
        self._voice: VoiceQueue | None = None
        self._banter: LlmBanterWorker | None = None
        self._ptt: PttListener | None = None
        self._telemetry_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_state: dict = {}

        self._build_ui()
        self._start_backend()
        self.after(50, self._poll_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── UI Construction ─────────────────────────────────────────────────────
    def _build_ui(self):
        # 1. Header & Status Bar
        header = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=8,
                              border_width=1, border_color=C_BORDER)
        header.pack(fill="x", padx=10, pady=(10, 5))

        # Title
        ctk.CTkLabel(header, text="🎙️ ACC ENGINEER",
                     font=ctk.CTkFont("Segoe UI", 14, weight="bold"),
                     text_color=C_ACCENT).pack(side="left", padx=10, pady=8)

        # Connection indicators
        self._ind_broadcast = self._status_indicator(header, "Broadcast")
        self._ind_broadcast.pack(side="right", padx=(5, 10))

        self._ind_local = self._status_indicator(header, "SharedMem")
        self._ind_local.pack(side="right", padx=(5, 5))

        # 2. Main Tabs
        self._tabview = ctk.CTkTabview(
            self, fg_color=C_PANEL,
            segmented_button_fg_color=C_CARD,
            segmented_button_selected_color=C_ACCENT,
            segmented_button_selected_hover_color="#C42A20",
            segmented_button_unselected_color=C_CARD,
            segmented_button_unselected_hover_color=C_BORDER,
            text_color=C_TEXT,
            border_width=1, border_color=C_BORDER,
        )
        self._tabview.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._tabview.add("🏁 HUD & Log")
        self._tabview.add("⚙️ Config")

        self._build_main_tab(self._tabview.tab("🏁 HUD & Log"))
        self._build_settings_tab(self._tabview.tab("⚙️ Config"))

    def _status_indicator(self, parent, label: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        dot = ctk.CTkLabel(frame, text="●", font=ctk.CTkFont("Segoe UI", 12),
                           text_color=C_MUTED)
        dot.pack(side="left")
        lbl = ctk.CTkLabel(frame, text=label, font=ctk.CTkFont("Segoe UI", 10),
                           text_color=C_MUTED)
        lbl.pack(side="left", padx=(2, 0))
        frame._dot = dot
        return frame

    def _set_indicator(self, indicator, connected: bool):
        indicator._dot.configure(text_color=C_GREEN if connected else C_MUTED)

    # ─── Tab 1: HUD & Log ───────────────────────────────────────────────────
    def _build_main_tab(self, parent):
        parent.configure(fg_color=C_PANEL)

        # A. Mini Telemetry Panel (Tires + Key stats)
        telemetry_frame = ctk.CTkFrame(parent, fg_color="transparent")
        telemetry_frame.pack(fill="x", padx=4, pady=4)

        # Suhu Ban (Grid 2x2) - Sangat Ringkas
        tyre_box = ctk.CTkFrame(telemetry_frame, fg_color=C_CARD, corner_radius=8,
                                border_width=1, border_color=C_BORDER)
        tyre_box.pack(side="left", fill="both", expand=True, padx=(0, 4))
        
        ctk.CTkLabel(tyre_box, text="TYRE TEMPS",
                     font=ctk.CTkFont("Segoe UI", 9, weight="bold"),
                     text_color=C_MUTED).pack(anchor="w", padx=8, pady=(4, 0))

        tyre_grid = ctk.CTkFrame(tyre_box, fg_color="transparent")
        tyre_grid.pack(expand=True, fill="both", padx=6, pady=4)
        tyre_grid.columnconfigure(0, weight=1)
        tyre_grid.columnconfigure(1, weight=1)
        tyre_grid.rowconfigure(0, weight=1)
        tyre_grid.rowconfigure(1, weight=1)

        self._tyre_labels = {}
        for name, r, c in [("FL", 0, 0), ("FR", 0, 1), ("RL", 1, 0), ("RR", 1, 1)]:
            lbl = ctk.CTkLabel(tyre_grid, text="--°", font=ctk.CTkFont("Consolas", 14, weight="bold"),
                               text_color=C_TEXT, fg_color=C_BORDER, corner_radius=4, height=28)
            lbl.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
            self._tyre_labels[name] = lbl

        # Key Stats (Pos, Delta, Fuel)
        stats_box = ctk.CTkFrame(telemetry_frame, fg_color=C_CARD, corner_radius=8,
                                 border_width=1, border_color=C_BORDER, width=170)
        stats_box.pack(side="right", fill="both", padx=(4, 0))
        stats_box.pack_propagate(False)

        # Pos
        self._lbl_pos = ctk.CTkLabel(stats_box, text="P--",
                                     font=ctk.CTkFont("Segoe UI", 18, weight="bold"),
                                     text_color=C_ACCENT)
        self._lbl_pos.pack(anchor="w", padx=10, pady=(6, 0))

        # Delta
        self._lbl_delta = ctk.CTkLabel(stats_box, text="Δ --s",
                                       font=ctk.CTkFont("Consolas", 12),
                                       text_color=C_MUTED)
        self._lbl_delta.pack(anchor="w", padx=10)

        # Fuel
        self._lbl_fuel = ctk.CTkLabel(stats_box, text="Fuel: --",
                                      font=ctk.CTkFont("Segoe UI", 11),
                                      text_color=C_GREEN)
        self._lbl_fuel.pack(anchor="w", padx=10, pady=(0, 6))

        # B. Push-to-Talk Status Banner
        self._ptt_banner = ctk.CTkFrame(parent, fg_color=C_BORDER, corner_radius=6)
        self._ptt_banner.pack(fill="x", padx=4, pady=4)
        
        self._ptt_label = ctk.CTkLabel(
            self._ptt_banner, text=f"🎙️ PTT READY ({config.PTT_KEY.upper()})",
            font=ctk.CTkFont("Segoe UI", 10, weight="bold"),
            text_color=C_MUTED,
        )
        self._ptt_label.pack(pady=4)

        # C. Engineer's Log Box
        log_frame = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=8,
                                 border_width=1, border_color=C_BORDER)
        log_frame.pack(fill="both", expand=True, padx=4, pady=(4, 2))

        ctk.CTkLabel(log_frame, text="RADIO LOG",
                     font=ctk.CTkFont("Segoe UI", 9, weight="bold"),
                     text_color=C_MUTED).pack(anchor="w", padx=10, pady=(6, 0))

        self._log_text = ctk.CTkTextbox(
            log_frame, fg_color=C_CARD, text_color=C_TEXT,
            font=ctk.CTkFont("Segoe UI", 11),
            activate_scrollbars=True, wrap="word", border_width=0,
        )
        self._log_text.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        self._log_text.configure(state="disabled")
        tb = self._log_text._textbox
        tb.tag_configure("urgent",    foreground=C_URGENT)
        tb.tag_configure("warning",   foreground=C_WARNING)
        tb.tag_configure("banter",    foreground=C_BANTER)
        tb.tag_configure("normal",    foreground=C_NORMAL)
        tb.tag_configure("timestamp", foreground=C_MUTED)
        tb.tag_configure("system",    foreground=C_BLUE)

        # Session Label Footer
        self._lbl_session = ctk.CTkLabel(parent, text="Session info waiting...",
                                         font=ctk.CTkFont("Segoe UI", 10),
                                         text_color=C_MUTED)
        self._lbl_session.pack(pady=2)

    # ─── Tab 2: Settings ─────────────────────────────────────────────────────
    def _build_settings_tab(self, parent):
        parent.configure(fg_color=C_PANEL)
        scroll = ctk.CTkScrollableFrame(parent, fg_color=C_PANEL)
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # API Keys
        self._groq_entry = self._labeled_entry(scroll, "Groq API Key", config.GROQ_API_KEY or "", show="*")
        
        # PTT & Personality
        self._ptt_entry = self._labeled_entry(scroll, "Push-to-Talk Key", config.PTT_KEY)
        
        ctk.CTkLabel(scroll, text="Engineer Personality", font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C_MUTED).pack(anchor="w", padx=12, pady=(6, 0))
        self._personality_var = tk.StringVar(value=config.ENGINEER_PERSONALITY)
        ctk.CTkOptionMenu(scroll, values=["galak", "santai", "cerewet_lucu"],
                          variable=self._personality_var, fg_color=C_BORDER, button_color=C_ACCENT,
                          button_hover_color="#C42A20", text_color=C_TEXT).pack(fill="x", padx=12, pady=(2, 6))

        # ACC Port / Pw
        self._broadcast_pw_entry = self._labeled_entry(scroll, "Broadcast Password", config.ACC_CONNECTION_PASSWORD or "", show="*")

        # Save Button
        ctk.CTkButton(scroll, text="💾 Save Settings", command=self._save_settings,
                      fg_color=C_ACCENT, hover_color="#C42A20",
                      font=ctk.CTkFont("Segoe UI", 12, weight="bold"),
                      height=32, corner_radius=6).pack(fill="x", padx=12, pady=12)

    def _labeled_entry(self, parent, label: str, value: str, show: str = "") -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label, font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C_MUTED).pack(anchor="w", padx=12, pady=(6, 0))
        entry = ctk.CTkEntry(parent, fg_color=C_BORDER, text_color=C_TEXT,
                             border_color=C_BORDER, show=show, height=28)
        if value:
            entry.insert(0, value)
        entry.pack(fill="x", padx=12, pady=(2, 6))
        return entry

    def _save_settings(self):
        config.GROQ_API_KEY = self._groq_entry.get()
        config.PTT_KEY = self._ptt_entry.get()
        config.ENGINEER_PERSONALITY = self._personality_var.get()
        config.ACC_CONNECTION_PASSWORD = self._broadcast_pw_entry.get()
        self._post_log("⚙️ Settings saved. Restart recommended.", priority=1, tag="system")

    # ─── Log & Update Helpers ────────────────────────────────────────────────
    def _post_log(self, text: str, priority: int = 1, tag: str = ""):
        self._ui_queue.put({"type": EVT_LOG, "text": text,
                            "priority": priority, "tag": tag})

    def _append_log(self, text: str, priority: int, tag: str = ""):
        tb = self._log_text._textbox
        self._log_text.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        tb.insert("end", f"[{ts}] ", "timestamp")
        used_tag = tag if tag else (
            "urgent"  if priority == 0 else
            "warning" if priority == 1 else
            "banter"  if priority == 2 else "normal"
        )
        tb.insert("end", text + "\n", used_tag)
        self._log_text.configure(state="disabled")
        self._log_text.see("end")

    # ─── Queue Polling ───────────────────────────────────────────────────────
    def _poll_ui_queue(self):
        try:
            while True:
                evt = self._ui_queue.get_nowait()
                self._handle_ui_event(evt)
        except queue.Empty:
            pass
        finally:
            self.after(50, self._poll_ui_queue)

    def _handle_ui_event(self, evt: dict):
        etype = evt.get("type")
        if etype == EVT_LOG:
            self._append_log(evt["text"], evt.get("priority", 1), evt.get("tag", ""))
        elif etype == EVT_STATUS:
            self._set_indicator(self._ind_local, evt.get("local", False))
            self._set_indicator(self._ind_broadcast, evt.get("broadcast", False))
            si = evt.get("session_info", "")
            if si:
                self._lbl_session.configure(text=si)
        elif etype == EVT_TELEMETRY:
            self._update_telemetry_display(evt.get("state", {}))
        elif etype == EVT_PTT:
            active = evt.get("active", False)
            self._ptt_banner.configure(fg_color=C_ACCENT if active else C_BORDER)
            self._ptt_label.configure(
                text="🔴 MIC RECORDING..." if active else f"🎙️ PTT READY ({config.PTT_KEY.upper()})",
                text_color=C_NORMAL if active else C_MUTED
            )

    def _update_telemetry_display(self, s: dict):
        if not s:
            return
        
        # 1. Update tyre cells
        for pos in ["FL", "FR", "RL", "RR"]:
            temp = s.get(f"tyre_{pos.lower()}", 0)
            cell = self._tyre_labels[pos]
            if temp <= 0:
                cell.configure(text="--°", fg_color=C_BORDER)
            else:
                cell.configure(text=f"{pos}: {temp:.0f}°")
                if temp < config.TYRE_TEMP_MIN_C:
                    cell.configure(fg_color=C_BLUE)
                elif temp > config.TYRE_TEMP_MAX_C:
                    cell.configure(fg_color=C_URGENT)
                else:
                    cell.configure(fg_color=C_GREEN)

        # 2. Update stats
        pos = s.get("position", 0)
        self._lbl_pos.configure(text=f"Pos: P{pos}" if pos else "Pos: P--")
        
        delta = s.get("delta", 0)
        self._lbl_delta.configure(
            text=f"Delta: {delta:+.3f}s",
            text_color=C_GREEN if delta < 0 else C_WARNING
        )

        fl = s.get("fuel_laps", 0)
        liters = s.get("fuel_liters", 0)
        self._lbl_fuel.configure(
            text=f"Fuel: {liters:.1f}L ({fl:.1f} laps)",
            text_color=C_URGENT if fl < config.FUEL_LAPS_CRITICAL else (C_WARNING if fl < config.FUEL_LAPS_WARNING else C_GREEN)
        )

    # ─── Backend Thread ──────────────────────────────────────────────────────
    def _start_backend(self):
        self._post_log("ACC Custom Engineer starting...", priority=1, tag="system")

        self._voice = VoiceQueue()
        self._voice.start()

        _orig_say = self._voice.say

        def _say_and_log(text: str, priority: int = 1):
            _orig_say(text, priority)
            self._post_log(text, priority)

        self._voice.say = _say_and_log
        last_state: dict = self._last_state

        def on_banter(text: str):
            self._voice.say(text, priority=2)

        def get_state():
            return last_state

        self._banter = LlmBanterWorker(on_message=on_banter, get_state=get_state)
        self._banter.start()

        self._ptt = PttListener(on_audio_ready=self._banter.handle_voice_command)
        self._ptt.start()

        # Update PTT listener to send GUI events
        orig_on_press = self._ptt._on_press
        orig_on_release = self._ptt._on_release

        def new_on_press(key):
            if self._ptt._is_ptt_key(key) and not self._ptt._recording:
                self._ui_queue.put({"type": EVT_PTT, "active": True})
            orig_on_press(key)

        def new_on_release(key):
            if self._ptt._is_ptt_key(key) and self._ptt._recording:
                self._ui_queue.put({"type": EVT_PTT, "active": False})
            orig_on_release(key)

        self._ptt._on_press = new_on_press
        self._ptt._on_release = new_on_release

        def telemetry_loop():
            local_reader = LocalTelemetryReader()
            broadcast    = BroadcastReader()
            rules        = RulesEngine()

            self._post_log("Connecting to Broadcasting API...", priority=1, tag="system")
            ok = broadcast.connect(timeout_sec=5.0)
            self._post_log("Broadcasting connected." if ok else "Broadcasting offline (will retry).", priority=1, tag="system")

            last_broadcast_retry = time.time()
            player_identified    = False
            consecutive_idle     = 0

            while not self._stop_event.is_set():
                snap = local_reader.read()
                bcast_connected = broadcast._connected.is_set()

                if snap is None:
                    consecutive_idle += 1
                    if consecutive_idle % 20 == 0:
                        if not bcast_connected and time.time() - last_broadcast_retry > 30:
                            last_broadcast_retry = time.time()
                            if broadcast.connect(timeout_sec=5.0):
                                self._post_log("Broadcasting reconnected.", priority=1, tag="system")
                    self._ui_queue.put({"type": EVT_STATUS, "local": False, "broadcast": bcast_connected})
                    time.sleep(config.POLL_INTERVAL_SEC)
                    continue

                consecutive_idle = 0
                if not player_identified:
                    idx = broadcast.identify_player_car(snap.player_full_name)
                    if idx is not None:
                        player_identified = True

                tyre    = snap.tyre_temp
                tyre_avg = sum(tyre) / len(tyre) if any(tyre) else 0
                compound = "wet" if snap.rain_tyres else "dry"
                gap_ahead  = round(abs(snap.gap_ahead_ms)  / 1000.0, 1) if snap.gap_ahead_ms  else None
                gap_behind = round(abs(snap.gap_behind_ms) / 1000.0, 1) if snap.gap_behind_ms else None

                last_state.update({
                    "connected":          True,
                    "lap":                snap.completed_laps,
                    "position":           snap.position,
                    "speed":              snap.speed_kmh,
                    "fuel_laps":          snap.fuel_estimated_laps,
                    "fuel_liters":        snap.fuel_liters,
                    "track":              snap.track,
                    "rain":               snap.rain_intensity,
                    "tyre_avg":           tyre_avg,
                    "tyre_fl":            tyre[0],
                    "tyre_fr":            tyre[1],
                    "tyre_rl":            tyre[2],
                    "tyre_rr":            tyre[3],
                    "compound":           compound,
                    "delta":              snap.delta_ms / 1000.0 if snap.delta_ms else 0,
                    "best_lap":           _fmt_laptime(snap.best_lap_ms),
                    "last_lap":           _fmt_laptime(snap.last_lap_ms),
                    "gap_ahead":          gap_ahead,
                    "gap_behind":         gap_behind,
                    "is_in_pit":          snap.is_in_pit or snap.is_in_pit_lane,
                    "valid_lap":          snap.is_valid_lap,
                    "flag":               snap.flag,
                    "session":            snap.session_type,
                    "car_model":          snap.car_model,
                    "driver_name":        snap.player_full_name,
                    "driver_surname":     snap.player_surname,
                    "tc":                 snap.tc_level,
                    "abs":                snap.abs_level,
                    "engine_map":         snap.engine_map,
                    "brake_bias":         snap.brake_bias,
                    "session_time_left":  snap.session_time_left,
                    "fuel_per_lap":       snap.fuel_per_lap,
                    "laps_remaining_estimate": snap.session_time_left / snap.last_lap_ms if snap.last_lap_ms and snap.last_lap_ms > 0 else 0,
                    "fuel_to_end":        ((snap.session_time_left / snap.last_lap_ms + 1.5) * snap.fuel_per_lap) if (snap.last_lap_ms and snap.last_lap_ms > 0 and snap.fuel_per_lap > 0) else 0,
                    "fuel_to_add_at_pit": max(0, ((snap.session_time_left / snap.last_lap_ms + 1.5) * snap.fuel_per_lap) - snap.fuel_liters) if (snap.last_lap_ms and snap.last_lap_ms > 0 and snap.fuel_per_lap > 0) else 0,
                    "pit_window_start":   snap.pit_window_start,
                    "pit_window_end":     snap.pit_window_end,
                    "penalty":            snap.penalty_type,
                    "track_grip":         snap.track_grip_status,
                    "air_temp":           snap.air_temp,
                    "road_temp":          snap.road_temp,
                })

                msgs: list[Message] = rules.evaluate(local=snap)
                ahead, behind = broadcast.car_ahead_behind()
                if ahead is not None:
                    g = abs(snap.gap_ahead_ms) / 1000.0 if snap.gap_ahead_ms else None
                    if g is not None:
                        m = rules.rival_close_ahead(g, ahead)
                        if m:
                            msgs.append(m)
                if behind is not None:
                    g = abs(snap.gap_behind_ms) / 1000.0 if snap.gap_behind_ms else None
                    if g is not None:
                        m = rules.rival_close_behind(g, behind)
                        if m:
                            msgs.append(m)

                for m in sorted(msgs, key=lambda x: x.priority):
                    self._voice.say(m.text, priority=m.priority)

                self._ui_queue.put({
                    "type": EVT_TELEMETRY,
                    "state": dict(last_state),
                })
                
                session_info = ""
                if snap.track:
                    session_info = f"{snap.track} | {snap.session_type} | Lap {snap.completed_laps}"
                
                self._ui_queue.put({
                    "type": EVT_STATUS,
                    "local": True,
                    "broadcast": bcast_connected,
                    "session_info": session_info,
                })
                time.sleep(config.POLL_INTERVAL_SEC)

            if self._banter:
                self._banter.stop()
            broadcast.close()
            local_reader.close()

        self._telemetry_thread = threading.Thread(target=telemetry_loop, daemon=True, name="TelemetryLoop")
        self._telemetry_thread.start()

    def _on_close(self):
        self._stop_event.set()
        if self._voice:
            self._voice.stop()
        if self._ptt:
            self._ptt.stop()
        self.destroy()


if __name__ == "__main__":
    app = RaceEngineerApp()
    app.mainloop()
