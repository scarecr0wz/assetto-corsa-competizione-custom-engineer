"""
Bagian "hybrid" otak engineer: buat komentar santai/nyeleneh yang gak
harus akurat detik itu juga (beda sama rule-based yang harus instant).
Jalan di thread terpisah biar gak bikin lag loop utama nunggu API.
"""

import random
import threading
import time
from typing import Callable, Optional

import config
from mfd_control import parse_intent, MfdController, VoiceIntent

_client = None
if config.ENABLE_LLM_BANTER and config.GROQ_API_KEY:
    try:
        from groq import Groq
        _client = Groq(api_key=config.GROQ_API_KEY, timeout=15.0, max_retries=1)
    except Exception as e:
        print(f"[llm_commentary] Gagal init groq client: {e}")
        _client = None

SYSTEM_PROMPT = (
    "You are a race engineer speaking on the radio to a sim racing driver in ACC. "
    "OUTPUT RULES — these are absolute, never break them:\n"
    "- Output EXACTLY one sentence. Never two. Never a list. Never a paragraph.\n"
    "- Maximum 20 words total.\n"
    "- No labels, no preamble, no 'Engineer:', no quotes, no newlines.\n"
    "- Sound like a real radio call: short, punchy, natural.\n"
    "Tone: casual, chatty, occasionally funny, always attentive."
)


