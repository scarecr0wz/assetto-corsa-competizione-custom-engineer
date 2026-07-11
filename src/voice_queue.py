"""
Text-to-speech using edge-tts (Microsoft neural voice) with a radio
effect chain applied via numpy + scipy:
  - Bandpass filter 300-3400 Hz (telephone/radio range)
  - Mild soft-clip saturation
  - Light white-noise static layer
  - Normalisation to -3 dBFS
  - Playback via sounddevice (uses Windows default audio device)

Priority queue:
  priority 0 = urgent (fuel critical etc.)   -> always first
  priority 1 = normal (overtake, tyre hot etc.)
  priority 2 = banter/idle chat              -> dropped if queue backs up
"""

import asyncio
import io
import queue
import random
import subprocess
import threading

import config

# ---------------------------------------------------------------------------
# Voice selection
# Change TTS_VOICE_HINT in config.py to any Edge TTS voice, e.g.:
#   "en-GB-RyanNeural"   British male  (default)
#   "en-US-GuyNeural"    American male
#   "en-AU-WilliamNeural" Australian male
# ---------------------------------------------------------------------------
_DEFAULT_VOICE = "en-GB-RyanNeural"


def _get_voice() -> str:
    hint = getattr(config, "TTS_VOICE_HINT", "")
    return hint if hint else _DEFAULT_VOICE


# ---------------------------------------------------------------------------
# Radio effect chain  (numpy + scipy)
# ---------------------------------------------------------------------------
def _apply_radio_effect(samples, sr: int):
    """
    samples : numpy float32 array, range [-1, 1], any number of channels
    sr      : sample rate (Hz)
    Returns : processed float32 array (mono), same sr
    """
    import numpy as np
    from scipy import signal

    # Mix to mono
    if samples.ndim > 1:
        samples = samples.mean(axis=1)

    # 1. Bandpass 300-3400 Hz  (typical radio/walkie-talkie range)
    nyq = sr / 2.0
    low = 300 / nyq
    high = min(3400 / nyq, 0.99)
    b, a = signal.butter(4, [low, high], btype="band")
    samples = signal.filtfilt(b, a, samples).astype(np.float32)

    # 2. Soft-clip saturation (tanh gives warm analogue-style distortion)
    drive = 3.0          # how hard to drive into saturation
    samples = np.tanh(samples * drive) / np.tanh(drive)

    # 3. White noise static  (very quiet — -32 dB relative to full scale)
    noise_level = 10 ** (-32 / 20)
    noise = (np.random.randn(len(samples)) * noise_level).astype(np.float32)
    samples = samples + noise

    # 4. Normalise to -3 dBFS
    peak = np.max(np.abs(samples))
    if peak > 0:
        target = 10 ** (-3 / 20)
        samples = samples * (target / peak)

    # 5. Synthesize Mic Clicks (radio beeps) at start and end
    # Beep is a ~1200 Hz sine wave for 50ms with a sharp decay
    t_beep = np.linspace(0, 0.05, int(sr * 0.05), endpoint=False)
    envelope = np.exp(-15 * t_beep)  # sharp decay for a "clicky" beep
    beep = (np.sin(2 * np.pi * 1200 * t_beep) * envelope * 0.3).astype(np.float32)
    
    # Silence gap
    silence = np.zeros(int(sr * 0.05), dtype=np.float32)
    
    # Prepend and append beep
    samples = np.concatenate([beep, silence, samples, silence, beep]).astype(np.float32)

    return samples


# ---------------------------------------------------------------------------
# Async edge-tts synthesis → raw MP3 bytes
# ---------------------------------------------------------------------------
async def _synthesize(text: str, voice: str) -> bytes:
    import edge_tts
    buf = io.BytesIO()
    # Convert WPM from config to edge-tts rate offset
    # edge-tts baseline ~150 wpm. config.TTS_RATE default=185 → about +23%
    wpm = getattr(config, "TTS_RATE", 185)
    rate_pct = int(round((wpm / 150.0 - 1.0) * 100))
    rate_str = f"{rate_pct:+d}%"
    communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch="+5Hz")
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Decode MP3 bytes → numpy float32 array via ffmpeg
# ---------------------------------------------------------------------------
def _mp3_to_numpy(mp3_bytes: bytes):
    import numpy as np

    cmd = [
        "ffmpeg", "-loglevel", "quiet",
        "-f", "mp3", "-i", "pipe:0",
        "-f", "f32le", "-ac", "1",
        "-ar", "22050",
        "pipe:1"
    ]
    proc = subprocess.run(cmd, input=mp3_bytes,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    raw = proc.stdout
    if not raw:
        return None, 22050
    samples = np.frombuffer(raw, dtype=np.float32).copy()
    return samples, 22050


# ---------------------------------------------------------------------------
# Play float32 PCM via sounddevice (uses Windows default output device)
# ---------------------------------------------------------------------------
def _play_f32(samples, sr: int):
    import sounddevice as sd
    import numpy as np
    sd.play(samples.astype(np.float32), samplerate=sr)
    sd.wait()


# ---------------------------------------------------------------------------
# Full pipeline: synthesise → decode → radio FX → play
# ---------------------------------------------------------------------------
def _speak(text: str, voice: str):
    mp3_bytes = asyncio.run(_synthesize(text, voice))
    if not mp3_bytes:
        return

    samples, sr = _mp3_to_numpy(mp3_bytes)
    if samples is None:
        return

    processed = _apply_radio_effect(samples, sr)
    _play_f32(processed, sr)


# ---------------------------------------------------------------------------
# VoiceQueue — same priority-queue interface as before
# ---------------------------------------------------------------------------
class VoiceQueue:
    def __init__(self):
        self._q: "queue.PriorityQueue" = queue.PriorityQueue()
        self._counter = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._q.put((-1, 0, 0, None))  # unblock

    def say(self, text: str, priority: int = 1):
        # Drop banter if queue is backing up
        if priority >= 2 and self._q.qsize() >= 2:
            return
        self._counter += 1
        import time
        self._q.put((priority, time.time(), self._counter, text))

    def _run(self):
        import time
        voice = _get_voice()
        print(f"[voice_queue] Using Edge TTS voice: {voice} (with radio effect)")
        while not self._stop.is_set():
            item = self._q.get()
            if len(item) == 4:
                priority, timestamp, _, text = item
            else:
                priority, _, text = item
                timestamp = 0

            if text is None:
                break
                
            # If not urgent (priority > 0) and the message is older than 7 seconds, drop it to avoid delay/stacking
            if priority > 0 and timestamp > 0 and (time.time() - timestamp > 7.0):
                print(f"[voice_queue] (Dropped late message): {text}")
                continue
                
            print(f"[Engineer] {text}")
            try:
                if not text or len(text.strip()) < 4:
                    continue  # skip empty / dot-only strings
                _speak(text, voice)
            except Exception as e:
                print(f"[voice_queue] TTS error: {e}")
