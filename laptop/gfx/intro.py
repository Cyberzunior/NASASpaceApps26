"""The 5 second intro, drawn in code with the game's own pygame renderer. No video files.
0-1.5 s sky and stars, the surface rises, title fades in. 1.5-3.5 s the view settles behind the base as it rolls forward,
its lights come on and the four meters fill one after another. 3.5-5 s the mission line, then a fade into the game."""
import math
import pygame
import config as C
from gfx import fonts, palette as K
from gfx.rover import Rover
from gfx.starfield import Starfield

METER_ORDER = (("Power", K.YELLOW), ("Oxygen", K.CYAN), ("Food", K.GREEN), ("Shield", (190, 140, 255)))


def _ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


class Intro:
    def __init__(self):
        self.stars = Starfield()
        self.rover = Rover(60)
        self.ground = None

    def draw(self, surf, t):
        W, H = C.RENDER_W, C.RENDER_H
        surf.fill((0, 0, 0))
        self.stars.draw(surf, (0, 0), (t * 0.02, 0))
        # the surface rises (0 to 1.5 s) then the camera tips down behind the base (1.5 to 3.5 s)
        rise = _ease(t / 1.5)
        tip = _ease((t - 1.5) / 2.0)
        horizon = H - rise * H * 0.38 - tip * H * 0.3 + 0.0
        horizon = max(H * 0.18, horizon)
        pygame.draw.rect(surf, (104, 105, 110), (0, horizon, W, H - horizon))
        for i in range(14):                                         # perspective grid lines
            f = i / 14.0
            y = horizon + (H - horizon) * f * f
            pygame.draw.line(surf, (88, 89, 94), (0, y), (W, y), 2)
        for i in range(-10, 11):
            pygame.draw.line(surf, (88, 89, 94), (W / 2 + i * 12, horizon), (W / 2 + i * 260, H), 2)
        pygame.draw.line(surf, (170, 172, 180), (0, horizon), (W, horizon), 3)
        # title
        if t < 3.5:
            a = int(255 * _ease(t / 1.2) * (1.0 - _ease((t - 3.0) / 0.5)))
            fonts.text(surf, "LUNAR OUTPOST T-MINUS_6", (W // 2, int(H * 0.14)), 72, K.WHITE, bold=True, anchor="center", alpha=max(0, a), shadow=True)
        # the base: small at the horizon, rolling forward and growing as the camera sweeps down behind it
        if t >= 1.0:
            k = _ease((t - 1.0) / 2.5)
            size = 80 + 380 * k
            cy = horizon + 40 + (H - horizon) * (0.12 + 0.62 * k)
            self.rover.draw_back(surf, W / 2, cy, size, t > 2.3, t)
        # meters fill one after another from 1.5 s
        if t >= 1.5:
            x0, y0 = W // 2 - 480, 70
            for i, (name, col) in enumerate(METER_ORDER):
                f = _ease((t - 1.5 - i * 0.4) / 0.7)
                bar = pygame.Rect(x0 + i * 250, y0, 220, 18)
                fonts.text(surf, name.upper(), (bar.left, bar.top - 4), 16, K.GREY, anchor="bottomleft")
                pygame.draw.rect(surf, (20, 32, 60), bar, border_radius=6)
                if f > 0:
                    pygame.draw.rect(surf, col, (bar.left, bar.top, int(bar.w * f), bar.h), border_radius=6)
                pygame.draw.rect(surf, K.mix(col, K.WHITE, 0.3), bar, 2, border_radius=6)
        if t >= 3.5:
            a = int(255 * _ease((t - 3.5) / 0.4))
            fonts.text(surf, "Keep the outpost alive. Collect samples. Watch the sky.", (W // 2, int(H * 0.5)), 44, K.WHITE, bold=True,
                       anchor="center", alpha=a, shadow=True)
        fonts.text(surf, "press any key to skip", (W - 30, H - 36), 16, K.DIM, anchor="bottomright")
        if t > C.INTRO_S - 0.5:                                      # quick fade into the game view: the caller blends with this alpha
            return int(255 * max(0.0, 1.0 - (t - (C.INTRO_S - 0.5)) / 0.5))
        return 255

    def update(self, dt):
        self.stars.update(dt)
