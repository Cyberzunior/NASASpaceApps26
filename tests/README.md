# T-Minus_6 tests

## Automated tests (pytest)

Headless, no hardware, about a minute:

    python tests/run_tests.py            # built-in runner, no extra packages
    pytest tests                         # same tests with pytest (pip install pytest)

`test_model` (mixer, dead zone, movement model, calibration), `test_protocol_config` (every line, garbage, settings file),
`test_game_rules` (hits, protection, game over, asteroid sequence, weather, zones, auto-pilot dodge 10 of 10),
`test_devices` (discovery, RTT, failsafe, latch, tower safety, unplug and replug over real loopback sockets),
`test_firmware_bridges` (static checks of the sketches, UNO Q bridge self-tests), `test_app_flow` (the whole game in `--sim`).
Soak: `python laptop/tools/soak.py --demos 3`.

# T-Minus_6 hardware triage

Two front ends for the same hardware:

- `triage_gui.py`: a simple PyQt5 window, one tab per part (below).
- `triage.py`: the terminal script that walks every piece of hardware and
  prints a PASS / FAIL / SKIP line per check, plus a summary at the end.

Also here: the bench sketches `PinTester.ino`, `ServoTest.ino`, `StepperTest.ino`
(upload to the board named in the filename, 115200 baud).

## Install

    pip install -r requirements.txt            # from the repo root; includes PyQt5

## GUI

    python tests/triage_gui.py

Connect the boards at the top (COM port for USB boards, `ip:port` for the UNO Qs), then
pick a tab. Each tab has buttons that send the real protocol lines, a live readout and a
checklist you tick by hand; **Save report** writes the checklists to `tests/reports/`.
**STOP ALL** stops the wheels, disarms the tower, releases the bench board and stops the camera.
The box under the log sends any line to any board (`I?`, `V,35`, `A,90`, `PING,D7,D8` ...).

| Tab | What it does |
|---|---|
| Weather + LCD | live `W` readout; buttons for `BZ` (buzz D7) / `V,24` / `V,35` / `V,10` / `H,14` / `G` / `R`; a mock 16x2 LCD showing what the real LCD should say right now |
| Robot | hold-to-drive pad (resent at 20 Hz), speed, auto-pilot flag, `X` / `R`, radar of the `S` lines, bumpers |
| Tower | `F` with a safety tick, `R` / `X`, F-to-K time |
| Bench | stepper moves and servo angles through `PinTester.ino` on a spare UNO |
| Camera | stream picture, resolution and fps |
| Gamepad | axes, buttons, last button number, expected numbers from `laptop/config.py` |

The weather LCD1602 is wired to the weather station UNO R3 (RS D8, E D9, D4-D7 to D10-D13,
RW to GND, see `Weather Station Wiring Lab (1).html`) and only `weather_station.ino` drives it,
so it is tested from the Weather tab with that board's own commands. Close the game first:
only one program can hold the UNO R3's COM port.

## Command line

    python tests/triage.py                     # everything, asks before each board
    python tests/triage.py weather --port COM5 # just one board
    python tests/triage.py robot               # UDP 192.168.1.50:5005 (or --port for serial)
    python tests/triage.py tower               # UDP 192.168.1.51:5005 (or --port for serial)
    python tests/triage.py wiring              # wire-by-wire on the PinTester board
    python tests/triage.py camera [--url http://192.168.1.60:81/stream]
    python tests/triage.py gamepad

The exit code is 1 when any check failed, so it works as a gate before a demo.

## What each board gets

- **weather** (UNO R3, USB): `W,temp,hum,state` line arrives and parses, DHT11
  ranges sane, green LED + LCD normal, hot air turns it HOT (red LED + fast
  high beeps), cold pack turns it COLD (blue LED + fast low beeps), back to NORMAL.
  The single buzzer is on D7; `BZ` makes it beep for 0.5 s.
- **robot** (UNO Q #1): `S,angle,dist,flags` line, sweep covers about +/-45 deg,
  HC-SR04 sees a hand at 10 cm, wheels forward and back together at `D,...`
  (wheels on blocks!), bumpers send `B,L` / `B,R`, status LED with auto-pilot.
- **tower** (UNO Q #2): armed LED on, `F` answered by `K`, exactly one ball
  drops, board does not reset, ball flight 2-3 s.
- **wiring**: upload `PinTester.ino` to a spare UNO, connect the harness, and it
  steps through every wire of the chosen board (weather / robot / tower):
  LEDs, buzzers, DHT, buttons, ultrasonic, servos, stepper, motors, LCD, I2C.
- **camera**: opens the ESP32-CAM or phone stream, checks 60 frames flow,
  resolution near 320x240 and at least 5 fps (doc wants 15-20).
- **gamepad**: lists the controller, samples axes and buttons for 4 s.

## Safety

- Robot on blocks for drive checks; Esc/Ctrl+C stops the script.
- UNO Q pins are 3.3 V: HC-SR04 ECHO needs the 1k + 2k divider.
- Keep the tower pointed away from people; `F` drops a real ball.
- Hair dryer on low, 30 cm from the DHT11; cold pack in a sealed bag.
- UNO R3 resets when the serial port opens: the script waits 2 s for you.
- Venue Wi-Fi often isolates devices: use the phone hotspot.
