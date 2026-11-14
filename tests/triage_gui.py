#!/usr/bin/env python3
"""T-Minus_6 hardware triage GUI (simple version).

    pip install -r requirements.txt
    python tests/triage_gui.py

Connect the boards at the top, then use one tab per part. Each tab has buttons that
send the real protocol lines, a live readout, and a short checklist you tick by hand.
"Save report" writes the ticked checklists to tests/reports/.

The weather LCD (16-pin LCD1602) is wired to the weather station UNO R3 and driven by
weather_station.ino, so it is tested from the Weather tab through that board's own
commands (V / H / G / R), not through the bench board.

The step-by-step acceptance walk-through is the command line tool tests/triage.py.
"""
import os
import re
import sys
import threading
import time

from PyQt5 import QtCore, QtGui, QtWidgets

import gamepad_io
from gui_common import (CAMERA_URLS, DEVICES, REPORT_DIR, Link, bgr_to_qimage, laptop_config,
                        list_serial_ports, load_settings, open_capture, parse_line, save_settings)
from gui_widgets import RadarWidget, VideoWidget

Qt = QtCore.Qt
STATE_COLOUR = {"closed": "#888888", "connecting": "#d29922", "open": "#3fb950", "error": "#f85149"}
PIN_RE = re.compile(r"^[DA]\d{1,2}$")


def hint(text):
    lab = QtWidgets.QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet("color:#555;")
    return lab


def big(text, px=28):
    lab = QtWidgets.QLabel(text)
    lab.setStyleSheet(f"font-size:{px}px; font-weight:bold;")
    return lab


class Tab(QtWidgets.QWidget):
    """A page with a 'controls' column on the left and a checklist under it."""
    checks = ()

    def __init__(self, links):
        super().__init__()
        self.links = links
        self.boxes = []

    def checklist(self):
        box = QtWidgets.QGroupBox("Checklist (tick what you saw working)")
        lay = QtWidgets.QVBoxLayout(box)
        for text in self.checks:
            cb = QtWidgets.QCheckBox(text)
            self.boxes.append(cb)
            lay.addWidget(cb)
        return box

    def results(self):
        return [(cb.text(), cb.isChecked()) for cb in self.boxes]

    def stop(self):
        """Called by STOP ALL and when the window closes."""


