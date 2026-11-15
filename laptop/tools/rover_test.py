"""Bench test for the rover's STM32 (robot.ino) over USB serial: each TT motor at full speed forward and reverse, both motors
together, and a slider for the camera stepper. A motor button runs only while it is held down (release = stop).

    python tools/rover_test.py              python tools/rover_test.py --port COM5

Lift the rover first so the wheels are free. Sends the real protocol lines (D,left,right,0 every 20 ms, C,angle)."""
import argparse
import os
import sys
import time
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config as C

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial missing: pip install pyserial")

MAXV = C.MAX_PWM            # what the game sends at full stick (200)
PAN = C.PAN_LIMIT_DEG       # stepper slider range, degrees each side

# (label, left, right)
BUTTONS = [
    ("LEFT  +max", MAXV, 0), ("LEFT  -max", -MAXV, 0),
    ("RIGHT +max", 0, MAXV), ("RIGHT -max", 0, -MAXV),
    ("BOTH  +max", MAXV, MAXV), ("BOTH  -max", -MAXV, -MAXV),
    ("SPIN  left", -MAXV, MAXV), ("SPIN  right", MAXV, -MAXV),
]


class App:
    def __init__(self, root, port):
        self.root, self.ser, self.rx = root, None, b""
        self.cmd = (0, 0)                      # what the 20 ms timer keeps sending
        self.pan_sent, self.pan_due = 0, 0.0
        root.title("Rover motor test")
        root.protocol("WM_DELETE_WINDOW", self.close)
        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Port").pack(side="left")
        self.port = tk.StringVar(value=port or "")
        self.combo = ttk.Combobox(top, textvariable=self.port, width=14, values=self.ports())
        self.combo.pack(side="left", padx=4)
        ttk.Button(top, text="Connect", command=self.connect).pack(side="left")
        self.status = tk.StringVar(value="not connected")
        ttk.Label(root, textvariable=self.status, padding=(8, 0)).pack(anchor="w")

        grid = ttk.LabelFrame(root, text="Hold a button to run it (left = D5/D6, right = D9/D10, full = %d)" % MAXV, padding=8)
        grid.pack(fill="x", padx=8, pady=6)
        for i, (label, l, r) in enumerate(BUTTONS):
            b = tk.Button(grid, text=label, width=14, height=2, font=("Consolas", 11))
            b.grid(row=i // 2, column=i % 2, padx=3, pady=3)
            b.bind("<ButtonPress-1>", lambda e, l=l, r=r: self.set_cmd(l, r))
            b.bind("<ButtonRelease-1>", lambda e: self.set_cmd(0, 0))
        self.out = tk.StringVar(value="wheels: 0, 0")
        ttk.Label(grid, textvariable=self.out).grid(row=4, column=0, columnspan=2)

        st = ttk.LabelFrame(root, text="Camera stepper (C,angle, degrees, 0 = power-up direction)", padding=8)
        st.pack(fill="x", padx=8, pady=6)
        self.pan = tk.IntVar(value=0)
        self.slider = ttk.Scale(st, from_=-PAN, to=PAN, orient="horizontal", length=360,
                                command=lambda v: self.pan.set(int(round(float(v)))))
        self.slider.pack(fill="x")
        self.pan_label = tk.StringVar(value="0")
        ttk.Label(st, textvariable=self.pan_label).pack()
        row = ttk.Frame(st)
        row.pack()
        for text, a in (("-%d" % PAN, -PAN), ("0", 0), ("+%d" % PAN, PAN)):
            ttk.Button(row, text=text, width=6, command=lambda a=a: self.set_pan(a)).pack(side="left", padx=2)

        tk.Button(root, text="STOP", bg="#c0392b", fg="white", font=("Consolas", 14, "bold"),
                  command=lambda: self.set_cmd(0, 0)).pack(fill="x", padx=8, pady=6)
        self.log = tk.Text(root, height=6, width=52, state="disabled")
        self.log.pack(padx=8, pady=(0, 8))
        root.after(20, self.tick)
        if port:
            self.connect()

    @staticmethod
    def ports():
        return [p.device for p in list_ports.comports()]

    def say(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def connect(self):
        self.close_port()
        name = self.port.get().strip()
        try:
            self.ser = serial.Serial(name, C.SERIAL_BAUD, timeout=0, write_timeout=0.2)
        except Exception as e:
            self.status.set("cannot open %s: %s" % (name, str(e)[:50]))
            return
        self.status.set("%s open, asking I? ..." % name)
        self.t_open = time.time()
        self.sent_who = False
        self.root.after(1800, self.ask)          # the board may reset when the port opens

    def ask(self):
        if self.ser:
            self.send("I?")
            self.sent_who = True

    def close_port(self):
        if self.ser:
            try:
                self.ser.write(b"D,0,0,0\n")
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def close(self):
        self.close_port()
        self.root.destroy()

    def send(self, line):
        if not self.ser:
            return
        try:
            self.ser.write((line + "\n").encode())
        except Exception as e:
            self.status.set("write failed: %s" % str(e)[:50])
            self.ser = None

    def set_cmd(self, l, r):
        self.cmd = (l, r)
        self.out.set("wheels: %d, %d" % (l, r))
        self.send("D,%d,%d,0" % (l, r))

    def set_pan(self, a):
        self.slider.set(a)
        self.pan.set(a)

    def tick(self):
        now = time.time()
        if self.ser:
            self.send("D,%d,%d,0" % self.cmd)                       # the rover stops 300 ms after the last D
            a = self.pan.get()
            self.pan_label.set("%d deg" % a)
            if a != self.pan_sent and now >= self.pan_due:           # at most 10 per second while sliding
                self.pan_sent, self.pan_due = a, now + 0.1
                self.send("C,%d" % a)
            try:
                data = self.ser.read(256)
            except Exception:
                data = b""
                self.ser = None
                self.status.set("unplugged")
            if data:
                self.rx += data
                *lines, self.rx = self.rx.split(b"\n")
                for l in lines:
                    l = l.decode("ascii", "ignore").strip()
                    if not l:
                        continue
                    if l.startswith("I,robot"):
                        self.status.set("connected: %s (%s)" % (self.port.get(), l))
                    self.say("rover: " + l)
        self.root.after(20, self.tick)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="")
    a = ap.parse_args()
    root = tk.Tk()
    App(root, a.port)
    root.mainloop()


if __name__ == "__main__":
    main()
