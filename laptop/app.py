"""The application: starts the device threads, owns the state machine, turns keyboard / gamepad events into actions
and draws every frame. The render loop never blocks on I/O: devices live in their own threads and meet the loop only
through the shared state (under a lock) and an event queue."""
import math
import os
import random
import sys
import threading
import time
import traceback

import pygame

import config as C
from core import statemachine as S
from core.clock import mmss, now
from core.events import Bus
from core.game import Game
from core.state import SharedState
from core.statemachine import StateMachine
from devio import recorder
from devio.camera import Camera
from devio.discovery import SerialScanner, UdpHub
from devio.gamepad import InputThread, rumble
from devio import pad as padmod
from devio.connections import Connections
from core.port_prompt import PortPrompt
from gfx.fonts import text as draw_text
from devio.keyboard_fallback import read_keys
from devio.links import HudLink, RobotLink, TowerLink, link_thread
from gfx.perf import PERF


class Args:
    """Command line options as a plain object (also used by the tests)."""
    sim_robot = sim_tower = sim_hud = sim_camera = False
    windowed = False
    debug = False
    demo = False
    no_audio = False
    no_serial = False        # never open real serial ports (tests)
    seed = None

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        if kw.get("sim"):
            self.sim_robot = self.sim_tower = self.sim_hud = self.sim_camera = True

    @property
    def sim_all(self):
        return self.sim_robot and self.sim_tower and self.sim_hud and self.sim_camera


