"""Screen shake: smooth layered-sine wobble with a decaying envelope (no harsh per-frame jitter)."""
import math


class Shake:
    def __init__(self):
        self.power = 0.0
        self.t = 0.0

    def add(self, amount):
        self.power = min(40.0, self.power + amount)

    def update(self, dt):
        self.t += dt
        self.power = max(0.0, self.power - 60.0 * dt)

    def offset(self):
        if self.power < 0.3:
            return 0, 0
        t = self.t
        x = math.sin(t * 47.0) * 0.55 + math.sin(t * 91.0 + 1.3) * 0.45
        y = math.cos(t * 53.0) * 0.55 + math.cos(t * 73.0 + 0.7) * 0.45
        return int(x * self.power * 0.5), int(y * self.power * 0.5)
