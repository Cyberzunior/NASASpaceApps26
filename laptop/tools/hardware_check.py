"""Command-line hardware check without the game window:  python tools/hardware_check.py [--sim]
Connects the rover (UDP), tower and HUD panel (serial, found by the I? handshake) and runs quick checks."""
import sys
import time

import _net
import config as C
from devio import protocol as P


def check(name, ok, note=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  (%s)" % note) if note else ""))
    return ok


def main():
    sim = "--sim" in sys.argv
    net = _net.Net(sim=sim)
    if not sim:
        net.scanner.enabled = True
    ok = True
    try:
        net.wait_for(["robot", "tower", "hud"], 12.0)
        time.sleep(2.5)
        L, st = net.links, net.state
        evs = net.drain()
        for role in ("robot", "tower", "hud"):
            d = st.devices[role]
            ok &= check("%s connected" % role, d.connected, "%s rtt %s ms" % (d.where, "-" if d.rtt_ms is None else "%.0f" % d.rtt_ms))
        if L["robot"].connected:
            print("\nRover (wheels off the table)")
            L["robot"].send_drive(C.MAX_PWM // 2, C.MAX_PWM // 2, 0)
            time.sleep(0.5)
            L["robot"].send_drive(0, 0, 0)
            ok &= check("wheel command sent", L["robot"].tx > 0)
            for a in (-60, 60, 0):
                L["robot"].pan(a)
                time.sleep(0.8)
            print("   camera pan sent -60, 60, 0: look at the camera")
        if L["tower"].connected:
            print("\nTower (nobody in front of it)")
            L["tower"].allow(True)
            L["tower"].fire(test=True)
            time.sleep(7.0)                          # ranging, the swing down, the 3 s countdown
            evs = net.drain()
            kinds = [e.kind for e in evs if e.kind in ("tower_warn", "tower_k")]
            ok &= check("warning first, then K", kinds == ["tower_warn", "tower_k"], str(kinds))
        if L["hud"].connected:
            print("\nHUD panel")
            check("joystick lines arriving (J,x,y,sw)", st.joy_t > 0, "stick %s" % (st.joy,))
            L["hud"].set_temp(118)
            L["hud"].set_meters(80, 65, 70, 40)
            L["hud"].set_lives(12)
            L["hud"].set_samples(3)
            L["hud"].pickup()
            time.sleep(1.5)
            for zone in (2, 1, 0):
                L["hud"].set_zone(zone)
                time.sleep(2.0)
            print("   look: LCD numbers, OLED hearts + samples, yellow blink, red/blue LEDs and buzzer")
    finally:
        net.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