class App:
    def __init__(self, args=None, headless=False):
        self.args = args or Args()
        self.headless = headless
        self.log, self.log_path = recorder.setup(self.args.debug)
        for m in C.MESSAGES:
            print("config: " + m)
            self.log("config: " + m)
        if self.args.seed is not None:
            random.seed(self.args.seed)
        if self.args.demo:
            C.DEMO_MODE = True
        self.sim_all = self.args.sim_all
        self.t = 0.0
        self.perf = PERF
        self.state = SharedState()
        self.bus = Bus()
        self.stop_flag = threading.Event()
        self.links = {"robot": RobotLink(self.state, self.bus, self.log), "tower": TowerLink(self.state, self.bus, self.log),
                      "hud": HudLink(self.state, self.bus, self.log)}
        from gfx import fonts, widgets
        fonts.reset()
        widgets._panels.clear()
        widgets._overlays.clear()
        self._init_display()
        self.threads = []
        self.sims = []
        self._start_devices()
        self.game = Game(self.state, self.links["robot"], self.links["tower"], self.links["hud"], self.log)
        self.intro = None
        self.intro_played = False
        self.pan_deg, self.pan_sent, self.t_pan = 0.0, 0, 0.0
        self.fade = 0.0
        self.sm = StateMachine(self._on_state)
        self.audio = None
        self.world_view = self.postfx = self.hud = None
        self.menu = self.settings = self.calib = self.pause = self.results = self.hwcheck = None
        self.gameover_fx = None
        self.hw_return = S.MENU
        self.last_results, self.last_mode = None, "MANUAL"
        self.history = {}
        self.pad_name = ""
        self.pad_button_seen = False
        self.cam_full = False
        self.debug_on = self.args.debug
        self.fps, self.frame_ms, self.worst_ms, self._fps_n, self._fps_t = 60.0, 16.0, 0.0, 0, now()
        self.estop = False
        self.start_down = None
        self.nav_t, self.back_held = 0.0, None
        self.keys_held_space = False
        self.errors = collections_deque()
        self.damage = 0.0
        self.ap_on_prev = False
        self.cam_prev = False
        self.boot = None
        self.wall = now()
        self._build_boot()
        self._scan_pads()

    # ------------------------------------------------------------------ setup
    def _init_display(self):
        os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
        pygame.display.set_caption("T-Minus_6")
        flags = pygame.RESIZABLE
        self.scaled = True
        try:
            if C.FULLSCREEN and not self.args.windowed:
                flags |= pygame.FULLSCREEN
            self.screen = pygame.display.set_mode((C.RENDER_W, C.RENDER_H), flags | pygame.SCALED, vsync=1 if C.VSYNC else 0)
        except Exception:
            try:
                self.screen = pygame.display.set_mode((C.RENDER_W, C.RENDER_H), flags | pygame.SCALED)
            except Exception:
                self.scaled = False
                self.screen = pygame.display.set_mode((C.WINDOW_W, C.WINDOW_H), pygame.RESIZABLE)
        # with SCALED the renderer already copies the display surface to the window: draw straight into it
        # and skip a full-screen blit (8 MB) every frame. Without it we need a canvas that gets scaled.
        self.canvas = self.screen if self.scaled else pygame.Surface((C.RENDER_W, C.RENDER_H)).convert()
        self.clock = pygame.time.Clock()
        self.flip_ms = 0.0

    def _start_devices(self):
        a = self.args
        self.hub = UdpHub(self.links, self.log)
        self.scanner = SerialScanner(self.links, self.log, None, enabled=C.AUTO_SCAN and not (a.no_serial or a.sim_all))
        from devio import sim_devices as sd
        field = None
        if a.sim_robot:
            r = sd.SimRobot(self.hub.port)
            self.sims.append(r)
            self.sim_robot = r
            field = r.field
        if a.sim_tower:
            t = sd.SimTower()
            self.sim_tower = t
            self.sims.append(t)
            self.scanner.add_sim("SIM-TOWER", t.port, "tower")
        self.sim_hud = None
        if a.sim_hud:
            s = sd.SimHud()
            self.sim_hud = s
            self.sims.append(s)
            self.scanner.add_sim("SIM-HUD", s.port, "hud")
        src = None
        if a.sim_camera:
            robot = getattr(self, "sim_robot", None)
            src = sd.sim_camera_source((lambda: robot.pose) if robot else (lambda: self.game.craft))
        self.camera = Camera(self.state, self.log, sim_source=src, robot_ip=self._robot_ip)
        self.connections = Connections(self.links, self.hub, self.scanner, self.camera, self.state, self.log)
        self.port_prompt = PortPrompt()
        self.input = InputThread(self.state, self.links["robot"], self.log)
        for target, name in ((self.hub.run, "udp-hub"), (self.scanner.run, "serial-scan")):
            th = threading.Thread(target=self._guard(target, name), daemon=True, name=name)
            self.threads.append(th)
        self.threads.append(threading.Thread(target=self._guard(lambda: link_thread(list(self.links.values()), self.stop_flag, self.state), "links"),
                                             daemon=True, name="links"))
        for th in self.threads:
            th.start()
        for s in self.sims:
            s.start()
        self.camera.start()
        self.input.start()
        if not (a.no_serial or a.sim_all):
            self.connections.connect_saved()

    def _guard(self, fn, name):
        """A device thread never dies on an error: log it, wait with a growing back-off, run again."""
        def run():
            delay = 0.5
            while not self.stop_flag.is_set():
                try:
                    fn()
                    return
                except Exception as e:
                    self.log("thread %s crashed: %r" % (name, e))
                    self.stop_flag.wait(delay)
                    delay = min(5.0, delay * 2)
        return run

    def _robot_ip(self):
        tr = self.links["robot"].best()
        if tr and ":" in tr.name and tr.name.split(":")[0].count(".") == 3 and not tr.name.startswith("127."):
            return tr.name.split(":")[0]
        return None

    def _build_boot(self):
        from audio.mixer import Mixer
        from gfx.hud import Hud
        from gfx.postfx import PostFx
        from gfx.screens import (BootScreen, CalibrateScreen, HwCheckScreen, MenuScreen, PauseOverlay, ResultsScreen,
                                 SettingsScreen)
        from gfx.world import WorldView

        def audio():
            self.audio = Mixer() if not self.args.no_audio else _SilentMixer()

        def world():
            self.world_view = WorldView()

        def post():
            self.postfx = PostFx()

        def hud():
            self.hud = Hud()
            from gfx.intro import Intro
            self.intro = Intro()

        def screens():
            self.menu, self.settings, self.calib = MenuScreen(), SettingsScreen(), CalibrateScreen()
            self.pause, self.results, self.hwcheck = PauseOverlay(), ResultsScreen(), HwCheckScreen()

        self.boot = BootScreen([("fonts", lambda: None), ("sounds", audio), ("lunar surface", world), ("post-processing", post),
                                ("interface", hud), ("screens", screens), ("devices", lambda: None)])

    def boot_all(self):
        """Finish booting at once (tests, and --sim runs that skip the logo)."""
        while not self.boot.finished and self.sm.state == S.BOOT:
            self.boot.update(self, 0.5)
            if self.boot.done >= self.boot.total:
                self.boot.finished = True
        self._finish_boot()

    def _finish_boot(self):
        if self.sm.state == S.BOOT:
            self.sm.go(S.MENU, self.t)
            self.game.reset()
            self.hud.reset(self.game)
            self.postfx.sync()

    # ------------------------------------------------------------------ pads
    def _scan_pads(self):
        try:
            padmod.init()
            if pygame.joystick.get_count() > 0:
                self._set_pad(padmod.open_pad(0))
        except Exception as e:
            self.log("pad scan failed: %r" % e)
        if self.state.pad is None and not self.sim_all:
            self.pad_name = ""

    def _set_pad(self, pad):
        try:
            pad.init()
        except Exception:
            pass
        self.state.pad = pad
        self.pad_name = pad.get_name()
        d = self.state.devices["pad"]
        with self.state.lock:
            d.connected, d.where = True, self.pad_name
        self.log("gamepad: %s (%d axes, %d buttons, %s layout)" % (self.pad_name, pad.get_numaxes(), pad.get_numbuttons(),
                                                                  "standard SDL" if pad.standard else "raw, set by config.py"))

    def _pad_gone(self):
        self.state.pad = None
        with self.state.lock:
            d = self.state.devices["pad"]
            d.connected, d.where = False, ""
        self.log("gamepad removed")

    # ------------------------------------------------------------------ state changes
    def _on_state(self, old, new):
        st = self.state
        self.log("state %s -> %s" % (old, new))
        st.drive_enabled = new in S.FLYING
        if new in S.FLYING:
            self.game.tower.allow(True)
        else:
            self.game.tower.allow(False)
        if new == S.PAUSE and self.audio:
            self.audio.play("pause")
        if new in (S.MENU, S.SETTINGS, S.HWCHECK, S.CALIBRATE, S.PAUSE, S.GAMEOVER, S.RESULTS):
            st.ap_cmd = (0.0, 0.0)
        if not ({old, new} <= {S.PLAY, S.PRACTICE, S.PAUSE} or new == S.GAMEOVER):
            self.fade = 1.0                                      # every new screen fades in from black (not pause, not the failure sequence)

    def goto(self, name):
        if name == S.HWCHECK:
            self.hw_return = self.sm.state if self.sm.state in (S.MENU, S.PAUSE) else S.MENU
        ok = self.sm.go(name, self.t)
        if ok and name == S.CALIBRATE:
            self.calib.reset()
        return ok

    def toast(self, text, kind="info"):
        if self.hud:
            self.hud.toasts.add(text, kind)

    def start_run(self, practice=False):
        intro = not self.intro_played and not C.SKIP_INTRO
        self.game.reset(practice=practice, intro=intro)
        self.intro_played = True
        self.hud.reset(self.game)
        self.world_view.reset_fx()
        self.gameover_fx = None
        self.estop = False
        self.damage = 0.0
        self.cam_full = False
        self.pan_deg = 0.0
        self.links["robot"].pan(0)
        self.goto(S.PRACTICE if practice else S.PLAY)

    def menu_choice(self, name):
        if name == "PLAY":
            self.start_run(False)
        elif name == "CALIBRATE":
            self.goto(S.CALIBRATE)
        elif name == "SETTINGS":
            self.goto(S.SETTINGS)
        elif name == "HARDWARE CHECK":
            self.goto(S.HWCHECK)
        elif name == "QUIT":
            raise SystemExit

    def pause_game(self):
        if self.sm.flying():
            self.goto(S.PAUSE)

    def resume(self):
        if self.sm.state != S.PAUSE:
            return
        if self.estop:
            self.estop = False
            self.links["robot"].latch(False)
            self.links["tower"].set_armed(True)
        self.goto(self.sm.resume)

    def pause_choice(self, name):
        if name == "HARDWARE CHECK":
            self.goto(S.HWCHECK)
        elif name == "QUIT TO MENU":
            self.links["robot"].latch(False)
            self.game.reset()
            self.goto(S.MENU)

    def resync(self):
        """Hold Start 2 s: restart the run."""
        practice = self.game.practice
        self.game.reset(practice=practice)
        self.hud.reset(self.game)
        self.estop = False
        self.toast("Run restarted", "ok")

    def emergency_stop(self):
        """Space+Esc or Back+Start held: robot and tower stop at once and the game pauses."""
        self.log("EMERGENCY STOP")
        self.links["robot"].latch(True)
        self.links["tower"].set_armed(False)
        self.estop = True
        self.state.test_cmd = None
        if self.sm.flying():
            self.goto(S.PAUSE)
        self.toast("EMERGENCY STOP: rover and tower stopped. Resume to release.", "bad")

    def after_results(self):
        self.links["robot"].latch(False)
        self.game.reset()
        self.hud.reset(self.game)
        if C.RESTART_TO_PLAY:
            self.start_run(self.game.practice)
        else:
            self.goto(S.MENU)
            self.goto(S.MENU)

    def _begin_game_over(self):
        from gfx.screens import GameOverFX
        g = self.game
        if self.sm.state == S.PLAY:
            self.sm.go(S.GAMEOVER, self.t)
        self.gameover_fx = GameOverFX(self.world_view, g, self.audio)
        res = g.results()
        self.last_results = res
        if res["time"] > C.BEST_TIME:
            C.save_local(BEST_TIME=round(res["time"], 1))
        rumble(self.state.pad, 1.0, 600)
        self.audio.hush()
        self.audio.play("alarm")
        self.state.ap_on = False

    # ------------------------------------------------------------------ input
    def _action(self, a):
        st = self.sm.state
        if st == S.BOOT:
            return
        if isinstance(a, str) and a.startswith("char:"):
            ch = a[5:]
            if st == S.HWCHECK:
                if ch in "yY":
                    a = "yes"
                elif ch in "nN":
                    a = "no"
            if st in (S.CALIBRATE, S.HWCHECK):
                (self.calib if st == S.CALIBRATE else self.hwcheck).handle(self, a)
            return
        if a == "mute":
            self.toast("Sound " + ("off" if self.audio.toggle_mute() else "on"))
            return
        if a == "fullscreen":
            try:
                pygame.display.toggle_fullscreen()
            except Exception:
                pass
            return
        if a == "postfx":
            self.postfx.user_level = (self.postfx.user_level + 1) % 3
            self.postfx.sync()
            self.toast("Post-processing: " + ("off", "vignette", "full")[self.postfx.user_level])
            return
        if a == "debug":
            self.debug_on = not self.debug_on
            return
        if a == "quality":
            mode = self.perf.cycle()
            C.save_local(QUALITY=mode)
            self.postfx.sync()
            self.toast("Quality: " + mode.upper(), "ok")
            return
        if a == "estop":
            self.emergency_stop()
            return
        if a == "hwcheck":
            if self.sm.flying():
                self.pause_game()
            if self.sm.state in (S.MENU, S.PAUSE):
                self.goto(S.HWCHECK)
            return
        if st in S.FLYING:
            g = self.game
            if a == "ap":
                on = g.toggle_autopilot()
                self.toast("Auto-pilot " + ("ON" if on else "OFF"), "ok" if on else "info")
                self.audio.play("click")
            elif a == "cam":
                self.cam_full = not self.cam_full
            elif a == "recenter":
                self.pan_deg = 0.0
                self.toast("Camera centred")
            elif a == "fire":
                if g.fire_test_asteroid():
                    self.toast("Test shot", "warn")
            elif isinstance(a, str) and a.startswith("act"):
                msg = g.action(int(a[3:]))
                if msg:
                    self.toast(msg, "warn" if ("Not enough" in msg or "locked" in msg) else "ok")
                    self.audio.play("click")
            elif a in ("start", "pause", "back"):
                self.pause_game()
        elif st == S.GAMEOVER:
            pass                                                       # after game over the stick does nothing
        elif st == S.PAUSE:
            self.pause.handle(self, "confirm" if a == "ap" else a)
        elif st == S.MENU:
            if a == "fire":                                            # Test shot from the menu: straight to the tower
                ok = self.links["tower"].test_sweep()
                self.toast("Tower test: sweep, then beam back down" if ok else "Test shot: tower not connected", "warn")
            else:
                self.menu.handle(self, a)
        elif st == S.SETTINGS:
            self.settings.handle(self, a)
        elif st == S.CALIBRATE:
            if a == "fire":
                self.calib.handle(self, "fire")
            else:
                self.calib.handle(self, a)
        elif st == S.HWCHECK:
            self.hwcheck.handle(self, a)
        elif st == S.RESULTS:
            self.results.handle(self, a)

    def _port_key(self, e):
        p = self.port_prompt
        if e.key == pygame.K_ESCAPE:
            p.cancel()
            self.toast("Port setup cancelled", "warn")
        elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if p.enter():
                for key, val in p.values.items():
                    self.connections.rows[key].value = val
                    self.connections.connect(key)
                self.toast("Ports: ipad %s, tower %s, rover %s" % (p.values["hud"], p.values["tower"], p.values["robot"]), "ok")
        elif e.key == pygame.K_BACKSPACE:
            p.back()
        else:
            p.type(e.unicode)

    def _draw_port_prompt(self, cv):
        p = self.port_prompt
        r = pygame.Rect(C.RENDER_W // 2 - 300, C.RENDER_H // 2 - 80, 600, 160)
        pygame.draw.rect(cv, (10, 14, 22), r, border_radius=12)
        pygame.draw.rect(cv, (90, 200, 255), r, 2, border_radius=12)
        draw_text(cv, p.question, (r.centerx, r.y + 28), 28, anchor="midtop", bold=True)
        draw_text(cv, "COM" + p.buf + "_", (r.centerx, r.y + 74), 40, anchor="midtop", mono=True)
        draw_text(cv, "type the number, Enter = next, Esc = cancel", (r.centerx, r.bottom - 32), 20, (150, 160, 175), anchor="midtop")

    KEYMAP = {pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left", pygame.K_RIGHT: "right",
              pygame.K_RETURN: "confirm", pygame.K_KP_ENTER: "confirm", pygame.K_F2: "hwcheck", pygame.K_F3: "postfx",
              pygame.K_F4: "debug", pygame.K_F6: "quality", pygame.K_F11: "fullscreen", pygame.K_m: "mute", pygame.K_c: "cam", pygame.K_x: "fire",
              pygame.K_p: "ap", pygame.K_y: "ap", pygame.K_r: "recenter",
              pygame.K_1: "act1", pygame.K_2: "act2", pygame.K_3: "act3", pygame.K_4: "act4"}

    def _key(self, e):
        k, st = e.key, self.sm.state
        held = pygame.key.get_pressed()
        if (k == pygame.K_ESCAPE and held[pygame.K_SPACE]) or (k == pygame.K_SPACE and held[pygame.K_ESCAPE]):
            return "estop"
        if st in (S.CALIBRATE, S.HWCHECK):
            if k == pygame.K_BACKSPACE:
                return "char:\b"
            if e.unicode and (e.unicode.isdigit() or e.unicode in ".yYnN") and not (st == S.CALIBRATE and e.unicode in "yYnN"):
                return "char:" + e.unicode
        if k == pygame.K_ESCAPE:
            return "back"
        if k == pygame.K_SPACE and pygame.key.get_mods() & pygame.KMOD_CTRL and st in S.FLYING:
            return "ap"                                          # Ctrl+Space: autopilot on / off
        if k == pygame.K_SPACE:
            return "ap" if st in S.FLYING else "confirm"
        if st == S.MENU or st == S.SETTINGS or st == S.PAUSE:
            if k in (pygame.K_w,):
                return "up"
            if k in (pygame.K_s,):
                return "down"
            if k == pygame.K_a:
                return "left"
            if k == pygame.K_d:
                return "right"
        if st in (S.PLAY, S.PRACTICE) and k in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT, pygame.K_w, pygame.K_a, pygame.K_s,
                                                pygame.K_d, pygame.K_q, pygame.K_e):
            return None
        if st == S.CALIBRATE and k == pygame.K_x:
            return "fire"
        a = self.KEYMAP.get(k)
        if a in ("recenter", "act1", "act2", "act3", "act4") and st not in S.FLYING:
            return None
        if a == "fire" and st == S.MENU:
            return a
        if a in ("ap", "cam", "fire") and st not in S.FLYING and st != S.CALIBRATE:
            return "back" if a == "cam" and st != S.HWCHECK else None
        return a

    def _button(self, b):
        st = self.sm.state
        if b == C.BTN_FIRE and (st in S.FLYING or st in (S.MENU, S.CALIBRATE)):   # RB: the test shot, like the X key
            return "fire"
        if st in S.FLYING and b in C.BTN_ACTIONS:
            return "act%d" % (C.BTN_ACTIONS.index(b) + 1)
        if b == C.BTN_BACK:
            self.back_held = now()
            return "hwcheck" if st in (S.MENU, S.PAUSE) or st in S.FLYING else "back"
        if b == C.BTN_RESTART:
            self.start_down = now()
            return "start"
        if b == C.BTN_AUTOPILOT:
            return "ap" if st in S.FLYING else ("yes" if st == S.HWCHECK else None)
        if b == C.BTN_CAMERA:
            return "cam" if st in S.FLYING else "back"
        if b == C.BTN_CONFIRM:
            return "confirm"
        return None

    def pump_events(self):
        for e in pygame.event.get():
            a = None
            if e.type == pygame.QUIT:
                raise SystemExit
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_y and e.mod & pygame.KMOD_CTRL:
                    self.port_prompt.start()                             # Ctrl+Y: set the three COM ports
                    continue
                if self.port_prompt.active:
                    self._port_key(e)
                    continue
                if self.game.intro_on and self.sm.flying():
                    self.game.skip_intro()                              # any key skips the intro
                    continue
                if self.sm.state == S.MENU and (e.key in (pygame.K_TAB, pygame.K_F5) or self.menu.typing) and self.menu.on_key(self, e):
                    continue
                a = self._key(e)
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self.sm.state == S.MENU:
                self.menu.on_click(self, e.pos)
            elif e.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP, pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP):
                b = padmod.button_number(self.state.pad, e)           # a standard pad: controller events only, else joystick events
                if b is None:
                    continue
                kind, n = b
                if kind == "dpad":
                    a = n
                elif kind == "down":
                    self.pad_button_seen = True
                    if self.game.intro_on and self.sm.flying():
                        self.game.skip_intro()
                        continue
                    a = self._button(n)
                else:
                    if n == C.BTN_RESTART:
                        self.start_down = None
                    if n == C.BTN_BACK:
                        self.back_held = None
            elif e.type == pygame.JOYHATMOTION:
                if self.state.pad is not None and self.state.pad.standard:
                    continue                                              # the d-pad arrives as controller buttons
                x, y = e.value
                a = "left" if x < 0 else "right" if x > 0 else "up" if y > 0 else "down" if y < 0 else None
            elif e.type == pygame.JOYDEVICEADDED:
                try:
                    if self.state.pad is None:                            # the first pad wins; a second one is ignored
                        self._set_pad(padmod.open_pad(e.device_index))
                        self.toast("Gamepad connected: " + self.pad_name, "ok")
                        self.audio and self.audio.play("connect")
                except Exception as ex:
                    self.log("pad add failed: %r" % ex)
            elif e.type == pygame.JOYDEVICEREMOVED:
                if self.state.pad is not None and getattr(self.state.pad, "instance_id", None) not in (None, e.instance_id):
                    continue                                              # some other pad went away
                self._pad_gone()
                self.toast("Gamepad disconnected: pair it again in Bluetooth settings", "warn")
                self.audio and self.audio.play("disconnect")
            if a:
                self._action(a)
        # keyboard drive: always on (the mixer takes whichever input is pushed furthest)
        self.state.keys = read_keys() if self.sm.flying() else (0.0, 0.0)
        # long presses: hold Start 2 s = re-sync, Back + Start held 1 s = emergency stop
        t = now()
        if self.start_down and t - self.start_down >= 2.0 and self.sm.state in (S.PLAY, S.PRACTICE, S.PAUSE):
            self.start_down = None
            self.resync()
        if self.start_down and self.back_held and t - max(self.start_down, self.back_held) >= 1.0:
            self.start_down = self.back_held = None
            self.emergency_stop()
        # stick navigation in menus (edge triggered with repeat)
        if not self.sm.flying() and self.state.pad is not None and self.sm.state in (S.MENU, S.SETTINGS, S.PAUSE, S.CALIBRATE):
            sp, tu = self.state.stick
            if t - self.nav_t > (0.18 if self.nav_t_active else 0.4) and (abs(sp) > 0.6 or abs(tu) > 0.6):
                self.nav_t, self.nav_t_active = t, True
                self._action("up" if sp > 0.6 else "down" if sp < -0.6 else "left" if tu < -0.6 else "right")
            elif abs(sp) < 0.3 and abs(tu) < 0.3:
                self.nav_t_active = False

    nav_t_active = False

    # ------------------------------------------------------------------ bus
    def drain_bus(self):
        for ev in self.bus.drain():
            k = ev.kind
            if k == "tower_old_fw":
                self.toast("Tower: old firmware on the Uno. Flash firmware/tower/tower.ino once", "bad")
            elif k == "joy_button":                                     # the joystick button is the test shot
                self._action("fire")
            elif k == "tower_range":
                self.toast("Tower distance: %.0f cm" % ev.data[0])
            elif k == "bumper":
                rumble(self.state.pad, 0.8, 300)
                self.toast("Bumper hit", "warn")
            elif k in ("device_up", "device_down"):
                role = ev.data[0]
                label = {"robot": "Rover", "tower": "Tower", "hud": "HUD panel"}.get(role, role)
                if k == "device_up":
                    self.toast(label + " connected", "ok")
                    self.audio and self.audio.play("connect")
                else:
                    self.game.handle(ev)
                    self.toast(label + " lost", "warn")
                    self.audio and self.audio.play("disconnect")

    def _fx(self):
        g, wv = self.game, self.world_view
        for e in g.fx:
            kind = e[0]
            wv.fx(g, e, self.shake, self.audio)
            if kind == "hit":
                self.damage = 1.0
                self.audio.play("hit")
                self.audio.play("heart")
                rumble(self.state.pad, 0.9, 350)
                self.hud.hit_flash = 0.35
            elif kind == "asteroid_miss":
                self.audio.play("hit", 0.4)
                rumble(self.state.pad, 0.35, 200)
            elif kind == "asteroid_warn":
                self.audio.play("incoming")
                rumble(self.state.pad, 0.3, 200)
                self.toast("ASTEROID INCOMING", "bad")
            elif kind == "heart":
                self.audio.play("heart")
                rumble(self.state.pad, 0.6, 250)
                self.hud.hit_flash = 0.25
            elif kind == "pickup":
                self.audio.play("pickup")
                rumble(self.state.pad, 0.3, 120)
                self.toast("Sample collected: %s" % e[3], "ok")
            elif kind == "storm":
                self.audio.play("spike")
                self.toast("RADIATION STORM", "warn")
            elif kind == "harvest":
                self.audio.play("confirm")
            elif kind == "intro_end":
                self.audio.play("ready")
            elif kind == "gameover":
                pass
        g.fx.clear()
        for text, kind in g.toasts:
            self.toast(text, kind)
        g.toasts.clear()

    # ------------------------------------------------------------------ frame
    @property
    def shake(self):
        if not hasattr(self, "_shake"):
            from gfx.shake import Shake
            self._shake = Shake()
        return self._shake

    def update(self, dt):
        st = self.sm.state
        g = self.game
        self.wall = now()
        self.drain_bus()
        pad_dev = self.state.devices["pad"]
        pad_dev.connected = self.state.pad is not None or self.sim_all
        self.connections.update()
        if self.sim_all and not self.pad_name:
            pad_dev.where, pad_dev.sim = "keyboard (sim)", True
        if st == S.BOOT:
            self.boot.update(self, dt)
            if self.boot.finished:
                self._finish_boot()
            return
        if st in S.FLYING:
            g.step(dt, self.wall)
            self._fx()
            if g.over and self.sm.state in S.FLYING:
                self._begin_game_over()
            self.state.ap_on = self.state.ap_on and not g.over
        elif st == S.GAMEOVER:
            g.idle(dt, self.wall)
            if self.gameover_fx and self.gameover_fx.update(dt, g):
                self.sm.go(S.RESULTS, self.t)
        else:
            g.idle(dt, self.wall)
            self._fx()
        if self.intro is not None and g.intro_on:
            self.intro.update(dt)
        if st in S.FLYING and not g.intro_on and not g.over:
            self._pan(dt)
        if st == S.GAMEOVER:
            self._fx()
        self.state.turn_scale = g.state.turn_scale
        {S.MENU: self.menu, S.SETTINGS: self.settings, S.CALIBRATE: self.calib, S.HWCHECK: self.hwcheck,
         S.RESULTS: self.results}.get(st, _NullScreen()).update(self, dt)
        speed01 = abs(g.speed_ms) / max(0.1, C.V_MAX * C.METERS_PER_CM) if st in S.FLYING else 0.0
        self.world_view.update(dt, g, speed01)
        self.postfx.update(dt, g.thermal.state if st in S.FLYING or st == S.PAUSE else 0)
        self.hud.update(dt, g)
        self.shake.update(dt)
        self.fade = max(0.0, self.fade - dt / 0.4)
        self.damage = max(0.0, self.damage - dt * 3.0)
        self.audio.update(speed01, st in S.FLYING and not g.over, st in S.FLYING or st == S.PAUSE)

    def _pan(self, dt):
        """Q / E and the right stick pan the camera; R recentres. Sends C,angle when it changes (at most 20 per second)."""
        keys = pygame.key.get_pressed()
        d = (1.0 if keys[pygame.K_e] else 0.0) - (1.0 if keys[pygame.K_q] else 0.0)
        pan_axis = getattr(self.state.pad, "pan_axis", C.AXIS_PAN)
        if d == 0.0 and self.state.pad is not None and 0 <= pan_axis < len(self.state.raw_axes):
            from core.model import shape_axis
            d = shape_axis(self.state.raw_axes[pan_axis])
        self.pan_deg = max(-C.PAN_LIMIT_DEG, min(C.PAN_LIMIT_DEG, self.pan_deg + d * C.PAN_SPEED_DEG_S * dt))
        t = now()
        if int(round(self.pan_deg)) != self.pan_sent and t - self.t_pan >= 0.05:
            self.pan_sent, self.t_pan = int(round(self.pan_deg)), t
            self.links["robot"].pan(self.pan_sent)

    def _ctx(self):
        return {"ap_on": self.state.ap_on, "speed01": min(1.0, abs(self.game.speed_ms) / max(0.1, C.V_MAX * C.METERS_PER_CM)),
                "shake": self.shake.offset(), "hide_craft": self.sm.state in (S.GAMEOVER,),
                "backdrop": self.sm.state in (S.MENU, S.SETTINGS, S.CALIBRATE, S.HWCHECK)}

    def draw(self):
        from gfx.screens import dim
        st, g, cv = self.sm.state, self.game, self.canvas
        if st == S.BOOT:
            cv.fill((5, 8, 20))
            self.boot.draw(cv, self)
        elif st == S.RESULTS:
            self.results.draw(cv, self)
        else:
            ctx = self._ctx()
            self.world_view.draw(cv, g, ctx)
            if ctx["shake"] != (0, 0):                           # the world shakes, the HUD drawn after it stays still
                cv.scroll(*ctx["shake"])
            if st == S.GAMEOVER and self.gameover_fx:
                pass
            self.postfx.apply(cv, self.damage)
            ui = {"conn": self.connections.snapshot(), "ap_on": self.state.ap_on, "pad_on": self.state.pad is not None, "camera": self.camera,
                  "cam_full": self.cam_full and st in S.FLYING, "debug": self._debug_info() if self.debug_on else None}
            if st in S.FLYING and g.intro_on:
                alpha = self.intro.draw(self.intro_surf(), g.intro_t)
                s = self.intro_surf()
                s.set_alpha(alpha)
                cv.blit(s, (0, 0))
            elif st in S.FLYING or st == S.PAUSE:
                self.hud.draw(cv, g, ui)
            elif st == S.GAMEOVER:
                self.hud.meters_panel(cv, g)
                self.hud.conn_strip(cv, ui["conn"])
                self.gameover_fx.draw(cv, g)
            else:
                dim(cv, 120 if st == S.MENU else 195)
                if st != S.MENU:
                    self.hud.conn_strip(cv, ui["conn"])
                self.hud.toasts.draw(cv, C.RENDER_W // 2, 840 if st == S.MENU else 74)
                if self.port_prompt.active:
                    self._draw_port_prompt(cv)
                {S.MENU: self.menu, S.SETTINGS: self.settings, S.CALIBRATE: self.calib, S.HWCHECK: self.hwcheck}[st].draw(cv, self)
            if st == S.PAUSE:
                self.pause.draw(cv, self)
            if self.hud.hit_flash > 0 and st in S.FLYING:
                from gfx.widgets import overlay
                overlay(cv, (255, 30, 30), 95 * min(1.0, self.hud.hit_flash / 0.35))
        if self.fade > 0.01:
            from gfx.widgets import overlay
            overlay(cv, (0, 0, 0), 255 * self.fade * self.fade)
        t0 = now()
        if self.canvas is not self.screen:                        # no SCALED: scale the canvas to the window
            pygame.transform.smoothscale(cv, self.screen.get_size(), self.screen)
        pygame.display.flip()
        self.flip_ms = (now() - t0) * 1000.0                      # vertical sync wait: not the game's cost

    def intro_surf(self):
        if not hasattr(self, "_intro_surf"):
            self._intro_surf = pygame.Surface((C.RENDER_W, C.RENDER_H)).convert()
        return self._intro_surf

    def _debug_info(self):
        now_t = now()
        threads = {}
        for n, tt in self.state.threads.items():
            threads[n] = "alive %4.0f ms ago" % ((now_t - tt) * 1000)
        threads["camera"] = "%.0f fps" % self.camera.fps if self.camera.is_alive() else "stopped"
        packets = ["rover  tx %d rx %d    tower tx %d rx %d    hud rx %d" % (
            self.links["robot"].tx, self.links["robot"].rx, self.links["tower"].tx, self.links["tower"].rx, self.links["hud"].rx),
            "input thread %.0f Hz   hub rx %d   errors %d" % (self.input.rate, self.hub.rx_count, self.input.errors)]
        rb = self.links["robot"].best()
        if rb and rb.rtt_ms is not None:
            packets.append("rover rtt %.1f ms   loss %.1f %%" % (rb.rtt_ms, rb.loss() * 100))
        return {"fps": self.fps, "ms": self.frame_ms, "worst": self.worst_ms, "postfx": self.postfx.level,
                "quality": self.perf.label(), "threads": threads, "packets": packets}

    def frame(self, dt=None):
        """One iteration. Returns False when the app wants to quit."""
        t0 = now()
        dt = min(0.05, dt if dt is not None else self.clock.get_time() / 1000.0 or 1 / 60)
        self.t += dt
        try:
            self.pump_events()
            self.update(dt)
            self.draw()
            self.errors.clear()
        except SystemExit:
            return False
        except Exception as e:
            self.log("frame error: %s" % traceback.format_exc())
            self.errors.append(now())
            if len(self.errors) > 30:
                print("The game keeps failing: %r. See %s" % (e, self.log_path))
                return False
        ms = (now() - t0) * 1000.0
        self.frame_ms = 0.9 * self.frame_ms + 0.1 * ms
        self.worst_ms = max(self.worst_ms * 0.995, ms)
        self.perf.note(ms - self.flip_ms, dt)                     # the governor watches CPU time, not the vblank wait
        self._fps_n += 1
        if now() - self._fps_t >= 1.0:
            self.fps, self._fps_n, self._fps_t = self._fps_n / (now() - self._fps_t), 0, now()
        return True

    def run(self):
        if self.args.sim_all or self.args.sim_robot:
            pass
        try:
            while True:
                self.clock.tick(C.FPS_CAP)
                if not self.frame():
                    break
        finally:
            self.shutdown()

    def shutdown(self):
        self.log("shutting down")
        try:
            self.state.test_cmd = (0, 0)
            self.state.drive_enabled = False
            time.sleep(0.06)
            self.links["robot"].send("D,0,0,0")
            self.links["robot"].send("X")
            self.links["tower"].idle()
        except Exception:
            pass
        self.stop_flag.set()
        self.input.stop()
        self.camera.stop()
        self.hub.close()
        self.scanner.close()
        for s in self.sims:
            s.stop()
        pygame.quit()


def collections_deque():
    import collections
    return collections.deque(maxlen=60)


class _NullScreen:
    def update(self, app, dt):
        pass


class _SilentMixer:
    muted = False

    def play(self, *a, **k):
        pass

    def update(self, *a, **k):
        pass

    def hush(self):
        pass

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted
