"""The mobile lunar base: drawn from above with plain shapes (body, wheels, solar panels, lights), plus the glow sprite."""
import math
import pygame
from gfx import palette as K


def glow_sprite(radius, color, power=2.0):
    s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    for r in range(radius, 0, -2):
        a = (1.0 - r / radius) ** power
        pygame.draw.circle(s, (color[0], color[1], color[2], int(255 * a)), (radius, radius), r)
    return s


class Rover:
    """draw_top(): the rover seen from above on the map. draw_back(): the same base seen from behind (intro)."""

    def __init__(self, scale):
        self.S = scale
        self.t = 0.0
        self.headlight = glow_sprite(60, (255, 240, 200), 1.8)
        self.cache = {}

    def update(self, dt):
        self.t += dt

    def sprite(self, size):
        """The rover pointing right (+x), `size` pixels long, cached."""
        key = int(size)
        if key in self.cache:
            return self.cache[key]
        L, W = size, size * 0.62
        s = pygame.Surface((int(L * 1.5), int(W * 1.9)), pygame.SRCALPHA)
        cx, cy = s.get_width() / 2, s.get_height() / 2
        for sx in (-0.30, 0.30):                                              # wheels
            for sy in (-1, 1):
                pygame.draw.rect(s, (28, 30, 38), (cx + sx * L - L * 0.13, cy + sy * W * 0.62 - W * 0.14, L * 0.26, W * 0.28), border_radius=3)
        for sy in (-1, 1):                                                    # solar panels folded out
            pygame.draw.rect(s, (40, 70, 150), (cx - L * 0.3, cy + sy * W * 0.86 - W * 0.1, L * 0.6, W * 0.2))
            pygame.draw.rect(s, (110, 150, 230), (cx - L * 0.3, cy + sy * W * 0.86 - W * 0.1, L * 0.6, W * 0.2), 1)
        body = pygame.Rect(0, 0, L, W)
        body.center = (cx, cy)
        pygame.draw.rect(s, K.HULL_DARK, body.inflate(4, 4), border_radius=8)
        pygame.draw.rect(s, K.HULL, body, border_radius=8)
        pygame.draw.rect(s, (160, 175, 200), (body.left + L * 0.1, body.top + W * 0.12, L * 0.5, W * 0.76), border_radius=5)   # roof
        pygame.draw.rect(s, (70, 110, 150), (body.left + L * 0.62, body.top + W * 0.18, L * 0.26, W * 0.64), border_radius=4)   # cab window
        pygame.draw.circle(s, (255, 235, 170), (int(body.right - 3), int(body.top + W * 0.2)), max(2, int(W * 0.09)))
        pygame.draw.circle(s, (255, 235, 170), (int(body.right - 3), int(body.bottom - W * 0.2)), max(2, int(W * 0.09)))
        self.cache[key] = s
        return s

    def draw_top(self, surf, x, y, theta, size, lights=True, glow_scale=1.0):
        if lights:
            g = self.headlight
            a = math.radians(theta)
            lx, ly = x + math.cos(a) * size * 1.1, y + math.sin(a) * size * 1.1
            surf.blit(g, (lx - g.get_width() / 2, ly - g.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
        img = pygame.transform.rotate(self.sprite(size), -theta)
        surf.blit(img, img.get_rect(center=(int(x), int(y))))

    def draw_back(self, surf, cx, cy, w, lights_on, t):
        """Rear view for the cutscene and the 3D view later: box body, two wheels, a mast with a beacon."""
        h = w * 0.55
        pygame.draw.rect(surf, (28, 30, 38), (cx - w * 0.62, cy + h * 0.1, w * 0.2, h * 0.7), border_radius=6)
        pygame.draw.rect(surf, (28, 30, 38), (cx + w * 0.42, cy + h * 0.1, w * 0.2, h * 0.7), border_radius=6)
        body = pygame.Rect(cx - w / 2, cy - h / 2, w, h)
        pygame.draw.rect(surf, K.HULL_DARK, body.inflate(6, 6), border_radius=12)
        pygame.draw.rect(surf, K.HULL, body, border_radius=12)
        pygame.draw.rect(surf, (80, 100, 140), (cx - w * 0.36, cy - h * 0.34, w * 0.72, h * 0.22), border_radius=6)
        pygame.draw.line(surf, K.HULL_DARK, (cx, cy - h / 2), (cx, cy - h * 0.95), 4)
        col = K.RED if int(t * 3) % 2 else K.DIM
        pygame.draw.circle(surf, col, (int(cx), int(cy - h * 0.95)), 7)
        for sx in (-1, 1):                                                    # tail lights, on once the base wakes up
            c = (255, 80, 60) if lights_on else (70, 30, 30)
            pygame.draw.rect(surf, c, (cx + sx * w * 0.4 - 9, cy + h * 0.2, 18, 12), border_radius=3)
            if lights_on:
                g = glow_sprite(34, (255, 70, 50), 1.6)
                surf.blit(g, (cx + sx * w * 0.4 - 34, cy + h * 0.2 - 28), special_flags=pygame.BLEND_RGB_ADD)
