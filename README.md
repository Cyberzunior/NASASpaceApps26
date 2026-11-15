# T-Minus_6

NASA Space Apps Challenge 2026, Toronto (Nov 14 and 15). Team D NOVAS.

**Lunar outpost on wheels.** A mobile lunar base rolls across the Moon's surface on the laptop. A real two-wheel rover with a
camera copies every move, an asteroid tower fires paper-ball strikes (after a warning), and a HUD panel with a screen, LEDs and a
buzzer reports the base's state. The player drives, collects ice, regolith and mineral samples, and keeps four meters alive
(Power, Oxygen, Food, Shield) with trade-off actions while radiation storms, hot and cold lunar conditions and asteroid strikes hit.
Base integrity is 15 hearts. Four NASA datasets drive the events (see `data/nasa/SOURCES.md`).

## Try it in 30 seconds (no hardware)
```
pip uninstall pygame          # only if plain "pygame" is installed: it cannot live next to pygame-ce
pip install -r requirements.txt
cd laptop
python main.py                # works with nothing connected: WASD / arrow keys drive
python main.py --sim          # software versions of the rover, tower, HUD panel and camera
```
Keys: W A S D or arrows drive, 1 Scrubber, 2 Greenhouse, 3 Shield boost, 4 Rest crew, Q / E pan the camera, R recentre,
C rover cam, Y or P auto-pilot (steers to the sample), Esc pause, Enter restarts after a run. Gamepad: left stick drives, A X LB RB are
actions 1 to 4, right stick pans, B cam, Y auto-pilot, Start pause. Under `--sim`, keys 7 / 8 / 9 set the simulated DHT11 hot / cold / normal.

## The three devices and the camera
| Unit | Board | Link |
|---|---|---|
| HUD panel (LCD, OLED, LEDs, buzzer, DHT11) | UNO Q, `firmware/hud_panel/` | USB cable, COM port |
| Asteroid tower | UNO Q, `firmware/tower/` | USB cable, COM port |
| Rover (2WD, two TT motors, two DRV8833) | UNO Q, `firmware/robot/` | Wi-Fi, `ip:port` (192.168.1.50:5005) |
| Camera | Logitech C920 on the rover (USB), panned by a stepper | MJPEG over Wi-Fi, `camera_stream.py` |

The menu's **Connections** bar sets all four (COM dropdowns, `ip:port`, camera URL, Connect, status dots, Refresh COM ports) and saves
them in `laptop/config.local.json`. Status: green connected, grey not connected, red lost (within 2 s). Pin tables: `docs/pin_map.md`.

## NASA data (all on disk, the game never needs the internet)
`python tools/fetch_nasa_data.py` fills `data/nasa/` (DONKI flares and SEP events, LRO Diviner temperatures, MEO lunar impact
flashes, ISS Veggie facts) and writes `data/nasa/SOURCES.md`. Set `NASA_API_KEY` in `config.local.json` (DEMO_KEY is rate limited).

## What is in this repo
| Folder | What |
|---|---|
| `laptop/` | The game: `main.py`, `app.py`, `config.py` (every number), `core/` (rules, NASA data, thermal), `devio/` (links, discovery, connections, gamepad, camera, simulators), `gfx/` (view, HUD, menu, intro), `audio/` |
| `firmware/` | `hud_panel/`, `tower/`, `robot/` (+ `linux_bridge/` for the rover's Wi-Fi and camera) |
| `tools/` | `fetch_nasa_data.py` |
| `data/nasa/` | downloaded NASA files and `SOURCES.md` |
| `tests/` | `python -m pytest tests` (30 automated tests) and the hardware triage tools (`triage.py`, `triage_gui.py`, PinTester) |
| `docs/` | `pin_map.md`, `CONVERSION_NOTES.md`, older project documents (they still describe the earlier orbit version) |

## Status
Software checked headless with simulated devices (`python -m pytest tests`). **Nothing has met real hardware yet**: HUD panel, tower and
rover sketches are not compiled or uploaded, PWM on D5 D6 D9 D10 is unverified, the camera stream is untested, and V_MAX / W_MAX are placeholders
until the rover is measured with `python laptop/tools/calibrate_robot.py`. The 3D chase-camera view is not built yet (the game uses a top-down lunar view).
