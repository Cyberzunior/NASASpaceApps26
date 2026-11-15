"""Three parallax star layers with twinkle, shooting stars and a nebula gradient. Built once, cheap to draw."""
import math
import random
import numpy as np
import pygame
import config as C
from gfx.perf import PERF


def _smooth_noise(w, h, seed, cells=(14, 8)):
    """Soft value noise (0..1, shape (h, w)): a tiny random grid blown up with bilinear scaling."""
    rng = np.random.default_rng(seed)
    g = (rng.random((cells[0], cells[1])) * 255).astype(np.uint8)
    small = pygame.surfarray.make_surface(np.dstack([g, g, g]))
    big = pygame.transform.smoothscale(small, (w, h))
    return pygame.surfarray.array3d(big)[..., 0].T.astype(np.float64) / 255.0


def _nebula(w, h):
    """Two soft colour clouds on the navy background, kept dark so the game stays readable."""
    sw, sh = w // 8, h // 8
    gx, gy = np.meshgrid(np.linspace(0, 1, sw), np.linspace(0, 1, sh))
    a = np.exp(-(((gx - 0.2) / 0.35) ** 2 + ((gy - 0.3) / 0.3) ** 2))
    b = np.exp(-(((gx - 0.85) / 0.3) ** 2 + ((gy - 0.75) / 0.35) ** 2))
    n = _smooth_noise(sw, sh, 11)
    base = np.zeros((sh, sw, 3))
    base[..., 0] = 7 + a * 16 + b * 4
    base[..., 1] = 10 + a * 5 + b * 11
    base[..., 2] = 24 + a * 24 + b * 28
    base *= (0.7 + 0.6 * n)[..., None]
    surf = pygame.surfarray.make_surface(np.clip(base, 0, 255).astype(np.uint8).swapaxes(0, 1))
    return pygame.transform.smoothscale(surf, (w, h)).convert()


class Starfield:
    def __init__(self, w=None, h=None):
        self.w, self.h = w or C.RENDER_W, h or C.RENDER_H
        rnd = random.Random(5)
        self.layers = []
        for n, speed, size, bright in ((140, 4.0, 1, 130), (80, 9.0, 2, 190), (28, 16.0, 3, 245)):
            self.layers.append([[rnd.uniform(0, self.w), rnd.uniform(0, self.h), rnd.uniform(0, 6.28), rnd.uniform(0.5, 2.0)]
                                for _ in range(n)] + [speed, size, bright])
        self.bg = _nebula(self.w, self.h)
        self.shoot = None
        self.t = 0.0
        self.drift = 1.0                 # 1 = the menu's slow sideways drift, 0 = fixed stars

    def update(self, dt):
        self.t += dt
        for layer in self.layers:
            speed = layer[-3] * self.drift
            for s in layer[:-3]:
                s[0] -= speed * dt
                if s[0] < -4:
                    s[0] += self.w + 8
        if self.shoot:
            self.shoot[0] += self.shoot[2] * dt
            self.shoot[1] += self.shoot[3] * dt
            self.shoot[4] -= dt
            if self.shoot[4] <= 0:
                self.shoot = None
        elif random.random() < dt / 6.0:
            a = random.uniform(0.2, 0.6)
            sp = random.uniform(900, 1400)
            self.shoot = [random.uniform(0, self.w * 0.7), random.uniform(0, self.h * 0.4), math.cos(a) * sp, math.sin(a) * sp, 0.6]

    def draw(self, surf, off=(0, 0), shift=(0.0, 0.0), pan=None):
        """pan (pixels): every star shifts by the same amount and wraps, the way a sky turns when the viewer turns."""
        surf.blit(self.bg, (0, 0))
        w = self.w
        col = surf.fill
        t = self.t
        sin = math.sin
        step = max(1, int(round(1.0 / max(0.05, PERF.k["stars"]))))       # density knob: draw every Nth star
        ox, oy = off
        for layer in self.layers:
            speed, size, bright = layer[-3], layer[-2], layer[-1]
            par = speed / 16.0
            stars = layer[:-3]
            for i in range(0, len(stars), step):
                s = stars[i]
                tw = 0.65 + 0.35 * sin(t * s[3] * 2 + s[2])
                v = int(bright * tw)
                if pan is None:
                    x, y = int(s[0] + ox * par - shift[0] * par * 20), int(s[1] + oy * par - shift[1] * par * 20)
                else:
                    x, y = int(s[0] + pan) % w, int(s[1])
                col((v, v, min(255, v + 12)), (x, y, size, size))
        if self.shoot:
            x, y, vx, vy, life = self.shoot
            n = math.hypot(vx, vy)
            for i in range(10):
                f = 1 - i / 10
                c = int(230 * f * min(1.0, life * 4))
                surf.fill((c, c, c), (int(x - vx / n * i * 9), int(y - vy / n * i * 9), 2, 2), special_flags=pygame.BLEND_RGB_ADD)
