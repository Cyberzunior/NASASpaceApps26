// T-Minus_6 rover, firmware v2. Arduino UNO Q, STM32 (microcontroller) side ONLY: no Linux program, no Arduino Bridge.
// The game runs on the laptop and talks to this sketch over the USB serial port, 115200 baud, newline-framed ASCII lines
// (laptop/devio/protocol.py). The laptop finds the board by asking I? and getting I,robot,2.
//
//   in : I?   P,seq,us   D,left,right,ap   C,angle   X (game-over latch)   R (release)
//   out: HELLO,robot,2 (boot)   I,robot,2   Q,seq,us   B,L / B,R (bumpers)
//
// Hardware (3.3 V logic): ONE dual DRV8833 board, 2WD. Channel 1 (IN1 D5, IN2 D6) = left motor, channel 2 (IN3 D9, IN4 D10) = right.
// Per motor: PWM on the first input = forward, PWM on the second = reverse, both low = coast. EEP / SLP is left floating (the
// board's own pull-up keeps it awake; if the motors stay dead, wire EEP to 3V3). An MB102 module at 5 V feeds the DRV8833 VCC and the
// ULN2003 +, about 700 mA, so every command is limited to MAX_CMD (the laptop's MAX_PWM) and changes by at most SLEW counts per 20 ms.
// Camera pan: 28BYJ-48 on a ULN2003 (D4 D7 D8 D12), AccelStepper, never blocks. C,angle sets the target, +-90 degrees, 0 = power-up.
//
// How the rover mimics the game: the laptop mixes the stick into left / right wheel values (core/model.py, the same numbers that
// move the craft on screen), scales them to +-MAX_PWM and sends D,left,right,ap every 20 ms. This sketch only has to drive the wheels
// with those numbers and stop when they stop coming.
//
// UNTESTED on hardware. The motor pins never get pinMode(): analogWrite() sets a PWM pin up itself, and the UNO Q core applies the
// pin mux per pin, so PWM on D5 / D6 does not take D12 / D8 (stepper) away. If a wheel runs backwards, flip INVERT_LEFT / INVERT_RIGHT
// in laptop/config.py (not here).
#include <AccelStepper.h>
#define FW_VERSION 2

// ---- pins (do not change without updating docs/pin_map.md)
const int L_IN1 = 5, L_IN2 = 6, R_IN1 = 9, R_IN2 = 10;      // DRV8833 IN1 IN2 (left motor), IN3 IN4 (right motor)
const int BUMP_L = A2, BUMP_R = A3, LED = 13;               // A0 and A1 are free
const unsigned long CMD_TIMEOUT = 300;     // ms without D: stop (stopAll)
const unsigned long LINK_LOST = 2000;      // ms without any D: park the camera, blink the LED slowly
const float PAN_LIMIT = 90.0;              // degrees each side: the USB cable must not wind up
const int MAX_CMD = 200;                   // the laptop's MAX_PWM: the largest |value| a D line carries (and the most we ever output)
const int MIN_PWM = 60;                    // TT motors do not turn below this duty: any non-zero command is lifted to it (0 = off). Tune on the floor
const int SLEW = 40;                       // PWM counts a motor command may change per SLEW_MS (MB102 current limit)
const unsigned long SLEW_MS = 20;

AccelStepper pan(AccelStepper::HALF4WIRE, 4, 8, 7, 12);     // ULN2003 IN1..IN4 on D4 D7 D8 D12, order IN1 IN3 IN2 IN4
const float STEPS_PER_DEG = 4096.0 / 360.0;

int cmdL = 0, cmdR = 0;                    // what the laptop asked for
int outL = 0, outR = 0;                    // what the motors get: cmd, rate limited
bool ap = false, latched = false, linkLost = false;
unsigned long tCmd = 0, tBumpL = 0, tBumpR = 0, tSlew = 0;