# --------------------------------------------------------------------- weather
class WeatherTab(Tab):
    checks = (
        "W,temp,hum,state line arrives about every 2 s",
        "DHT11 temperature and humidity look right for the room",
        "LCD shows text (if only a blue block: turn the contrast pot)",
        "NORMAL: green LED solid, silent, LCD 'T xx.xC NORMAL' / 'H nn%'",
        "Buzz (BZ): the D7 buzzer beeps for 0.5 s",
        "HOT (V,35): red LED blinks, buzzer beeps fast (100 ms), LCD '!! HOT ZONE !!'",
        "COLD (V,10): blue LED blinks, buzzer beeps slower (200 ms), LCD '!! COLD ZONE !!'",
        "Hit (H,14): yellow hit LED on A0 lights for 1 s",
        "Game over (G): LEDs off, silent, LCD 'SIGNAL LOST' / 'GAME OVER'",
        "Custom text (L,line1|line2) shows on both LCD lines",
        "Reset (R): back to green and the real temperature",
    )
    BUTTONS = (
        ("Normal  (V,24)", "V,24", "green LED solid, silent"),
        ("Buzz D7  (BZ)", "BZ", "buzzer on D7 sounds for 0.5 s"),
        ("Hot  (V,35)", "V,35", "red LED blinks, buzzer beeps fast (100 ms on/off)"),
        ("Cold  (V,10)", "V,10", "blue LED blinks, buzzer beeps slower (200 ms on/off)"),
        ("Hit  (H,14)", "H,14", "yellow hit LED for 1 s, LCD unchanged"),
        ("Game over  (G)", "G", "all LEDs off, silent"),
        ("Reset  (R)", "R", "real sensor again, 15 lives"),
    )
    STATE = {0: ("NORMAL", "#2e7d32"), 1: ("COLD", "#1565c0"), 2: ("HOT", "#c62828")}

    def __init__(self, links):
        super().__init__(links)
        self.link = links["weather"]
        self.last_t = None
        self.reading = None          # (temp, hum, state)
        self.game_over = False
        self.custom = None           # (line1, line2) while L,text is pinned

        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        row = QtWidgets.QHBoxLayout()
        self.temp = big("--.- C", 40)
        self.hum = big("-- %", 28)
        self.state = big("NO DATA", 24)
        self.state.setAlignment(Qt.AlignCenter)
        self.state.setMinimumWidth(150)
        row.addWidget(self.temp)
        row.addWidget(self.hum)
        row.addStretch(1)
        row.addWidget(self.state)
        left.addLayout(row)
        self.age = QtWidgets.QLabel("no reading yet")
        left.addWidget(self.age)

        cmds = QtWidgets.QGroupBox("Send to the weather station")
        g = QtWidgets.QGridLayout(cmds)
        for i, (label, line, expect) in enumerate(self.BUTTONS):
            b = QtWidgets.QPushButton(label)
            b.setMinimumWidth(140)
            b.clicked.connect(lambda _, line=line: self.send(line))
            g.addWidget(b, i, 0)
            g.addWidget(hint(expect), i, 1)
        left.addWidget(cmds)
        left.addWidget(hint("Close the game first: only one program can open the UNO R3's COM port. "
                            "V makes the board ignore the DHT11 until R. Breathe on or warm the DHT11 "
                            "for a real test (above 30 C is HOT, below 18 C is COLD, 1 C hysteresis)."))
        left.addStretch(1)
        lay.addLayout(left, 3)

        right = QtWidgets.QVBoxLayout()
        lcd_box = QtWidgets.QGroupBox("LCD1602 should show")
        ll = QtWidgets.QVBoxLayout(lcd_box)
        self.lcd = QtWidgets.QLabel()
        self.lcd.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.lcd.setStyleSheet("background:#1d3fbf; color:#e8f0ff; font-size:22px; padding:10px 14px;"
                               "border:6px solid #222; border-radius:4px;")
        self.lcd.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ll.addWidget(self.lcd)
        row = QtWidgets.QHBoxLayout()
        self.text = QtWidgets.QLineEdit()
        self.text.setMaxLength(33)
        self.text.setPlaceholderText("custom text: line 1|line 2 (16 characters each)")
        self.text.returnPressed.connect(self._send_text)
        send = QtWidgets.QPushButton("Send")
        send.clicked.connect(self._send_text)
        back = QtWidgets.QPushButton("Back to weather")
        back.clicked.connect(lambda: self.send("L,"))
        row.addWidget(self.text, 1)
        row.addWidget(send)
        row.addWidget(back)
        ll.addLayout(row)
        ll.addWidget(hint("Driven by the weather station UNO R3 (weather_station.ino): RS D8, E D9, "
                          "D4-D7 to D10-D13, RW (pin 5) to GND, contrast pot wiper to V0. The board "
                          "redraws the temperature every 5 s and a warning at once."))
        right.addWidget(lcd_box)
        right.addWidget(self.checklist())
        right.addStretch(1)
        lay.addLayout(right, 2)

        self.link.line_received.connect(self._on_line)
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(500)
        self._draw_lcd()

    def send(self, line):
        if not self.link.send(line):
            self.age.setText("weather station is not connected")
            return
        if line == "G":
            self.game_over = True
        elif line == "R":
            self.game_over, self.custom = False, None
        elif line.startswith("L,"):
            parts = (line[2:].split("|", 1) + [""])[:2]
            self.custom = (parts[0][:16], parts[1][:16]) if line[2:] else None
        self._draw_lcd()

    def _send_text(self):
        text = self.text.text().encode("ascii", "replace").decode()    # the LCD has no accents or emoji
        if text.strip():
            self.send("L," + text)

    def _on_line(self, line):
        v = parse_line(line, "W", 3)
        if not v:
            return
        temp, hum, st = v
        self.reading = (temp, hum, int(st))
        self.last_t = time.monotonic()
        self.temp.setText(f"{temp:.1f} C")
        self.hum.setText(f"{hum:.0f} %")
        name, colour = self.STATE.get(int(st), ("?", "#555"))
        self.state.setText(name)
        self.state.setStyleSheet(f"font-size:24px; font-weight:bold; background:{colour}; color:white;"
                                 "border-radius:6px; padding:6px;")
        self._draw_lcd()

    def _draw_lcd(self):
        """Same text as showWeather() in weather_station.ino."""
        if self.custom:
            l1, l2 = self.custom
        elif self.game_over:
            l1, l2 = "SIGNAL LOST", "GAME OVER"
        elif self.reading is None:
            l1, l2 = "(waiting for W)", ""
        else:
            temp, hum, st = self.reading
            if st == 2:
                l1, l2 = "!! HOT ZONE !!", "MOVE AWAY NOW!"
            elif st == 1:
                l1, l2 = "!! COLD ZONE !!", "MOVE AWAY NOW!"
            else:
                l1, l2 = f"T {temp:4.1f}C NORMAL", f"H {int(hum)}%"
        self.lcd.setText(f"{l1:<16.16}\n{l2:<16.16}")

    def _tick(self):
        if self.last_t is not None:
            self.age.setText(f"last W line {time.monotonic() - self.last_t:.1f} s ago (expect one every 2 s)")


