import threading
import tempfile
import os
import numpy as np
import sounddevice as sd
import soundfile as sf
from pynput import keyboard
from typing import Callable

import config

class PttListener:
    def __init__(self, on_audio_ready: Callable[[str], None]):
        self.on_audio_ready = on_audio_ready
        self._recording = False
        self._stream = None
        self._frames = []
        self._listener = None
        self._sr = 16000

    def start(self):
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        print(f"[voice_input] Push-To-Talk ready. Tahan tombol '{config.PTT_KEY}' untuk bicara dengan AI Engineer.")

    def stop(self):
        if self._listener:
            self._listener.stop()

    def _on_press(self, key):
        if self._is_ptt_key(key):
            if not self._recording:
                self._recording = True
                self._frames = []
                print(f"[voice_input] Mendengarkan... (lepas '{config.PTT_KEY}' untuk mengirim)")
                try:
                    self._stream = sd.InputStream(samplerate=self._sr, channels=1, dtype='float32', callback=self._callback)
                    self._stream.start()
                except Exception as e:
                    print(f"[voice_input] Error buka mic: {e}")
                    self._recording = False

    def _on_release(self, key):
        if self._is_ptt_key(key):
            if self._recording:
                self._recording = False
                if self._stream:
                    self._stream.stop()
                    self._stream.close()
                    self._stream = None
                
                if self._frames:
                    audio_data = np.concatenate(self._frames, axis=0)
                    print(f"[voice_input] Selesai merekam. Frame terkumpul: {len(audio_data)}")
                    # Hanya proses kalau lebih dari 0.3 detik
                    if len(audio_data) > self._sr * 0.3:
                        fd, path = tempfile.mkstemp(suffix=".wav")
                        os.close(fd)
                        sf.write(path, audio_data, self._sr)
                        print(f"[voice_input] Audio disimpan ke {path}, mengirim ke AI...")
                        threading.Thread(target=self._dispatch, args=(path,), daemon=True).start()
                    else:
                        print("[voice_input] Audio terlalu pendek (kurang dari 0.3s), diabaikan.")
                else:
                    print("[voice_input] Tidak ada data audio terekam.")

    def _dispatch(self, path: str):
        try:
            self.on_audio_ready(path)
        except Exception as e:
            print(f"[voice_input] Error di dispatch callback: {e}")
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    def _callback(self, indata, frames, time, status):
        if status:
            print(f"[voice_input] mic status: {status}")
        if self._recording:
            self._frames.append(indata.copy())

    def _is_ptt_key(self, key):
        # Cek jika berupa tombol huruf/biasa
        try:
            if key.char and key.char.lower() == config.PTT_KEY.lower():
                return True
        except AttributeError:
            pass
            
        # Cek jika berupa tombol spesial (Shift, Ctrl, Alt, dll)
        try:
            if config.PTT_KEY.lower() in str(key).lower():
                return True
        except Exception:
            pass
            
        return False
