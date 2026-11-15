"""Line protocol v2: ASCII text lines, comma separated, at most 64 characters, one line per UDP datagram or serial line.
The same lines travel over UDP, USB serial and the UNO Q Bridge. decode() returns a typed tuple or None
(unknown or malformed lines are ignored, never raised).

Some letters mean two things depending on how many fields follow (the decoder tells them apart by the field count):
  P,seq,us  ping                      P      pickup (laptop -> HUD panel)
  W,3       asteroid warning, seconds to impact (tower -> laptop)
  K,1 / K,0 impact: hit / miss (tower -> laptop)        K   impact, result not known (older firmware)
  J,x,y,sw  joystick (HUD panel -> laptop)              J   jiggle the push servo once (laptop -> tower)
  Z,state   thermal state (laptop -> HUD panel)         Z   swing the beam back up (laptop -> tower)
  R,cm      one distance reading (tower -> laptop)      R   release / reset (rover, HUD panel) or "send one reading" (tower)
Laptop -> rover (firmware v3, a plain two-wheel drive + camera pan: the laptop decides, the rover obeys and stops when the lines stop):
  D,left,right,ap  wheel values +-MAX_PWM   C,deg  camera pan   X / R  stop latch / release   LED,mode  0 off 1 on 2 fast 3 slow blink
  G,maxCmd,minPwm,slew,timeoutMs,panLimit,panSps,panAcc  settings   ?  state      rover -> laptop: B,L / B,R bumpers   S,left,right,pan,latched
Laptop -> tower (firmware v3, a plain pan/tilt laser: the laptop decides everything, the tower only moves and measures):
  Y,deg yaw   T,deg servo 0..180   L,0|1 laser   H here is yaw 0   O coils off   G,sps,acc,ms speeds   R range   ?  state
  tower -> laptop: D,yaw,servo (both motors arrived)   S,yaw,servo,laser,moving   R,cm   B,1 (test button)
Laptop -> HUD panel (firmware v4, plain output devices: the laptop draws every screen, see devio/hud_render.py):
  L,line1|line2  LCD 16x2 (L, alone clears)   LD,on,blink,ms  LEDs, bits 1 green 2 red 4 yellow, the blink bits toggle every ms
  N,r,g,b,ms  ARGB pixel (ms > 0 blinks)   BZ,hz,onMs,periodMs  buzzer (hz 0 silent, period 0 one beep)
  OC clear   OT,x,y,size,text   OR,x,y,w,h,fill   OH,x,y,size,fill (heart)   OP push the frame to the OLED 128x64
  JS,ms  joystick period (0 off)   JZ  re-centre the stick   ?  state     P,seq,us / I?  as everywhere
HUD panel -> laptop: J,x,y,sw every 33 ms (x right, y forward, -100..100, sw 1 while pressed)   S,oled,lost (reply to ?)
"""
MAX_LEN = 64
FW = 2

# kind -> field types (i int, f float, s text)
_SPEC = {
    "HELLO": "sis", "I": "si", "WHO?": "", "I?": "",
    "P": "ii", "Q": "ii",
    "D": "iii", "X": "", "R": "",
    "B": "s",
    "F": "", "C": "i",
    "Z": "i", "V": "f", "H": "i",
    "M": "iiii", "E": "i", "BZ": "", "J": "iii",
    "Y": "f", "T": "f", "L": "s", "O": "", "?": "", "S": "ffii",
    "LED": "i", "LD": "iii", "N": "iiii", "OC": "", "OP": "", "OR": "iiiii", "OH": "iiii", "OT": "iiis", "OI": "ii", "JS": "i", "JZ": "",
}
# the same letter with another field count: (letter, fields) -> (kind, types)
_ALT = {
    ("P", 0): ("PICKUP", ""), ("W", 1): ("WARN", "f"), ("K", 1): ("K", "i"), ("K", 0): ("K", ""),
    ("F", 1): ("F", "i"), ("J", 0): ("JIGGLE", ""), ("Z", 0): ("UP", ""), ("R", 1): ("RANGE", "f"),
    ("H", 0): ("HOME", ""), ("D", 2): ("ARRIVED", "ff"),
    ("G", 3): ("G", "fff"), ("G", 7): ("G", "iiiiifff"), ("BZ", 3): ("BEEP", "iii"), ("S", 2): ("S2", "ii"),
}


def encode(*parts):
    line = ",".join(str(p) for p in parts)
    if len(line) > MAX_LEN:
        raise ValueError("line longer than %d characters: %r" % (MAX_LEN, line))
    return line


def decode(line):
    if isinstance(line, bytes):
        line = line.decode("ascii", "ignore")
    line = line.strip()
    if not line or len(line) > MAX_LEN:
        return None
    parts = line.split(",")
    kind, fields = parts[0], parts[1:]
    if (kind, len(fields)) in _ALT:
        kind, types = _ALT[(kind, len(fields))]
    else:
        types = _SPEC.get(kind)
    if types is None or len(fields) != len(types):
        return None
    out = [kind]
    try:
        for f, t in zip(fields, types):
            out.append(int(f) if t == "i" else float(f) if t == "f" else f)
    except ValueError:
        return None
    if kind == "K" and len(out) == 1:
        out.append(-1)                            # bare K: the result is not known
    return tuple(out)


def split_datagram(data):
    """A datagram or a serial chunk may hold several lines."""
    if isinstance(data, bytes):
        data = data.decode("ascii", "ignore")
    return [l for l in data.replace("\r", "").split("\n") if l.strip()]