// ---- motors: v from -MAX_CMD to MAX_CMD
void drive(int in1, int in2, int v) {
  v = constrain(v, -MAX_CMD, MAX_CMD);
  if (v != 0 && MIN_PWM > 0) {             // 1..MAX_CMD -> MIN_PWM..MAX_CMD, so a gentle stick still moves the wheels
    int m = MIN_PWM + (int)((long)(abs(v) - 1) * (MAX_CMD - MIN_PWM) / (MAX_CMD - 1));
    v = v > 0 ? m : -m;
  }
  if (v >= 0) { analogWrite(in1, v);  analogWrite(in2, 0); }
  else        { analogWrite(in1, 0);  analogWrite(in2, -v); }
}
void stopAll() {                           // coast
  analogWrite(L_IN1, 0); analogWrite(L_IN2, 0);
  analogWrite(R_IN1, 0); analogWrite(R_IN2, 0);
  outL = outR = 0;
}
int ramp(int out, int want) {              // move out toward want by at most SLEW
  if (want > out + SLEW) return out + SLEW;
  if (want < out - SLEW) return out - SLEW;
  return want;
}

// ---- one protocol line from the laptop (never blocks)
void onLine(String s) {
  unsigned long now = millis();
  if (s == "I?") { Serial.println("I,robot,2"); return; }
  if (s.startsWith("P,")) { Serial.print("Q"); Serial.println(s.substring(1)); return; }      // P,seq,us -> Q,seq,us
  if (s.startsWith("D,")) {
    int a = s.indexOf(',', 2), b = s.indexOf(',', a + 1);
    if (a > 0 && b > 0) {
      tCmd = now;
      if (!latched) { cmdL = s.substring(2, a).toInt(); cmdR = s.substring(a + 1, b).toInt(); ap = s.substring(b + 1).toInt() != 0; }
    }
  } else if (s.startsWith("C,")) {
    pan.moveTo((long)(constrain((float)s.substring(2).toInt(), -PAN_LIMIT, PAN_LIMIT) * STEPS_PER_DEG));
  } else if (s == "X") { latched = true; cmdL = cmdR = 0; stopAll(); }
  else if (s == "R") { latched = false; cmdL = cmdR = 0; }
}

String rx;                                 // line being assembled
void serialService() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { rx.trim(); if (rx.length()) onLine(rx); rx = ""; }
    else if (rx.length() < 64) rx += c;
    else rx = "";                          // longer than any valid line: drop it
  }
}

void setup() {
  stopAll();                               // no pinMode() on the PWM pins: analogWrite() sets them up
  pinMode(BUMP_L, INPUT_PULLUP); pinMode(BUMP_R, INPUT_PULLUP); pinMode(LED, OUTPUT);
  pan.setMaxSpeed(700); pan.setAcceleration(1500);
  pan.setCurrentPosition(0);               // the camera faces straight ahead at power-up: that is zero
  Serial.begin(115200);
  Serial.println("HELLO,robot,2");
  tCmd = millis();
}

void loop() {
  unsigned long now = millis();
  serialService();

  if (now - tCmd > CMD_TIMEOUT) cmdL = cmdR = 0;                   // laptop gone: stop within 300 ms
  linkLost = (now - tCmd > LINK_LOST);
  if (linkLost) pan.moveTo(0);                                     // park the camera so the cable cannot wind up
  if (latched || (cmdL == 0 && cmdR == 0)) stopAll();              // game over and every stop go through stopAll()
  else if (now - tSlew >= SLEW_MS) {                               // at most SLEW counts per 20 ms, so a stall cannot brown out the MB102
    tSlew = now;
    outL = ramp(outL, cmdL); outR = ramp(outR, cmdR);
    drive(L_IN1, L_IN2, outL); drive(R_IN1, R_IN2, outR);
  }
  pan.run();                                                       // never waits for the stepper

  if (digitalRead(BUMP_L) == LOW && now - tBumpL > 200) { tBumpL = now; Serial.println("B,L"); }
  if (digitalRead(BUMP_R) == LOW && now - tBumpR > 200) { tBumpR = now; Serial.println("B,R"); }
  // status LED: steady = auto-pilot on, fast blink = game over, slow blink = link lost
  if (latched)       digitalWrite(LED, (now / 100) % 2);
  else if (linkLost) digitalWrite(LED, (now / 500) % 2);
  else               digitalWrite(LED, ap);
}
