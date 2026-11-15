"""The Connections bar at the top of the menu: one row per device (HUD panel, Tower, Rover, Camera URL), a Connect button,
a status dot with text (green "connected", grey "not connected", red "lost") and a "Refresh COM ports" button.
Mouse: click a COM field to cycle ports (left half back, right half forward), click a text field to type, click Connect.
Keyboard: Tab enters the bar, Up / Down rows, Left / Right ports, type in text fields, Enter connects, F5 refreshes, Esc / Tab leaves."""
import pygame
import config as C
from gfx import fonts, palette as K
from gfx.widgets import dot, panel

COLORS = {"connected": K.GREEN, "not connected": K.GREY, "lost": K.RED}


class ConnectionsPanel:
    X, Y, W, H = 60, 14, 1800, 262
    ROW0, ROW_H = 74, 46

    def __init__(self):
        self.focus = None            # None = menu has the keyboard, else row index
        self.editing = False

    def rect(self):
        return pygame.Rect(self.X, self.Y, self.W, self.H)

    def field_rect(self, i):
        return pygame.Rect(self.X + 250, self.Y + self.ROW0 + i * self.ROW_H, 800, 38)

    def button_rect(self, i):
        return pygame.Rect(self.X + 1070, self.Y + self.ROW0 + i * self.ROW_H, 170, 38)

    def refresh_rect(self):
        return pygame.Rect(self.X + self.W - 270, self.Y + 14, 250, 38)

    # ---- input
    def on_click(self, conn, pos):
        if self.refresh_rect().collidepoint(pos):
            conn.refresh_ports()
            return True
        for i, key in enumerate(conn.order):
            row = conn.rows[key]
            f = self.field_rect(i)
            if f.collidepoint(pos):
                self.focus = i
                if row.kind == "port":
                    conn.cycle_port(key, -1 if pos[0] < f.centerx else 1)
                    self.editing = False
                else:
                    self.editing = True
                return True
            if self.button_rect(i).collidepoint(pos):
                self.focus, self.editing = i, False
                conn.toggle(key)
                return True
        return False

    def on_key(self, conn, e):
        """Returns True when the key was used. Called only while the bar has focus, or for Tab / F5 in the menu."""
        k = e.key
        if k == pygame.K_F5:
            conn.refresh_ports()
            return True
        if self.focus is None:
            if k == pygame.K_TAB:
                self.focus = 0
                return True
            return False
        key = conn.order[self.focus]
        row = conn.rows[key]
        if k in (pygame.K_TAB, pygame.K_ESCAPE):
            self.focus, self.editing = None, False
        elif k == pygame.K_UP:
            self.focus = (self.focus - 1) % len(conn.order)
        elif k == pygame.K_DOWN:
            self.focus = (self.focus + 1) % len(conn.order)
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
            conn.toggle(key)
        elif row.kind == "port" and k in (pygame.K_LEFT, pygame.K_RIGHT):
            conn.cycle_port(key, -1 if k == pygame.K_LEFT else 1)
        elif row.kind != "port":
            if k == pygame.K_BACKSPACE:
                row.value = row.value[:-1]
            elif e.unicode and e.unicode.isprintable():
                row.value += e.unicode
        return True

    # ---- drawing
    def draw(self, surf, conn, t):
        r = panel(surf, self.rect(), 200, scan=False)
        fonts.text(surf, "CONNECTIONS", (r.left + 20, r.top + 18), 24, K.CYAN, bold=True)
        fonts.text(surf, "Tab: keyboard    click a field to change it    the game also runs with nothing connected", (r.left + 250, r.top + 24), 17, K.GREY)
        b = self.refresh_rect()
        pygame.draw.rect(surf, (28, 50, 90), b, border_radius=8)
        pygame.draw.rect(surf, K.CYAN, b, 2, border_radius=8)
        fonts.text(surf, "Refresh COM ports", b.center, 19, K.WHITE, anchor="center")
        snap = conn.snapshot()
        desc = dict(conn.ports)
        for i, key in enumerate(conn.order):
            row = conn.rows[key]
            status, value, wanted, detail = snap[key]
            y = self.Y + self.ROW0 + i * self.ROW_H
            sel = self.focus == i
            fonts.text(surf, row.label, (self.X + 20, y + 19), 22, K.WHITE if sel else K.GREY, bold=sel, anchor="midleft")
            f = self.field_rect(i)
            pygame.draw.rect(surf, (16, 26, 52), f, border_radius=8)
            pygame.draw.rect(surf, K.CYAN if sel else (50, 80, 130), f, 2, border_radius=8)
            if row.kind == "port":
                text = value + ("   " + desc[value][:40] if value in desc else "") if value else "choose a COM port"
                fonts.text(surf, "<", (f.left + 14, f.centery), 22, K.GREY, anchor="midleft")
                fonts.text(surf, ">", (f.right - 14, f.centery), 22, K.GREY, anchor="midright")
                fonts.text(surf, text, f.center, 19, K.WHITE if value else K.DIM, mono=True, anchor="center")
            else:
                shown = value + ("_" if sel and int(t * 2) % 2 else "")
                fonts.text(surf, shown or ("ip:port" if row.kind == "addr" else "http://ip:port/stream"), (f.left + 14, f.centery), 19,
                           K.WHITE if value else K.DIM, mono=True, anchor="midleft")
            bt = self.button_rect(i)
            pygame.draw.rect(surf, (30, 90, 70) if wanted else (28, 50, 90), bt, border_radius=8)
            pygame.draw.rect(surf, K.GREEN if wanted else K.CYAN, bt, 2, border_radius=8)
            fonts.text(surf, "Disconnect" if wanted else "Connect", bt.center, 19, K.WHITE, anchor="center")
            col = COLORS[status]
            dot(surf, (self.X + 1280, y + 19), col, 8)
            fonts.text(surf, status, (self.X + 1300, y + 19), 21, col, anchor="midleft")
            if detail and status != "connected":
                fonts.text(surf, detail[:34], (self.X + 1470, y + 19), 15, K.DIM, anchor="midleft")