class LlmBanterWorker:
    def __init__(self, on_message: Callable[[str], None], get_state: Callable[[], dict]):
        self.on_message = on_message
        self.get_state  = get_state
        self._stop      = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # MFD controller untuk voice → setting ACC
        self._mfd = MfdController(
            on_feedback=lambda text: on_message(text),
            get_state=get_state,
        )

    def start(self):
        if not _client:
            print("[llm_commentary] LLM banter nonaktif (no API key / disabled). "
                  "Set GROQ_API_KEY kalau mau enable.")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            wait = random.uniform(
                config.LLM_BANTER_MIN_INTERVAL_SEC, config.LLM_BANTER_MAX_INTERVAL_SEC
            )
            if self._stop.wait(wait):
                return
            try:
                text = self._generate()
                if text:
                    self.on_message(text)
            except Exception as e:
                print(f"[llm_commentary] API error: {e}")
                time.sleep(10)

    def handle_voice_command(self, wav_path: str):
        if not _client:
            return
            
        print("[llm_commentary] Mentranskripsi suara...")
        try:
            with open(wav_path, "rb") as f:
                transcription = _client.audio.transcriptions.create(
                    file=(wav_path, f.read()),
                    model="whisper-large-v3-turbo",
                    prompt="Racing terminology, assetto corsa, pit stop, fuel liters, engine map, brake bias, tyre compound.",
                    response_format="text",
                    language="en"
                )
            text = transcription.strip()
            print(f"[Kamu]: \"{text}\"")
        except Exception as e:
            print(f"[llm_commentary] Whisper error: {e}")
            return
            
        if len(text) < 2:
            return

        # --- Intent check dulu sebelum kirim ke LLM ---
        intent = parse_intent(text)
        print(f"[llm_commentary] Intent parsed: {intent}")
        if intent.action != 'unknown':
            # Command dikenal → langsung ke MFD controller, skip LLM
            self._mfd.handle_intent(intent)
            return
        # Tidak dikenal → fallback ke LLM untuk jawaban conversational
            
        state = self.get_state()
        gap_str = ""
        if state.get('gap_ahead'):
            gap_str += f"Gap ahead {state.get('gap_ahead'):.1f}s. "
        if state.get('gap_behind'):
            gap_str += f"Gap behind {state.get('gap_behind'):.1f}s. "

        time_left_mins = state.get('session_time_left', 0) / 1000 / 60
        delta = state.get('delta') or 0.0
        fuel_liters = state.get('fuel_liters') or 0.0
        fuel_laps = state.get('fuel_laps') or 0.0
        brake_bias = state.get('brake_bias') or 0.0
        tyre_avg = state.get('tyre_avg') or 0.0
        
        sys_prompt = (
            "You are a highly strategic race engineer in Assetto Corsa Competizione. "
            "The driver is talking to you on the radio. Reply DIRECTLY to the driver's message based on the telemetry data. "
            "OUTPUT RULES:\n"
            "- MAXIMUM two punchy sentences. Keep it under 30 words.\n"
            "- No labels (like 'Engineer:'), no preamble, no quotes.\n"
            "- Realistic, calm but urgent radio tone. Give PRECISE numbers when asked.\n"
            "- For fuel/pit questions: calculate exact liters to add = fuel_to_end minus current fuel. Always round UP.\n"
            "- For strategy: factor in tyre life, track position, gaps, and remaining time.\n"
            "- Sound like a real F1/GT3 race engineer: concise, data-driven, confident."
        )
        
        laps_remaining = state.get('laps_remaining_estimate') or 0.0
        fuel_to_end = state.get('fuel_to_end') or 0.0
        fuel_to_add = state.get('fuel_to_add_at_pit') or 0.0
        fuel_per_lap_val = state.get('fuel_per_lap') or 0.0
        air_temp_val = state.get('air_temp') or 0.0
        road_temp_val = state.get('road_temp') or 0.0
        track_grip_val = state.get('track_grip') or 'unknown'
        penalty_val = state.get('penalty') or 'none'
        
        telemetry = (
            f"Driver: {state.get('driver_surname')}. Lap {state.get('lap')}, P{state.get('position')}. "
            f"Delta: {delta:+.1f}s. {gap_str}"
            f"Fuel: {fuel_liters:.1f}L ({fuel_laps:.1f} laps left). Fuel/lap: {fuel_per_lap_val:.2f}L. "
            f"Laps remaining in session: {laps_remaining:.1f}. "
            f"Fuel needed to finish: {fuel_to_end:.1f}L. Fuel to ADD at pit: {fuel_to_add:.0f}L. "
            f"Time left: {time_left_mins:.1f} mins. "
            f"Setup: Map {state.get('engine_map')}, BBias {brake_bias:.1f}%, TC {state.get('tc')}, ABS {state.get('abs')}. "
            f"Tyres: {state.get('compound')} (avg {tyre_avg:.0f}°C, FL:{state.get('tyre_fl', 0):.0f} FR:{state.get('tyre_fr', 0):.0f} RL:{state.get('tyre_rl', 0):.0f} RR:{state.get('tyre_rr', 0):.0f}). "
            f"Track: grip {track_grip_val}, air {air_temp_val:.0f}°C, road {road_temp_val:.0f}°C. "
            f"Weather: {state.get('rain') or 'dry'}. Flag: {state.get('flag') or 'GREEN'}. Penalty: {penalty_val}."
        )

        user_prompt = f"[Telemetry Context]\n{telemetry}\n\n[Driver Radio]: \"{text}\""

        try:
            resp = _client.chat.completions.create(
                model=config.LLM_MODEL,
                max_tokens=80,
                temperature=0.7,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = resp.choices[0].message.content.strip()
            final = raw[:200]  # allow full response for voice commands
            self.on_message(final)
        except Exception as e:
            print(f"[llm_commentary] chat error: {e}")

    def _generate(self) -> Optional[str]:
        state = self.get_state()
        if not state.get("connected"):
            return None
        gap_str = ""
        if state.get('gap_ahead'):
            gap_str += f"Gap to P{max(1, state.get('position', 1)-1)} is {state.get('gap_ahead')}s. "
        if state.get('gap_behind'):
            gap_str += f"Gap to car behind is {state.get('gap_behind')}s. "
            
        driver_name = state.get('driver_surname') or state.get('driver_name') or "mate"

        time_left_mins = state.get('session_time_left', 0) / 1000 / 60
        
        prompt = (
            f"Driver: {driver_name}. Lap {state.get('lap')}, P{state.get('position')}, {state.get('speed'):.0f} km/h. "
            f"Delta: {state.get('delta'):+.1f}s. "
            f"{gap_str}"
            f"Fuel: {state.get('fuel_liters', 0):.1f}L ({state.get('fuel_laps'):.1f} laps), {state.get('fuel_per_lap', 0):.2f}L/lap. Time left: {time_left_mins:.1f} mins. "
            f"Setup: Map {state.get('engine_map')}, BBias {state.get('brake_bias'):.1f}%, TC {state.get('tc')}, ABS {state.get('abs')}. "
            f"Tyres: {state.get('compound')} (avg {state.get('tyre_avg'):.0f}°C). "
            f"Track: grip {state.get('track_grip', 'unknown')}, road {state.get('road_temp', 0):.0f}°C. "
            f"Weather: {state.get('rain') or 'dry'}. Flag: {state.get('flag') or 'GREEN'}. "
            "Give ONE punchy radio comment. You are a highly strategic, data-driven race engineer. "
            "You can: encourage pace, warn about gaps or tyre degradation, suggest dynamic setup changes "
            "(e.g. Engine Map for fuel saving/pushing, Brake Bias adjustments for understeer/oversteer, "
            "TC/ABS tweaks for conditions), call pit strategy, or comment on track/weather conditions. "
            "Keep it under 15 words, sharp and realistic like real GT3 radio."
        )
        resp = _client.chat.completions.create(
            model=config.LLM_MODEL,
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=0.9,
            stop=["\n", "\r"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        raw = resp.choices[0].message.content.strip()
        return _first_sentence(raw)


def _first_sentence(text: str) -> Optional[str]:
    """Sanitise LLM output: one clean sentence only."""
    import re
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Reject lines that start with punctuation/comma (fragment from multi-line)
        if line[0] in '.,;:-':
            continue
        # Strip surrounding quotes
        line = line.strip('"\'')
        # Trim to first sentence
        m = re.match(r'^(.+?[.!?])(?:\s|$)', line)
        sentence = m.group(1).strip() if m else line[:120]
        # Reject if fewer than 4 real letters (e.g. just punctuation)
        if len(re.sub(r'[^a-zA-Z]', '', sentence)) < 4:
            continue
        # Reject if it looks like raw telemetry data (starts with a number/unit)
        if re.match(r'^\d', sentence):
            continue
        return sentence
    return None
