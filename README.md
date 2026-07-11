# ACC Custom Race Engineer

<p align="center">
  <img src="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRorBJUINFC2G08W_BLrv2CrVioN-YyJKA-ht_4cXfqMg&s=10" alt="ACC Custom Race Engineer Logo" width="400"/>
</p>

A virtual, highly reactive GT3 race engineer for **Assetto Corsa Competizione (ACC)**. 

No more squinting at your HUD in the middle of a Eau Rouge flat-out run. This tool monitors your telemetry in real-time, calculates pit strategy numbers, recognizes your driving consistency, alerts you to competitor movements, and even lets you **talk back via Voice Control** to adjust MFD settings (fuel, map, bias, compounds) on the fly. 

It also applies a retro-style radio signal effect (bandpass filters, analogue saturation, mic clicks) to make the engineer sound like they're sitting in the pit wall talking to your helmet headset.

---

## 🎧 What Your Engineer Does Automatically

The engineer processes telemetry via a hybrid system: a **Rule-Based Engine** for instant, zero-delay calls (like flags, temperatures, and spots) and a background **LLM Engine** (via Groq/Llama-3.3) for casual tactical banter and strategic voice responses.

### ⏱️ Session & Race flow
* **Pre-Race Suppression**: During the grid line-up and formation lap, the engineer keeps the radio clear of racing noise (no delta alerts or gap metrics). They welcome you, warn you about pre-race rain, and wait for the green flag.
* **Race Starts & Flags**: Yells `"Green green green!"` at the start. Monitors yellow, blue, red, and checkered flags instantly.
* **Session Time Countdowns**: Keeps you updated on the clock with callouts at 30, 15, 10, 5, and 1 minute remaining.

### 📊 Driving Performance & Consistency
* **Consistency Recognition**: Ran three laps in a row within a `0.3s` window? The engineer will chime in to praise your rhythm.
* **Gap Trend Tracker**: Compares lap-by-lap pace. If you are catching the car ahead by more than `0.15s` a lap, they'll report: *"You're closing the gap ahead at roughly 0.4 seconds a lap. Keep this up."*
* **Gap to Leader**: Every 5 laps, they'll update you on your position and distance to the leader or the car directly ahead.

### 🔧 Car Maintenance & Pit Strategy
* **Thermal Alerts**: Instant warning if tires are freezing (under optimal grip) or brakes are cooking (overheating past normal GT3 thresholds).
* **Driver Swap Detection**: In endurance races, when you pull a pit stop and swap drivers, the engineer automatically detects the surname change, welcomes the incoming driver, and updates the name-injection engine so all future radio lines use the new driver's name.
* **Out-Lap Coaching**: Reminds you to take it easy and warm up cold tires gradually when exiting the pit lane.
* **Pit Window Math**: Calculates the exact fuel amount to add at the pit window start to finish the race without carrying excess weight.

---

## 🎙️ Talk Back: Voice Control & MFD Keypress Simulation

Hold down the **Push-to-Talk (PTT)** key (default: `Caps Lock`), speak your request, and the engineer will execute the setup adjustment directly in-game by simulating keyboard inputs to navigate your MFD:

| What you say (examples) | What the engineer does | Keypress Simulation |
|---|---|---|
| `"set fuel to 45"` or `"fuel 45"` | Sets absolute pit fuel to 45 Litres | Pages MFD to Pit $\rightarrow$ Selects Fuel $\rightarrow$ Decrements to 0 $\rightarrow$ Increments to 45 |
| `"add 15 liters"` or `"add 15"` | Adds 15 Litres to current setting | Pages MFD to Pit $\rightarrow$ Selects Fuel $\rightarrow$ Increments by 15 |
| `"switch to wet"` or `"dry tyres"` | Toggles your next tire set compound | Pages MFD to Pit $\rightarrow$ Selects Compound $\rightarrow$ Toggles to Wet/Dry |
| `"engine map 3"` or `"map to 2"` | Switches your ECU engine map | Sends relative Left/Right arrow keys directly to ACC |
| `"brake bias 54.5"` or `"bias 55"` | Adjusts your brake bias percentage | Computes difference from telemetry and presses Left/Right arrows |

