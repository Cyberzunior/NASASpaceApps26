# Firmware

| Folder | Board | Files |
|---|---|---|
| `hud_panel/` | UNO Q, USB to the laptop | `hud_panel.ino` |
| `tower/` | UNO R3 (5 V logic), USB to the laptop | `tower.ino` |
| `robot/` | UNO Q, STM32 only, USB to the laptop | `robot.ino` (no Linux program needed for driving); optional `linux_bridge/` (old Wi-Fi bridge, C920 stream) |

**None of this has been compiled or run on a board yet.** Pins: `docs/pin_map.md`. Protocol: `laptop/devio/protocol.py`
(ASCII lines, same as the triage suite: serial 115200 baud or one UDP datagram per line; ping `P,seq,us` answered `Q,seq,us`;
serial boards answer `I?` with `I,<role>,2`).

## HUD panel
Libraries: LiquidCrystal, Adafruit SSD1306, Adafruit GFX, Adafruit NeoPixel. Lines in: `M,pwr,o2,food,shield`,
`H,hearts,samples`, `V,tempC` (lunar temperature, once a second, also the keep-alive), `S,state` (0 normal, 1 cold,
2 hot, 3 radiation storm, 4 asteroid incoming), `P` (pickup: yellow LED 5 blinks in 1 s, chirp), `B` (run starts), `G`.
Out: `J,x,y,sw` every 33 ms (joystick on A1 / A2, button on D6; x right, y forward, -100..100; centre calibrated at
power-up, stick untouched), `HELLO,HUD,1` once at boot, `HB` heartbeat once a second. No line for 3 s: `NO LINK`.
One passive buzzer on D7 via `tone()`, one NeoPixel on D4. No `delay()`. If the stick moves the wrong way, set
`JOY_INVERT_X` / `JOY_INVERT_Y` on the laptop.

## Tower (UNO R3)
**Flash `tower/tower.ino` once.** It is a plain serial-driven pan/tilt laser and knows nothing about the game: the game, `tests/triage_gui.py`
and `tests/triage.py tower` all drive it with the same lines. Libraries: Servo, AccelStepper. The laser (D13 through a 2N2222) is on from power-up.
Lines: `Y,deg` yaw (0 = the stepper's power-up heading, +-100), `T,deg` servo 0..180, `L,0|1` laser, `H` here is yaw 0, `O` coils off,
`G,sps,acc,ms` speeds, `R` range (`R,cm`, 999 = nothing), `?` state (`S,yaw,servo,laser,moving`), `I?`, `P,seq,us`. The tower answers `D,yaw,servo`
when both motors arrive and `B,1` for the test button on D2. Moves never block, so pings are answered while it moves.
In a run the laptop does the thinking (`laptop/core/tower_aim.py`): the tower is assumed to stand `TOWER_BACK_CM` behind the rover's start,
facing the way the rover faces, at yaw 0. When a run starts it looks left and right for `TOWER_SCAN_S` (3 s), then locks on the rover (Y and T at 10 Hz from the
game's rover position, laser height `TOWER_LASER_H_CM` and distance give the pitch). An asteroid moves the beam onto the marked spot for the 3 s
countdown, then it returns to the rover. Menus, pause and game over send the beam straight up with yaw 0. The game decides hits itself: with the tower connected a
rover inside `STRIKE_HIT_M` of the spot is hit. Every number to tune is in `laptop/config.py` (`TOWER_*`), never in the sketch:
`TOWER_YAW_DIR`, `TOWER_PITCH_DIR`, `TOWER_PITCH_LEVEL`, `TOWER_LASER_H_CM`, `TOWER_BACK_CM`.
**Power it up, and connect the laptop, with the beam straight up and the stepper facing ahead:** an UNO R3 resets when its serial port opens, and
the sketch counts steps from there. If the game toasts "old firmware", the Uno still runs an earlier tower sketch: flash this one.

## Rover
One dual DRV8833 (D5 D6 left, D9 D10 right) fed from an MB102 at 5 V. `MAX_PWM` (200) scaling happens on the laptop; the sketch limits
every motor command to 40 PWM counts of change per 20 ms. `D,left,right,ap` every 20 ms, wheels stop 300 ms after the
last `D` (`stopAll()`), `C,angle` pans the camera stepper (AccelStepper, +-90 degrees), `X` latch on game over, `R` release.
Motor values below `MIN_PWM` (60) do not turn a TT motor, so any non-zero command is lifted into 60..200. Plug the UNO Q into the laptop, then in the
game's Connections bar put the rover's COM port in the Rover row (or leave auto scan on): the board answers `I?` with `I,robot,2`.
Bumpers send `B,L` / `B,R`. The old Wi-Fi path (`linux_bridge/robot_bridge.py`, `--selftest`) still works but is not needed for driving.

## Verify on day one (not checked against a real board)
1. D5, D6, D9, D10 give PWM, and `analogWrite()` works without `pinMode()` on them (forum reports: `pinMode()` can break it; PWM on one pin can disable other GPIO).
2. `tone()` works on the UNO Q core (HUD buzzer on D7). `analogReadResolution(10)` exists on the core. The LCD1602 works from the UNO Q's supply at 3.3 V logic.
3. The HUD panel appears as a USB serial port and sends `HELLO,HUD,1` at boot (the sketch uses `Serial`); the Arduino Bridge API names for the rover come from community write-ups.
4. Tower: `T,130` points the beam DOWN (else `TOWER_PITCH_DIR = -1`), `Y,30` swings it right (else `TOWER_YAW_DIR = -1`), `R` gives sane centimetres, and the spot lands on the rover.
5. Wi-Fi power saving on the rover: the bridge tries `iw dev wlan0 set power_save off`; check the interface name.
