// T-Minus_6 rover, firmware v3: a general serial-driven two-wheel base with a camera pan. Arduino UNO Q, STM32 (microcontroller) side ONLY:
// no Linux program, no Arduino Bridge. FLASH IT ONCE. It knows nothing about the game: the laptop (the game, tests/triage_gui.py, or a
// terminal) decides everything and sends it as lines over USB serial, 115200 baud, newline-framed ASCII (laptop/devio/protocol.py).
//
//   in : I?                         who are you                         -> I,robot,2
//        P,seq,us                   ping                                -> Q,seq,us
//        D,left,right,ap            wheel values, +-MAX_CMD (the laptop's MAX_PWM); ap is carried for the laptop and ignored here
//        C,deg                      camera pan target, +-PAN_LIMIT degrees, 0 = power-up heading
//        X / R                      stop latch (wheels held at 0 until R) / release
//        LED,mode                   status LED: 0 off, 1 on, 2 fast blink, 3 slow blink (the laptop decides what it means)
//        G,maxCmd,minPwm,slew,timeoutMs,panLimit,panSps,panAcc    settings; 0 keeps the present value; the laptop sends them on connect
//        ?                          state                               -> S,left,right,pan,latched
//        utest                      bench test: wheels forward 2 s, back 2 s, camera swings, then stops (X aborts)
//   out: B,L / B,R (bumpers)   I,robot,2   Q,seq,us   S,...   UTEST,start / UTEST,done
//
// Hardware (3.3 V logic): ONE dual DRV8833 board, 2WD. Channel 1 (IN1 D5, IN2 D6) = left motor, channel 2 (IN3 D9, IN4 D10) = right.
// Per motor: PWM on the first input = forward, PWM on the second = reverse, both low = coast. EEP / SLP is left floating (the
// board's own pull-up keeps it awake; if the motors stay dead, wire EEP to 3V3). An MB102 module at 5 V feeds the DRV8833 VCC and the
// ULN2003 +, about 700 mA, so every command is limited to MAX_CMD and changes by at most SLEW counts per SLEW_MS.
// Camera pan: 28BYJ-48 on a ULN2003 (D4 D7 D8 D12), AccelStepper, never blocks.
//
// Safety that stays in the firmware because the laptop cannot do it: the wheels stop CMD_TIMEOUT ms after the last D, and the camera parks
// at 0 and the LED blinks slowly when nothing has arrived for LINK_LOST ms. Everything else (mixing, scaling, inversion, LED meaning,
// when to latch) is the laptop's job: laptop/core/model.py mixes the stick, laptop/config.py holds every number.
//
// UNTESTED on hardware. The motor pins never get pinMode(): analogWrite() sets a PWM pin up itself, and the UNO Q core applies the
// pin mux per pin, so PWM on D5 / D6 does not take D12 / D8 (stepper) away. If a wheel runs backwards, flip INVERT_LEFT / INVERT_RIGHT
// in laptop/config.py (not here).
#include <AccelStepper.h>
#define FW_VERSION 2

// ---- pins (do not change without updating docs/pin_map.md)
const int L_IN1 = 5, L_IN2 = 6, R_IN1 = 9, R_IN2 = 10;      // DRV8833 IN1 IN2 (left motor), IN3 IN4 (right motor)
const int BUMP_L = A2, BUMP_R = A3, LED = 13;               // A0 and A1 are free
const unsigned long LINK_LOST = 2000;      // ms without any line: park the camera, blink the LED slowly
const unsigned long SLEW_MS = 20;

// ---- settings the laptop can change with G (these are the power-up defaults)
unsigned long CMD_TIMEOUT = 300;           // ms without D: stop (stopAll)
float PAN_LIMIT = 90.0;                    // degrees each side: the USB cable must not wind up
int MAX_CMD = 200;                         // the laptop's MAX_PWM: the largest |value| a D line carries (and the most we ever output)
int MIN_PWM = 60;                          // TT motors do not turn below this duty: any non-zero command is lifted to it (0 = off). Tune on the floor
int SLEW = 40;                             // PWM counts a motor command may change per SLEW_MS (MB102 current limit)

AccelStepper pan(AccelStepper::HALF4WIRE, 4, 8, 7, 12);     // ULN2003 IN1..IN4 on D4 D7 D8 D12, order IN1 IN3 IN2 IN4
const float STEPS_PER_DEG = 4096.0 / 360.0;

int cmdL = 0, cmdR = 0;                    // what the laptop asked for
int outL = 0, outR = 0;                    // what the motors get: cmd, rate limited
int ledMode = 0;                           // 0 off, 1 on, 2 fast blink, 3 slow blink
bool latched = false, linkLost = false;
unsigned long tCmd = 0, tLine = 0, tBumpL = 0, tBumpR = 0, tSlew = 0;

