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
6. Section 2 (3D chase-camera view) built last, in `gfx/world.py`.

## Revision 2 (Nov 15): joystick, laser tower, Diviner-only temperature
Step 0 findings: the repo already held the first conversion (connections bar, samples, meters, debrief, DRV8833 rover, C920
stream, intro, NASA loaders, and a 3D chase view). The IO scheme is unchanged: newline-framed ASCII lines, `I?` / `I,<role>,2`,
`P,seq,us` / `Q,seq,us`, lost after 2 s. New and changed lines, all told apart by field count like `P` and `W` already were:

| Meaning | Wire line | Note |
|---|---|---|
| joystick, HUD panel to laptop | `J,x,y,sw` | every 33 ms, x right, y forward, -100..100 |
| jiggle the tower servo | `J` (bare) | laptop to tower |
| impact result | `K,1` hit, `K,0` miss | bare `K` still decodes as "result not known" |
| beam back up | `Z` (bare) | `Z,state` stays the HUD panel's thermal state |
| one distance reading | `R` (bare) asks, the tower answers `R,cm` | the spec's bare number became `R,cm` so it is a framed line |
| lunar temperature to HUD panel | `V,tempC` | once a second, only while the panel is connected |

Choices made (the spec said not to stop and ask):
1. The tower sketch is line framed and answers `I?` and pings, not single characters, because that is the suite's scheme. Its waits and
   stepper moves keep servicing serial so the link never reads "lost" during the 5 to 6 s sequence.
2. The hot / cold state still travels as `Z,state` (same thresholds as the game), and `V,tempC` carries the number shown on the LCD.
3. Thermal thresholds stay fractions of the Diviner table's night-to-day range (`THERMAL_HOT_FRAC`, `THERMAL_COLD_FRAC`).
4. On screen the marked spot is `STRIKE_LEAD_M` ahead of the rover. With the tower, `K,1` / `K,0` decides; without it (or with no
   `W` within 8 s of `F`, or no `K` 2 s after the countdown) a strike hits unless the rover went faster than 30 percent of full speed.
5. The 3D chase view (section 2) was already in the repo, so it was left as it is. `VIEW_3D = False` gives the top-down map.
6. The intro was authored on a 6 s timeline; it now plays in `INTRO_S` = 5 s.
7. The temperature part, the armed LED, the pan servo, the tower tuning line and the unused `scenario.json` are gone.
