"""Particles: exhaust smoke, sparks, fragments, shockwave rings, heat shimmer, ice crystals, burn-up debris.
Rows are plain lists for speed: [x, y, vx, vy, life, max_life, size, color, kind, drag].
Sparks draw as cached soft glow dots (additive); smoke draws as soft alpha puffs that grow as they fade."""
import math
import random
import pygame
from gfx.perf import PERF

_dots = {}
_puffs = {}


def _dot(s, color):
    """Soft additive glow dot, cached by (radius, quantised colour)."""
    key = (s, color[0] >> 2, color[1] >> 2, color[2] >> 2)
    img = _dots.get(key)
    if img is None:
        d = s * 2 + 2
        img = pygame.Surface((d, d))
        rim = (int(color[0] * 0.4), int(color[1] * 0.4), int(color[2] * 0.4))
        pygame.draw.circle(img, rim, (s, s), s)
        pygame.draw.circle(img, color, (s, s), max(1, s * 3 // 5))
        if len(_dots) > 400:
            _dots.clear()
        _dots[key] = img = img.convert()
    return img


def _puff(s):
    """Soft round smoke puff, brighter (more alpha) toward the centre, cached by radius."""
    img = _puffs.get(s)
    if img is None:
        d = s * 2 + 2
        img = pygame.Surface((d, d), pygame.SRCALPHA)
        for r in range(s, 0, -1):
            a = int(26 + 150 * (1.0 - r / s) ** 1.6)
            pygame.draw.circle(img, (172, 170, 176, a), (s, s), r)
        _puffs[s] = img
    return img


class Particles:
    def __init__(self, cap=900):
        self.p = []
        self.rings = []          # [x, y, radius, max_radius, life, max_life, color]
        self.cap = cap

    def emit(self, x, y, n, color, speed=90.0, life=(0.3, 0.8), size=(1.5, 3.5), spread=6.283, angle=0.0,
             kind="spark", drag=0.0):
        cap = min(self.cap, PERF.k["parts"])
        for _ in range(n):
            if len(self.p) >= cap:
                break
            a = angle + random.uniform(-spread / 2, spread / 2)
            v = random.uniform(0.25, 1.0) * speed
            L = random.uniform(*life)
            c = color if not isinstance(color, list) else random.choice(color)
            self.p.append([x, y, math.cos(a) * v, math.sin(a) * v, L, L, random.uniform(*size), c, kind, drag])

    def ring(self, x, y, max_r, color, life=0.6):
        self.rings.append([x, y, 4.0, max_r, life, life, color])

    def update(self, dt):
        out = []
        for q in self.p:
            q[4] -= dt
            if q[4] <= 0:
                continue
            k = 1.0 - q[9] * dt
            q[2] *= k
            q[3] *= k
            q[0] += q[2] * dt
            q[1] += q[3] * dt
            out.append(q)
        self.p = out
        for r in self.rings:
            r[4] -= dt
            r[2] = r[3] * (1.0 - r[4] / r[5])
        self.rings = [r for r in self.rings if r[4] > 0]

    def draw(self, surf):
        for q in self.p:
            f = q[4] / q[5]
            x, y = int(q[0]), int(q[1])
            if q[8] == "smoke":
                s = max(2, int(q[6] * (2.4 - 1.4 * f)))                 # puffs expand as they fade
                img = _puff(min(20, s))
                if img.get_width() != s * 2 + 2:
                    img = pygame.transform.smoothscale(img, (s * 2 + 2, s * 2 + 2))
                img.set_alpha(int(120 * f * f))
                surf.blit(img, (x - s, y - s))
                continue
            c = q[7]
            col = (int(c[0] * f), int(c[1] * f), int(c[2] * f))
            if q[8] == "ice":
                s = max(1, int(q[6] * (0.4 + 0.6 * f)))
                pygame.draw.line(surf, col, (x - s, y), (x + s, y), 1)
                pygame.draw.line(surf, col, (x, y - s), (x, y + s), 1)
            else:
                s = max(1, int(q[6] * (0.4 + 0.6 * f)))
                surf.blit(_dot(min(7, s), col), (x - s, y - s), special_flags=pygame.BLEND_RGB_ADD)
        for r in self.rings:
            f = r[4] / r[5]
            c = r[6]
            col = (int(c[0] * f), int(c[1] * f), int(c[2] * f))
            rr = int(r[2])
            if rr > 2:
                cx, cy = int(r[0]), int(r[1])
                pygame.draw.circle(surf, (col[0] // 3, col[1] // 3, col[2] // 3), (cx, cy), rr, max(2, int(9 * f)))
                pygame.draw.circle(surf, col, (cx, cy), rr, max(1, int(4 * f)))
