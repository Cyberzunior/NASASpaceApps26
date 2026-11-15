# Firmware

| Folder | Board | Files |
|---|---|---|
| `hud_panel/` | UNO Q, USB to the laptop | `hud_panel.ino` |
| `tower/` | UNO R3 (5 V logic), USB to the laptop | `tower.ino` |
| `robot/` | UNO Q, Wi-Fi | `robot.ino` (STM32 side), `linux_bridge/robot_bridge.py` (UDP <-> Bridge), `linux_bridge/camera_stream.py` (C920 MJPEG) |

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
Libraries: Servo, AccelStepper. The laser (D13 through a 2N2222) is on from power-up and never blinks; idle = beam straight up.
`F,bearing` or the test button on D2 (bearing 0): measure the target (HC-SR04, median of 5), yaw the stepper to the bearing (-40..40),
pitch the servo so the beam lands `LEAD_CM` ahead of the target (`DEFAULT_CM` if nothing is in range), `W,3`, 3 s countdown, then `K,1`
(something in the spot) or `K,0` (nothing there, or the bearing is beyond `HIT_BEARING_DEG`, where the fixed sensor cannot check), beam back up.
`Z` goes idle (pitch up, yaw 0), `R` answers `R,cm`. The sketch is line framed like every other board (`I?`, `P,seq,us`)
and keeps answering pings during a sequence, so the laptop's status dot stays green. **Power it up, and connect the laptop, with the beam
straight up:** the sketch counts steps from there and an UNO R3 resets when its serial port opens.
Measure `LASER_H_CM`; tune `LEAD_CM`, `HIT_TOL_CM`, `TILT_DIR` and `AHEAD_DEFAULT` on the real track.

## Rover
One dual DRV8833 (D5 D6 left, D9 D10 right) fed from an MB102 at 5 V. `MAX_PWM` (200) scaling happens on the laptop; the sketch limits
every motor command to 40 PWM counts of change per 20 ms. `D,left,right,ap` every 20 ms, wheels stop 300 ms after the
last `D` (`stopAll()`), `C,angle` pans the camera stepper (AccelStepper, +-90 degrees), `X` latch on game over, `R` release.
On the UNO Q's Linux side run `linux_bridge/robot_bridge.py` (UDP port 5005, Wi-Fi) and `linux_bridge/camera_stream.py` (HTTP port 8080).
Test the bridge without a board: `python firmware/robot/linux_bridge/robot_bridge.py --selftest`.

## Verify on day one (not checked against a real board)
1. D5, D6, D9, D10 give PWM, and `analogWrite()` works without `pinMode()` on them (forum reports: `pinMode()` can break it; PWM on one pin can disable other GPIO).
2. `tone()` works on the UNO Q core (HUD buzzer on D7). `analogReadResolution(10)` exists on the core. The LCD1602 works from the UNO Q's supply at 3.3 V logic.
3. The HUD panel appears as a USB serial port and sends `HELLO,HUD,1` at boot (the sketch uses `Serial`); the Arduino Bridge API names for the rover come from community write-ups.
4. Tower: the beam swings DOWN on `F` (else flip `PITCH_DIR`; `YAW_DIR` if bearings swing the wrong way), `R` gives sane centimetres, and the spot lands just ahead of the rover.
5. Wi-Fi power saving on the rover: the bridge tries `iw dev wlan0 set power_save off`; check the interface name.
