"""Ctrl+Y: ask for the COM number of the three serial devices, one at a time: the ipad (HUD panel), the tower and the rover."""
STEPS = (("hud", "Which COM is the ipad (HUD panel)?"),
         ("tower", "Which COM is the tower?"),
         ("robot", "Which COM is the rover?"))


class PortPrompt:
    def __init__(self):
        self.active = False
        self.step = 0
        self.buf = ""
        self.values = {}                  # role -> "COMn"

    def start(self):
        self.active, self.step, self.buf, self.values = True, 0, "", {}

    def cancel(self):
        self.active = False

    @property
    def question(self):
        return STEPS[self.step][1]

    def type(self, ch):
        if ch and ch.isdigit() and len(self.buf) < 3:
            self.buf += ch

    def back(self):
        self.buf = self.buf[:-1]

    def enter(self):
        """Keep the number typed for this step. Returns True once all three are set."""
        if not self.buf:
            return False
        self.values[STEPS[self.step][0]] = "COM" + self.buf
        self.buf = ""
        self.step += 1
        if self.step == len(STEPS):
            self.active = False
            return True
        return False