> [!NOTE]
> The keypress simulator sends Windows messages directly to the `AC2` window (ACC). For this to work, ensure ACC is in focus and you are using default MFD bindings (Page Up/Down for pages, Arrows for values/navigation, Enter to select).

---

## 📻 How the Radio Voice Sound Effect Works

The system doesn't just read dry text. The offline `edge-tts` output is piped through a custom digital signal processing (DSP) chain in `voice_queue.py`:
1. **Bandpass Filter (300Hz - 3400Hz)**: Mimics the frequency response of a classic walkie-talkie/telephone receiver.
2. **Tanh Soft-Clip Saturation**: Drives the signal slightly to add warm, analogue harmonic clipping distortion.
3. **Static Noise Floor**: Blends a quiet layer of constant white noise.
4. **Beeps & Mic Clicks**: Synthesizes custom 1200Hz sine wave beeps with exponential decay at the start and end of every transmission.

---

## 🚀 Setup & Installation

### 1. Requirements
* Windows PC (ACC shared memory is Windows-only).
* Python 3.10 to 3.14.
* FFmpeg installed and added to your Windows system PATH (required by the TTS decoder).

### 2. Install Dependencies
Clone the repository, open a terminal in the folder, and run:
```bash
pip install -r requirements.txt
```

### 3. Setup ACC Broadcasting API
Open your ACC config file:
```text
Documents\Assetto Corsa Competizione\Config\broadcasting.json
```
Ensure it matches the following port and password (which is automatically written by `run.bat` on launch):
```json
{
    "updListenerPort": 9000,
    "connectionPassword": "asd",
    "commandPassword": ""
}
```

### 4. Enable AI Strategic Banter (Optional)
If you want the engineer to hold conversational strategy talks and use LLM banter:
1. Get a free API Key from [console.groq.com](https://console.groq.com).
2. Set it as an environment variable:
   ```cmd
   setx GROQ_API_KEY "your_gsk_key_here"
   ```
If no key is provided, the engineer will run perfectly in rule-only mode (instant alerts without filler conversation).

---

## 🏎️ Running the App

Simply run the batch file:
```cmd
run.bat
```
You will be prompted to choose:
* **[1] GUI Mode (Recommended)**: Opens a sleek dark-themed desktop dashboard showing live tire graphs, delta meters, session timers, and a voice command log.
* **[2] Console Mode**: Runs the script directly in your terminal.

Once running, get in your car and head out on track. The engineer will check the radio status and welcome you.

---

## 📁 Repository Layout

To keep the repository clean, all core engine files are organized inside the `src/` directory:

```text
├── docs/
│   └── technical_walkthrough.md  # Detailed inner code architecture
├── src/                          # System core modules
│   ├── config.py                 # Tweak thresholds, PTT keys, & timings here
│   ├── rules_engine.py           # Instant logic & evaluation criteria
│   ├── telemetry_local.py        # Shared memory reader (your car)
│   ├── telemetry_broadcast.py    # UDP broadcast reader (opponents & gaps)
│   ├── voice_queue.py            # Priority audio queue & DSP radio filter
│   ├── voice_input.py            # PTT recording system
│   ├── llm_commentary.py         # Whisper transcriber & Groq pipeline
│   ├── mfd_control.py            # Keypress emulation & voice command parser
│   └── personality.py            # Preset dialogue lines bank
├── main.py                       # CLI Launcher entrypoint
├── gui_app.py                    # GUI Launcher entrypoint
├── run.bat                       # Startup helper
├── requirements.txt              # Dependency lists
└── LICENSE                       # MIT License
```

*Tidy driving, and see you on the podium!*
