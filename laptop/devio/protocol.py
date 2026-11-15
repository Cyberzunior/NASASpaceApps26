"""Line protocol v2: ASCII text lines, comma separated, at most 64 characters, one line per UDP datagram or serial line.
The same lines travel over UDP, USB serial and the UNO Q Bridge. decode() returns a typed tuple or None
(unknown or malformed lines are ignored, never raised).

Some letters mean two things depending on how many fields follow (the decoder tells them apart, like it always did for T):
  P,seq,us  ping           P          pickup (laptop -> HUD panel)
  W,temp,hum,state  HUD temperature report    W,3   asteroid warning, seconds to impact (tower -> laptop)
  T,rest,push,ms  tower tuning (kind TUNE)
Laptop -> rover: D,left,right,ap   C,angle (camera pan, degrees, 0 = straight ahead)   X / R (stop latch / release)
Laptop -> tower: F (warn, fire, release)   X / R (disarm / arm)        tower -> laptop: W,secs then K
Laptop -> HUD panel: M,power,oxygen,food,shield   H,hearts   E,samples   Z,state   V,tempC   L,line1|line2   BZ   P   G   R
"""
MAX_LEN = 64
FW = 2

# kind -> field types (i int, f float, s text)
_SPEC = {
    "HELLO": "sis", "I": "si", "WHO?": "", "I?": "",
    "P": "ii", "Q": "ii",
    "D": "iii", "X": "", "R": "",
    "B": "s",
    "F": "", "A": "i", "K": "", "C": "i",
    "W": "fii", "Z": "i", "V": "f", "H": "i", "G": "",
    "M": "iiii", "E": "i", "BZ": "",
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
    if kind == "T" and len(fields) == 3:          # T,rest,push,ms to the tower
        kind, types = "TUNE", "iii"
    elif kind == "P" and not fields:              # bare P: a sample was picked up
        return ("PICKUP",)
    elif kind == "W" and len(fields) == 1:        # W,3: asteroid warning
        kind, types = "WARN", "f"
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
    return tuple(out)


def split_datagram(data):
    """A datagram or a serial chunk may hold several lines."""
    if isinstance(data, bytes):
        data = data.decode("ascii", "ignore")
    return [l for l in data.replace("\r", "").split("\n") if l.strip()]