# ----------------------------------------------------------------------- robot
class RobotTab(Tab):
    checks = (
        "S,angle,dist,flags lines arrive, sweep covers about -45 to +45 deg",
        "Hand at 10 cm reads about 10 cm",
        "Closer than 8 cm: STOP flag lights and Forward is refused",
        "Forward / Back: all four wheels turn the same way",
        "Left / Right: tank turn",
        "Wheels stop within 300 ms of releasing the button",
        "Left and right bumpers send B,L / B,R",
        "Auto-pilot flag turns the status LED on",
        "X latches the robot stopped, R releases it",
    )

    def __init__(self, links):
        super().__init__(links)
        self.link = links["robot"]
        self.cmd = (0, 0)
        self.s_times = []
        lay = QtWidgets.QHBoxLayout(self)

        left = QtWidgets.QVBoxLayout()
        self.safe = QtWidgets.QCheckBox("Wheels are off the ground / area is clear")
        left.addWidget(self.safe)
        grid = QtWidgets.QGridLayout()
        for name, (r, c), (sl, sr) in (("Forward", (0, 1), (1, 1)), ("Left", (1, 0), (-1, 1)),
                                       ("Right", (1, 2), (1, -1)), ("Back", (2, 1), (-1, -1))):
            b = QtWidgets.QPushButton(name)
            b.setMinimumSize(90, 50)
            b.pressed.connect(lambda sl=sl, sr=sr: self._hold(sl, sr))
            b.released.connect(self.stop)
            grid.addWidget(b, r, c)
        stop = QtWidgets.QPushButton("STOP")
        stop.setMinimumSize(90, 50)
        stop.setStyleSheet("background:#b3261e; color:white; font-weight:bold;")
        stop.clicked.connect(self.stop)
        grid.addWidget(stop, 1, 1)
        left.addLayout(grid)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Speed"))
        self.speed = QtWidgets.QSpinBox()
        self.speed.setRange(0, 255)
        self.speed.setValue(120)
        row.addWidget(self.speed)
        self.ap = QtWidgets.QCheckBox("auto-pilot flag")
        self.ap.toggled.connect(lambda on: self.link.send(f"D,0,0,{int(on)}"))
        row.addWidget(self.ap)
        row.addStretch(1)
        left.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        for label, line in (("Latch stop (X)", "X"), ("Reset (R)", "R")):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(lambda _, line=line: self.link.send(line))
            row.addWidget(b)
        left.addLayout(row)
        left.addWidget(hint("Hold a button to drive: D,left,right,ap is resent 20 times a second; the "
                            "robot stops by itself 300 ms after the commands stop."))
        left.addWidget(self.checklist())
        left.addStretch(1)
        lay.addLayout(left, 2)

        right = QtWidgets.QVBoxLayout()
        self.radar = RadarWidget()
        right.addWidget(self.radar, 1)
        self.readout = QtWidgets.QLabel("no scan yet")
        right.addWidget(self.readout)
        self.flags = QtWidgets.QLabel("")
        right.addWidget(self.flags)
        lay.addLayout(right, 3)

        self.link.line_received.connect(self._on_line)
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._resend)
        timer.start(50)

    def _hold(self, sl, sr):
        if not self.safe.isChecked():
            self.readout.setText("tick the safety box first")
            return
        s = self.speed.value()
        self.cmd = (sl * s, sr * s)
        self._resend()

    def _resend(self):
        if self.cmd != (0, 0):
            self.link.send(f"D,{self.cmd[0]},{self.cmd[1]},{int(self.ap.isChecked())}", quiet=True)

    def stop(self):
        self.cmd = (0, 0)
        for _ in range(2):
            self.link.send(f"D,0,0,{int(self.ap.isChecked())}", quiet=True)

    def _on_line(self, line):
        v = parse_line(line, "S", 3)
        if v:
            angle, cm, flag = v
            self.radar.add(angle, cm)
            now = time.monotonic()
            self.s_times = [t for t in self.s_times if now - t < 3.0] + [now]
            rate = f"   {(len(self.s_times) - 1) / (now - self.s_times[0]):.1f} scans/s" \
                if len(self.s_times) > 3 else ""
            dist = "no echo" if cm >= 400 else f"{cm:.0f} cm"
            stop = "   STOP (< 8 cm)" if flag >= 1 else ""
            self.readout.setText(f"angle {angle:+.0f} deg   {dist}{rate}{stop}")
        elif line.startswith("B,"):
            self.flags.setText(f"bumper {line[2:].strip()} at {time.strftime('%H:%M:%S')}")


