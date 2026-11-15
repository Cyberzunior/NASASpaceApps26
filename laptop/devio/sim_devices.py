"""Software versions of every device. They speak the real line protocol: the rover over UDP on the loopback interface
(so the real link code runs), the tower and the HUD panel over a fake serial port (so the real handshake runs).

SimRobot integrates the SAME model as the game, has the firmware's 300 ms timeout and the X/R latch, and records the wheel
values and camera pan it was given. SimTower is the v3 pan/tilt firmware (Y, T, L, R, ?). SimHud is the HUD panel firmware: it
keeps the LCD text, LEDs, buzzer and OLED numbers the real one would show and sends the joystick as J,x,y,sw."""
import collections
import math
import socket
import threading
import time
import config as C
from core.clock import now
from core.model import Pose, start_pose, step_pose
from devio import protocol as P


class _UdpDevice(threading.Thread):
    role = "device"

    def __init__(self, hub_port, delay_ms=0.0):
        super().__init__(daemon=True, name="sim-" + self.role)
        self.hub = ("127.0.0.1", hub_port)
        self.delay = delay_ms / 1000.0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.003)
        self.stop_flag = threading.Event()
        self.inbox = collections.deque()           # (due, line)
        self.outbox = collections.deque()          # (due, line)
        self.t_hello = 0.0
        self.peer = self.hub

    def out(self, line):
        self.outbox.append((now() + self.delay / 2, line))

    def handle(self, msg, t):
        pass

    def periodic(self, t, dt):
        pass

    def run(self):
        last = now()
        while not self.stop_flag.is_set():
            t = now()
            try:
                data, addr = self.sock.recvfrom(256)
                self.peer = addr
                for line in P.split_datagram(data):
                    self.inbox.append((t + self.delay / 2, line))
            except socket.timeout:
                pass
            except OSError:
                time.sleep(0.003)
            t = now()
            while self.inbox and self.inbox[0][0] <= t:
                line = self.inbox.popleft()[1]
                msg = P.decode(line)
                if msg is None:
                    continue
                if msg[0] == "P":
                    self.out(P.encode("Q", msg[1], msg[2]))
                elif msg[0] in ("WHO?", "I?"):
                    self.t_hello = 0.0
                else:
                    self.handle(msg, t)
            self.periodic(t, t - last)
            last = t
            if t - self.t_hello >= 1.0:
                self.t_hello = t
                try:
                    self.sock.sendto(P.encode("HELLO", self.role, P.FW, "127.0.0.1").encode() + b"\n", self.hub)
                except OSError:
                    pass
            while self.outbox and self.outbox[0][0] <= t:
                try:
                    self.sock.sendto((self.outbox.popleft()[1] + "\n").encode(), self.peer)
                except OSError:
                    pass

    def stop(self):
        self.stop_flag.set()


class SimRobot(_UdpDevice):
    role = "robot"

    def __init__(self, hub_port, delay_ms=None, field=None):
        super().__init__(hub_port, C.SIM_ROBOT_DELAY_MS if delay_ms is None else delay_ms)
        self.pose = start_pose()
        self.cmd = (0, 0)
        self.t_cmd = -9.0
        self.latched = False
        self.ap = 0
        self.pan = 0
        self.field = None

    def handle(self, msg, t):
        k = msg[0]
        if k == "D" and not self.latched:
            self.cmd, self.ap, self.t_cmd = (msg[1], msg[2]), msg[3], t
        elif k == "C":
            self.pan = max(-90, min(90, msg[1]))
        elif k == "X":
            self.latched, self.cmd = True, (0, 0)
        elif k == "R":
            self.latched, self.cmd = False, (0, 0)

    def periodic(self, t, dt):
        if dt <= 0 or dt > 0.5:
            return
        timed_out = t - self.t_cmd > 0.3
        left, right = (0, 0) if (timed_out or self.latched) else self.cmd
        speed = (left + right) / 2.0 / C.MAX_PWM
        turn = (left - right) / 2.0 / C.MAX_PWM / C.TURN_GAIN
        step_pose(self.pose, speed, turn, dt)


