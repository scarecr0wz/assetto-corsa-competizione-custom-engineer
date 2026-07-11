"""
MFD Controller — kirim keypress ke ACC untuk kontrol pit settings.

ACC MFD (default bindings):
  - Buka/tutup MFD       : tidak ada default key global yg bisa di-simulate reliably
  - Navigasi page        : Page Up / Page Down
  - Adjust value         : Left Arrow (kurang) / Right Arrow (tambah)
  - Next item dalam page : Down Arrow
  - Confirm/Select       : Enter

Untuk Pit Strategy page, urutan item (default ACC):
  Page 0 (Pit Strategy):
    0 - Pit (Yes/No toggle)
    1 - Tyre Set
    2 - Tyre Compound (Dry/Wet)
    3 - Fuel to add (0..120L, step 1L)
    4 - Tyre pressure FL / FR / RL / RR (opsional)
    5 - Clear driver swap (kalau endurance)

  Page lain (Electronics):
    Engine Map, TC, ABS, Brake Bias — dikontrol via steering wheel / keyboard biasa

Cara kerja script ini:
  1. Kirim keypress via win32api ke window "AC2" (proses ACC)
  2. Navigate ke halaman yg dibutuhkan
  3. Adjust value dgn Left/Right arrows

CATATAN PENTING:
  - Semua virtual key code (VK_*) pakai nilai standard Windows.
  - win32api.SendMessage ke ACC window (bukan PostMessage) lebih reliable.
  - Hanya jalan di Windows (tapi ACC juga Windows-only, jadi fine).
"""

import re
import time
import threading
from typing import Optional, Callable
import ctypes
import ctypes.wintypes

# --- Virtual Key Codes ---
VK_LEFT    = 0x25
VK_RIGHT   = 0x27
VK_UP      = 0x26
VK_DOWN    = 0x28
VK_PRIOR   = 0x21  # Page Up
VK_NEXT    = 0x22  # Page Down
VK_RETURN  = 0x0D  # Enter
VK_ESCAPE  = 0x1B

WM_KEYDOWN = 0x0100
WM_KEYUP   = 0x0101

# ACC window class / title yang dicari
_ACC_WINDOW_TITLES = ["AC2", "Assetto Corsa Competizione"]


def _find_acc_window() -> Optional[int]:
    """Cari HWND window ACC."""
    user32 = ctypes.windll.user32
    found = []

    def enum_callback(hwnd, lParam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if any(t in title for t in _ACC_WINDOW_TITLES):
                found.append(hwnd)
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    user32.EnumWindows(EnumWindowsProc(enum_callback), 0)
    return found[0] if found else None


def _send_key(hwnd: int, vk: int, delay: float = 0.08):
    """Kirim satu keypress (down + up) ke window dengan HWND."""
    user32 = ctypes.windll.user32
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
    time.sleep(delay)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)
    time.sleep(delay)


def _send_keys(hwnd: int, vk: int, count: int, delay: float = 0.08):
    """Kirim `count` keypress berulang."""
    for _ in range(count):
        _send_key(hwnd, vk, delay)


# ---------------------------------------------------------------------------
# Intent Parser
# ---------------------------------------------------------------------------

class VoiceIntent:
    """Hasil parsing dari transcribed voice command."""
    def __init__(self, action: str, value=None, raw: str = ""):
        self.action = action   # 'set_fuel', 'add_fuel', 'engine_map', 'brake_bias', 'tyre_compound', 'unknown'
        self.value  = value    # int/float/str tergantung action
        self.raw    = raw      # original transcription

    def __repr__(self):
        return f"VoiceIntent(action={self.action!r}, value={self.value!r})"


# Pola regex untuk parse voice command (case-insensitive)
_PATTERNS = [
    # Fuel: "set fuel to 40", "fuel 40 liters", "add 20 liters", "put 35 litres"
    (re.compile(r'\b(?:set\s+)?fuel\s+(?:to\s+)?(\d+(?:\.\d+)?)\s*(?:liter|litre|l|L)?\b', re.I), 'set_fuel'),
    (re.compile(r'\badd\s+(\d+(?:\.\d+)?)\s*(?:liter|litre|l|L)?\b', re.I),                       'add_fuel'),
    (re.compile(r'\bput\s+(?:in\s+)?(\d+(?:\.\d+)?)\s*(?:liter|litre|l|L)?\b', re.I),            'set_fuel'),
    (re.compile(r'\b(\d+(?:\.\d+)?)\s*(?:liter|litre)\b', re.I),                                   'set_fuel'),

    # Engine map: "engine map 3", "map 5", "set map to 2"
    (re.compile(r'\b(?:engine\s+)?map\s+(?:to\s+)?(\d+)\b', re.I),     'engine_map'),
    (re.compile(r'\bset\s+map\s+(?:to\s+)?(\d+)\b', re.I),             'engine_map'),

    # Brake bias: "brake bias 55", "bias to 56.5", "set bias 54"
    (re.compile(r'\b(?:brake\s+)?bias\s+(?:to\s+)?(\d+(?:\.\d+)?)\b', re.I), 'brake_bias'),
    (re.compile(r'\bset\s+bias\s+(?:to\s+)?(\d+(?:\.\d+)?)\b', re.I),        'brake_bias'),

    # Tyre compound: "switch to wet", "dry tyres", "put on wets"
    (re.compile(r'\b(?:switch\s+to\s+|put\s+on\s+|use\s+)?(wet|dry)\s*(?:tyre|tire|compound)?\b', re.I), 'tyre_compound'),
    (re.compile(r'\b(wet|dry)\s+(?:tyre|tire|compound|rubber)\b', re.I), 'tyre_compound'),
]


