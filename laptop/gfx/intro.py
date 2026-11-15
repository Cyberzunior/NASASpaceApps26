"""The opening shot, drawn in code with the game's own renderer. A real camera model: a ground plane seen through a
pinhole camera, so the regolith grid, craters and the base all converge the way they would from the surface.
0.0-0.6 s fade in from black. 0.4-2.2 s high and far: the whole base is a speck on a wide plain, the Earth hangs in the sky.
2.2-4.6 s the camera descends and dollies in, pitching down to keep the base framed. 3.4-4.6 s the base rolls forward
and kicks up dust from its wheels. 4.6-5.2 s the camera settles with a small shake. 4.6-6 s meters fill, mission line, fade out."""
import math
import random
import pygame
import config as C
from gfx import fonts, palette as K
from gfx.rover import Rover, glow_add
from gfx.starfield import Starfield
from gfx.widgets import bar
from gfx.world import make_earth

FOCAL = 1150.0             # pixels, for a 1920 wide frame
BODY_W = 2.4               # metres: the base is about 2.4 m across
GRID_M = 10.0
METER_ORDER = (("Power", K.YELLOW), ("Oxygen", K.CYAN), ("Food", K.GREEN), ("Shield", K.VIOLET))


def _ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _ease_in_out(x):
    x = max(0.0, min(1.0, x))
    return x * x * x * (x * (6 * x - 15) + 10)


def _camera(t):
    """Camera position (behind the base, height, metres) and the base's roll-in offset. Time in seconds."""
    far, near = 240.0, 8.0
    k = _ease_in_out((t - 2.2) / 2.4)
    back = far + (near - far) * k
    height = 62.0 + (3.0 - 62.0) * k
    if t < 2.2:                                                  # slow drift while high up
        back += (t / 2.2) * 18.0
    roll = 0.0
    if t > 3.4:
        roll = 7.0 * _ease((t - 3.4) / 1.4)
    return back, height, roll