class SimTower(threading.Thread):
    """Tower firmware v3: a serial-driven pan/tilt laser. Y,deg / T,deg move the simulated stepper and servo (at the speeds G sets),
    D comes back when both arrive, R answers range_cm, ? answers S. Over a fake serial port."""
    role = "tower"
    STEPS_PER_DEG = 4096.0 / 360.0

    def __init__(self, hub_port=None, **_):
        super().__init__(daemon=True, name="sim-tower")
        self.port = FakeSerial(self)
        self.stop_flag = threading.Event()
        self.range_cm = 60.0
        self.yaw = 0.0                                        # degrees now, 0 = power-up
        self.yaw_target = 0.0
        self.servo = 180.0                                    # SERVO_START
        self.servo_target = 180.0
        self.laser = True
        self.yaw_sps, self.servo_ms = 800.0, 15.0
        self.arrived_sent = True
        self.targets = []                                     # every (kind, value) command received, for the tests
        self.coils_off = False
        self.rx = bytearray()
        self.sent = []
        self._t = now()

    def out(self, line):
        self.sent.append(line)
        self.port.feed_from_device(line)

    def press_button(self):
        self.out("B,1")

    def moving(self):
        return abs(self.yaw - self.yaw_target) > 1e-6 or abs(self.servo - self.servo_target) > 1e-6

    def feed(self, data):
        self.rx += data
        while b"\n" in self.rx:
            line, _, rest = bytes(self.rx).partition(b"\n")
            self.rx = bytearray(rest)
            m = P.decode(line.decode("ascii", "ignore").strip())
            if m is None:
                continue
            k = m[0]
            if k == "I?":
                self.out("I,tower,%d" % P.FW)
            elif k == "P":
                self.out(P.encode("Q", m[1], m[2]))
            elif k == "Y":
                self.yaw_target = max(-100.0, min(100.0, m[1]))
                self.targets.append(("Y", m[1]))
                self.arrived_sent = False
            elif k == "T":
                self.servo_target = max(0.0, min(180.0, round(m[1])))
                self.targets.append(("T", m[1]))
                self.arrived_sent = False
            elif k == "L":
                self.laser = m[1] != "0"
            elif k == "HOME":
                self.yaw = self.yaw_target = 0.0
            elif k == "O":
                self.coils_off = True
            elif k == "G":
                self.yaw_sps, self.servo_ms = max(50.0, min(1000.0, m[1])), float(m[3])
            elif k == "R":
                self.out("R,%.0f" % self.range_cm)
            elif k == "?":
                self.out("S,%.1f,%d,%d,%d" % (self.yaw, round(self.servo), 1 if self.laser else 0, 1 if self.moving() else 0))

    def run(self):
        while not self.stop_flag.is_set():
            t = now()
            dt, self._t = t - self._t, t
            dy = self.yaw_sps / self.STEPS_PER_DEG * dt            # degrees the stepper can turn this tick
            self.yaw += max(-dy, min(dy, self.yaw_target - self.yaw))
            ds = dt * 1000.0 / self.servo_ms if self.servo_ms > 0 else 1e9
            self.servo += max(-ds, min(ds, self.servo_target - self.servo))
            if not self.arrived_sent and not self.moving():
                self.arrived_sent = True
                self.out("D,%.1f,%d" % (self.yaw, round(self.servo)))
            time.sleep(0.01)

    def stop(self):
        self.stop_flag.set()


class FakeSerial:
    """Quacks like serial.Serial for the scanner: write() sends to the device, read() returns what it said."""

    def __init__(self, device):
        self.device, self.buf, self.lock, self.closed = device, bytearray(), threading.Lock(), False

    def write(self, data):
        self.device.feed(bytes(data))

    def read(self, n=1):
        if self.closed:
            raise OSError("device unplugged")                 # what pyserial does when the USB cable is pulled
        with self.lock:
            out, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return out

    def feed_from_device(self, line):
        with self.lock:
            self.buf += (line + "\n").encode()

    def reset_input_buffer(self):
        with self.lock:
            self.buf.clear()

    def close(self):
        self.closed = True


