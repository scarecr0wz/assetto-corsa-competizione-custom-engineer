"""
Baca data dari ACC Shared Memory (data mobil sendiri): fuel, tyre temp,
brake temp, lap time, delta, cuaca/grip, gap ke depan/belakang (versi simple).

Shared Memory otomatis aktif begitu ACC running, gak perlu setting apapun
di game. Ini cuma jalan di Windows (nama named-memory pakai "Local\\...").
"""

from dataclasses import dataclass, field
from typing import Optional

from pyaccsharedmemory import accSharedMemory, ACC_map


@dataclass
class LocalSnapshot:
    connected: bool = False

    # Basic driving
    speed_kmh: float = 0.0
    gear: int = 0
    rpm: int = 0

    # Fuel
    fuel_liters: float = 0.0
    fuel_per_lap: float = 0.0
    fuel_estimated_laps: float = 0.0

    # Tyres & brakes (FL, FR, RL, RR)
    tyre_temp: tuple = (0, 0, 0, 0)
    brake_temp: tuple = (0, 0, 0, 0)
    rain_tyres: bool = False

    # Timing
    is_in_pit: bool = False
    is_in_pit_lane: bool = False
    completed_laps: int = 0
    current_lap_ms: int = 0
    last_lap_ms: int = 0
    best_lap_ms: int = 0
    delta_ms: int = 0
    is_valid_lap: bool = True
    position: int = 0
    current_sector_index: int = 0
    last_sector_time: int = 0
    
    # Session info
    session_time_left: float = 0.0
    pit_window_start: int = 0
    pit_window_end: int = 0
    
    # Setup Info
    tc_level: int = 0
    abs_level: int = 0
    engine_map: int = 0
    brake_bias: float = 0.0
    
    # Global flags (RCTRL)
    global_green: bool = False
    global_yellow: bool = False
    global_chequered: bool = False
    global_red: bool = False

    # Gap on-track (dari ACC langsung, satuan biasanya ms)
    gap_ahead_ms: int = 0
    gap_behind_ms: int = 0

    # Cuaca / grip
    track_grip_status: str = ""
    rain_intensity: str = ""
    air_temp: float = 0.0
    road_temp: float = 0.0

    # Info statis
    car_model: str = ""
    track: str = ""
    player_full_name: str = ""
    player_surname: str = ""
    session_type: str = ""
    status: str = ""
    flag: str = ""
    penalty_type: str = ""


class LocalTelemetryReader:
    def __init__(self):
        self._asm: Optional[accSharedMemory] = None

    def connect(self):
        self._asm = accSharedMemory()

    def close(self):
        if self._asm:
            self._asm.close()
            self._asm = None

    def read(self) -> Optional[LocalSnapshot]:
        """Return None kalau ACC belum jalan / belum ada data baru."""
        if self._asm is None:
            self.connect()

        try:
            data: Optional[ACC_map] = self._asm.read_shared_memory()
        except Exception:
            return None

        if data is None:
            return None

        p, g, s = data.Physics, data.Graphics, data.Static

        car_model = s.car_model.replace('\x00', '').strip().replace('_', ' ').title()
        track = s.track.replace('\x00', '').strip().title()
        p_name = s.player_name.replace('\x00', '').strip()
        p_surname = s.player_surname.replace('\x00', '').strip()

        return LocalSnapshot(
            connected=True,
            speed_kmh=p.speed_kmh,
            gear=p.gear,
            rpm=p.rpm,
            fuel_liters=p.fuel,
            fuel_per_lap=g.fuel_per_lap,
            fuel_estimated_laps=g.fuel_estimated_laps,
            tyre_temp=tuple(_wheels_to_tuple(p.tyre_core_temp)),
            brake_temp=tuple(_wheels_to_tuple(p.brake_temp)),
            rain_tyres=bool(g.rain_tyres),
            is_in_pit=bool(g.is_in_pit),
            is_in_pit_lane=bool(g.is_in_pit_lane),
            completed_laps=g.completed_lap,
            current_lap_ms=g.current_time,
            last_lap_ms=g.last_time,
            best_lap_ms=g.best_time,
            delta_ms=g.delta_lap_time,
            is_valid_lap=bool(g.is_valid_lap),
            position=g.position,
            
            session_time_left=getattr(g, 'session_time_left', 0),
            pit_window_start=getattr(s, 'pit_window_start', 0),
            pit_window_end=getattr(s, 'pit_window_end', 0),
            
            current_sector_index=getattr(g, 'current_sector_index', 0),
            last_sector_time=getattr(g, 'last_sector_time', 0),
            
            global_green=bool(getattr(g, 'global_green', False)),
            global_yellow=bool(getattr(g, 'global_yellow', False)),
            global_chequered=bool(getattr(g, 'global_chequered', False)),
            global_red=bool(getattr(g, 'global_red', False)),
            
            gap_ahead_ms=getattr(g, "gap_ahead", 0),
            gap_behind_ms=getattr(g, "gap_behind", 0),
            track_grip_status=_enum_name(g.track_grip_status),
            rain_intensity=_enum_name(g.rain_intensity),
            air_temp=p.air_temp,
            road_temp=p.road_temp,
            tc_level=getattr(g, 'tc_level', 0),
            abs_level=getattr(g, 'abs_level', 0),
            engine_map=getattr(g, 'engine_map', 0),
            brake_bias=getattr(p, 'brake_bias', 0.0),
            car_model=car_model,
            track=track,
            player_full_name=f"{p_name} {p_surname}".strip(),
            player_surname=p_surname,
            session_type=_enum_name(g.session_type),
            status=_enum_name(g.status),
            flag=_enum_name(getattr(g, 'flag', None) or ""),
            penalty_type=_enum_name(getattr(g, 'penalty_type', None) or ""),
        )


def _wheels_to_tuple(w) -> tuple:
    # pyaccsharedmemory punya class Wheels dgn atribut front_left, front_right, rear_left, rear_right
    return (w.front_left, w.front_right, w.rear_left, w.rear_right)


def _enum_name(value) -> str:
    return getattr(value, "name", str(value))
