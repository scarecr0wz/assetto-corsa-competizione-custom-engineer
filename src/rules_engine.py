"""
Rule-based brain for time-critical events (fuel, tyres, overtakes, race start,
pit window, flags, track limits, weather, etc.). Responses are instant — no LLM wait.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

import config
import personality as p

TYRE_NAMES = ["FL", "FR", "RL", "RR"]

# Actual ACC enum names returned by _enum_name()
_LIVE_STATUS   = {"ACC_LIVE", "LIVE"}
_OFF_STATUS    = {"ACC_OFF",  "OFF", ""}
_RACE_SESSIONS = {"ACC_RACE", "RACE", "RACE2", "RACE3", "HOTSTINT"}

# ACC flag enum names (from pyaccsharedmemory ACC_FLAG_TYPE)
_YELLOW_FLAGS    = {"ACC_YELLOW_FLAG",  "YELLOW_FLAG",  "FULL_COURSE_YELLOW"}
_BLUE_FLAGS      = {"ACC_BLUE_FLAG",    "BLUE_FLAG"}
_WHITE_FLAGS     = {"ACC_WHITE_FLAG",   "WHITE_FLAG"}
_CHECKERED_FLAGS = {"ACC_CHECKERED_FLAG", "CHECKERED_FLAG"}
_PENALTY_FLAGS   = {"ACC_PENALTY_FLAG", "PENALTY_FLAG",
                    "STOP_AND_GO", "STOP_AND_GO_10", "STOP_AND_GO_20",
                    "STOP_AND_GO_30", "DRIVE_THROUGH"}

# ACC rain intensity enum names
_WET_VALUES = {"ACC_DRIZZLE", "ACC_LIGHT_RAIN", "ACC_MEDIUM_RAIN",
               "ACC_HEAVY_RAIN", "ACC_THUNDERSTORM",
               "DRIZZLE", "LIGHT_RAIN", "MEDIUM_RAIN",
               "HEAVY_RAIN", "THUNDERSTORM"}
_HEAVY_RAIN  = {"ACC_HEAVY_RAIN", "ACC_THUNDERSTORM", "HEAVY_RAIN", "THUNDERSTORM"}


@dataclass
class Message:
    text: str
    priority: int  # 0 = urgent, 1 = normal, 2 = banter/low
    category: str


class RulesEngine:
    def __init__(self):
        self._last_fired:       dict[str, float] = {}
        self._last_position:    Optional[int]    = None
        self._last_best_lap_ms: Optional[int]    = None
        self._last_rain_value:  str              = ""
        self._last_status:      str              = ""
        self._last_flag:        str              = ""
        self._last_lap_valid:   bool             = True
        self._last_in_pit_lane: bool             = False
        self._race_started:     bool             = False
        self._session_started:  bool             = False
        self._last_global_green: bool            = False
        self._last_global_yellow: bool           = False
        self._last_global_chequered: bool        = False
        self._last_global_red: bool              = False
        self._pit_window_open:  bool             = False
        self._track_limits_count: int            = 0
        self._rival_pit_status: dict[int, bool]  = {}
        self._last_penalty: str                  = ""
        self._last_completed_laps: int           = 0
        
        self._best_sector_times: dict[int, int]  = {}
        self._last_sector_index: int             = -1

        # Driver swap tracking
        self._current_driver_surname: str        = ""
        self._current_driver_full: str           = ""

        # Session time countdown callouts (ms thresholds, counted DOWN)
        # We fire when session_time_left crosses below each mark.
        _MINS = 60_000
        self._time_callout_marks: list[int] = [
            30 * _MINS, 15 * _MINS, 10 * _MINS, 5 * _MINS, 1 * _MINS
        ]
        self._time_callouts_fired: set[int]      = set()
        self._last_chequered_fired: bool         = False

        # Gap trend tracking (catching / pulling away)
        self._gap_ahead_history: list[float]     = []  # last N gap values
        self._gap_trend_laps: int                = 0   # laps since trend last fired

        # Lap consistency tracking
        self._recent_lap_times: list[int]        = []  # last 5 valid lap ms
        self._consistency_fired_lap: int         = -1

        # Gap to leader tracking
        self._last_leader_gap_lap: int           = 0

        # Out-lap coaching (after pit exit)
        self._out_lap_active: bool               = False
        self._out_lap_laps_done: int             = 0

    def _cooldown_ok(self, key: str, sec: float = None) -> bool:
        now = time.time()
        cooldown = sec if sec is not None else config.COOLDOWN_SAME_EVENT_SEC
        last = self._last_fired.get(key, 0)
        if now - last >= cooldown:
            self._last_fired[key] = now
            return True
        return False

    def evaluate(self, local, ahead=None, behind=None) -> list[Message]:
        msgs: list[Message] = []
        if local is None or not local.connected:
            return msgs

        session = local.session_type.upper()
        in_race = any(r in session for r in _RACE_SESSIONS)
        pre_race = in_race and not self._race_started  # formation lap / grid

        # --- Always run: session welcome + race start detection ---
        msgs += self._check_session_start(local)
        msgs += self._check_race_start(local)

        if pre_race:
            # Before green flag: suppress all race-specific messages.
            # Still run state-syncing checks silently (no output) so stale
            # events don't burst the moment racing begins.
            self._check_flags(local)       # sync flag state only
            self._check_position(local)    # sync position state only
            self._check_penalties(local)   # sync penalty state only
            self._check_weather(local)     # rain warning IS relevant pre-race
            # Everything else: skip entirely
        else:
            # Normal running — full checks
            msgs += self._check_flags(local)
            msgs += self._check_fuel(local)
            msgs += self._check_tyres(local)
            msgs += self._check_brakes(local)
            msgs += self._check_delta(local)
            msgs += self._check_new_best(local)
            msgs += self._check_position(local)
            msgs += self._check_weather(local)
            msgs += self._check_track_limits(local)
            msgs += self._check_penalties(local)
            msgs += self._check_lap_summary(local)
            msgs += self._check_sector_times(local)
            msgs += self._check_pit_status(local)
            msgs += self._check_pit_window(local)
            msgs += self._check_rivals(ahead, behind)
            msgs += self._check_session_time(local)
            msgs += self._check_gap_trend(local)
            msgs += self._check_lap_consistency(local)
            msgs += self._check_gap_to_leader(local)
            msgs += self._check_out_lap(local)

        
        # Keep _current_driver_surname in sync on every tick.
        # On first run (or after reset) it won't be set yet, so seed it from
        # the live snapshot. After a driver swap, _check_pit_status already
        # updated it to the NEW driver's name — don't override with old data.
        snap_surname = local.player_surname.strip() if local.player_surname else ""
        snap_full    = local.player_full_name.strip() if local.player_full_name else ""
        if snap_surname and not self._current_driver_surname:
            # First initialization only
            self._current_driver_surname = snap_surname
            self._current_driver_full    = snap_full

        # Sprinkle driver's name occasionally for immersion.
        # Use the TRACKED name (correctly updated on driver swap) — NOT raw shared
        # memory which may reflect the host player profile, not the current driver.
        name = self._current_driver_surname or (
            self._current_driver_full.split()[-1] if self._current_driver_full else ""
        )
        # Ultimate fallback: live snapshot (covers edge case before first swap tracking)
        if not name:
            name = snap_surname or (snap_full.split()[-1] if snap_full else "")
            
        if name and msgs:
            import random
            for msg in msgs:
                # 40% chance to inject name if not already in message
                if random.random() < 0.4 and name.lower() not in msg.text.lower() \
                        and msg.category not in ("session_start", "driver_swap"):
                    if random.random() < 0.5:
                        # Prepend (e.g. "Auer, box this lap.")
                        msg.text = f"{name}, {msg.text[0].lower()}{msg.text[1:]}"
                    else:
                        # Append (e.g. "Box this lap, Auer.")
                        if msg.text.endswith('.') or msg.text.endswith('!'):
                            punct = msg.text[-1]
                            msg.text = f"{msg.text[:-1]}, {name}{punct}"
                        else:
                            msg.text = f"{msg.text}, {name}."

        return msgs

    # ---- individual checks ----

    def _check_session_start(self, l) -> list[Message]:
        out = []

        # --- Detect IN-GAME session restart ---
        # When player restarts a race from the pause menu, completed_laps drops
        # back to 0 while the session is still LIVE (car/track strings stay populated).
        # Use > 3 as threshold to avoid false positives at the very start of a session.
        if self._session_started and l.completed_laps == 0 and self._last_completed_laps > 3:
            self._session_started = False
            self._race_started = False
            self._last_completed_laps = 0
            self._current_driver_surname = ""
            self._current_driver_full = ""
            # Fall through so the welcome block below re-fires immediately

        # If we have just entered a valid session from offline (or post-restart)
        if not self._session_started and (l.status in _LIVE_STATUS or l.status in _OFF_STATUS):
            car_model = l.car_model.strip() if l.car_model else ""
            track = l.track.strip() if l.track else ""
            surname = l.player_surname.strip() if l.player_surname else ""
            full_name = l.player_full_name.strip() if l.player_full_name else ""
            
            # Only greet if we actually have data (speed, gear, etc. might still be parsing)
            if len(car_model) > 1 and len(track) > 1:
                self._session_started = True
                # Record the starting driver
                self._current_driver_surname = surname
                self._current_driver_full = full_name
                
                name_to_use = surname if surname else full_name
                name_part = f", {name_to_use}" if name_to_use else ""
                
                out.append(Message(
                    f"Radio check. Welcome to {track}{name_part}. We're running the {car_model}.",
                    1, "session_start"
                ))
        
        # Reset FULLY when game goes offline/disconnected — so a script restart
        # (or reconnect) fires the welcome greeting fresh again.
        if self._session_started and not l.car_model and not l.track:
            self._session_started = False
            self._race_started = False
            self._current_driver_surname = ""
            self._current_driver_full = ""
            
        return out

    def _check_race_start(self, l) -> list[Message]:
        out  = []
        status  = l.status.upper()
        session = l.session_type.upper()
        in_race = any(r in session for r in _RACE_SESSIONS)

        # Race Start based on Global Green flag transitioning to True
        if in_race and status in _LIVE_STATUS:
            if l.global_green and not self._last_global_green and not self._race_started:
                self._race_started = True
                out.append(Message(
                    "Green green green! Go go go, push hard!",
                    0, "race_start"
                ))
            
            # Restart after FCY or Red flag
            elif l.global_green and not self._last_global_green and self._race_started:
                if self._cooldown_ok("green_flag", sec=60):
                    out.append(Message("We are green! Back to racing speed.", 0, "flag"))

        self._last_global_green = l.global_green

        # Reset when session ends / goes off
        if status in _OFF_STATUS:
            self._race_started = False
            self._last_global_green = False

        self._last_status = status
        return out

    def _check_flags(self, l) -> list[Message]:
        out  = []
        if l.status.upper() not in _LIVE_STATUS:
            # Sync last states quietly so they don't fire when we transition to LIVE
            self._last_global_yellow = l.global_yellow
            self._last_global_chequered = l.global_chequered
            self._last_global_red = l.global_red
            return out
            
        flag = l.flag.upper().strip() if l.flag else ""
        
        # Use accurate RCTRL global flags
        if l.global_yellow and not self._last_global_yellow:
            if self._cooldown_ok("flag_yellow", sec=30):
                out.append(Message(
                    "Yellow flag! Slow down, no overtaking, stay alert.",
                    0, "flag"
                ))
        self._last_global_yellow = l.global_yellow
        
        if l.global_chequered and not self._last_global_chequered:
            out.append(Message(
                "Checkered flag! Good job, bring it home safely.",
                0, "flag"
            ))
        self._last_global_chequered = l.global_chequered
        
        session = l.session_type.upper()
        in_race = any(r in session for r in _RACE_SESSIONS)
        is_formation_lap = in_race and not self._race_started
        
        if l.global_red and not self._last_global_red:
            # Suppress red flag if we are on the formation lap (ACC grid state)
            if not is_formation_lap:
                out.append(Message("Red flag! Session stopped, reduce speed and return to pits.", 0, "flag"))
        self._last_global_red = l.global_red

        if flag == self._last_flag:
            self._last_flag = flag
        else:
            self._last_flag = flag
            if any(f in flag for f in ("BLUE",)):
                if self._cooldown_ok("flag_blue", sec=20):
                    out.append(Message(
                        "Blue flag! Let them past, don't fight it.",
                        1, "flag"
                    ))
            elif any(f in flag for f in ("PENALTY", "STOP_AND_GO", "DRIVE_THROUGH")):
                if self._cooldown_ok("flag_penalty", sec=30):
                    out.append(Message(
                        "Penalty incoming! Check your MFD and serve it when instructed.",
                        0, "flag"
                    ))

        # Penalty from penalty_type field as backup
        penalty = (l.penalty_type or "").upper().strip()
        if penalty and penalty not in ("NO_PENALTY", "NONE", "ACC_NONE", "") \
                and self._cooldown_ok("penalty_type", sec=30):
            out.append(Message(
                "Penalty on the car! Check the MFD, sort it out.",
                0, "flag"
            ))

        return out

    def _check_fuel(self, l) -> list[Message]:
        out = []
        laps_left = l.fuel_estimated_laps
        if laps_left <= 0:
            return out
        if laps_left <= config.FUEL_LAPS_CRITICAL and self._cooldown_ok("fuel_critical", sec=30):
            msg = p.pick(p.FUEL_CRITICAL, laps=laps_left)
            # Add engine map suggestion if on a presumably high-power map (0 or 1)
            if l.engine_map in (0, 1):
                msg += " Switch to a lean engine map to save fuel."
            out.append(Message(msg, 0, "fuel"))
        elif laps_left <= config.FUEL_LAPS_WARNING and self._cooldown_ok("fuel_warning", sec=120):
            out.append(Message(p.pick(p.FUEL_WARNING, laps=laps_left), 1, "fuel"))
        return out

    def _check_tyres(self, l) -> list[Message]:
        out = []
        if l.speed_kmh < 20 or l.is_in_pit or l.is_in_pit_lane:
            return out
        fired_cold = False
        for name, temp in zip(TYRE_NAMES, l.tyre_temp):
            if temp <= 1:
                continue
            key = f"tyre_{name}"
            if temp > config.TYRE_TEMP_MAX_C and self._cooldown_ok(key + "_hot", sec=45):
                out.append(Message(p.pick(p.TYRE_HOT, tyre=name, temp=temp), 1, "tyre"))
            elif temp < config.TYRE_TEMP_MIN_C and not fired_cold \
                    and self._cooldown_ok("tyre_cold_any", sec=120):
                out.append(Message(p.pick(p.TYRE_COLD, tyre=name, temp=temp), 2, "tyre"))
                fired_cold = True
        return out

    def _check_brakes(self, l) -> list[Message]:
        out = []
        if l.speed_kmh < 20 or l.is_in_pit:
            return out
        for name, temp in zip(TYRE_NAMES, l.brake_temp):
            if temp <= 1:
                continue
            if temp > config.BRAKE_TEMP_MAX_C and self._cooldown_ok(f"brake_{name}"):
                out.append(Message(p.pick(p.BRAKE_HOT, corner=name, temp=temp), 1, "brake"))
        return out

    def _check_delta(self, l) -> list[Message]:
        out = []
        if l.delta_ms == 0 or l.current_lap_ms < 5000 or l.is_in_pit or l.is_in_pit_lane:
            return out
        delta_sec = l.delta_ms / 1000.0
        if delta_sec <= config.DELTA_GOOD_SEC and self._cooldown_ok("delta_good", sec=120):
            out.append(Message(p.pick(p.DELTA_GOOD, delta=delta_sec), 2, "delta"))
        elif delta_sec >= abs(config.DELTA_GOOD_SEC) * 3 and self._cooldown_ok("delta_bad", sec=120):
            out.append(Message(p.pick(p.DELTA_BAD, delta=delta_sec), 2, "delta"))
        return out

    def _check_new_best(self, l) -> list[Message]:
        out = []
        if l.best_lap_ms and l.best_lap_ms != self._last_best_lap_ms:
            if self._last_best_lap_ms is not None:
                out.append(Message(
                    p.pick(p.NEW_BEST_LAP, time=_fmt_ms(l.best_lap_ms)), 1, "lap"))
            self._last_best_lap_ms = l.best_lap_ms
        return out

    def _check_position(self, l) -> list[Message]:
        out = []
        if l.position <= 0:
            return out
        # Suppress position change noise while in pit box or pit lane
        if l.is_in_pit or l.is_in_pit_lane:
            self._last_position = l.position  # track silently
            return out
        if self._last_position is not None and l.position != self._last_position:
            if l.position < self._last_position and self._cooldown_ok("pos_gain", sec=5):
                out.append(Message(p.pick(p.POSITION_GAINED, position=l.position), 1, "position"))
            elif l.position > self._last_position and self._cooldown_ok("pos_lose", sec=5):
                out.append(Message(p.pick(p.POSITION_LOST,   position=l.position), 1, "position"))
        self._last_position = l.position
        return out

    def _check_weather(self, l) -> list[Message]:
        out  = []
        rain = l.rain_intensity.upper().strip() if l.rain_intensity else ""
        is_wet    = rain in _WET_VALUES
        is_heavy  = rain in _HEAVY_RAIN
        rain_changed = rain != self._last_rain_value
        self._last_rain_value = rain

        if is_wet and rain_changed:
            if is_heavy and self._cooldown_ok("rain_heavy", sec=60):
                out.append(Message(
                    "Heavy rain out there! Brake early, stay smooth, don't push the limits.",
                    0, "weather"
                ))
            elif not is_heavy and self._cooldown_ok("rain", sec=60):
                out.append(Message(p.pick(p.RAIN_INCOMING), 1, "weather"))
        return out

    def _check_track_limits(self, l) -> list[Message]:
        out    = []
        status = l.status.upper()
        # Only during a live session, and car is actually moving
        if status in _LIVE_STATUS and l.speed_kmh > 30:
            if not l.is_valid_lap and self._last_lap_valid:
                self._track_limits_count += 1
                if self._cooldown_ok("track_limit", sec=10):
                    if self._track_limits_count == 1:
                        out.append(Message("Track limits. Keep it inside the white lines.", 1, "track_limit"))
                    elif self._track_limits_count == 2:
                        out.append(Message("Track limits again! Second warning, tidy it up.", 1, "track_limit"))
                    elif self._track_limits_count == 3:
                        out.append(Message("Track limits, third time! One more and it's a penalty.", 0, "track_limit"))
                    else:
                        out.append(Message("Track limits! The stewards are watching closely.", 0, "track_limit"))
                        
        self._last_lap_valid = l.is_valid_lap
        
        # Reset counter if session changes
        if status in _OFF_STATUS:
            self._track_limits_count = 0
            
        return out

    def _check_penalties(self, l) -> list[Message]:
        out = []
        penalty = (l.penalty_type or "").upper().strip()
        no_penalty = penalty in ("", "NO_PENALTY", "NONE", "ACC_NONE")
        
        if not no_penalty and penalty != self._last_penalty:
            if "DRIVE_THROUGH" in penalty:
                out.append(Message(
                    "Drive-through penalty! Serve it as soon as possible, don't stack more laps.",
                    0, "penalty"
                ))
            elif "STOP_AND_GO" in penalty:
                seconds = ""
                for s in ["10", "20", "30"]:
                    if s in penalty:
                        seconds = f" {s}-second"
                        break
                out.append(Message(
                    f"Stop-and-go{seconds} penalty! Box this lap and serve it, no excuses.",
                    0, "penalty"
                ))
            elif "WARNING" in penalty or "CUT" in penalty:
                out.append(Message(
                    "Track limit warning from the stewards. Keep it clean or we'll get a penalty.",
                    0, "penalty"
                ))
            else:
                out.append(Message(
                    f"We have a penalty \u2014 check the MFD and serve it immediately.",
                    0, "penalty"
                ))
        
        self._last_penalty = penalty if not no_penalty else self._last_penalty
        # Clear last penalty when penalty goes away
        if no_penalty:
            self._last_penalty = ""
            
        return out

    def _check_sector_times(self, l) -> list[Message]:
        out = []
        if l.status.upper() not in _LIVE_STATUS:
            return out
            
        if self._last_sector_index == -1:
            self._last_sector_index = l.current_sector_index
            
        if l.current_sector_index != self._last_sector_index:
            completed_sector = self._last_sector_index
            sector_time = l.last_sector_time
            
            if sector_time > 0 and l.is_valid_lap:
                best = self._best_sector_times.get(completed_sector)
                if best is None or sector_time < best:
                    self._best_sector_times[completed_sector] = sector_time
                else:
                    diff_ms = sector_time - best
                    # Jika lebih lambat 200ms (2 tenths)
                    if diff_ms > 200 and self._cooldown_ok(f"sector_{completed_sector}_slow", sec=60):
                        tenths = diff_ms // 100
                        out.append(Message(
                            f"You're bleeding {tenths} tenths in Sector {completed_sector + 1}. Tidy it up.",
                            1, "sector"
                        ))
                        
            self._last_sector_index = l.current_sector_index
            
        return out

    def _check_lap_summary(self, l) -> list[Message]:
        """Give a concise lap summary every few laps like a real engineer."""
        out = []
        if l.completed_laps <= 0 or l.completed_laps == self._last_completed_laps:
            self._last_completed_laps = max(l.completed_laps, self._last_completed_laps)
            return out
        
        self._last_completed_laps = l.completed_laps
        
        # Only every 5 laps to avoid spam, or on first completed lap
        if l.completed_laps == 1 or (l.completed_laps % 5 == 0 and self._cooldown_ok("lap_summary", sec=60)):
            parts = []
            
            if l.last_lap_ms and l.last_lap_ms > 0:
                parts.append(f"Last lap {_fmt_ms(l.last_lap_ms)}")
            
            if l.fuel_estimated_laps > 0:
                parts.append(f"fuel for {l.fuel_estimated_laps:.1f} laps")
            
            tyre_avg = sum(l.tyre_temp) / len(l.tyre_temp) if any(l.tyre_temp) else 0
            if tyre_avg > 0:
                parts.append(f"tyres {tyre_avg:.0f} degrees")
            
            if parts:
                summary = ". ".join(parts) + "."
                out.append(Message(f"Lap {l.completed_laps} done. {summary}", 2, "lap_summary"))
        
        return out

    def _check_pit_status(self, l) -> list[Message]:
        out = []
        # Fire ONCE on entry transition (False → True)
        if l.is_in_pit_lane and not self._last_in_pit_lane:
            out.append(Message(
                "Pit lane speed limit, keep it on the limiter.",
                0, "pit"
            ))
        # Fire ONCE on exit transition (True → False) — go go go!
        elif not l.is_in_pit_lane and self._last_in_pit_lane:
            if l.speed_kmh > 10:  # actually leaving, not just a data glitch
                # Detect driver swap: compare surname (most reliable unique field)
                new_surname = l.player_surname.strip() if l.player_surname else ""
                new_full    = l.player_full_name.strip() if l.player_full_name else ""
                driver_changed = (
                    new_surname and self._current_driver_surname
                    and new_surname.lower() != self._current_driver_surname.lower()
                )

                if driver_changed:
                    # Welcome the incoming driver
                    name_to_use = new_surname if new_surname else new_full
                    out.append(Message(
                        f"Driver swap complete. Welcome, {name_to_use}! Tyres are cold — build them up carefully.",
                        0, "driver_swap"
                    ))
                    # Update tracked driver
                    self._current_driver_surname = new_surname
                    self._current_driver_full    = new_full
                else:
                    # Normal pit exit
                    if l.fuel_estimated_laps > 0:
                        out.append(Message(
                            f"Good stop! Tyres are cold, build them up. Fuel for {l.fuel_estimated_laps:.1f} laps.",
                            0, "pit"
                        ))
                    else:
                        out.append(Message(
                            "Good stop! Back out there, tyres are cold so take it easy for a lap.",
                            0, "pit"
                        ))

        self._last_in_pit_lane = l.is_in_pit_lane
        return out

    def _check_pit_window(self, l) -> list[Message]:
        out = []
        # pit_window_start / pit_window_end are in milliseconds, same as session_time_left
        # Note: session_time_left counts DOWN.
        # pit_window_end is the LARGER number (e.g. 29 mins left), when the window OPENS.
        # pit_window_start is the SMALLER number (e.g. 1 min left), when the window CLOSES.
        if l.pit_window_end > 0:
            is_open = l.pit_window_start <= l.session_time_left <= l.pit_window_end
            if is_open and not self._pit_window_open:
                self._pit_window_open = True
                
                # Precise Pit Math calculation
                math_msg = ""
                if l.fuel_per_lap > 0 and l.last_lap_ms > 0:
                    laps_to_go = l.session_time_left / l.last_lap_ms
                    # Add 1.5 laps of safety margin
                    fuel_needed = (laps_to_go + 1.5) * l.fuel_per_lap
                    fuel_to_add = max(0, int(fuel_needed - l.fuel_liters))
                    if fuel_to_add > 0:
                        math_msg = f" Adjust your MFD to add exactly {fuel_to_add} liters to make it to the end."
                        
                out.append(Message(f"Box this lap.{math_msg}", 0, "pit_window"))
            elif not is_open and self._pit_window_open:
                self._pit_window_open = False
                if l.session_time_left < l.pit_window_start:
                    out.append(Message("Pit window is closed. Pit window is closed.", 1, "pit_window"))
        return out

    def _check_rivals(self, ahead, behind) -> list[Message]:
        out = []
        
        # Check if ahead or behind just entered the pit lane
        for car, rel in [(ahead, "ahead"), (behind, "behind")]:
            if car is None: 
                continue
            # car.location is often an enum, so we convert to string to check 'Pit'
            is_pit = "Pit" in str(car.location)
            last_pit = self._rival_pit_status.get(car.car_index, False)
            
            if is_pit and not last_pit:
                name = car.driver_name.strip() or f"Car #{car.race_number}"
                # We split by space to just get surname if possible
                name = name.split()[-1] if name else name
                if rel == "ahead":
                    out.append(Message(f"{name} ahead is pitting. Clean air now, push for the overcut!", 0, "rival_pit"))
                else:
                    out.append(Message(f"Car behind is pitting. Push now, defend the undercut!", 0, "rival_pit"))
                    
            self._rival_pit_status[car.car_index] = is_pit
            
        return out

    def rival_close_ahead(self, gap_sec: float, car) -> Optional[Message]:
        name = car.driver_name.strip() if car.driver_name else ""
        name = name or f"Car #{car.race_number}"
        if gap_sec <= config.GAP_CLOSE_THRESHOLD_SEC and self._cooldown_ok("rival_ahead", sec=90):
            return Message(p.pick(
                p.CAR_AHEAD_CLOSE, gap=gap_sec,
                name=name,
                last_lap=_fmt_ms(car.last_lap_ms) if car.last_lap_ms else "-",
            ), 1, "rival")
        return None

    def rival_close_behind(self, gap_sec: float, car) -> Optional[Message]:
        name = car.driver_name.strip() if car.driver_name else ""
        name = name or f"Car #{car.race_number}"
        if gap_sec <= config.GAP_CLOSE_THRESHOLD_SEC and self._cooldown_ok("rival_behind", sec=90):
            return Message(p.pick(
                p.CAR_BEHIND_CLOSE, gap=gap_sec,
                name=name,
                last_lap=_fmt_ms(car.last_lap_ms) if car.last_lap_ms else "-",
            ), 1, "rival")
        return None

    # ------------------------------------------------------------------ #
    #  NEW FEATURE CHECKS                                                  #
    # ------------------------------------------------------------------ #

    def _check_session_time(self, l) -> list[Message]:
        """Fire countdown callouts at 30 / 15 / 10 / 5 / 1 minutes remaining."""
        out = []
        time_left_ms = l.session_time_left
        if time_left_ms <= 0:
            return out

        for mark_ms in self._time_callout_marks:
            if mark_ms in self._time_callouts_fired:
                continue
            # Fire when we cross below the mark
            if time_left_ms <= mark_ms:
                self._time_callouts_fired.add(mark_ms)
                mins = mark_ms // 60_000
                if mins == 1:
                    out.append(Message(
                        "One minute remaining! Push hard, no mistakes.",
                        0, "session_time"
                    ))
                elif mins == 5:
                    out.append(Message(
                        "Five minutes to go. Bring it home clean.",
                        1, "session_time"
                    ))
                elif mins == 10:
                    out.append(Message(
                        "Ten minutes remaining. Stay focused.",
                        1, "session_time"
                    ))
                elif mins == 15:
                    out.append(Message(
                        "Fifteen minutes to go. Keep the pace.",
                        2, "session_time"
                    ))
                elif mins == 30:
                    out.append(Message(
                        "Thirty minutes remaining. Good rhythm, keep it up.",
                        2, "session_time"
                    ))
                break  # only one callout per tick

        # Reset fired marks when session resets (time goes back up significantly)
        if time_left_ms > (35 * 60_000) and self._time_callouts_fired:
            self._time_callouts_fired.clear()

        return out

    def _check_gap_trend(self, l) -> list[Message]:
        """
        Track gap_ahead over laps. If consistently closing or losing,
        call it out — like a real engineer reporting stint trends.
        Only fires in race sessions, outside pits, when gap data is valid.
        """
        out = []
        session = l.session_type.upper()
        in_race = any(r in session for r in _RACE_SESSIONS)
        if not in_race:
            return out
        if l.is_in_pit or l.is_in_pit_lane:
            self._gap_ahead_history.clear()
            return out
        if not l.gap_ahead_ms or l.gap_ahead_ms == 0:
            return out

        gap_sec = abs(l.gap_ahead_ms) / 1000.0
        self._gap_ahead_history.append(gap_sec)

        # Keep only last 5 readings (at 0.5s poll = ~5 lap worth of end-of-lap samples)
        # We use lap-boundary sampling to avoid spamming mid-lap
        # Simple approach: keep a rolling window of last 6 values
        if len(self._gap_ahead_history) > 6:
            self._gap_ahead_history.pop(0)

        # Need at least 4 points to assess trend
        if len(self._gap_ahead_history) < 4:
            return out

        diffs = [
            self._gap_ahead_history[i] - self._gap_ahead_history[i - 1]
            for i in range(1, len(self._gap_ahead_history))
        ]
        avg_delta = sum(diffs) / len(diffs)

        # Threshold: consistently closing > 0.15s/sample or losing > 0.15s/sample
        THRESHOLD = 0.15
        if avg_delta < -THRESHOLD and self._cooldown_ok("gap_trend_close", sec=60):
            # Closing in on car ahead
            rate = abs(avg_delta)
            out.append(Message(
                f"You're closing the gap ahead at roughly {rate:.1f} seconds a lap. Keep this up.",
                2, "gap_trend"
            ))
        elif avg_delta > THRESHOLD and self._cooldown_ok("gap_trend_lose", sec=90):
            # Losing ground to car ahead
            out.append(Message(
                f"You're losing time to the car ahead. Gap is growing — check your pace.",
                2, "gap_trend"
            ))

        return out

    def _check_lap_consistency(self, l) -> list[Message]:
        """
        Recognize when the driver is running consistent lap times —
        3+ laps within ±0.3s of each other. Fire once per consistency streak.
        """
        out = []
        # Only during live sessions with valid, meaningful lap times
        if l.status.upper() not in _LIVE_STATUS:
            return out
        if not l.last_lap_ms or l.last_lap_ms <= 0:
            return out
        if l.is_in_pit or l.is_in_pit_lane:
            return out
        # Only record on lap change
        if l.completed_laps == self._consistency_fired_lap:
            # Track already recorded this lap
            pass
        else:
            if l.is_valid_lap and l.last_lap_ms > 60_000:  # > 1 min, must be real
                self._recent_lap_times.append(l.last_lap_ms)
                if len(self._recent_lap_times) > 5:
                    self._recent_lap_times.pop(0)

        if len(self._recent_lap_times) < 3:
            return out

        # Check variance of last 3 laps
        last3 = self._recent_lap_times[-3:]
        spread_ms = max(last3) - min(last3)
        SPREAD_THRESHOLD_MS = 300  # 0.3 seconds

        if spread_ms <= SPREAD_THRESHOLD_MS and l.completed_laps != self._consistency_fired_lap:
            best_ms = min(last3)
            self._consistency_fired_lap = l.completed_laps
            if self._cooldown_ok("consistency", sec=120):
                lap_str = _fmt_ms(best_ms)
                out.append(Message(
                    f"Three consistent laps around {lap_str}. Solid pace, keep that rhythm.",
                    2, "consistency"
                ))

        return out

    def _check_gap_to_leader(self, l) -> list[Message]:
        """
        Every 5 completed laps (when not in P1), report the gap to the leader.
        Uses gap_ahead data — approximation since we only have gap to car directly ahead.
        Only fires in race sessions.
        """
        out = []
        session = l.session_type.upper()
        in_race = any(r in session for r in _RACE_SESSIONS)
        if not in_race:
            return out
        if l.position <= 1 or l.position == 0:
            return out  # leading or unknown — skip
        if l.completed_laps == 0:
            return out
        if l.completed_laps % 5 != 0:
            return out
        if l.completed_laps == self._last_leader_gap_lap:
            return out  # already fired this lap milestone

        self._last_leader_gap_lap = l.completed_laps

        if not l.gap_ahead_ms or l.gap_ahead_ms == 0:
            return out

        if not self._cooldown_ok("gap_leader", sec=120):
            return out

        gap_sec = abs(l.gap_ahead_ms) / 1000.0
        pos = l.position

        if pos == 2:
            # Can directly reference the leader
            out.append(Message(
                f"Gap to P1 is {gap_sec:.1f} seconds. You're in the fight.",
                2, "gap_leader"
            ))
        else:
            out.append(Message(
                f"You're P{pos}, {gap_sec:.1f} seconds off the car ahead.",
                2, "gap_leader"
            ))

        return out

    def _check_out_lap(self, l) -> list[Message]:
        """
        After a pit exit, flag the out-lap and give coaching to build tyres.
        We already say 'Good stop! Tyres are cold...' on pit exit — this adds
        a follow-up reminder at the END of that out-lap (lap completed after pit).
        """
        out = []

        # Activate out-lap mode on pit exit (tracked via _last_in_pit_lane transition
        # which is handled in _check_pit_status — we piggyback on _last_in_pit_lane)
        if not l.is_in_pit_lane and self._last_in_pit_lane and l.speed_kmh > 10:
            # Pit exit detected — arm out-lap tracker
            self._out_lap_active = True
            self._out_lap_laps_done = l.completed_laps

        if not self._out_lap_active:
            return out

        # Wait until the out-lap is complete (one more lap done)
        if l.completed_laps > self._out_lap_laps_done:
            self._out_lap_active = False
            if l.is_valid_lap and l.last_lap_ms > 0:
                lap_str = _fmt_ms(l.last_lap_ms)
                out.append(Message(
                    f"Out-lap done, {lap_str}. Tyres should be up to temperature now — time to push.",
                    1, "out_lap"
                ))

        return out


def _fmt_ms(ms: int) -> str:
    if not ms:
        return "-"
    total_sec  = ms / 1000.0
    minutes    = int(total_sec // 60)
    seconds    = total_sec - minutes * 60
    return f"{minutes}:{seconds:06.3f}"
