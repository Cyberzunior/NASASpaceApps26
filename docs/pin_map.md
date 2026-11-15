# Pin maps (match the firmware in firmware/)
The HUD panel and the rover are Arduino UNO Q: 3.3 V logic, never put 5 V on an input. The tower is an Arduino UNO R3: 5 V logic.

## HUD panel: UNO Q, USB cable to the laptop (`firmware/hud_panel/hud_panel.ino`)
| Pin | Goes to |
|---|---|
| A1 | Joystick VRx (left and right) |
| A2 | Joystick VRy (forward and back) |
| D6 | Joystick SW (button, `INPUT_PULLUP`, pressed reads LOW) |
| D3 | Green LED (220 ohm): normal |
| D4 | Blue LED (220 ohm): cold |
| D5 | Red LED (220 ohm): hot (if fitted) |
| A0 | Yellow LED (220 ohm): sample picked up |
| D7 | Passive buzzer + (driven with `tone()`: 2000 Hz hot, 400 Hz cold, 1200 Hz chirp on pickup) |
| D8 / D9 | LCD RS / E |
| D10 D11 D12 D13 | LCD D4 D5 D6 D7 |
| SDA / SCL | I2C OLED SSD1306 at 0x3C, powered from 3V3 |
| 3V3 | Joystick + and OLED VCC (keeps the analog outputs under 3.3 V) |

D2 is not connected. The joystick sits in the big round hole of the front panel and drives the rover.

## Rover: UNO Q, Wi-Fi (`firmware/robot/`), 2WD on one dual DRV8833 board
Two TT gear motors, one left, one right, plus a caster or skid. Channel 1 (IN1, IN2, OUT1, OUT2) drives the left motor and
channel 2 (IN3, IN4, OUT3, OUT4) the right. Power: an MB102 module set to 5 V (9 V battery on its barrel jack: check the polarity
with a meter first) feeds the DRV8833 VCC and the ULN2003 +. All grounds are common. The MB102 gives about 700 mA per rail, so the
laptop scales every command to MAX_PWM = 200 and the sketch changes a motor command by at most 40 counts per 20 ms.

| Pin | Goes to |
|---|---|
| D5 (PWM) | DRV8833 IN1: left motor |
| D6 (PWM) | DRV8833 IN2: left motor |
| D9 (PWM) | DRV8833 IN3: right motor |
| D10 (PWM) | DRV8833 IN4: right motor |
| 3V3 | DRV8833 SLP (sleep). Leave it unwired if the J1 jumper on the board is closed |
| GND | GND on the DRV8833, the MB102 and the ULN2003 |
| A2, A3 | Left and right bumper buttons (if fitted, other leg to GND) |
| D4, D7, D8, D12 | ULN2003 IN1 to IN4: the 28BYJ-48 that pans the C920 webcam |
| D13 | Status LED |
| A0, A1 | free |

Forward = PWM on the first input with the second low, reverse = PWM on the second, both low = coast (`stopAll()`).
**Not verified on hardware:** third-party pinouts list PWM on D3 D5 D6 D9 D10 D11, but forum posts report that `pinMode()` on a PWM pin
can stop `analogWrite()` on the UNO Q core (the rover sketch never calls it on those pins) and that enabling PWM on one pin can disable
other GPIO. If a wheel does not turn, or the stepper misbehaves once PWM runs, move that input to another PWM pin and edit this table.

The Logitech C920 plugs into the rover's USB port (Linux side). `firmware/robot/linux_bridge/camera_stream.py` serves it as MJPEG
(640 x 480, 15 fps) at `http://<rover ip>:8080/stream`: put that in the Camera URL field.

## Tower: UNO R3 (5 V logic), USB cable to the laptop (`firmware/tower/tower.ino`)
| Pin | Goes to |
|---|---|
| D2 | Test button to GND (optional, `INPUT_PULLUP`): runs the same sequence as `F` |
| D4 to D7 | ULN2003 IN1 to IN4: the 28BYJ-48 tilt stepper (AccelStepper `HALF4WIRE`, pin order 4, 6, 5, 7) |
| D9 | Push servo signal: jiggles on a hit |
| D11 | HC-SR04 TRIG |
| D12 | HC-SR04 ECHO |
| D13 | Green laser through a 2N2222, held HIGH: D13 to the base through 220 ohm to 1 kohm, laser on the collector, emitter to GND. A laser wired straight to 5 V works too, and D13 is then unused |
| 5 V | HC-SR04 VCC |

The stepper's shaft is horizontal with the laser on an arm, so the beam tilts in a vertical plane. **Power the tower up with the beam
pointing straight up** (the sketch counts steps from there), and connect the laptop while it is up: an UNO R3 resets when its serial
port opens. The HC-SR04 is fixed, level, and faces the track; keep the rover alone on a clear track in front of it.
Power: the servo, the stepper and the laser run from a second MB102 on 5 V (use its 3.3 V rail for the laser if the module is rated
3 to 4.5 V). Its GND joins the UNO R3 GND; nothing else joins the two + rails.
The laser never blinks. Never aim it at a face. Keep the idle beam pointed at an empty ceiling or open space.
Measure `LASER_H_CM` (the laser's height above the floor) and tune `LEAD_CM` and `HIT_TOL_CM` on the real track.
A loose TRIG wire makes every reading 999.
