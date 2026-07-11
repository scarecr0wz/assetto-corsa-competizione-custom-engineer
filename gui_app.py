"""
Race Engineer Bawel - Desktop GUI
Gunakan ini sebagai pengganti main.py untuk mode GUI.
    python gui_app.py
"""

import sys
import os

# Insert src directory into sys.path to find core modules
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


# ─── Theme ───────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

C_BG        = "#0D0F14"
C_PANEL     = "#13161D"
C_CARD      = "#1A1E28"
C_BORDER    = "#252A38"
C_ACCENT    = "#E8352A"
C_ACCENT2   = "#F5A623"
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


def _fmt_laptime(ms: int) -> str:
    if not ms:
        return "-:--.---"
    total_sec = ms / 1000.0
    minutes = int(total_sec // 60)
    seconds = total_sec - minutes * 60
    return f"{minutes}:{seconds:06.3f}"


class RaceEngineerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🏎️  Race Engineer Bawel")
        self.geometry("1100x720")
        self.minsize(900, 600)
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
        self._build_topbar()

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
        self._tabview.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._tabview.add("🏁  Engineer's Log")
        self._tabview.add("📊  Telemetry")
        self._tabview.add("⚙️  Settings")

        self._build_log_tab(self._tabview.tab("🏁  Engineer's Log"))
        self._build_telemetry_tab(self._tabview.tab("📊  Telemetry"))
        self._build_settings_tab(self._tabview.tab("⚙️  Settings"))

    def _build_topbar(self):
        bar = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=10,
                           border_width=1, border_color=C_BORDER)
        bar.pack(fill="x", padx=12, pady=(12, 6))

        ctk.CTkLabel(bar, text="🏎️  Race Engineer Bawel",
                     font=ctk.CTkFont("Segoe UI", 18, weight="bold"),
                     text_color=C_ACCENT).pack(side="left", padx=16, pady=10)

        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.pack(side="right", padx=16, pady=8)

        self._lbl_session = ctk.CTkLabel(right, text="No Session",
                                         font=ctk.CTkFont("Segoe UI", 12),
                                         text_color=C_MUTED)
        self._lbl_session.pack(side="right", padx=(16, 8))

        self._ind_broadcast = self._status_indicator(right, "Broadcast API", C_MUTED)
        self._ind_broadcast.pack(side="right", padx=(8, 0))

        self._ind_local = self._status_indicator(right, "Shared Memory", C_MUTED)
        self._ind_local.pack(side="right", padx=(8, 0))

    def _status_indicator(self, parent, label: str, color: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        dot = ctk.CTkLabel(frame, text="●", font=ctk.CTkFont("Segoe UI", 14),
                           text_color=color)
        dot.pack(side="left")
        lbl = ctk.CTkLabel(frame, text=label, font=ctk.CTkFont("Segoe UI", 11),
                           text_color=C_MUTED)
        lbl.pack(side="left", padx=(2, 0))
        frame._dot = dot
        frame._lbl = lbl
        return frame

    def _set_indicator(self, indicator, connected: bool):
        indicator._dot.configure(text_color=C_GREEN if connected else C_MUTED)

    # ─── Log Tab ─────────────────────────────────────────────────────────────
    def _build_log_tab(self, parent):
        parent.configure(fg_color=C_PANEL)
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=0)
        parent.rowconfigure(0, weight=1)

        log_frame = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=8,
                                 border_width=1, border_color=C_BORDER)
        log_frame.grid(row=0, column=0, padx=(8, 4), pady=8, sticky="nsew")

        ctk.CTkLabel(log_frame, text="ENGINEER'S LOG",
                     font=ctk.CTkFont("Segoe UI", 11, weight="bold"),
                     text_color=C_MUTED).pack(anchor="w", padx=12, pady=(8, 0))

        self._log_text = ctk.CTkTextbox(
            log_frame, fg_color=C_CARD, text_color=C_TEXT,
            font=ctk.CTkFont("Consolas", 12),
            activate_scrollbars=True, wrap="word", border_width=0,
        )
        self._log_text.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self._log_text.configure(state="disabled")
        tb = self._log_text._textbox
        tb.tag_configure("urgent",    foreground=C_URGENT)
        tb.tag_configure("warning",   foreground=C_WARNING)
        tb.tag_configure("banter",    foreground=C_BANTER)
        tb.tag_configure("normal",    foreground=C_NORMAL)
        tb.tag_configure("timestamp", foreground=C_MUTED)
        tb.tag_configure("system",    foreground="#4A9EFF")

        # Sidebar
        sidebar = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=8,
                               border_width=1, border_color=C_BORDER, width=160)
        sidebar.grid(row=0, column=1, padx=(4, 8), pady=8, sticky="nsew")
        sidebar.pack_propagate(False)

        ctk.CTkLabel(sidebar, text="VOICE COMMAND",
                     font=ctk.CTkFont("Segoe UI", 10, weight="bold"),
                     text_color=C_MUTED).pack(pady=(12, 4))

        self._mic_frame = ctk.CTkFrame(sidebar, fg_color=C_BORDER,
                                       corner_radius=50, width=80, height=80)
        self._mic_frame.pack(pady=8)
        self._mic_frame.pack_propagate(False)
        self._mic_label = ctk.CTkLabel(self._mic_frame, text="🎙️",
                                       font=ctk.CTkFont("Segoe UI", 32))
        self._mic_label.pack(expand=True)

        self._ptt_status_label = ctk.CTkLabel(
            sidebar, text="Hold CAPS LOCK\nto speak",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=C_MUTED, justify="center",
        )
        self._ptt_status_label.pack(pady=4)

        ctk.CTkFrame(sidebar, fg_color=C_BORDER, height=1).pack(
            fill="x", padx=12, pady=12)

        ctk.CTkLabel(sidebar, text="PRIORITY LEGEND",
                     font=ctk.CTkFont("Segoe UI", 10, weight="bold"),
                     text_color=C_MUTED).pack(pady=(0, 6))

        for color, label in [
            (C_URGENT,  "🔴 Urgent"),
            (C_WARNING, "🟡 Warning"),
            (C_NORMAL,  "⚪ Normal"),
            (C_BANTER,  "🔵 Banter"),
        ]:
            ctk.CTkLabel(sidebar, text=label,
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=color).pack(anchor="w", padx=16, pady=1)

    # ─── Telemetry Tab ────────────────────────────────────────────────────────
    def _build_telemetry_tab(self, parent):
        parent.configure(fg_color=C_PANEL)
        for c in range(3):
            parent.columnconfigure(c, weight=1)
        for r in range(3):
            parent.rowconfigure(r, weight=1)

        # Tyre temps
        tyre_card = self._make_card(parent, "🏎️  TYRE TEMPERATURES (°C)")
        tyre_card.grid(row=0, column=0, columnspan=2, padx=(8, 4), pady=(8, 4), sticky="nsew")

        tyre_inner = ctk.CTkFrame(tyre_card, fg_color="transparent")
        tyre_inner.pack(fill="both", expand=True, padx=8, pady=8)
        for c in range(2):
            tyre_inner.columnconfigure(c, weight=1)
        for r in range(2):
            tyre_inner.rowconfigure(r, weight=1)

        self._tyre_labels = {}
        for name, r, c in [("FL", 0, 0), ("FR", 0, 1), ("RL", 1, 0), ("RR", 1, 1)]:
            f = self._make_tyre_cell(tyre_inner, name)
            f.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
            self._tyre_labels[name] = f

        # Fuel
        fuel_card = self._make_card(parent, "⛽  FUEL")
        fuel_card.grid(row=0, column=2, padx=(4, 8), pady=(8, 4), sticky="nsew")
        self._fuel_value = ctk.CTkLabel(fuel_card, text="--",
                                        font=ctk.CTkFont("Segoe UI", 36, weight="bold"),
                                        text_color=C_GREEN)
        self._fuel_value.pack(expand=True)
        ctk.CTkLabel(fuel_card, text="laps remaining",
                     font=ctk.CTkFont("Segoe UI", 12), text_color=C_MUTED).pack(pady=(0, 4))
        self._fuel_liters_label = ctk.CTkLabel(fuel_card, text="-- L",
                                               font=ctk.CTkFont("Segoe UI", 14),
                                               text_color=C_TEXT)
        self._fuel_liters_label.pack(pady=(0, 8))

        # Lap times
        lap_card = self._make_card(parent, "⏱  LAP TIMES")
        lap_card.grid(row=1, column=0, columnspan=2, padx=(8, 4), pady=4, sticky="nsew")
        lap_inner = ctk.CTkFrame(lap_card, fg_color="transparent")
        lap_inner.pack(fill="both", expand=True, padx=12, pady=8)
        lap_inner.columnconfigure(0, weight=1)
        lap_inner.columnconfigure(1, weight=1)

        ctk.CTkLabel(lap_inner, text="Last Lap", font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C_MUTED).grid(row=0, column=0, pady=(0, 2))
        ctk.CTkLabel(lap_inner, text="Best Lap", font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C_MUTED).grid(row=0, column=1, pady=(0, 2))
        self._last_lap_lbl = ctk.CTkLabel(lap_inner, text="-:--.---",
                                          font=ctk.CTkFont("Consolas", 22, weight="bold"),
                                          text_color=C_TEXT)
        self._last_lap_lbl.grid(row=1, column=0)
        self._best_lap_lbl = ctk.CTkLabel(lap_inner, text="-:--.---",
                                          font=ctk.CTkFont("Consolas", 22, weight="bold"),
                                          text_color=C_GREEN)
        self._best_lap_lbl.grid(row=1, column=1)
        self._delta_lbl = ctk.CTkLabel(lap_inner, text="Δ +0.000",
                                       font=ctk.CTkFont("Consolas", 14),
                                       text_color=C_MUTED)
        self._delta_lbl.grid(row=2, column=0, columnspan=2, pady=4)

        # Position
        gap_card = self._make_card(parent, "🏁  POSITION & GAPS")
        gap_card.grid(row=1, column=2, padx=(4, 8), pady=4, sticky="nsew")
        self._pos_label = ctk.CTkLabel(gap_card, text="P--",
                                       font=ctk.CTkFont("Segoe UI", 40, weight="bold"),
                                       text_color=C_ACCENT)
        self._pos_label.pack(pady=(8, 0))
        self._gap_ahead_lbl = ctk.CTkLabel(gap_card, text="▲ ahead: --s",
                                           font=ctk.CTkFont("Segoe UI", 12),
                                           text_color=C_MUTED)
        self._gap_ahead_lbl.pack()
        self._gap_behind_lbl = ctk.CTkLabel(gap_card, text="▼ behind: --s",
                                            font=ctk.CTkFont("Segoe UI", 12),
                                            text_color=C_MUTED)
        self._gap_behind_lbl.pack(pady=(0, 8))

        # Car info
        info_card = self._make_card(parent, "🚗  CAR / SESSION INFO")
        info_card.grid(row=2, column=0, columnspan=3, padx=8, pady=(4, 8), sticky="nsew")
        info_inner = ctk.CTkFrame(info_card, fg_color="transparent")
        info_inner.pack(fill="both", expand=True, padx=12, pady=8)
        for c in range(6):
            info_inner.columnconfigure(c, weight=1)

        self._info_labels = {}
        for col, (display, key) in enumerate([
            ("Track", "track"), ("Car", "car_model"), ("Session", "session"),
            ("Driver", "driver_name"), ("Lap", "lap"), ("Speed", "speed"),
        ]):
            ctk.CTkLabel(info_inner, text=display, font=ctk.CTkFont("Segoe UI", 10),
                         text_color=C_MUTED).grid(row=0, column=col, pady=(0, 2))
            lbl = ctk.CTkLabel(info_inner, text="--",
                               font=ctk.CTkFont("Segoe UI", 13, weight="bold"),
                               text_color=C_TEXT)
            lbl.grid(row=1, column=col)
            self._info_labels[key] = lbl

    def _make_card(self, parent, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=8,
                            border_width=1, border_color=C_BORDER)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont("Segoe UI", 11, weight="bold"),
                     text_color=C_MUTED).pack(anchor="w", padx=12, pady=(8, 2))
        return card

    def _make_tyre_cell(self, parent, pos: str) -> ctk.CTkFrame:
        cell = ctk.CTkFrame(parent, fg_color=C_BORDER, corner_radius=8)
        ctk.CTkLabel(cell, text=pos, font=ctk.CTkFont("Segoe UI", 11, weight="bold"),
                     text_color=C_MUTED).pack(pady=(6, 0))
        temp_lbl = ctk.CTkLabel(cell, text="--°",
                                font=ctk.CTkFont("Consolas", 22, weight="bold"),
                                text_color=C_TEXT)
        temp_lbl.pack()
        bar = ctk.CTkProgressBar(cell, height=6, progress_color=C_GREEN,
                                 fg_color=C_CARD, corner_radius=3)
        bar.set(0)
        bar.pack(fill="x", padx=8, pady=(2, 8))
        cell._temp_lbl = temp_lbl
        cell._bar = bar
        return cell

    def _update_tyre_cell(self, cell, temp: float):
        if temp <= 0:
            cell._temp_lbl.configure(text="--°", text_color=C_MUTED)
            cell._bar.set(0)
            return
        cell._temp_lbl.configure(text=f"{temp:.0f}°")
        if temp < config.TYRE_TEMP_MIN_C:
            color = C_BLUE
        elif temp > config.TYRE_TEMP_MAX_C:
            color = C_URGENT
        else:
            color = C_GREEN
        cell._temp_lbl.configure(text_color=color)
        cell._bar.configure(progress_color=color)
        val = max(0.0, min(1.0, (temp - 20) / 110))
        cell._bar.set(val)

    # ─── Settings Tab ─────────────────────────────────────────────────────────
    def _build_settings_tab(self, parent):
        parent.configure(fg_color=C_PANEL)
        scroll = ctk.CTkScrollableFrame(parent, fg_color=C_PANEL)
        scroll.pack(fill="both", expand=True, padx=8, pady=8)
        scroll.columnconfigure(0, weight=1)
        scroll.columnconfigure(1, weight=1)

        # API Keys
        api_card = self._make_card(scroll, "🔑  API KEYS")
        api_card.grid(row=0, column=0, columnspan=2, padx=4, pady=4, sticky="ew")
        self._groq_entry = self._labeled_entry(api_card, "Groq API Key",
                                               config.GROQ_API_KEY or "",
                                               placeholder="gsk_...", show="*")

        # ACC Connection
        acc_card = self._make_card(scroll, "🔌  ACC CONNECTION")
        acc_card.grid(row=1, column=0, padx=4, pady=4, sticky="nsew")
        self._broadcast_pw_entry = self._labeled_entry(acc_card, "Broadcast Password",
                                                       config.ACC_CONNECTION_PASSWORD or "",
                                                       show="*")
        self._acc_host_entry = self._labeled_entry(acc_card, "Host", config.ACC_HOST)
        self._acc_port_entry = self._labeled_entry(acc_card, "Port", str(config.ACC_PORT))

        # Voice Settings
        voice_card = self._make_card(scroll, "🔊  VOICE SETTINGS")
        voice_card.grid(row=1, column=1, padx=4, pady=4, sticky="nsew")
        self._voice_hint_entry = self._labeled_entry(voice_card, "TTS Voice Hint",
                                                     config.TTS_VOICE_HINT or "",
                                                     placeholder="e.g. en-GB-RyanNeural")
        ctk.CTkLabel(voice_card, text="Speech Rate (wpm)",
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=C_MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self._rate_var = tk.IntVar(value=config.TTS_RATE)
        rate_slider = ctk.CTkSlider(voice_card, from_=100, to=300, number_of_steps=40,
                                    variable=self._rate_var,
                                    button_color=C_ACCENT, button_hover_color="#C42A20",
                                    progress_color=C_ACCENT)
        rate_slider.pack(fill="x", padx=12, pady=(4, 0))
        self._rate_display = ctk.CTkLabel(voice_card, text=f"{config.TTS_RATE} wpm",
                                          font=ctk.CTkFont("Segoe UI", 11),
                                          text_color=C_TEXT)
        self._rate_display.pack(anchor="w", padx=12, pady=(0, 8))
        rate_slider.configure(command=lambda v: self._rate_display.configure(
            text=f"{int(v)} wpm"))

        # Personality
        pers_card = self._make_card(scroll, "🎭  PERSONALITY")
        pers_card.grid(row=2, column=0, padx=4, pady=4, sticky="nsew")
        ctk.CTkLabel(pers_card, text="Engineer Personality",
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=C_MUTED).pack(anchor="w", padx=12, pady=(8, 2))
        self._personality_var = tk.StringVar(value=config.ENGINEER_PERSONALITY)
        ctk.CTkOptionMenu(pers_card,
                          values=["galak", "santai", "cerewet_lucu"],
                          variable=self._personality_var,
                          fg_color=C_BORDER, button_color=C_ACCENT,
                          button_hover_color="#C42A20",
                          text_color=C_TEXT).pack(fill="x", padx=12, pady=(0, 12))

        # Controls
        ptt_card = self._make_card(scroll, "⌨️  CONTROLS")
        ptt_card.grid(row=2, column=1, padx=4, pady=4, sticky="nsew")
        self._ptt_entry = self._labeled_entry(ptt_card, "Push-to-Talk Key",
                                              config.PTT_KEY,
                                              placeholder="e.g. caps_lock")

        # LLM
        llm_card = self._make_card(scroll, "🤖  LLM BANTER")
        llm_card.grid(row=3, column=0, columnspan=2, padx=4, pady=4, sticky="ew")
        self._enable_llm_var = tk.BooleanVar(value=config.ENABLE_LLM_BANTER)
        ctk.CTkSwitch(llm_card, text="Enable LLM Banter",
                      variable=self._enable_llm_var,
                      onvalue=True, offvalue=False,
                      progress_color=C_ACCENT,
                      font=ctk.CTkFont("Segoe UI", 12),
                      text_color=C_TEXT).pack(anchor="w", padx=12, pady=8)
        self._llm_model_entry = self._labeled_entry(llm_card, "LLM Model", config.LLM_MODEL)

        # Save
        ctk.CTkButton(scroll, text="💾  Save & Apply Settings",
                      command=self._save_settings,
                      fg_color=C_ACCENT, hover_color="#C42A20",
                      font=ctk.CTkFont("Segoe UI", 13, weight="bold"),
                      height=40, corner_radius=8).grid(
            row=4, column=0, columnspan=2, padx=4, pady=12, sticky="ew")

    def _labeled_entry(self, parent, label: str, value: str,
                       placeholder: str = "", show: str = "") -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label, font=ctk.CTkFont("Segoe UI", 12),
                     text_color=C_MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        entry = ctk.CTkEntry(parent, placeholder_text=placeholder or label,
                             fg_color=C_BORDER, text_color=C_TEXT,
                             border_color=C_BORDER, show=show)
        if value:
            entry.insert(0, value)
        entry.pack(fill="x", padx=12, pady=(2, 0))
        return entry

    def _save_settings(self):
        config.GROQ_API_KEY = self._groq_entry.get()
        config.ACC_CONNECTION_PASSWORD = self._broadcast_pw_entry.get()
        config.ACC_HOST = self._acc_host_entry.get()
        try:
            config.ACC_PORT = int(self._acc_port_entry.get())
        except ValueError:
            pass
        config.TTS_VOICE_HINT = self._voice_hint_entry.get()
        config.TTS_RATE = self._rate_var.get()
        config.ENGINEER_PERSONALITY = self._personality_var.get()
        config.PTT_KEY = self._ptt_entry.get()
        config.ENABLE_LLM_BANTER = self._enable_llm_var.get()
        config.LLM_MODEL = self._llm_model_entry.get()
        self._post_log("⚙️ Settings applied. Restart required for some changes.",
                       priority=1, tag="system")

    # ─── Log helpers ──────────────────────────────────────────────────────────
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

    # ─── UI queue polling ─────────────────────────────────────────────────────
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
                self._lbl_session.configure(text=si, text_color=C_TEXT)
        elif etype == EVT_TELEMETRY:
            self._update_telemetry_display(evt.get("state", {}))
        elif etype == EVT_PTT:
            active = evt.get("active", False)
            self._mic_frame.configure(fg_color=C_ACCENT if active else C_BORDER)
            self._ptt_status_label.configure(
                text="🎙️ Listening..." if active else "Hold CAPS LOCK\nto speak",
                text_color=C_URGENT if active else C_MUTED,
            )

    def _update_telemetry_display(self, s: dict):
        if not s:
            return
        for pos, key in [("FL","tyre_fl"),("FR","tyre_fr"),
                          ("RL","tyre_rl"),("RR","tyre_rr")]:
            self._update_tyre_cell(self._tyre_labels[pos], s.get(key, 0))

        fl = s.get("fuel_laps", 0)
        liters = s.get("fuel_liters", 0)
        fuel_color = (C_URGENT  if fl < config.FUEL_LAPS_CRITICAL else
                      C_WARNING if fl < config.FUEL_LAPS_WARNING  else C_GREEN)
        self._fuel_value.configure(text=f"{fl:.1f}", text_color=fuel_color)
        self._fuel_liters_label.configure(text=f"{liters:.1f} L")

        self._last_lap_lbl.configure(text=s.get("last_lap", "-:--.---"))
        self._best_lap_lbl.configure(text=s.get("best_lap", "-:--.---"))
        delta = s.get("delta", 0)
        self._delta_lbl.configure(
            text=f"Δ {delta:+.3f}s",
            text_color=C_GREEN if delta < 0 else C_WARNING)

        pos = s.get("position", 0)
        self._pos_label.configure(text=f"P{pos}" if pos else "P--")
        ga = s.get("gap_ahead")
        gb = s.get("gap_behind")
        self._gap_ahead_lbl.configure(
            text=f"▲ ahead: {ga:.1f}s" if ga else "▲ ahead: --")
        self._gap_behind_lbl.configure(
            text=f"▼ behind: {gb:.1f}s" if gb else "▼ behind: --")

        speed = s.get("speed", 0)
        lap_num = s.get("lap", 0)
        for key, val in [
            ("track",       s.get("track", "--")),
            ("car_model",   s.get("car_model", "--")),
            ("session",     s.get("session", "--")),
            ("driver_name", s.get("driver_name", "--")),
            ("lap",         str(lap_num) if lap_num else "--"),
            ("speed",       f"{speed:.0f} km/h" if speed else "--"),
        ]:
            self._info_labels[key].configure(text=str(val)[:20])

    # ─── Backend ──────────────────────────────────────────────────────────────
    def _start_backend(self):
        self._post_log("🏎️  Race Engineer Bawel starting up...", priority=1, tag="system")

        self._voice = VoiceQueue()
        self._voice.start()
        self._post_log("✅ Voice queue ready.", priority=1, tag="system")

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
        self._post_log(f"🎙️ Push-to-Talk ready ({config.PTT_KEY})", priority=1, tag="system")

        def telemetry_loop():
            local_reader = LocalTelemetryReader()
            broadcast    = BroadcastReader()
            rules        = RulesEngine()

            self._post_log("Connecting to ACC Broadcasting API...", priority=1, tag="system")
            ok = broadcast.connect(timeout_sec=5.0)
            self._post_log(
                "✅ Broadcasting API connected." if ok
                else "⚠️ Broadcasting API not available — will retry every 30s.",
                priority=1, tag="system")

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
                                self._post_log("✅ Broadcasting API reconnected.",
                                               priority=1, tag="system")
                    self._ui_queue.put({"type": EVT_STATUS,
                                        "local": False, "broadcast": bcast_connected})
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
                    session_info = (f"{snap.track}  |  {snap.session_type}"
                                    f"  |  P{snap.position}")
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

        self._telemetry_thread = threading.Thread(
            target=telemetry_loop, daemon=True, name="TelemetryLoop")
        self._telemetry_thread.start()
        self._post_log("✅ Telemetry thread started.", priority=1, tag="system")

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
