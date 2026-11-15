#!/usr/bin/env python3
"""T-Minus_6 hardware triage: quick pass/fail checks that each part works.

Run one board, or everything in one pass:

    python tests/triage.py                    # everything, in order
    python tests/triage.py weather --port COM5   # the HUD panel (kept under the old name)
    python tests/triage.py robot              # UDP 192.168.1.50:5005
    python tests/triage.py tower --port COM6  # USB serial
    python tests/triage.py wiring             # step through wires on the PinTester board
    python tests/triage.py camera [--url http://...]
    python tests/triage.py gamepad

Baud is 115200 everywhere. Boards that reply over the network use UDP;
pass --port to talk to any of them over serial instead.
Every check prints PASS / FAIL / SKIP; a summary and the exit code follow.
"""
import argparse
import os
import socket
import sys
import threading
import time

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rw_timeout;8000000|timeout;8000000")

BAUD = 115200
ROBOT_ADDR = ("192.168.1.50", 5005)
CAMERA_URLS = [
    "http://192.168.1.60:81/stream",    # ESP32-CAM CameraWebServer
    "http://192.168.1.61:8080/video",   # phone IP Webcam
]

results = []   # (name, status) with status in PASS / FAIL / SKIP


# --------------------------------------------------------------- reporting
def check(name, ok, note=""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f"  ({note})" if note else ""))
    results.append((name, status))
    return ok


def skip(name, note=""):
    print(f"[SKIP] {name}" + (f"  ({note})" if note else ""))
    results.append((name, "SKIP"))


def _input(prompt):
    try:
        return input(prompt)
    except EOFError:
        return None
    except KeyboardInterrupt:
        print("\nstopped")
        sys.exit(130)


def ask(name, question):
    a = _input(f"  ? {question} [y/n/s] ")
    if a is None:
        skip(name, "no answer (input ended)")
        return False
    a = a.strip().lower()
    if a in ("s", "skip"):
        skip(name, "answered skip")
        return False
    return check(name, a in ("y", "yes"))


def pause(msg):
    _input(f"  ... {msg} (Enter) ")


def summary():
    n_pass = sum(1 for _, s in results if s == "PASS")
    n_fail = sum(1 for _, s in results if s == "FAIL")
    n_skip = sum(1 for _, s in results if s == "SKIP")
    print(f"\n== Summary: {n_pass} pass, {n_fail} fail, {n_skip} skip ==")
    for name, status in results:
        if status == "FAIL":
            print(f"   failed: {name}")
    return 1 if n_fail else 0