// ---- bench test: type "utest" in a serial monitor (newline ending). Both wheels forward 2 s, stop, both back 2 s, stop; the camera
// stepper swings to +60 during the forward half and -60 during the reverse half, then returns to 0. D lines are ignored meanwhile; X aborts.
const unsigned long UT_RUN = 2000, UT_PAUSE = 700;
const int UT_PAN = 60;
int utStep = 0;                            // 0 = off, 1 forward, 2 pause, 3 reverse, 4 pause
unsigned long tUt = 0;
void utStart(unsigned long now) { utStep = 1; tUt = now; Serial.println("UTEST,start"); }
void utStop() { utStep = 0; cmdL = cmdR = 0; pan.moveTo(0); Serial.println("UTEST,done"); }
void utUpdate(unsigned long now) {         // sets the wheel and pan targets; the normal ramp below drives them
  if (!utStep) return;
  tCmd = now;                              // keeps CMD_TIMEOUT / LINK_LOST quiet while the test runs
  tLine = now;
  unsigned long t = now - tUt;
  if (utStep == 1 || utStep == 3) {
    int v = utStep == 1 ? MAX_CMD : -MAX_CMD;
    cmdL = cmdR = v;
    pan.moveTo((long)((utStep == 1 ? UT_PAN : -UT_PAN) * STEPS_PER_DEG));
    if (t >= UT_RUN) { cmdL = cmdR = 0; utStep++; tUt = now; }
  } else {
    cmdL = cmdR = 0;
    if (t >= UT_PAUSE) { if (utStep == 4) utStop(); else { utStep = 3; tUt = now; } }
  }
}

// ---- motors: v from -MAX_CMD to MAX_CMD
void drive(int in1, int in2, int v) {
  v = constrain(v, -MAX_CMD, MAX_CMD);
  if (v != 0 && MIN_PWM > 0 && MAX_CMD > 1) {   // 1..MAX_CMD -> MIN_PWM..MAX_CMD, so a gentle stick still moves the wheels
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
void applySettings(const String &s) {     // G,maxCmd,minPwm,slew,timeoutMs,panLimit,panSps,panAcc : 0 or a missing value keeps the present one
  long v[7] = {0, 0, 0, 0, 0, 0, 0};
  int n = 0, from = 2;
  while (n < 7 && from <= (int)s.length()) {
    int c = s.indexOf(',', from);
    if (c < 0) c = s.length();
    v[n++] = s.substring(from, c).toInt();
    from = c + 1;
  }
  if (v[0] > 1) MAX_CMD = constrain((int)v[0], 2, 255);
  if (v[1] > 0) MIN_PWM = constrain((int)v[1], 0, MAX_CMD);
  if (v[2] > 0) SLEW = (int)v[2];
  if (v[3] > 0) CMD_TIMEOUT = (unsigned long)v[3];
  if (v[4] > 0) PAN_LIMIT = constrain((float)v[4], 5.0, 180.0);
  if (v[5] > 0) pan.setMaxSpeed(constrain((float)v[5], 50.0, 1000.0));
  if (v[6] > 0) pan.setAcceleration(constrain((float)v[6], 50.0, 4000.0));
}

void onLine(String s) {
  unsigned long now = millis();
  tLine = now;
  if (s == "I?") { Serial.println("I,robot,2"); return; }
  if (s == "utest" || s == "UTEST") { if (!latched && !utStep) utStart(now); return; }
  if (s.startsWith("P,")) { Serial.print("Q"); Serial.println(s.substring(1)); return; }      // P,seq,us -> Q,seq,us
  if (s.startsWith("D,")) {
    int a = s.indexOf(',', 2), b = s.indexOf(',', a + 1);
    if (a > 0 && b > 0) {
      tCmd = now;
      if (!latched && !utStep) { cmdL = s.substring(2, a).toInt(); cmdR = s.substring(a + 1, b).toInt(); }
    }
  } else if (s.startsWith("C,")) {
    if (!utStep) pan.moveTo((long)(constrain(s.substring(2).toFloat(), -PAN_LIMIT, PAN_LIMIT) * STEPS_PER_DEG));
  } else if (s == "X") { latched = true; utStep = 0; cmdL = cmdR = 0; stopAll(); }
  else if (s == "R") { latched = false; cmdL = cmdR = 0; }
  else if (s.startsWith("LED,")) ledMode = constrain((int)s.substring(4).toInt(), 0, 3);
  else if (s.startsWith("G,")) applySettings(s);
  else if (s == "?") {
    Serial.print("S,"); Serial.print(outL); Serial.print(','); Serial.print(outR);
    Serial.print(','); Serial.print((int)(pan.currentPosition() / STEPS_PER_DEG));
    Serial.print(','); Serial.println(latched ? 1 : 0);
  }
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
  tCmd = tLine = millis();
}

void loop() {
  unsigned long now = millis();
  serialService();
  utUpdate(now);

  if (now - tCmd > CMD_TIMEOUT) cmdL = cmdR = 0;                   // laptop gone: stop within CMD_TIMEOUT
  linkLost = (now - tLine > LINK_LOST);
  if (linkLost) pan.moveTo(0);                                     // park the camera so the cable cannot wind up
  if (latched || (cmdL == 0 && cmdR == 0)) stopAll();              // every stop goes through stopAll()
  else if (now - tSlew >= SLEW_MS) {                               // at most SLEW counts per SLEW_MS, so a stall cannot brown out the MB102
    tSlew = now;
    outL = ramp(outL, cmdL); outR = ramp(outR, cmdR);
    drive(L_IN1, L_IN2, outL); drive(R_IN1, R_IN2, outR);
  }
  pan.run();                                                       // never waits for the stepper

  if (digitalRead(BUMP_L) == LOW && now - tBumpL > 200) { tBumpL = now; Serial.println("B,L"); }
  if (digitalRead(BUMP_R) == LOW && now - tBumpR > 200) { tBumpR = now; Serial.println("B,R"); }
  int mode = linkLost ? 3 : ledMode;                               // link lost: slow blink whatever the laptop last said
  if (mode == 0)      digitalWrite(LED, LOW);
  else if (mode == 1) digitalWrite(LED, HIGH);
  else                digitalWrite(LED, (now / (mode == 2 ? 100 : 500)) % 2);
}
