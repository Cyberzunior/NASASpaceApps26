"""Soak test: run the headless game with software devices for a while and report memory and thread growth.
    python tools/soak.py [seconds]"""
import os
import sys
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    import pygame
    pygame.init()
    from app import App, Args
    app = App(Args(sim=True, no_audio=True, seed=1), headless=True)
    app.boot_all()
    app.menu_choice("PLAY")
    app.game.skip_intro()
    n0, t0, frames = threading.active_count(), time.time(), 0
    while time.time() - t0 < secs:
        app.state.keys = (1.0, 0.4 if int(time.time()) % 4 < 2 else -0.4)
        app.frame(1 / 60)
        frames += 1
        if app.game.over and app.sm.state.name if False else app.sm.state == "RESULTS":
            app.results.handle(app, "confirm")
    print("frames %d, threads %d -> %d, samples %d" % (frames, n0, threading.active_count(), sum(app.game.samples.values())))
    app.shutdown()


if __name__ == "__main__":
    main()