# ----------------------------------------------------------------------- tower
class TowerTab(Tab):
    checks = (
        "Armed LED is on after R",
        "F is answered by K",
        "Exactly one ball drops per F",
        "Board does not reset when the servo moves",
        "X disarms: armed LED off and F is ignored",
        "Test button on the tower fires one ball",
        "Ball reaches the robot area in 2-3 s",
    )

    def __init__(self, links):
        super().__init__(links)
        self.link = links["tower"]
        self.sent = self.acks = 0
        self.t_fire = None
        lay = QtWidgets.QVBoxLayout(self)
        self.safe = QtWidgets.QCheckBox("Line of fire is clear: nobody in front of the tower")
        lay.addWidget(self.safe)
        self.fire = QtWidgets.QPushButton("FIRE  (F)")
        self.fire.setMinimumHeight(70)
        self.fire.setEnabled(False)
        self.fire.setStyleSheet("QPushButton{background:#b3261e; color:white; font-size:24px; font-weight:bold;}"
                                "QPushButton:disabled{background:#e6b9b6; color:#888;}")
        self.safe.toggled.connect(self.fire.setEnabled)
        self.fire.clicked.connect(self._fire)
        lay.addWidget(self.fire)
        row = QtWidgets.QHBoxLayout()
        for label, line in (("Arm (R)", "R"), ("Disarm (X)", "X")):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(lambda _, line=line: self.link.send(line))
            row.addWidget(b)
        lay.addLayout(row)
        self.stats = QtWidgets.QLabel()
        lay.addWidget(self.stats)
        lay.addWidget(hint("The optional pan servo takes A,angle: type it in the send box under the log."))
        lay.addWidget(self.checklist())
        lay.addStretch(1)
        self.link.line_received.connect(self._on_line)
        self._show()

    def _show(self, extra=""):
        self.stats.setText(f"F sent: {self.sent}    K received: {self.acks}    {extra}")

    def _fire(self):
        if self.link.send("F"):
            self.sent += 1
            self.t_fire = time.monotonic()
            self._show("waiting for K ...")

    def _on_line(self, line):
        if line.strip() != "K":
            return
        self.acks += 1
        if self.t_fire is None:
            self._show("K without F (test button)")
        else:
            self._show(f"F to K: {(time.monotonic() - self.t_fire) * 1000:.0f} ms")
            self.t_fire = None

    def stop(self):
        self.safe.setChecked(False)


