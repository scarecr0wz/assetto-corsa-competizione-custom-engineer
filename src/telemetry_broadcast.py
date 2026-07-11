"""
Konek ke ACC Broadcasting API (UDP) buat dapetin data SEMUA mobil di sesi:
posisi, nama driver, lap time lawan, delta antar mobil, dsb.

Prasyarat di ACC:
  Documents\\Assetto Corsa Competizione\\Config\\broadcasting.json
  -> isi "connectionPassword" (bebas, terserah kamu), sesuaikan config.py

Pakai package `accapi` (community wrapper, MIT/Apache, murni UDP client -
tidak memodifikasi game sama sekali, cuma nerima data yang ACC broadcast).
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from accapi.client import AccClient, Event

import config


@dataclass
class CarState:
    car_index: int = -1
    driver_name: str = ""
    team_name: str = ""
    race_number: int = 0
    position: int = 0
    cup_position: int = 0
    laps: int = 0
    location: str = ""
    kmh: float = 0.0
    delta_ms: int = 0
    last_lap_ms: Optional[int] = None
    best_lap_ms: Optional[int] = None
    last_lap_valid: bool = True


class BroadcastReader:
    """
    Jalan di background thread (accapi sudah pakai thread sendiri utk
    socket, ini cuma nyimpen state terakhir biar gampang di-query dari
    main loop tanpa perlu nunggu callback).
    """

    def __init__(self):
        self.client = AccClient()
        self.track_name: str = ""
        self.session_type: str = ""
        self.player_car_index: Optional[int] = None
        self.cars: Dict[int, CarState] = {}
        self._entry_names: Dict[int, str] = {}
        self._connected = threading.Event()
        self._lock = threading.Lock()

        self.client.onConnectionStateChange.subscribe(self._on_connection)
        self.client.onTrackDataUpdate.subscribe(self._on_track_data)
        self.client.onEntryListCarUpdate.subscribe(self._on_entry_list_car)
        self.client.onRealtimeUpdate.subscribe(self._on_realtime_update)
        self.client.onRealtimeCarUpdate.subscribe(self._on_realtime_car_update)

    # ---- lifecycle ----

    def connect(self, timeout_sec: float = 5.0) -> bool:
        self.client.start(
            config.ACC_HOST,
            config.ACC_PORT,
            config.ACC_CONNECTION_PASSWORD,
            commandPassword=config.ACC_COMMAND_PASSWORD,
            displayName=config.ACC_DISPLAY_NAME,
            updateIntervalMs=config.ACC_UPDATE_INTERVAL_MS,
        )
        return self._connected.wait(timeout=timeout_sec)

    def close(self):
        try:
            self.client.stop()
        except Exception:
            pass

    # ---- callbacks (dipanggil dari thread accapi) ----

    def _on_connection(self, event: Event):
        if event.content == "connected":
            self._connected.set()
        elif event.content in ("disconnected", "lost"):
            self._connected.clear()

    def _on_track_data(self, event: Event):
        self.track_name = event.content.trackName

    def _on_entry_list_car(self, event: Event):
        car = event.content
        driver = ""
        if car.drivers:
            d = car.drivers[car.currentDriverIndex] if car.currentDriverIndex < len(car.drivers) else car.drivers[0]
            driver = f"{d.firstName} {d.lastName}".strip()
        with self._lock:
            self._entry_names[car.carIndex] = driver
            state = self.cars.setdefault(car.carIndex, CarState(car_index=car.carIndex))
            state.driver_name = driver
            state.team_name = car.teamName
            state.race_number = car.raceNumber

    def _on_realtime_update(self, event: Event):
        self.session_type = event.content.sessionType

    def _on_realtime_car_update(self, event: Event):
        u = event.content
        with self._lock:
            state = self.cars.setdefault(u.carIndex, CarState(car_index=u.carIndex))
            state.driver_name = self._entry_names.get(u.carIndex, state.driver_name)
            state.position = u.position
            state.cup_position = u.cupPosition
            state.laps = u.laps
            state.location = u.location
            state.kmh = u.kmh
            state.delta_ms = u.delta
            if u.lastLap and u.lastLap.lapTimeMs not in (None, 0, 2147483647):
                state.last_lap_ms = u.lastLap.lapTimeMs
                state.last_lap_valid = bool(u.lastLap.isValidForBest)
            if u.bestSessionLap and u.bestSessionLap.lapTimeMs not in (None, 0, 2147483647):
                state.best_lap_ms = u.bestSessionLap.lapTimeMs

    # ---- query helper buat main loop ----

    def identify_player_car(self, player_full_name: str) -> Optional[int]:
        """Cocokkan nama pemain (dari Shared Memory) dgn entry list broadcast,
        biar tau carIndex kita sendiri -> jadi bisa cari 'mobil di depan/belakang'."""
        if not player_full_name:
            return None
        with self._lock:
            for idx, name in self._entry_names.items():
                if name and player_full_name.lower() in name.lower():
                    self.player_car_index = idx
                    return idx
        return None

    def car_ahead_behind(self):
        """Return (car_ahead: CarState|None, car_behind: CarState|None) relatif posisi finish."""
        if self.player_car_index is None:
            return None, None
        with self._lock:
            me = self.cars.get(self.player_car_index)
            if not me:
                return None, None
            ahead = behind = None
            for c in self.cars.values():
                if c.car_index == self.player_car_index:
                    continue
                if c.position == me.position - 1:
                    ahead = c
                elif c.position == me.position + 1:
                    behind = c
            return ahead, behind