# --------------------------------------------------------------- link
class Link:
    """Serial (COM port) or UDP link, line based, 115200 baud."""

    def __init__(self, port=None, addr=None):
        self.port, self.addr = port, addr
        self.ser = None
        self.sock = None
        self.buf = b""

    def open(self):
        if self.addr:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(0.1)
            print(f"  link: udp {self.addr[0]}:{self.addr[1]}")
        else:
            import serial
            self.ser = serial.Serial(self.port, BAUD, timeout=0.05)
            time.sleep(2)   # UNO R3 resets when the port opens
            print(f"  link: serial {self.port} @ {BAUD}")

    def close(self):
        if self.ser:
            self.ser.close()
        if self.sock:
            self.sock.close()

    def send(self, line):
        data = (line + "\n").encode()
        if self.ser:
            self.ser.write(data)
        else:
            self.sock.sendto(data, self.addr)

    def line(self, match=None, timeout=2.0):
        """Next line (optionally containing match), or None on timeout."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.ser:
                data = self.ser.read(256)
            else:
                try:
                    data, _ = self.sock.recvfrom(2048)
                except socket.timeout:
                    continue
            self.buf += data
            while b"\n" in self.buf:
                raw, self.buf = self.buf.split(b"\n", 1)
                text = raw.decode(errors="replace").strip()
                if text and (match is None or match in text):
                    return text
        return None


def open_serial_link(args, title):
    port = args.port
    if not port:
        try:
            from serial.tools import list_ports
        except ImportError:
            print("pyserial missing: pip install -r requirements.txt")
            return None
        ports = [(p.device, p.description or "") for p in list_ports.comports()]
        if not ports:
            print(f"  no serial port found for {title}; plug it in or use --port")
            return None
        if len(ports) == 1:
            port = ports[0][0]
        else:
            print(f"  pick the port for {title}:")
            for dev, desc in ports:
                print(f"    {dev}  {desc}")
            port = _input("  port: ") or ""
    link = Link(port=port)
    try:
        link.open()
    except Exception as e:
        print(f"  could not open {port}: {e}")
        return None
    return link


def open_udp_or_serial(args, title, addr):
    link = Link(addr=addr) if not args.port or title == "rover" and not args.port else Link(port=args.port)
    try:
        link.open()
    except Exception as e:
        print(f"  could not connect for {title}: {e}")
        return None
    return link


# --------------------------------------------------------------- parsing
def split_csv(line):
    return [p.strip() for p in line.split(",")]


def floats(parts, n):
    if len(parts) != n:
        return None
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


# --------------------------------------------------------------- HUD panel
def triage_weather(args):
    print("\n== HUD panel (UNO Q, USB serial) ==")
    link = open_serial_link(args, "HUD panel")
    if not link:
        return
    try:
        link.send("I?")
        check("hud: I? answered I,hud,2", link.line("I,hud", 2.0) is not None)
        link.send("P,1,100")
        check("hud: ping P,seq,us answered by Q,seq,us", link.line("Q,1", 2.0) is not None)
        line = link.line("J,", 2.0)
        if not check("hud: joystick line J,x,y,sw arrives (every 33 ms)", line is not None):
            return
        v = floats(split_csv(line), 4)
        if not check("hud: J parses as J,x,y,sw", v is not None, line):
            return
        check("hud: stick untouched reads 0,0 (centre calibrated at power-up)", v[1] == 0 and v[2] == 0, line)

        def stick(test):
            end = time.time() + 6.0
            while time.time() < end:
                w = floats(split_csv(link.line("J,", 1.0) or ""), 4)
                if w and test(w):
                    return True
            return False
        pause("then push the joystick FORWARD and hold it")
        check("hud: forward gives y > 60 (else set JOY_INVERT_Y)", stick(lambda w: w[2] > 60))
        pause("then push the joystick RIGHT and hold it")
        check("hud: right gives x > 60 (else set JOY_INVERT_X)", stick(lambda w: w[1] > 60))
        pause("then press and hold the joystick button")
        check("hud: button gives sw = 1", stick(lambda w: w[3] == 1))
        link.send("M,80,65,70,40")
        link.send("H,3")
        link.send("E,3")
        ask("hud: LCD shows PWR 80 O2 65 / FOOD 70 SHLD 40", "LCD shows the four numbers on two lines?")
        ask("hud: OLED shows BASE 3/5 and SAMPLES 3", "OLED shows hearts 3/5 and samples 3?")
        link.send("P")
        ask("hud: yellow LED blinks 5 times in 1 s and a short chirp", "Yellow LED blinked 5 times and the buzzer chirped?")
        link.send("Z,2")
        ask("hud: hot = red LED blinks, 2000 Hz fast beeps, LCD HOT", "Red LED blinking, fast high beeps, LCD shows HOT?")
        link.send("Z,1")
        ask("hud: cold = blue LED blinks, 400 Hz fast beeps, LCD COLD", "Blue LED blinking, fast low beeps, LCD shows COLD?")
        link.send("Z,0")
        link.send("V,118")
        link.send("Z,2")
        ask("hud: V,tempC shows on the LCD with the hot warning", "LCD line 2 shows COOLING 118C?")
        link.send("Z,0")
    finally:
        link.close()


# --------------------------------------------------------------- rover
def triage_robot(args):
    print("\n== Rover (UNO Q, Wi-Fi) ==")
    print("  safety: wheels on blocks for the drive checks")
    link = open_udp_or_serial(args, "rover", ROBOT_ADDR)
    if not link:
        return
    try:
        link.send("P,1,100")
        if not check("rover: ping answered by Q", link.line("Q,1", 3.0) is not None):
            return
        link.send("D,200,0,0")
        ask("rover: LEFT wheel only turns forward at D,200,0,0", "Left wheel forward, right wheel still?")
        link.send("D,0,200,0")
        ask("rover: RIGHT wheel only turns forward at D,0,200,0", "Right wheel forward, left wheel still?")
        link.send("D,200,200,0")
        ask("rover: both wheels forward at D,200,200,0", "Both wheels forward (W key = forward)?")
        link.send("D,-200,-200,0")
        ask("rover: both wheels reverse", "Both wheels backward?")
        link.send("D,0,0,0")
        link.send("D,200,-200,0")
        ask("rover: right turn = left wheel forward, right wheel back (D key)", "Rover turns right?")
        link.send("D,0,0,0")
        link.send("C,60")
        pause("camera should pan 60 degrees")
        link.send("C,-60")
        pause("camera should pan -60 degrees (left)")
        link.send("C,0")
        check("rover: pan lines sent (C,angle)", True)
        link.send("D,120,120,0")
        time.sleep(0.8)
        ask("rover: wheels stop 300 ms after the last D", "Wheels stopped by themselves?")
        pause("press and release the LEFT bumper button")
        check("rover: left bumper sends B,L", link.line("B,L", 5.0) is not None)
        pause("press and release the RIGHT bumper button")
        check("rover: right bumper sends B,R", link.line("B,R", 5.0) is not None)
    finally:
        link.send("D,0,0,0")
        link.close()


# --------------------------------------------------------------- tower
def triage_tower(args):
    print("\n== Asteroid tower (UNO R3, USB serial) ==")
    print("  safety: the green laser is always on. Nobody looks into it; the idle beam points at empty ceiling")
    link = open_serial_link(args, "tower")
    if not link:
        return
    try:
        link.send("I?")
        check("tower: I? answered I,tower,2", link.line("I,tower", 2.0) is not None)
        link.send("P,1,100")
        check("tower: ping P,seq,us answered by Q,seq,us", link.line("Q,1", 2.0) is not None)
        ask("tower: laser on, beam straight up", "Laser lit and pointing straight up?")
        pause("put the rover on the track, 40 to 100 cm in front of the tower")
        link.send("R")
        line = link.line("R,", 3.0)
        v = floats(split_csv(line or ""), 2)
        check("tower: R answered by R,cm inside 10..150 (999 = a loose TRIG / ECHO wire)", bool(v) and 10 <= v[1] <= 150, str(line))
        link.send("J")
        ask("tower: J jiggles the push servo once", "Servo jiggled?")
        link.send("F")
        link.send("P,2,100")
        check("tower: pings are answered during the sequence", link.line("Q,2", 2.0) is not None)
        check("tower: F answered by W,3 once the beam is down", link.line("W,3", 6.0) is not None)
        ask("tower: beam on the floor just ahead of the rover", "Laser spot on the floor just ahead of the rover? (else TILT_DIR, LASER_H_CM, LEAD_CM)")
        check("tower: K,1 about 3 s later (the rover stayed in the spot)", link.line("K,1", 5.0) is not None)
        ask("tower: servo jiggled on the hit and the beam went back up", "Jiggle, then beam straight up again?")
        time.sleep(2.5)
        pause("now press Enter, and drive or lift the rover off the track during the countdown")
        link.send("F")
        check("tower: second F warns again", link.line("W,3", 6.0) is not None)
        check("tower: K,0 when the rover left the spot", link.line("K,0", 5.0) is not None)
        time.sleep(2.5)
        pause("press the test button on the tower (D2), if fitted")
        check("tower: button runs the same W,3 then K", link.line("W,3", 8.0) is not None and link.line("K,", 5.0) is not None)
        link.send("Z")
        check("tower: Z sent (beam back up)", True)
    finally:
        link.close()


# --------------------------------------------------------------- wiring
# name, pin(s), kind  -> kinds: led active_buzzer tone analog button ultrasonic servo stepper motor lcd i2c
WIRES = {
    "weather": [
        ("joystick VRx", "A1", "analog"), ("joystick VRy", "A2", "analog"),
        ("joystick button", "D6", "button"),
        ("green LED", "D3", "led"),
        ("blue LED", "D4", "led"),
        ("red LED", "D5", "led"),
        ("yellow pickup LED", "A0", "led"),
        ("passive buzzer", "D7", "tone"),
        ("LCD RS", "D8", "lcd"), ("LCD E", "D9", "lcd"),
        ("LCD D4", "D10", "lcd"), ("LCD D5", "D11", "lcd"),
        ("LCD D6", "D12", "lcd"), ("LCD D7", "D13", "lcd"),
        ("I2C SDA", "SDA", "i2c"), ("I2C SCL", "SCL", "i2c"),
    ],
    "robot": [
        ("left bumper", "A2", "button"), ("right bumper", "A3", "button"),
        ("status LED", "D13", "led"),
        ("pan stepper IN1", "D4", "stepper"), ("pan stepper IN2", "D7", "stepper"),
        ("pan stepper IN3", "D8", "stepper"), ("pan stepper IN4", "D12", "stepper"),
        ("left motor DRV8833 IN1/IN2", "D5,D6", "motor2"),
        ("right motor DRV8833 IN1/IN2", "D9,D10", "motor2"),
    ],
    "tower": [
        ("test button (optional)", "D2", "button"),
        ("tilt stepper IN1", "D4", "stepper"), ("tilt stepper IN2", "D5", "stepper"),
        ("tilt stepper IN3", "D6", "stepper"), ("tilt stepper IN4", "D7", "stepper"),
        ("push servo", "D9", "servo"),
        ("HC-SR04 TRIG", "D11", "ultrasonic_trig"), ("HC-SR04 ECHO", "D12", "ultrasonic_echo"),
        ("green laser (2N2222)", "D13", "led"),
    ],
}


def bench_cmd(link, cmd, timeout=2.0):
    link.send(cmd)
    return link.line(None, timeout)


def triage_wiring(args):
    print("\n== Wiring triage (PinTester bench board) ==")
    link = open_serial_link(args, "PinTester")
    if not link:
        return
    try:
        hello = bench_cmd(link, "HELLO", 3.0)
        if not check("bench: HELLO answers OK,HELLO,PINTESTER",
                     hello is not None and "OK,HELLO,PINTESTER" in hello, str(hello)):
            return
        which = (_input("  which wire list (weather = HUD panel / robot / tower): ") or "").strip().lower()
        if which not in WIRES:
            print("  unknown list")
            return
        lcd_pins = []
        stepper_checked = False
        for name, pins, kind in WIRES[which]:
            print(f" - {name} on {pins}")
            pin = pins.split(",")[0]
            if kind == "led":
                bench_cmd(link, f"DW,{pin},1")
                ask(f"wiring: {name}", f"{name} lit?")
                bench_cmd(link, f"DW,{pin},0")
            elif kind == "active_buzzer":
                bench_cmd(link, f"DW,{pin},1")
                ask(f"wiring: {name}", f"{name} sounding?")
                bench_cmd(link, f"DW,{pin},0")
            elif kind == "tone":
                bench_cmd(link, f"TONE,{pin},1000,800")
                ask(f"wiring: {name}", f"Beep heard from {name}?")
            elif kind == "analog":
                reply = bench_cmd(link, f"AR,{pin}")
                ask(f"wiring: {name} reads mid-scale at rest", f"{name}: bench board answered {reply}. About half of full scale?")
            elif kind == "button":
                bench_cmd(link, f"WATCH,{pin}")
                pause(f"press and release {name}")
                hit = link.line("EDGE", 5.0)
                check(f"wiring: {name} seen", hit is not None, str(hit))
                bench_cmd(link, f"UNWATCH,{pin}")
            elif kind == "ultrasonic_trig":
                pass   # checked together with the echo wire
            elif kind == "ultrasonic_echo":
                trig = next(p for n, p, k in WIRES[which] if k == "ultrasonic_trig")
                pause("hold a hand or box about 10 cm from the HC-SR04")
                reply = bench_cmd(link, f"PING,{trig},{pin}")
                try:
                    cm = float(reply.split(",")[2])
                except (ValueError, IndexError, AttributeError):
                    cm = -1
                check("wiring: HC-SR04 reads ~10 cm", 3 <= cm <= 20, str(reply))
            elif kind == "servo":
                bench_cmd(link, f"SERVO,{pin},0")
                pause("servo went to 0 deg")
                bench_cmd(link, f"SERVO,{pin},180")
                ask(f"wiring: {name} swings full range", f"{name} moved to 180?")
                bench_cmd(link, f"SERVOOFF,{pin}")
            elif kind == "stepper":
                if stepper_checked:
                    continue   # one sweep exercises all four stepper wires
                pins4 = ",".join(p for n, p, k in WIRES[which] if k == "stepper")
                bench_cmd(link, f"STEP,{pins4},512,2", 4.0)
                ask("wiring: stepper shaft turns", "Stepper shaft rotated?")
                stepper_checked = True
            elif kind == "motor2":
                in1, in2 = pins.split(",")          # DRV8833: PWM on IN1 = forward, PWM on IN2 = reverse
                bench_cmd(link, f"PWM,{in1},150")
                ask(f"wiring: {name} forward on IN1", "That wheel spun forward?")
                bench_cmd(link, f"PWM,{in1},0")
                bench_cmd(link, f"PWM,{in2},150")
                ask(f"wiring: {name} reverse on IN2", "Same wheel spun backward?")
                bench_cmd(link, f"PWM,{in2},0")
            elif kind == "lcd":
                lcd_pins.append(pin)
            elif kind == "i2c":
                reply = bench_cmd(link, "I2CSCAN")
                found = reply and ("27" in reply or "3F" in reply)
                check(f"wiring: {name} (I2C device found)", bool(found), str(reply))
                ask(f"wiring: I2C display shows text", "Text visible on the I2C display?")
        if lcd_pins:
            bench_cmd(link, f"LCD,{','.join(lcd_pins)},TRIAGE|OK", 3.0)
            ask("wiring: LCD1602 shows TRIAGE / OK", "LCD1602 shows TRIAGE / OK?")
        bench_cmd(link, "ALLOFF")
    finally:
        link.close()


# --------------------------------------------------------------- camera
def _open_capture(src, mod, timeout_s=8.0):
    """Open a capture in a helper thread; None if it does not answer in time."""
    box = []

    def run():
        cap = mod.VideoCapture(src)
        ok = cap.isOpened() and cap.read()[0]
        box.append((cap, ok))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout_s)
    return box[0] if box else None


def triage_camera(args):
    print("\n== Camera ==")
    try:
        import cv2
    except ImportError:
        print("  opencv missing: pip install -r requirements.txt")
        skip("camera: stream opens", "no opencv")
        return
    urls = [args.url] if args.url else CAMERA_URLS
    cap = None
    used = None
    for url in urls:
        src = int(url) if url.isdigit() else url
        print(f"  trying {url} (max 8 s) ...")
        got = _open_capture(src, cv2)
        if got and got[1]:
            cap, used = got
            break
        if got:
            got[0].release()
    if not check("camera: stream opens", cap is not None):
        return
    n, t0 = 0, time.monotonic()
    while n < 60:
        ok, frame = cap.read()
        if not ok:
            break
        n += 1
    dt = time.monotonic() - t0
    fps = n / dt if dt else 0
    h, w = frame.shape[:2] if n else (0, 0)
    check("camera: frames keep flowing (60 read)", n >= 60, f"read {n}")
    check("camera: resolution near 320x240", abs(w - 320) <= 80 and abs(h - 240) <= 60, f"{w}x{h}")
    check("camera: fps at least 5 (doc wants 15-20)", fps >= 5, f"{fps:.1f} fps")
    print(f"  source: {used}")
    cap.release()
    ask("camera: picture is live and usable", "Picture live, right scene, steering still feels instant?")


# --------------------------------------------------------------- gamepad
def triage_gamepad(args):
    print("\n== Gamepad ==")
    try:
        import pygame
    except ImportError:
        print("  pygame missing: pip install -r requirements.txt")
        skip("gamepad: detected", "no pygame")
        return
    pygame.init()
    pygame.joystick.init()
    n = pygame.joystick.get_count()
    if not check("gamepad: at least one controller found", n > 0):
        return
    js = pygame.joystick.Joystick(0)
    js.init()
    print(f"  {js.get_name()}: {js.get_numaxes()} axes, {js.get_numbuttons()} buttons")
    print("  move the sticks for 4 s; sample of raw values:")
    end = time.monotonic() + 4.0
    while time.monotonic() < end:
        pygame.event.pump()
        axes = [f"{js.get_axis(i):+.2f}" for i in range(js.get_numaxes())]
        print("    " + " ".join(axes))
        time.sleep(0.5)
    ask("gamepad: axes and buttons respond", "Every axis and button moved and read cleanly?")


# --------------------------------------------------------------- main
BOARD_FUN = {
    "weather": triage_weather,
    "robot": triage_robot,
    "tower": triage_tower,
    "wiring": triage_wiring,
    "camera": triage_camera,
    "gamepad": triage_gamepad,
}


def main():
    ap = argparse.ArgumentParser(description="T-Minus_6 hardware triage")
    ap.add_argument("board", nargs="?", default="all",
                    choices=("all",) + tuple(BOARD_FUN))
    ap.add_argument("--port", help="serial port, e.g. COM5 or /dev/ttyACM0")
    ap.add_argument("--url", help="camera stream URL instead of the defaults")
    args = ap.parse_args()

    boards = list(BOARD_FUN) if args.board == "all" else [args.board]
    if args.board == "all":
        print("T-Minus_6 hardware triage - hardware in this order, Enter between steps")
    for b in boards:
        if args.board == "all":
            if (_input(f"\nRun {b} now? [Enter=skip / y=run] ") or "").strip().lower() not in ("y", "yes"):
                skip(f"{b}: triage", "skipped by user")
                continue
        BOARD_FUN[b](args)
    sys.exit(summary())


if __name__ == "__main__":
    main()