# ----------------------------------------------------------------------- bench
class BenchTab(Tab):
    """Stepper and servo through PinTester.ino on a spare UNO (the game firmware has no commands for them)."""
    checks = (
        "Stepper turns one way for + steps and back for - steps",
        "Stepper: 4096 half steps is one full turn",
        "Servo follows 0 / 90 / 180 deg without jitter",
    )

    def __init__(self, links):
        super().__init__(links)
        self.link = links["bench"]
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(hint("Upload tests/PinTester.ino to a spare UNO and connect it as 'Bench board'. "
                           "Power servos and the stepper from their own 5 V and share GND."))

        st = QtWidgets.QGroupBox("Stepper (28BYJ-48 + ULN2003)")
        sl = QtWidgets.QHBoxLayout(st)
        sl.addWidget(QtWidgets.QLabel("IN1-IN4"))
        self.step_pins = QtWidgets.QLineEdit("D9,D10,D11,D12")
        sl.addWidget(self.step_pins)
        self.steps = QtWidgets.QSpinBox()
        self.steps.setRange(-8192, 8192)
        self.steps.setValue(1024)
        sl.addWidget(self.steps)
        move = QtWidgets.QPushButton("Move")
        move.clicked.connect(self._move)
        sl.addWidget(move)
        off = QtWidgets.QPushButton("Release coils")
        off.clicked.connect(self.stop)
        sl.addWidget(off)
        lay.addWidget(st)

        sv = QtWidgets.QGroupBox("Servo (SG90)")
        vl = QtWidgets.QHBoxLayout(sv)
        vl.addWidget(QtWidgets.QLabel("Pin"))
        self.servo_pin = QtWidgets.QLineEdit("D9")
        self.servo_pin.setMaximumWidth(60)
        vl.addWidget(self.servo_pin)
        for a in (0, 45, 90, 135, 180):
            b = QtWidgets.QPushButton(f"{a} deg")
            b.clicked.connect(lambda _, a=a: self._servo(a))
            vl.addWidget(b)
        detach = QtWidgets.QPushButton("Detach")
        detach.clicked.connect(lambda: self._pin_cmd("SERVOOFF", self.servo_pin.text()))
        vl.addWidget(detach)
        lay.addWidget(sv)

        self.status = QtWidgets.QLabel("")
        lay.addWidget(self.status)
        lay.addWidget(self.checklist())
        lay.addStretch(1)
        self.link.line_received.connect(self._on_line)

    def _pin_cmd(self, cmd, pins, *rest):
        pins = pins.replace(" ", "").upper()
        if not all(PIN_RE.match(p) for p in pins.split(",")):
            self.status.setText("pins look like D9 or D9,D10,D11,D12")
            return
        if not self.link.send(",".join([cmd, pins] + [str(r) for r in rest])):
            self.status.setText("bench board is not connected")

    def _move(self):
        if len(self.step_pins.text().split(",")) != 4:
            self.status.setText("the stepper needs four pins")
            return
        self._pin_cmd("STEP", self.step_pins.text(), self.steps.value(), 2)

    def _servo(self, angle):
        self._pin_cmd("SERVO", self.servo_pin.text(), angle)

    def _on_line(self, line):
        if line.startswith(("OK,", "ERR,", "DONE,")):
            self.status.setText(line)

    def stop(self):
        self.link.send("ALLOFF")