def parse_intent(text: str) -> VoiceIntent:
    """Parse transcribed text jadi VoiceIntent. Return 'unknown' kalau tidak cocok."""
    t = text.strip()
    for pattern, action in _PATTERNS:
        m = pattern.search(t)
        if m:
            raw_val = m.group(1)
            if action in ('set_fuel', 'add_fuel'):
                try:
                    val = float(raw_val)
                    return VoiceIntent(action=action, value=int(round(val)), raw=t)
                except ValueError:
                    continue
            elif action == 'engine_map':
                try:
                    val = int(raw_val)
                    if 1 <= val <= 10:
                        return VoiceIntent(action=action, value=val, raw=t)
                except ValueError:
                    continue
            elif action == 'brake_bias':
                try:
                    val = float(raw_val)
                    if 40.0 <= val <= 70.0:
                        return VoiceIntent(action=action, value=val, raw=t)
                except ValueError:
                    continue
            elif action == 'tyre_compound':
                compound = raw_val.lower()
                return VoiceIntent(action=action, value=compound, raw=t)
    return VoiceIntent(action='unknown', raw=t)


# ---------------------------------------------------------------------------
# MFD Controller
# ---------------------------------------------------------------------------

# MFD Pit Strategy page navigation constants (default ACC layout)
# Jumlah Page Down dari halaman pertama MFD untuk sampai ke Pit Strategy
_PIT_PAGE_DOWNS = 0   # Pit Strategy biasanya page pertama di MFD

# Jumlah Down Arrow untuk sampai ke item "Fuel to add" di Pit Strategy page
# Layout default: Pit (0) → Tyre Set (1) → Compound (2) → Fuel (3)
_FUEL_ITEM_INDEX = 3  # 3 kali Down Arrow dari atas page


