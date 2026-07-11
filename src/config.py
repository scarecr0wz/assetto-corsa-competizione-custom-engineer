"""
Konfigurasi Race Engineer.
Sesuaikan angka-angka ini sesuai mobil/track yang kamu pakai.
"""

import os

# --- Koneksi ke ACC Broadcasting API ---
# Password ini di-set di file:
# Documents\Assetto Corsa Competizione\Config\broadcasting.json
# Buka file itu dan isi "connectionPassword", lalu copy nilainya ke sini
# (atau lebih aman: set via environment variable ACC_BROADCAST_PASSWORD)
ACC_HOST = "127.0.0.1"
ACC_PORT = 9000
ACC_CONNECTION_PASSWORD = os.environ.get("ACC_BROADCAST_PASSWORD", "asd")
ACC_COMMAND_PASSWORD = os.environ.get("ACC_BROADCAST_COMMAND_PASSWORD", "")
ACC_DISPLAY_NAME = "Race Engineer Bawel"
ACC_UPDATE_INTERVAL_MS = 250  # seberapa sering ACC kirim update (ms)

# --- Polling loop (shared memory + brain tick) ---
POLL_INTERVAL_SEC = 0.5

# --- Threshold Rule-Based (silakan tuning sesuai mobil) ---
FUEL_LAPS_WARNING = 3          # warning kalau sisa fuel < segini lap
FUEL_LAPS_CRITICAL = 1.2       # critical / harus pit sekarang
TYRE_TEMP_MIN_C = 70           # di bawah ini ban dingin, kurang grip
TYRE_TEMP_MAX_C = 105          # di atas ini ban overheat
BRAKE_TEMP_MAX_C = 750         # brake overheating (indikatif, GT3 umum)
GAP_CLOSE_THRESHOLD_SEC = 2.0  # gap ke mobil depan/belakang dianggap "deket" kalau < ini
DELTA_GOOD_SEC = -0.1          # delta lebih cepat dari ini dianggap "on it"
COOLDOWN_SAME_EVENT_SEC = 45   # jangan spam event yang sama dalam X detik

# Voice Input Config
PTT_KEY = 'caps_lock'          # tombol keyboard untuk push-to-talk (Voice Command)

# --- Hybrid "otak" LLM buat banter santai ---
ENABLE_LLM_BANTER = True
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_BANTER_MIN_INTERVAL_SEC = 90   # jangan banter LLM lebih sering dari ini (dikurangi frekuensinya)
LLM_BANTER_MAX_INTERVAL_SEC = 180  # kalau sepi event, banter muncul random di rentang ini
LLM_MAX_TOKENS = 80

# --- TTS ---
TTS_RATE = 185          # kata per menit, defaultnya cenderung lambat
TTS_VOLUME = 1.0
# Kosongkan buat pakai voice default OS. Isi substring nama voice kalau mau pilih
# (jalankan tools/list_voices.py buat lihat voice yang ada di komputer kamu)
TTS_VOICE_HINT = ""

# --- Kepribadian ---
# "galak" | "santai" | "cerewet_lucu"
ENGINEER_PERSONALITY = "cerewet_lucu"