# ---------------------------------------------------------------------- camera
class CameraTab(Tab):
    checks = (
        "Stream opens",
        "Resolution about 320x240",
        "15-20 fps",
        "Delay looks short when you wave a hand",
    )
    frame = QtCore.pyqtSignal(QtGui.QImage)
    info_text = QtCore.pyqtSignal(str)

    def __init__(self, links, url_box):
        super().__init__(links)
        self.url_box = url_box
        self._stop = None
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.btn = QtWidgets.QPushButton("Start")
        self.btn.clicked.connect(self._toggle)
        left.addWidget(self.btn)
        self.info = QtWidgets.QLabel("stopped")
        self.info.setWordWrap(True)
        left.addWidget(self.info)
        left.addWidget(hint("Uses the camera URL at the top (a number such as 0 opens a local webcam)."))
        left.addWidget(self.checklist())
        left.addStretch(1)
        lay.addLayout(left, 1)
        self.video = VideoWidget()
        lay.addWidget(self.video, 2)
        self.frame.connect(self.video.set_image)
        self.info_text.connect(self.info.setText)

    def _toggle(self):
        if self._stop is not None:
            self.stop()
            return
        url = self.url_box.currentText().strip()
        if not url:
            self.info.setText("enter a camera URL at the top")
            return
        self._stop = threading.Event()
        threading.Thread(target=self._run, args=(url, self._stop), daemon=True).start()
        self.btn.setText("Stop")

    def _run(self, url, stop):
        try:
            import cv2
        except ImportError:
            self.info_text.emit("opencv missing: pip install -r requirements.txt")
            return
        self.info_text.emit(f"connecting to {url} (up to 8 s) ...")
        cap = open_capture(int(url) if url.isdigit() else url, cv2, 8.0, stop)
        if cap is None:
            if not stop.is_set():
                self.info_text.emit("could not open the stream")
            return
        n, t0 = 0, time.monotonic()
        while not stop.is_set():
            ok, img = cap.read()
            if not ok:
                self.info_text.emit("stream lost")
                break
            n += 1
            self.frame.emit(bgr_to_qimage(img))
            now = time.monotonic()
            if now - t0 >= 1.0:
                h, w = img.shape[:2]
                self.info_text.emit(f"live   {w}x{h}   {n / (now - t0):.1f} fps")
                n, t0 = 0, now
        cap.release()

    def stop(self):
        if self._stop is not None:
            self._stop.set()
            self._stop = None
            self.btn.setText("Start")
            self.info.setText("stopped")
            self.video.clear_image()


# --------------------------------------------------------------------- gamepad
class GamepadTab(Tab):
    checks = (
        "Controller found after pairing",
        "Sticks rest inside the dead zone",
        "Sticks reach about -1 and +1 at full travel",
        "Y / B / Start numbers match laptop/config.py",
    )

    def __init__(self, links):
        super().__init__(links)
        cfg = laptop_config()
        self.dead = float(cfg["DEAD_ZONE"])
        self.prev = []
        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.pads = QtWidgets.QComboBox()
        rescan = QtWidgets.QPushButton("Rescan")
        rescan.clicked.connect(self._rescan)
        self.pads.currentIndexChanged.connect(self._select)
        row.addWidget(self.pads, 1)
        row.addWidget(rescan)
        lay.addLayout(row)
        self.info = QtWidgets.QLabel("no controller")
        lay.addWidget(self.info)
        self.axes = QtWidgets.QLabel("")
        self.axes.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        lay.addWidget(self.axes)
        self.buttons = QtWidgets.QLabel("")
        self.buttons.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        lay.addWidget(self.buttons)
        self.last = big("press a button to see its number", 18)
        lay.addWidget(self.last)
        lay.addWidget(hint(f"laptop/config.py expects: Y = {cfg['BTN_AUTOPILOT']} (auto-pilot), "
                           f"B = {cfg['BTN_CAMERA']} (camera), Start = {cfg['BTN_RESTART']} (restart); "
                           f"turn axis {cfg['AXIS_TURN']}, speed axis {cfg['AXIS_SPEED']}, "
                           f"dead zone {self.dead:.2f}."))
        lay.addWidget(self.checklist())
        lay.addStretch(1)
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._poll)
        timer.start(30)
        QtCore.QTimer.singleShot(0, self._rescan)

    def _rescan(self):
        if not gamepad_io.available():
            self.info.setText("pygame is missing: pip install -r requirements.txt")
            return
        found = gamepad_io.rescan()
        self.pads.blockSignals(True)
        self.pads.clear()
        for i, name in found:
            self.pads.addItem(f"{i}: {name}", i)
        self.pads.blockSignals(False)
        if found:
            self._select()
        else:
            gamepad_io.select(-1)
            self.info.setText("No controller found. Pair it over Bluetooth, wake it, then press Rescan.")

    def _select(self):
        idx = self.pads.currentData()
        if idx is not None:
            self.info.setText(gamepad_io.select(idx) or "could not open that controller")

    def _poll(self):
        st = gamepad_io.read()
        if st is None:
            return
        self.axes.setText("axes     " + "  ".join(
            f"{i}:{v:+.2f}{'' if abs(v) < self.dead else '*'}" for i, v in enumerate(st["axes"]))
            + "     (* = outside the dead zone)")
        self.buttons.setText("buttons  " + " ".join(f"[{i}]" if b else f" {i} " for i, b in enumerate(st["buttons"])))
        for i, b in enumerate(st["buttons"]):
            if b and (i >= len(self.prev) or not self.prev[i]):
                self.last.setText(f"last button pressed: {i}")
        self.prev = list(st["buttons"])


