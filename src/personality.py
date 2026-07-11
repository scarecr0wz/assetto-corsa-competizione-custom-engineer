"""
Sentence template bank. Split by category so you can add new
variations without touching any logic. {placeholders} are filled
by rules_engine.py.
"""

import random

FUEL_WARNING = [
    "Heads up, fuel's good for about {laps:.1f} laps. Start thinking about that pit.",
    "Fuel check — roughly {laps:.1f} laps left. Keep pit strategy in mind.",
    "Getting low on fuel, around {laps:.1f} laps remaining. Don't leave it too late.",
]

FUEL_CRITICAL = [
    "Box box box! Fuel only good for {laps:.1f} laps, don't gamble it!",
    "Critical fuel — {laps:.1f} laps max! Box box box!",
    "Fuel is almost gone, {laps:.1f} laps left. Pit this lap, no arguments!",
]

TYRE_COLD = [
    "{tyre} tyre at {temp:.0f} degrees — not in the window yet. Take it easy.",
    "{tyre} tyre temp only {temp:.0f}C, grip's not there. Build it up carefully.",
]

TYRE_HOT = [
    "{tyre} tyre running hot, {temp:.0f} degrees! Watch for overheat.",
    "Overheat warning on {tyre}, {temp:.0f}C. Ease off a touch.",
]

BRAKE_HOT = [
    "Brake temp at {corner} is {temp:.0f} degrees, that's on the high side. Give them a bit of air.",
    "{corner} brakes at {temp:.0f}C. Don't keep hammering the late braking all the time.",
]

DELTA_GOOD = [
    "Nice, delta is {delta:+.2f}. You're on fire right now!",
    "Purple pace, delta {delta:+.2f}. Keep it coming!",
    "{delta:+.2f} up on best lap. Keep pushing, that's the pace!",
]

DELTA_BAD = [
    "Delta {delta:+.2f}, dropping off best lap a bit. Sharpen up.",
    "Losing time, delta {delta:+.2f}. Have a think about where you're bleeding it.",
]

NEW_BEST_LAP = [
    "Yes! New personal best — {time}. Absolutely nailed that one!",
    "New best lap, {time}! Mega lap, very solid.",
]

POSITION_GAINED = [
    "Overtake confirmed! You're P{position} now. Keep it up!",
    "Up one to P{position}. Good move, well done.",
]

POSITION_LOST = [
    "Position lost, you're P{position} now. Plenty of time to take it back.",
    "Down to P{position}. Stay calm, focus on the next lap.",
]

CAR_AHEAD_CLOSE = [
    "Car ahead is only {gap:.1f} seconds, that's {name}. Last lap {last_lap}. You're right on it.",
    "Gap to {name} is just {gap:.1f} seconds. Stay on them, the opportunity is there.",
]

CAR_BEHIND_CLOSE = [
    "Watch out, car behind is {gap:.1f} seconds — {name} is chasing hard. Last lap {last_lap}.",
    "{name} right on your tail, {gap:.1f} seconds. Protect your line.",
]

RAIN_INCOMING = [
    "Looks like rain's on the way. Track grip's going to drop, stay sharp.",
    "Rain intensity picking up — careful, it's getting slippery out there.",
]

PIT_REMINDER = [
    "Reminder, pit window is still open. Manage your timing.",
    "Don't forget the pit window — don't miss a mandatory stop.",
]

# Random chatter to keep the driver awake when nothing critical is happening
IDLE_BANTER_FALLBACK = [
    "How's the car feeling? Still happy or starting to slide around a bit?",
    "Stay focused, don't switch off. Long way to go yet.",
    "Just keep it consistent, no need to hero it.",
    "Glance at the mirrors occasionally — someone might be sneaking up.",
]


def pick(category: list, **kwargs) -> str:
    template = random.choice(category)
    return template.format(**kwargs)
