"""Pair the gamepad (Xbox wireless controller: hold the pair button until the light blinks fast), run this, press every
button and move every stick. It shows which layout the game will use.   python tools/gamepad_test.py
Standard layout (the Xbox pad and most others): nothing to configure. Raw layout (a pad SDL does not know): copy the axis and
button numbers it prints into AXIS_* and BTN_* in config.py or config.local.json."""
import os
import sys

os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import config as C  # noqa: E402
from devio import pad as padmod  # noqa: E402


def main():
    pygame.init()
    padmod.init()
    pygame.display.set_mode((420, 80))
    pygame.display.set_caption("gamepad test (close this window to stop)")
    if pygame.joystick.get_count() == 0:
        print("No gamepad found. Pair it in the Bluetooth settings first, or plug it in.")
        return 1
    pad = padmod.open_pad(0)
    print("Gamepad: %s | %d axes, %d buttons | layout: %s" % (pad.get_name(), pad.get_numaxes(), pad.get_numbuttons(),
          "standard SDL (nothing to configure)" if pad.standard else "RAW (SDL does not know this pad: set AXIS_* and BTN_* below)"))
    print("Drive: axis %d turn, axis %d speed | pan: axis %d | triggers: axis %d brake, axis %d boost" %
          (pad.turn_axis, pad.speed_axis, pad.pan_axis, pad.brake_axis, pad.boost_axis))
    print("Buttons: A/confirm=%d B/camera=%d Y/autopilot=%d RB/test-shot=%d Back=%d Start=%d actions=%s" %
          (C.BTN_CONFIRM, C.BTN_CAMERA, C.BTN_AUTOPILOT, C.BTN_FIRE, C.BTN_BACK, C.BTN_RESTART, C.BTN_ACTIONS))
    last = {}
    clock = pygame.time.Clock()
    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return 0
            b = padmod.button_number(pad, e)
            if b:
                print("button %s %s" % (b[0], b[1]))
        for i in range(pad.get_numaxes()):                              # print an axis only when it moved a lot
            v = round(pad.get_axis(i), 2)
            if abs(v - last.get(i, 0.0)) > 0.25:
                print("axis %d = %+.2f" % (i, v))
                last[i] = v
        clock.tick(60)


if __name__ == "__main__":
    sys.exit(main())