class SimHud(threading.Thread):
    """HUD panel firmware (protocol 2) in Python. It keeps what the real panel would show: the two LCD rows, the LED bits,
    the ARGB pixel, the buzzer pattern, the chirps and the OLED frame. It answers I?, P and ? like the real one."""
    role = "hud"

    def __init__(self):
        super().__init__(daemon=True, name="sim-hud")
        self.port = FakeSerial(self)
        self.stop_flag = threading.Event()
        self.rows = ["HUD PANEL".ljust(16), "WAITING...".ljust(16)]
        self.led = (0, 0, 0)                       # on, blink, ms
        self.pixel = (0, 0, 0, 0)                  # r, g, b, ms
        self.buzzer = (0, 0, 0)                    # hz, on ms, period ms
        self.chirps = 0
        self.oled = []                             # frame as drawn: list of (op, args)
        self.oled_frame = []
        self.oled_pushes = 0
        self.rx = bytearray()
        self.got = []

    def feed(self, data):
        self.rx += data
        while b"\n" in self.rx:
            line, _, rest = bytes(self.rx).partition(b"\n")
            self.rx = bytearray(rest)
            self._line(line.decode("ascii", "ignore").strip())

    def lcd(self):
        return tuple(self.rows)

    def _line(self, s):
        self.got.append(s)
        if not s:
            return
        if s == "I?":
            self.port.feed_from_device("I,hud,%d" % P.FW)
        elif s == "?":
            self.port.feed_from_device("S,%d,0" % 1)
        elif s[0] == "P" and s[1:2] == ",":
            self.port.feed_from_device("Q" + s[1:])
        elif s.startswith("LD,"):
            f = [int(x) for x in s[3:].split(",")]
            self.led = tuple(f[:3])
        elif s == "L" or s == "L,":
            self.rows = ["".ljust(16), "".ljust(16)]
        elif s.startswith("L,"):
            l1, _, l2 = s[2:].partition("|")
            self.rows = [l1[:16].ljust(16), l2[:16].ljust(16)]
        elif s.startswith("N,"):
            f = [int(x) for x in s[2:].split(",")]
            self.pixel = tuple(f[:4])
        elif s == "BZ":
            self.chirps += 1
        elif s.startswith("BZ,"):
            hz, on, per = [int(x) for x in s[3:].split(",")]
            if hz and on and not per:
                self.chirps += 1                  # one beep: the chirp
            else:
                self.buzzer = (hz, on, per)
        elif s == "OC":
            self.oled_frame = []
        elif s == "OP":
            self.oled = list(self.oled_frame)
            self.oled_pushes += 1
        elif s[:2] in ("OT", "OR", "OH", "OI"):
            self.oled_frame.append(s)

    def run(self):
        while not self.stop_flag.is_set():
            time.sleep(0.05)

    def stop(self):
        self.stop_flag.set()


def sim_camera_source(get_pose, field=None):
    """A rendered view (320x240) from the rover: black sky, grey ground with a grid."""
    import numpy as np
    W, H = 320, 240

    def render():
        p = get_pose()
        img = np.zeros((H, W, 3), np.uint8)
        img[H // 2:] = np.linspace((70, 70, 74), (140, 140, 146), H - H // 2).astype(np.uint8)[:, None, :]
        off = int((p.x * 3 + p.y * 3) % 20)
        for y in range(H // 2 + 6, H, 14):
            img[y:y + 1, :] = (90, 90, 96)
        for x in range(-20 + off, W, 20):
            img[H // 2:, max(0, x):x + 1] = (96, 96, 102)
        return img
    return render