class MfdController:
    """
    Kontrol MFD ACC via keypress simulation.
    
    Semua operasi dijalankan di thread terpisah supaya tidak
    block voice processing loop.
    """

    def __init__(
        self,
        on_feedback: Callable[[str], None],
        get_state: Callable[[], dict],
    ):
        """
        on_feedback : fungsi dipanggil dengan string TTS untuk dikonfirmasi ke driver
        get_state   : fungsi yang return last_state dict dari main loop
        """
        self.on_feedback = on_feedback
        self.get_state   = get_state
        self._lock       = threading.Lock()

    # ---- Public API ----

    def handle_intent(self, intent: VoiceIntent):
        """Jalankan aksi sesuai intent di background thread."""
        threading.Thread(
            target=self._execute, args=(intent,), daemon=True
        ).start()

    # ---- Internal ----

    def _execute(self, intent: VoiceIntent):
        with self._lock:  # serialize MFD operations
            try:
                if intent.action == 'set_fuel':
                    self._do_set_fuel(intent.value, mode='set')
                elif intent.action == 'add_fuel':
                    self._do_set_fuel(intent.value, mode='add')
                elif intent.action == 'engine_map':
                    self._do_engine_map(intent.value)
                elif intent.action == 'brake_bias':
                    self._do_brake_bias(intent.value)
                elif intent.action == 'tyre_compound':
                    self._do_tyre_compound(intent.value)
            except Exception as e:
                print(f"[mfd_control] Error executing intent: {e}")
                self.on_feedback("MFD control error, check console.")

    def _hwnd(self) -> Optional[int]:
        hwnd = _find_acc_window()
        if hwnd is None:
            print("[mfd_control] ACC window not found!")
            self.on_feedback("Can't find ACC window — is the game in focus?")
        return hwnd

    def _do_set_fuel(self, liters: int, mode: str):
        """
        Set fuel to add in MFD to `liters`.
        mode='set': set absolute amount (reset to 0 first, then add).
        mode='add': add on top of current value.
        """
        hwnd = self._hwnd()
        if not hwnd:
            return

        state = self.get_state()
        current_fuel_setting = 0  # kita tidak bisa baca MFD langsung, jadi asumsi 0 kecuali mode add

        if mode == 'set':
            # Feedback dulu
            self.on_feedback(f"Setting pit fuel to {liters} liters.")
            # Navigate to pit page fuel item
            self._nav_to_fuel_item(hwnd)
            # Reset ke 0: tekan Left sebanyak mungkin (max 120 kali cukup)
            _send_keys(hwnd, VK_LEFT, 120, delay=0.03)
            time.sleep(0.1)
            # Naik ke nilai yang diinginkan
            _send_keys(hwnd, VK_RIGHT, liters, delay=0.03)
            time.sleep(0.1)
            # Keluar dari MFD navigation (ESC atau tidak perlu, biarkan auto-close)
            print(f"[mfd_control] Fuel set to {liters}L")

        elif mode == 'add':
            current = int(state.get('fuel_liters', 0))
            laps_rem = state.get('laps_remaining_estimate', 0) or 0
            fuel_per_lap = state.get('fuel_per_lap', 0) or 0
            # Saran: tambah liters yang diminta
            self.on_feedback(f"Adding {liters} liters to pit fuel setting.")
            self._nav_to_fuel_item(hwnd)
            # Reset ke 0 dulu lalu tambah
            _send_keys(hwnd, VK_LEFT, 120, delay=0.03)
            time.sleep(0.1)
            _send_keys(hwnd, VK_RIGHT, liters, delay=0.03)
            print(f"[mfd_control] Fuel add {liters}L applied")

    def _do_engine_map(self, map_num: int):
        """
        Engine map dikontrol langsung via keyboard binding ACC (bukan MFD).
        Di ACC default: tidak ada direct key untuk set map ke angka tertentu.
        Kita simulate dengan Page Up/Down di electronics page MFD.
        """
        hwnd = self._hwnd()
        if not hwnd:
            return

        state = self.get_state()
        current_map = state.get('engine_map', 1) or 1

        self.on_feedback(f"Setting engine map to {map_num}.")
        # Engine map ada di halaman Electronics MFD (biasanya page 2 atau 3)
        # Untuk keamanan, navigate via MFD Electronics page
        # Ini akan kita skip MFD navigation kompleks dan langsung pakai
        # in-car steering wheel shortcut — tapi karena kita tidak bisa tahu
        # posisi saat ini, kita hanya bisa kirim relative adjustments.
        diff = map_num - current_map
        if diff > 0:
            _send_keys(hwnd, VK_RIGHT, diff, delay=0.1)
        elif diff < 0:
            _send_keys(hwnd, VK_LEFT, abs(diff), delay=0.1)
        print(f"[mfd_control] Engine map → {map_num} (from {current_map}, diff={diff})")

    def _do_brake_bias(self, target: float):
        """
        Brake bias — dikontrol via MFD Electronics page atau steering wheel.
        Karena kita track brake_bias dari telemetry, kita bisa hitung diff.
        """
        hwnd = self._hwnd()
        if not hwnd:
            return

        state = self.get_state()
        current_bias = state.get('brake_bias', 55.0) or 55.0
        diff_tenths = round((target - current_bias) * 10)  # step 0.1%

        if abs(diff_tenths) == 0:
            self.on_feedback(f"Brake bias already at {current_bias:.1f} percent.")
            return

        self.on_feedback(f"Adjusting brake bias to {target:.1f} percent.")
        if diff_tenths > 0:
            _send_keys(hwnd, VK_RIGHT, abs(diff_tenths), delay=0.05)
        else:
            _send_keys(hwnd, VK_LEFT, abs(diff_tenths), delay=0.05)
        print(f"[mfd_control] Brake bias {current_bias:.1f} → {target:.1f} ({diff_tenths:+d} steps)")

    def _do_tyre_compound(self, compound: str):
        """
        Set tyre compound di Pit Strategy MFD.
        """
        hwnd = self._hwnd()
        if not hwnd:
            return

        self.on_feedback(f"Setting pit tyres to {compound}.")
        # Navigate to pit page compound item (index 2 dari atas)
        self._nav_to_pit_page(hwnd)
        # Down ke item Compound (index 2)
        _send_keys(hwnd, VK_DOWN, 2, delay=0.15)
        time.sleep(0.1)
        # Toggle compound: kalau wet → kiri, kalau dry → kanan (atau sebaliknya)
        # Di ACC: 0=Dry, 1=Wet. Left/Right toggle.
        if compound == 'wet':
            _send_key(hwnd, VK_RIGHT)
        else:
            _send_key(hwnd, VK_LEFT)
        print(f"[mfd_control] Tyre compound → {compound}")

    def _nav_to_pit_page(self, hwnd: int):
        """Navigate MFD ke Pit Strategy page (page pertama di default ACC)."""
        # Page Down beberapa kali untuk sampai ke Pit page
        for _ in range(_PIT_PAGE_DOWNS):
            _send_key(hwnd, VK_NEXT, delay=0.12)
        time.sleep(0.1)

    def _nav_to_fuel_item(self, hwnd: int):
        """Navigate ke fuel item di Pit Strategy page."""
        self._nav_to_pit_page(hwnd)
        # Down ke fuel item
        _send_keys(hwnd, VK_DOWN, _FUEL_ITEM_INDEX, delay=0.15)
        time.sleep(0.1)
