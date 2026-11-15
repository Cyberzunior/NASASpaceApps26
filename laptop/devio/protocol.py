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
Laptop -> rover: D,left,right,ap   C,angle (camera pan, degrees, 0 = straight ahead)   X / R (stop latch / release)
Laptop -> tower: F,bearing (run one asteroid sequence; bare F = bearing 0; -40..40 degrees, negative left)   J   Z   R        tower -> laptop: W,3 then K,1 or K,0
Laptop -> HUD panel: M,power,oxygen,food,shield   H,hearts   E,samples   Z,state   V,tempC   L,line1|line2   BZ   P   G   R
HUD panel -> laptop: J,x,y,sw every 33 ms (x right, y forward, -100..100, sw 1 while pressed)
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
    "Z": "i", "V": "f", "H": "i", "G": "",
    "M": "iiii", "E": "i", "BZ": "", "J": "iii",
}
# the same letter with another field count: (letter, fields) -> (kind, types)
_ALT = {
    ("P", 0): ("PICKUP", ""), ("W", 1): ("WARN", "f"), ("K", 1): ("K", "i"), ("K", 0): ("K", ""),
    ("F", 1): ("F", "i"), ("J", 0): ("JIGGLE", ""), ("Z", 0): ("UP", ""), ("R", 1): ("RANGE", "f"),
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