class Intro:
    def __init__(self):
        self.stars = Starfield()
        self.rover = Rover(60)
        self.earth = make_earth(150).convert_alpha()
        self.earth_glow = glow_add(190, (40, 84, 176), 2.6)
        self.sun = glow_add(120, (255, 236, 200), 2.2)
        self.puff = self._puff_sprite(48)
        self.puffs = []                                          # [x, z, y, age, life, size]
        self.puff_cache = {}
        self.rnd = random.Random(4)
        self.last_t = 0.0
        W, H = C.RENDER_W, C.RENDER_H
        g = pygame.Surface((1, 256))                              # regolith tone: hazy far away, lit close up
        for y in range(256):
            f = (y / 255) ** 0.55
            g.set_at((0, y), (int(74 + 58 * f), int(75 + 58 * f), int(82 + 56 * f)))
        self.ground = pygame.transform.smoothscale(g, (W, H)).convert()
        self.craters = [(self.rnd.uniform(-160, 160), self.rnd.uniform(-20, 330), self.rnd.uniform(0.8, 3.2)) for _ in range(140)]

    @staticmethod
    def _puff_sprite(r):
        s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        for i in range(r, 0, -2):
            a = int(120 * (1 - i / r) ** 1.5)
            pygame.draw.circle(s, (176, 178, 186, a), (r, r), i)
        return s.convert_alpha()

    # ---- camera projection: world metres (x right, y up, z forward from the base) -> screen
    def _project(self, cam, x, y, z):
        back, height, pitch, shake = cam
        W, H = C.RENDER_W, C.RENDER_H
        dz = z + back                                              # camera sits at (0, height, -back), looking down by `pitch`
        dy = y - height
        depth = -dy * math.sin(pitch) + dz * math.cos(pitch)
        if depth <= 0.5:
            return None
        right = x
        up = dy * math.cos(pitch) + dz * math.sin(pitch)
        sx = W / 2 + FOCAL * right / depth + shake[0]
        sy = H / 2 - FOCAL * up / depth + shake[1]
        return sx, sy, depth

    def _camera_state(self, t):
        back, height, roll = _camera(t)
        pitch = math.atan2(height - 1.0, back)                    # tilt down so the base stays framed (its body is ~1 m up)
        shake = (0.0, 0.0)
        if 4.4 < t < 5.4:                                         # the touchdown settle: a small shake that dies away
            amp = 9.0 * math.exp(-(t - 4.4) * 4.0)
            shake = (amp * math.sin(t * 61.0), amp * math.cos(t * 47.0))
        return (back, height, pitch, shake), roll

    def _ground_grid(self, surf, cam, roll):
        W, H = C.RENDER_W, C.RENDER_H
        for i in range(-16, 17):                                  # lines running away from the camera
            x = i * GRID_M
            a = self._project(cam, x, 0, -cam[0] + 0.5)
            b = self._project(cam, x, 0, 900.0)
            if a and b:
                v = int(96 + 22 * max(0.0, 1 - abs(i) / 16))
                pygame.draw.aaline(surf, (v, v, v + 6), (a[0], a[1]), (b[0], b[1]))
        k0 = math.floor((-cam[0] - 2) / GRID_M)
        for k in range(k0, 300):                                  # rows across the ground, spacing grows with distance
            z = k * GRID_M
            a = self._project(cam, -400.0, 0, z)
            b = self._project(cam, 400.0, 0, z)
            if a and b and -2 < a[1] < H + 2:
                v = int(96 + 22 * max(0.0, 1 - abs(z) / 300.0))
                pygame.draw.line(surf, (v, v, v + 6), (a[0], a[1]), (b[0], b[1]), 1 if z > 40 else 2)

    def _craters(self, surf, cam):
        for x, z, r in self.craters:
            p = self._project(cam, x, 0, z)
            if not p:
                continue
            sx, sy, depth = p
            rr = FOCAL * r / depth
            if rr < 2 or not (-rr < sx < C.RENDER_W + rr):
                continue
            rect = pygame.Rect(0, 0, int(rr * 2), int(rr * 0.9))
            rect.center = (int(sx), int(sy))
            pygame.draw.ellipse(surf, (84, 85, 91), rect)
            pygame.draw.ellipse(surf, (60, 61, 67), rect.inflate(-rect.w * 0.25, -rect.h * 0.25).move(0, int(rect.h * 0.08)))
            pygame.draw.ellipse(surf, (150, 152, 158), rect, max(1, int(rr * 0.08)))

    def _base(self, surf, cam, roll, t):
        back, height, pitch, shake = cam
        body = self._project(cam, 0, 1.0, roll)
        if not body:
            return
        sx, sy, depth = body
        w = FOCAL * BODY_W / depth
        if w < 6:
            return
        self.rover.draw_back(surf, sx, sy, w, t > 4.9, t)

    def _dust(self, surf, cam, roll, t, dt):
        """Dust kicked up by the wheels while the base rolls forward (3.4 to 4.8 s)."""
        if 3.4 < t < 4.9 and roll > 0.5:
            for side in (-1.3, 1.3):
                for _ in range(2):
                    self.puffs.append([side + self.rnd.uniform(-0.2, 0.2), roll - 0.8, 0.0, 0.0, self.rnd.uniform(0.7, 1.2), self.rnd.uniform(0.8, 1.6)])
        alive = []
        for p in self.puffs:
            p[3] += dt
            p[2] += dt * 1.6                                    # drifts up and back
            if p[3] < p[4]:
                alive.append(p)
                q = self._project(cam, p[0], p[2] * 0.6, p[1] - p[3] * 0.4)
                if q:
                    size = int(FOCAL * p[5] * (0.4 + p[3] / p[4]) / q[2])
                    if size > 4:
                        img = self._puff_at(size, int(255 * (1 - p[3] / p[4])))
                        surf.blit(img, (q[0] - img.get_width() / 2, q[1] - img.get_height() / 2))
        self.puffs = alive[-90:]

    def _puff_at(self, size, alpha):
        """Dust sprite at a quantised size and alpha, cached: scaling a sprite for every puff every frame is too slow."""
        key = (size // 6, alpha // 24)
        img = self.puff_cache.get(key)
        if img is None:
            if len(self.puff_cache) > 200:
                self.puff_cache.clear()
            img = pygame.transform.smoothscale(self.puff, (max(6, key[0] * 6), max(6, key[0] * 6)))
            img.set_alpha(key[1] * 24)
            self.puff_cache[key] = img
        return img

    def draw(self, surf, t):
        W, H = C.RENDER_W, C.RENDER_H
        real, t = t, t * 6.0 / C.INTRO_S                         # the shot is authored on 6 s and played in INTRO_S (5 s)
        dt = max(0.0, min(0.1, t - self.last_t))
        self.last_t = t
        surf.fill((0, 0, 0))
        cam, roll = self._camera_state(t)
        # sky: stars, the Earth, the sun glare
        self.stars.draw(surf, (0, 0), (0.0, 0.0))
        hz = H / 2 - FOCAL * math.tan(cam[2])                     # the horizon: the limit of the ground at infinity
        hz = max(H * 0.12, min(H * 0.9, hz))
        earth_x = W * 0.72 + math.sin(t * 0.05) * 20
        surf.blit(self.earth_glow, (earth_x - self.earth_glow.get_width() / 2, hz * 0.45 - self.earth_glow.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
        surf.blit(self.earth, (earth_x - self.earth.get_width() / 2, hz * 0.45 - self.earth.get_height() / 2))
        sun_x, sun_y = W * 0.12, hz * 0.22
        surf.blit(self.sun, (sun_x - self.sun.get_width() / 2, sun_y - self.sun.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
        # ground: a flat plane from the horizon down, then the grid, craters and the base
        if hz < H:
            surf.blit(self.ground, (0, int(hz)), pygame.Rect(0, int(hz), W, H - int(hz)))
        pygame.draw.line(surf, (196, 200, 210), (0, int(hz)), (W, int(hz)), 2)
        self._ground_grid(surf, cam, roll)
        self._craters(surf, cam)
        self._base(surf, cam, roll, t)
        self._dust(surf, cam, roll, t, dt)
        # title
        if t < 3.0:
            a = int(255 * _ease((t - 0.6) / 1.0) * (1.0 - _ease((t - 2.4) / 0.6)))
            if a > 0:
                fonts.text(surf, "LUNAR OUTPOST  T-MINUS_6", (W // 2, int(H * 0.16)), 76, K.WHITE, bold=True, anchor="center", alpha=a, shadow=True,
                           display=True, track=6)
        # meters fill one after another once the base is in frame
        if t >= 4.4:
            x0, y0 = W // 2 - 480, 70
            for i, (name, col) in enumerate(METER_ORDER):
                f = _ease((t - 4.4 - i * 0.3) / 0.7)
                b = pygame.Rect(x0 + i * 250, y0, 220, 18)
                fonts.text(surf, name.upper(), (b.left, b.top - 6), 14, K.GREY, bold=True, anchor="bottomleft", track=2)
                bar(surf, b, f, col)
        if t >= 5.0:
            a = int(255 * _ease((t - 5.0) / 0.5))
            fonts.text(surf, "Keep the outpost alive. Collect samples. Watch the sky.", (W // 2, int(H * 0.30)), 42, K.WHITE, bold=True,
                       anchor="center", alpha=a, shadow=True, track=1)
        fonts.text(surf, "press any key to skip", (W - 30, H - 36), 16, K.DIM, anchor="bottomright")
        if real > C.INTRO_S - 0.5:                               # the caller blends the intro into the game with this alpha
            return int(255 * max(0.0, 1.0 - (real - (C.INTRO_S - 0.5)) / 0.5))
        return int(255 * min(1.0, t / 0.6))

    def update(self, dt):
        self.stars.update(dt)
