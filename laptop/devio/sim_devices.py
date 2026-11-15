"""Software versions of every device. They speak the real line protocol: the rover over UDP on the loopback interface
(so the real link code runs), the tower and the HUD panel over a fake serial port (so the real handshake runs).

SimRobot integrates the SAME model as the game, has the firmware's 300 ms timeout and the X/R latch, and records the wheel
values and camera pan it was given. SimTower answers F with W,secs then K. SimHud is the HUD panel firmware: it keeps the
LCD text, LEDs, buzzer and OLED numbers the real one would show, so the tests can check them."""
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
    """Tower firmware: F (or its button) -> W,3 warning, a wait, the push, then K. Over a fake serial port."""
    role = "tower"

    def __init__(self, hub_port=None, k_ms=None, warn_s=None):
        super().__init__(daemon=True, name="sim-tower")
        self.port = FakeSerial(self)
        self.stop_flag = threading.Event()
        self.k_delay = (C.SIM_TOWER_K_MS if k_ms is None else k_ms) / 1000.0
        self.warn_s = 3.0 if warn_s is None else warn_s       # the real tower waits 3 s; tests shorten it
        self.armed = True
        self.last_fire = -99.0
        self.balls = 0
        self.tune = (C.TOWER_REST_DEG, C.TOWER_PUSH_DEG, C.TOWER_PUSH_MS)
        self.pending = []
        self.rx = bytearray()
        self.sent = []

    def out(self, line):
        self.sent.append(line)
        self.port.feed_from_device(line)

    def press_button(self):
        self._shot(now())

    def _shot(self, t):
        if self.armed and t - self.last_fire >= 1.5:
            self.last_fire = t
            self.out("W,%d" % round(self.warn_s))
            self.pending.append(t + self.warn_s + self.k_delay)

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
            elif k == "F":
                self._shot(now())
            elif k == "X":
                self.armed = False
            elif k == "R":
                self.armed = True
            elif k == "TUNE":
                self.tune = m[1:]

    def run(self):
        while not self.stop_flag.is_set():
            t = now()
            while self.pending and self.pending[0] <= t:
                self.pending.pop(0)
                self.balls += 1
                self.out("K")
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
    """HUD panel firmware (UNO Q) in Python. Zone Z sets the state; V is a simulated temperature; the DHT11 can be
    killed with kill_sensor() (then W is not sent unless V is active, with humidity -1 so the laptop knows it is not real)."""
    role = "hud"

    def __init__(self):
        super().__init__(daemon=True, name="sim-hud")
        self.port = FakeSerial(self)
        self.stop_flag = threading.Event()
        self.air = 23.0
        self.hum = 40
        self.sensor_ok = True
        self.virtual = None
        self.t_virtual = -9.0
        self.zone = 0
        self.lives = C.LIVES
        self.samples = 0
        self.meters = (0, 0, 0, 0)
        self.over = False
        self.text = None
        self.pickups = 0
        self.chirps = 0
        self.rx = bytearray()
        self.t_w = 0.0
        self.got = []

    def set_air(self, c):
        self.air = c

    def kill_sensor(self, dead=True):
        self.sensor_ok = not dead

    def feed(self, data):
        self.rx += data
        while b"\n" in self.rx:
            line, _, rest = bytes(self.rx).partition(b"\n")
            self.rx = bytearray(rest)
            self._line(line.decode("ascii", "ignore").strip())

    def _send_w(self):
        if self.sensor_ok:
            self.port.feed_from_device("W,%.1f,%d,%d" % (self.air, self.hum, self.zone))
        elif now() - self.t_virtual < 4.0 and self.virtual is not None:
            self.port.feed_from_device("W,%.1f,-1,%d" % (self.virtual, self.zone))
        self.t_w = now()

    def lcd(self):
        if self.over:
            return ("OUTPOST LOST", "")
        if self.text is not None:
            return self.text
        if self.zone == 2:
            return ("!! HOT !!", "COOLING")
        if self.zone == 1:
            return ("!! COLD !!", "HEATING")
        p, o, f, s = self.meters
        return ("PWR %-3d O2 %-3d" % (p, o), "FOOD %-3d SHLD %-3d" % (f, s))

    def _line(self, s):
        self.got.append(s)
        raw_kind = s.split(",", 1)[0]
        m = P.decode(s)
        if m is None:
            if raw_kind == "L":
                body = s[2:]
                self.text = tuple((body.split("|") + [""])[:2]) if body else None
            return
        k = m[0]
        if k == "I?":
            self.port.feed_from_device("I,hud,%d" % P.FW)
        elif k == "P":
            self.port.feed_from_device(P.encode("Q", m[1], m[2]))
        elif k == "PICKUP":
            self.pickups += 1
        elif k == "BZ":
            self.chirps += 1
        elif k == "Z":
            self.zone = m[1]
        elif k == "V":
            self.virtual, self.t_virtual = m[1], now()
        elif k == "H":
            self.lives = m[1]
        elif k == "E":
            self.samples = m[1]
        elif k == "M":
            self.meters = tuple(m[1:])
        elif k == "G":
            self.over = True
        elif k == "R":
            self.over, self.lives, self.samples, self.virtual, self.zone, self.text = False, C.LIVES, 0, None, 0, None

    def run(self):
        while not self.stop_flag.is_set():
            if now() - self.t_w >= 1.0:
                self._send_w()
            time.sleep(0.02)

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
