"""Post-processing on the CPU, built around what pygame does fast (opaque ADD / MULT blits, small scales):

  * bloom: downscale, bright pass, blur on a tiny copy, add back. The glow layer is refreshed every few
    frames (see gfx.perf): it is a blur, so a few frames of lag are invisible. The downscale is nearest
    neighbour - 50x cheaper than smoothscale and unnoticeable once the blur has run.
  * vignette: one opaque MULT blit; red glow in heat and frost in cold are quantized ADD blits (no
    per-pixel alpha with surface alpha, which is slow in pygame).
  * chromatic aberration: only while damaged, done on the small bloom copy (red and blue fringes either side).
Level 0 = off, 1 = vignette only, 2 = full."""
import numpy as np
import pygame
import config as C
from gfx.perf import PERF

LEVELS = (0.34, 0.67, 1.0)


def _field(w, h, power):
    ys, xs = np.mgrid[0:h // 4, 0:w // 4]
    d = np.sqrt(((xs / (w / 4) - 0.5) * 2) ** 2 + ((ys / (h / 4) - 0.5) * 2) ** 2) / 1.414
    return np.clip(d ** power, 0, 1)


def _opaque(w, h, rgb_arr):
    small = pygame.image.frombuffer(np.ascontiguousarray(rgb_arr.astype(np.uint8)).tobytes(), (w // 4, h // 4), "RGB")
    return pygame.transform.smoothscale(small, (w, h)).convert()


class PostFx:
    def __init__(self, w=None, h=None):
        self.w, self.h = w or C.RENDER_W, h or C.RENDER_H
        f = _field(self.w, self.h, 2.6)
        self.dark = _opaque(self.w, self.h, np.dstack([255 * (1 - 0.6 * f)] * 3))          # MULT: darker toward the edges
        g = _field(self.w, self.h, 2.2)
        self.heat = [_opaque(self.w, self.h, np.dstack([g * 150 * k, g * 26 * k, g * 6 * k])) for k in LEVELS]
        self.frost = [_opaque(self.w, self.h, np.dstack([g * 40 * k, g * 85 * k, g * 120 * k])) for k in LEVELS]
        self.user_level = C.POSTFX
        self.level = C.POSTFX
        self.heat_a = self.frost_a = 0.0
        self.small_size = (self.w // 8, self.h // 8)
        self.tiny_size = (self.w // 24, self.h // 24)
        self.scratch = pygame.Surface(self.small_size).convert()
        self.glow = pygame.Surface((self.w, self.h)).convert()
        self.frame = 0

    def sync(self):
        """Recompute the effective level after the player changes the setting."""
        self.level = min(self.user_level, PERF.k["postfx"])

    def update(self, dt, state):
        """state 0 normal, 1 cold, 2 hot: tween the tinted vignettes."""
        self.heat_a += ((1.0 if state == 2 else 0.0) - self.heat_a) * min(1.0, dt * 4)
        self.frost_a += ((1.0 if state == 1 else 0.0) - self.frost_a) * min(1.0, dt * 4)

    @staticmethod
    def _pick(levels, a):
        if a < 0.08:
            return None
        return levels[min(2, int(a * 3.0))]

    def _blur(self, small, damage):
        tiny = pygame.transform.smoothscale(small, self.tiny_size)
        blur = pygame.transform.smoothscale(tiny, self.small_size)
        if damage > 0.05:                                       # chromatic fringes, made at 1/8 size: one pixel is 8
            red, blue = blur.copy(), blur.copy()
            red.fill((255, 0, 0), special_flags=pygame.BLEND_RGB_MULT)
            blue.fill((0, 70, 255), special_flags=pygame.BLEND_RGB_MULT)
            blur.blit(red, (1, 0), special_flags=pygame.BLEND_RGB_ADD)
            blur.blit(blue, (-1, 0), special_flags=pygame.BLEND_RGB_ADD)
        blur.fill((3, 3, 3), special_flags=pygame.BLEND_RGB_ADD)
        pygame.transform.smoothscale(blur, (self.w, self.h), self.glow)

    def apply(self, surf, damage=0.0):
        cap = PERF.k["postfx"]
        level = self.user_level if self.user_level < cap else cap      # the tier may cap, never raise
        self.level = level
        if level <= 0:
            return
        self.frame += 1
        if level >= 2:
            every = PERF.k["bloom_every"]
            if self.frame % every == 0 or damage > 0.05:
                # bright pass at 1/8: nearest is fine, the blur that follows removes the aliasing
                pygame.transform.scale(surf, self.small_size, self.scratch)
                self.scratch.fill((88, 88, 88), special_flags=pygame.BLEND_RGB_SUB)
                self._blur(self.scratch, damage)
            surf.blit(self.glow, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
        surf.blit(self.dark, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        h = self._pick(self.heat, self.heat_a)
        if h is not None:
            surf.blit(h, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
        f = self._pick(self.frost, self.frost_a)
        if f is not None:
            surf.blit(f, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
