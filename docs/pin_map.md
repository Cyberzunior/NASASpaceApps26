# Pin maps (match the firmware in firmware/). All three boards are Arduino UNO Q: 3.3 V logic, never put 5 V on an input.

## HUD panel: UNO Q, USB cable to the laptop (`firmware/hud_panel/hud_panel.ino`)
| Pin | Goes to |
|---|---|
| D2 | DHT11 data (sensor powered from 3V3) |
| D3 | Green LED (220 ohm): normal |
| D4 | Blue LED (220 ohm): cold |
| D5 | Red LED (220 ohm): hot (if fitted) |
| A0 | Yellow LED (220 ohm): sample picked up |
| D6 | unused |
| D7 | Passive buzzer + (driven with `tone()`: 2000 Hz hot, 400 Hz cold, 1200 Hz chirp on pickup) |
| D8 / D9 | LCD RS / E |
| D10 D11 D12 D13 | LCD D4 D5 D6 D7 |
| SDA / SCL | I2C OLED SSD1306 at 0x3C, powered from 3V3 |

## Rover: UNO Q, Wi-Fi (`firmware/robot/`), 2WD with two DRV8833 boards
Two TT gear motors, one left, one right, plus a caster or skid. One DRV8833 per motor, channel 1 of each board
(IN1, IN2, OUT1, OUT2). Channel 2 of each board is unused. Motor power: 9 V pack on VM of both boards (the laptop scales
every command to MAX_PWM = 170 because TT motors are 6 V parts). No capacitors are part of this build.

| Pin | Goes to |
|---|---|
| D5 (PWM) | Left DRV8833 IN1 |
| D6 (PWM) | Left DRV8833 IN2 |
| D9 (PWM) | Right DRV8833 IN1 |
| D10 (PWM) | Right DRV8833 IN2 |
| 3V3 | EEP / SLP (sleep) pin on both boards |
| GND | GND on both boards and the 9 V pack - |
| A2, A3 | Left and right bumper buttons (if fitted, other leg to GND) |
| D4, D7, D8, D12 | ULN2003 IN1 to IN4: the 28BYJ-48 that pans the C920 webcam |
| D13 | Status LED |
| A0, A1 | free (the HC-SR04 is gone) |

Forward = PWM on IN1 with IN2 low, reverse = PWM on IN2, both low = coast (`stopAll()`).
**Not verified on hardware:** third-party pinouts list PWM on D3 D5 D6 D9 D10 D11, but forum posts report that `pinMode()` on a PWM pin
can stop `analogWrite()` on the UNO Q core (the rover sketch never calls it on those pins) and that enabling PWM on one pin can disable
other GPIO. If a wheel does not turn, or the stepper misbehaves once PWM runs, move that input to another PWM pin and edit this table.

The Logitech C920 plugs into the rover's USB port (Linux side). `firmware/robot/linux_bridge/camera_stream.py` serves it as MJPEG
(640 x 480, 15 fps) at `http://<rover ip>:8080/stream`: put that in the Camera URL field.

## Tower: UNO Q, USB cable to the laptop (`firmware/tower/tower.ino`)
| Pin | Goes to |
|---|---|
| D9 | Push servo signal |
| D10 | Pan servo signal (second SG90, `HAS_PAN 1`) |
| D13 | Armed LED (220 ohm), blinks during the warning |
| D2 | Test-fire button (other leg to GND): runs the same warn, fire, release sequence |
