# Firmware

| Folder | Board | Files |
|---|---|---|
| `hud_panel/` | UNO Q, USB to the laptop | `hud_panel.ino` |
| `tower/` | UNO Q, USB to the laptop | `tower.ino` |
| `robot/` | UNO Q, Wi-Fi | `robot.ino` (STM32 side), `linux_bridge/robot_bridge.py` (UDP <-> Bridge), `linux_bridge/camera_stream.py` (C920 MJPEG) |

**None of this has been compiled or run on a board yet.** Pins: `docs/pin_map.md`. Protocol: `laptop/devio/protocol.py`
(ASCII lines, same as the triage suite: serial 115200 baud or one UDP datagram per line; ping `P,seq,us` answered `Q,seq,us`;
serial boards answer `I?` with `I,<role>,2`).

## HUD panel
Libraries: LiquidCrystal, DHT sensor library, Adafruit SSD1306, Adafruit GFX. Lines in: `M,pwr,o2,food,shield`, `H,hearts`, `E,samples`,
`Z,state`, `V,tempC`, `P` (pickup: yellow LED 5 blinks in 1 s, chirp), `BZ`, `G`, `R`, `L,line1|line2`. Out: `W,temp,hum,state` every 2 s
(hum -1 = the board is repeating a laptop `V` value because its DHT11 is dead). One passive buzzer on D7 via `tone()`.

## Tower
`F` or the test button on D2: `W,3` (warning), 3 s wait, push the ball, `K`. Disarmed (`X`) or within 1.5 s of the last shot = ignored.

## Rover
Two DRV8833 channels (D5 D6 left, D9 D10 right), `MAX_PWM` scaling happens on the laptop. `D,left,right,ap` every 20 ms, wheels stop 300 ms after the
last `D` (`stopAll()`), `C,angle` pans the camera stepper (AccelStepper, +-90 degrees), `X` latch on game over, `R` release.
On the UNO Q's Linux side run `linux_bridge/robot_bridge.py` (UDP port 5005, Wi-Fi) and `linux_bridge/camera_stream.py` (HTTP port 8080).
Test the bridge without a board: `python firmware/robot/linux_bridge/robot_bridge.py --selftest`.

## Verify on day one (not checked against a real board)
1. D5, D6, D9, D10 give PWM, and `analogWrite()` works without `pinMode()` on them (forum reports: `pinMode()` can break it; PWM on one pin can disable other GPIO).
2. `tone()` works on the UNO Q core (HUD buzzer on D7). The LCD1602 and DHT11 work from the UNO Q's supply at 3.3 V logic.
3. The tower and HUD panel appear as a USB serial port and answer `I?` (the sketches use `Serial`); the Arduino Bridge API names for the rover come from community write-ups.
4. The `Servo` library runs on the UNO Q core and D9 / D10 can drive servos.
5. Wi-Fi power saving on the rover: the bridge tries `iw dev wlan0 set power_save off`; check the interface name.
