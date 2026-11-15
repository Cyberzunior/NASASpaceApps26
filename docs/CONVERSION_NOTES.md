# Lunar outpost conversion: Step 0 findings and plan

## What the repo is (read before any edit)
- `laptop/` pygame-ce game. Threads: input/mixer (`devio/gamepad.py`), `UdpHub` + `SerialScanner` (`devio/discovery.py`),
  link health (`devio/links.py`), camera (`devio/camera.py`, newest frame only). Game rules in `core/game.py`, drawing in `gfx/`.
- IO scheme (also used by the triage suite `tests/triage.py`, `tests/gui_common.py`): ASCII lines, comma separated, max 64 chars,
  newline framing, 115200 baud serial or one UDP datagram per line. Health: the laptop pings `P,seq,us`, the device answers
  `Q,seq,us`; no answer for `LINK_TIMEOUT_S` (2 s) = lost. Serial devices answer `I?` with `I,<role>,<fw>`.
  The triage "Connections" panel = one row per device (COM dropdown or ip:port, Connect, status) + camera URL + Refresh COM ports.
- Baseline: 61 tests pass (`python -m pytest tests`).

## Protocol decisions (no second protocol; same framing, same decoder)
| Meaning | Wire line | Note |
|---|---|---|
| pickup to HUD panel | `P` (bare, no fields) | `P,seq,us` with fields stays the ping. The decoder tells them apart by field count, like the existing `T` |
| asteroid warning from tower | `W,3` | the HUD's `W,temp,hum,state` has 3 fields; decoder tells them apart by field count |
| strike released | `K` | existing |
| ask for a shot | `F` | existing; tower now runs warn (W,3) -> 3 s -> fire -> K |
| camera pan | `C,angle` | spec `C` had 3 ints and no user; now 1 int |
| meters to HUD | `M,pwr,o2,food,shield` | new, at most 5 per second |
| lives to HUD | `H,n` | existing |
| samples to HUD | `E,n` | new |
| simulated temp to HUD | `V,tempC` | existing |
| LCD text | `L,line1\|line2` | existing |
| chirp | `BZ` | existing test beep, now the 1200 Hz chirp |

## Changes
1. Roles: `station` -> `hud` (HUD panel, UNO Q, USB serial, answers `I,hud,2`). Tower is wired: serial, `I,tower,2`.
   Robot stays UDP (`ip:port`). Camera is a URL.
2. Connections bar in the menu (COM dropdowns, ip:port, camera URL, Connect, dots, Refresh), saved in `config.local.json`,
   compact dot strip during play.
3. New rules in `core/game.py` (4 meters, 15 hearts, samples, strikes, storms, thermal state, day clock, debrief data).
   Orbit, Earth, debris, ring, ultrasonic scans removed. View stays top-down (3D view deferred), re-themed to lunar ground.
4. Firmware: HUD panel (UNO Q, tone on D7, OLED), tower (serial, warn/fire/K), robot (one DRV8833 channel per motor,
   D5 D6 D9 D10, AccelStepper pan on D4 D7 D8 D12, no HC-SR04, no TB6612), `firmware/robot/camera_stream.py` (C920 MJPEG).
5. NASA data: `tools/fetch_nasa_data.py` -> `data/nasa/` + `SOURCES.md`; game reads disk only.
6. Not touched until the rest works: section 2 (3D view).
