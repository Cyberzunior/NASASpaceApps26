// T-Minus_6 rover, firmware v2. Arduino UNO Q, microcontroller (STM32) side. 3.3 V pins. 2WD.
//
// Two TT gear motors (one left, one right, plus a caster or skid), one DRV8833 board per motor, channel 1 of each board.
// Per motor: PWM on IN1 for forward, PWM on IN2 for reverse, both low = coast. EEP / SLP of both boards goes to 3V3.
// Motor supply: 9 V pack on VM of both boards. The laptop scales every command to MAX_PWM (config.py, 170) before sending.
// Camera pan: 28BYJ-48 on a ULN2003 (AccelStepper, never blocks) turns the C920. C,angle sets the target, +-90 degrees.
//
// Talks to the Linux side through the Arduino Bridge: linux_bridge/robot_bridge.py calls "line" with one protocol line and
// this sketch answers with Bridge.notify("mcu_line", line). Protocol: laptop/devio/protocol.py.
//   in : D,left,right,ap   C,angle   X (game-over latch)   R (release)        out: B,L / B,R (bumpers)
//
// UNTESTED on hardware. Check before the demo:
//  * D5, D6, D9, D10 give PWM. Third-party pinouts list PWM on D3 D5 D6 D9 D10 D11; forum posts report that calling pinMode() on a
//    PWM pin can stop analogWrite() on the UNO Q core, and that enabling PWM on one pin can disable other GPIO. So this sketch
//    never calls pinMode() on the four motor pins. If a wheel does not turn, or the stepper on D8 / D7 / D12 misbehaves once PWM is on,
//    move the motor inputs to other PWM pins and update docs/pin_map.md.
//  * Bridge.provide_safe / notify behave as in the current Arduino docs.
#include <Arduino_RouterBridge.h>
#include <AccelStepper.h>
#define FW_VERSION 2

// ---- pins (do not change without updating docs/pin_map.md)
const int L_IN1 = 5, L_IN2 = 6, R_IN1 = 9, R_IN2 = 10;      // DRV8833 channel 1 of the left and right board
const int BUMP_L = A2, BUMP_R = A3, LED = 13;               // A0 and A1 are free
const unsigned long CMD_TIMEOUT = 300;     // ms without D: stop (stopAll)
const unsigned long LINK_LOST = 2000;      // ms without any D: park the camera, blink the LED slowly
const float PAN_LIMIT = 90.0;              // degrees each side: the USB cable must not wind up

AccelStepper pan(AccelStepper::HALF4WIRE, 4, 8, 7, 12);     // ULN2003 IN1..IN4 on D4 D7 D8 D12, order IN1 IN3 IN2 IN4
const float STEPS_PER_DEG = 4096.0 / 360.0;

int cmdL = 0, cmdR = 0;
bool ap = false, latched = false, linkLost = false;
unsigned long tCmd = 0, tBumpL = 0, tBumpR = 0;

// ---- lines from Linux (set variables only; loop() acts on them)
volatile bool pendingD = false, pendingC = false, pendingX = false, pendingR = false;
volatile int newL = 0, newR = 0, newAp = 0, newPan = 0;

void onLine(String s) {                    // runs between two passes of loop() (provide_safe)
  if (s.startsWith("D,")) {
    int a = s.indexOf(',', 2), b = s.indexOf(',', a + 1);
    if (a > 0 && b > 0) { newL = s.substring(2, a).toInt(); newR = s.substring(a + 1, b).toInt(); newAp = s.substring(b + 1).toInt(); pendingD = true; }
  } else if (s.startsWith("C,")) { newPan = s.substring(2).toInt(); pendingC = true; }
  else if (s == "X") pendingX = true;
  else if (s == "R") pendingR = true;
}
void send(const String& s) { Bridge.notify("mcu_line", s); }

// ---- motors: v from -255 to 255
void drive(int in1, int in2, int v) {
  v = constrain(v, -255, 255);
  if (v >= 0) { analogWrite(in1, v);  analogWrite(in2, 0); }
  else        { analogWrite(in1, 0);  analogWrite(in2, -v); }
}
void stopAll() {                           // coast
  analogWrite(L_IN1, 0); analogWrite(L_IN2, 0);
  analogWrite(R_IN1, 0); analogWrite(R_IN2, 0);
}

void setup() {
  stopAll();                               // no pinMode() on the PWM pins: analogWrite() sets them up
  pinMode(BUMP_L, INPUT_PULLUP); pinMode(BUMP_R, INPUT_PULLUP); pinMode(LED, OUTPUT);
  pan.setMaxSpeed(700); pan.setAcceleration(1500);
  pan.setCurrentPosition(0);               // the camera faces straight ahead at power-up: that is zero
  Bridge.begin();
  Bridge.provide_safe("line", onLine);
  tCmd = millis();
}

void loop() {
  unsigned long now = millis();
  if (pendingD) { pendingD = false; if (!latched) { cmdL = newL; cmdR = newR; ap = newAp; } tCmd = now; }
  if (pendingC) { pendingC = false; pan.moveTo((long)(constrain((float)newPan, -PAN_LIMIT, PAN_LIMIT) * STEPS_PER_DEG)); }
  if (pendingX) { pendingX = false; latched = true; cmdL = cmdR = 0; stopAll(); }
  if (pendingR) { pendingR = false; latched = false; cmdL = cmdR = 0; }

  if (now - tCmd > CMD_TIMEOUT) cmdL = cmdR = 0;                   // laptop or Wi-Fi gone: stop within 300 ms
  linkLost = (now - tCmd > LINK_LOST);
  if (linkLost) pan.moveTo(0);                                     // park the camera so the cable cannot wind up
  if (latched || (cmdL == 0 && cmdR == 0)) stopAll();              // game over and every stop go through stopAll()
  else { drive(L_IN1, L_IN2, cmdL); drive(R_IN1, R_IN2, cmdR); }
  pan.run();                                                       // never waits for the stepper

  if (digitalRead(BUMP_L) == LOW && now - tBumpL > 200) { tBumpL = now; send("B,L"); }
  if (digitalRead(BUMP_R) == LOW && now - tBumpR > 200) { tBumpR = now; send("B,R"); }
  // status LED: steady = auto-pilot on, fast blink = game over, slow blink = link lost
  if (latched)       digitalWrite(LED, (now / 100) % 2);
  else if (linkLost) digitalWrite(LED, (now / 500) % 2);
  else               digitalWrite(LED, ap);
}