# ----------------------------------------------------------------- main window
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("T-Minus_6 hardware triage")
        self.settings = load_settings()
        self.links = {key: Link(key) for key, _, _ in DEVICES}
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)

        # ---- connections
        conn = QtWidgets.QGroupBox("Connections  (COM port for USB, ip:port for the UNO Qs)")
        conn.setObjectName("conn")
        conn.setStyleSheet("QGroupBox#conn{background:#000; color:#fff; border:1px solid #333; border-radius:4px;"
                           "margin-top:0; padding-top:24px;}"
                           "QGroupBox#conn::title{subcontrol-origin:padding; subcontrol-position:top left;"
                           "left:8px; top:4px; color:#fff;}"
                           "QGroupBox#conn QLabel{color:#e8e8e8; background:transparent;}")
        grid = QtWidgets.QGridLayout(conn)
        self.rows = {}
        saved = self.settings.get("targets", {})
        for i, (key, label, default) in enumerate(DEVICES):
            combo = QtWidgets.QComboBox()
            combo.setEditable(True)
            combo.setMinimumWidth(220)
            btn = QtWidgets.QPushButton("Connect")
            status = QtWidgets.QLabel()
            r, c = divmod(i, 2)
            grid.addWidget(QtWidgets.QLabel(label), r, c * 4)
            grid.addWidget(combo, r, c * 4 + 1)
            grid.addWidget(btn, r, c * 4 + 2)
            grid.addWidget(status, r, c * 4 + 3)
            self.rows[key] = (combo, btn, status, default, saved.get(key))
            btn.clicked.connect(lambda _, k=key: self._toggle(k))
            self.links[key].state_changed.connect(lambda s, d, k=key: self._on_state(k, s, d))
            self._on_state(key, "closed", "")
        self.cam_url = QtWidgets.QComboBox()
        self.cam_url.setEditable(True)
        self.cam_url.addItems(CAMERA_URLS + ["0"])
        if self.settings.get("camera"):
            self.cam_url.setEditText(self.settings["camera"])
        refresh = QtWidgets.QPushButton("Refresh COM ports")
        refresh.clicked.connect(self._fill_ports)
        n = (len(DEVICES) + 1) // 2
        grid.addWidget(QtWidgets.QLabel("Camera URL"), n, 0)
        grid.addWidget(self.cam_url, n, 1, 1, 2)
        grid.addWidget(refresh, n, 5, 1, 2)
        self._fill_ports(first=True)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(conn, 1)
        side = QtWidgets.QVBoxLayout()
        estop = QtWidgets.QPushButton("STOP ALL")
        estop.setMinimumHeight(50)
        estop.setStyleSheet("background:#b3261e; color:white; font-weight:bold; font-size:16px;")
        estop.setToolTip("Stop the wheels, disarm the tower, release the bench board, stop the camera")
        estop.clicked.connect(self.stop_all)
        report = QtWidgets.QPushButton("Save report")
        report.clicked.connect(self.save_report)
        side.addWidget(estop)
        side.addWidget(report)
        side.addStretch(1)
        top.addLayout(side)
        outer.addLayout(top)

        # ---- one tab per part
        self.tabs = QtWidgets.QTabWidget()
        self.pages = [("Weather + LCD", WeatherTab(self.links)), ("Robot", RobotTab(self.links)),
                      ("Tower", TowerTab(self.links)), ("Bench (stepper/servo)", BenchTab(self.links)),
                      ("Camera", CameraTab(self.links, self.cam_url)), ("Gamepad", GamepadTab(self.links))]
        for title, page in self.pages:
            self.tabs.addTab(page, title)
        self.tabs.setCurrentIndex(int(self.settings.get("tab", 0)) % len(self.pages))
        self.tabs.currentChanged.connect(lambda _: self.pages[1][1].stop())    # no driving from a hidden tab

        # ---- log + raw send
        logw = QtWidgets.QWidget()
        ll = QtWidgets.QVBoxLayout(logw)
        ll.setContentsMargins(0, 0, 0, 0)
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(1500)
        self.log_box.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        ll.addWidget(self.log_box)
        row = QtWidgets.QHBoxLayout()
        self.raw_to = QtWidgets.QComboBox()
        for key, _, _ in DEVICES:
            self.raw_to.addItem(key)
        self.raw = QtWidgets.QLineEdit()
        self.raw.setPlaceholderText("send any line, e.g. I?  V,35  A,90  PING,D7,D8")
        self.raw.returnPressed.connect(self._send_raw)
        self.hide_s = QtWidgets.QCheckBox("hide S, scan lines")
        self.hide_s.setChecked(True)
        clear = QtWidgets.QPushButton("Clear log")
        clear.clicked.connect(self.log_box.clear)
        row.addWidget(QtWidgets.QLabel("Send to"))
        row.addWidget(self.raw_to)
        row.addWidget(self.raw, 1)
        row.addWidget(self.hide_s)
        row.addWidget(clear)
        ll.addLayout(row)

        split = QtWidgets.QSplitter(Qt.Vertical)
        split.addWidget(self.tabs)
        split.addWidget(logw)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)

        for key, link in self.links.items():
            link.line_received.connect(lambda t, k=key: self._rx(k, t))
            link.tx.connect(lambda t, k=key: self.log(f"{k} -> {t}"))
            link.state_changed.connect(lambda s, d, k=key: s != "connecting" and self.log(f"{k}: {s} {d}".rstrip()))

    # -- connections
    def _fill_ports(self, first=False):
        ports = list_serial_ports()
        for key, (combo, _, _, default, saved) in self.rows.items():
            keep = saved if first else combo.currentText()
            combo.clear()
            if default:
                combo.addItem(default)
            combo.addItems([f"{dev}  ({desc})" if desc else dev for dev, desc in ports])
            if keep:
                combo.setEditText(keep)

    def _toggle(self, key):
        link = self.links[key]
        if link.state in ("open", "connecting"):
            link.close_link()
        else:
            link.open_link(self.rows[key][0].currentText())

    def _on_state(self, key, state, detail):
        _, btn, status, _, _ = self.rows[key]
        btn.setText({"open": "Disconnect", "connecting": "Cancel"}.get(state, "Connect"))
        text = {"closed": "not connected", "open": "connected"}.get(state, detail or state)
        status.setText(f"<span style='color:{STATE_COLOUR[state]}; font-size:16px;'>&#9679;</span> {text}")

    # -- log
    def log(self, text):
        self.log_box.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    def _rx(self, key, text):
        if not (self.hide_s.isChecked() and text.startswith("S,")):
            self.log(f"{key} <- {text}")

    def _send_raw(self):
        key, line = self.raw_to.currentText(), self.raw.text().strip()
        if line and not self.links[key].send(line):
            self.log(f"{key}: not connected")
        self.raw.clear()

    # -- actions
    def stop_all(self):
        for _, page in self.pages:
            page.stop()
        self.links["robot"].send("D,0,0,0", quiet=True)
        self.links["tower"].send("X")
        self.log("STOP ALL")

    def save_report(self):
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = os.path.join(REPORT_DIR, time.strftime("triage_%Y%m%d_%H%M%S.md"))
        lines = [f"# T-Minus_6 triage {time.strftime('%Y-%m-%d %H:%M')}", ""]
        for key, (combo, _, _, _, _) in self.rows.items():
            lines.append(f"- {key}: {self.links[key].state} ({combo.currentText().strip() or '-'})")
        for title, page in self.pages:
            lines += ["", f"## {title}", ""]
            lines += [f"- [{'x' if ok else ' '}] {text}" for text, ok in page.results()]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self.log(f"report saved: {path}")

    def closeEvent(self, e):
        self.stop_all()
        save_settings({"tab": self.tabs.currentIndex(), "camera": self.cam_url.currentText().strip(),
                       "targets": {k: row[0].currentText().strip() for k, row in self.rows.items()}})
        for link in self.links.values():
            link.close_link()
        super().closeEvent(e)


def main():
    QtWidgets.QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(app.style().standardPalette())
    win = MainWindow()
    win.resize(1200, 820)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
