// T-Minus_6 asteroid tower, firmware v2. Arduino UNO R3 (5 V logic). USB serial, 115200 baud, wired to the laptop.
// A tilt stepper aims an always-on green laser. A fixed, level HC-SR04 finds the rover. A push servo jiggles on a hit.
// Protocol: laptop/devio/protocol.py (newline-framed lines, the same scheme the triage suite uses).
//   in : I?   P,seq,us (ping -> Q,seq,us)   F (run one asteroid sequence)   J (jiggle the servo once)
//        Z (swing the beam back up)   R (send one distance reading)
//   out: I,tower,2   Q,seq,us   W,3 (beam is down on the marked spot, impact in 3 s)
//        K,1 (impact, the rover was inside the marked spot: hit)   K,0 (the rover had left the spot, or none was found: miss)
//        R,cm (one distance reading; 999 = nothing there)
//
// One sequence: measure the rover, swing the beam down onto the floor just ahead of it, W,3, wait 3 s, measure again,
// K,1 or K,0, jiggle on a hit, swing back up. The test button on D2 runs the SAME sequence and sends the same lines.
// The tower does one thing at a time, so the sequence runs start to finish; every wait and every stepper move keeps
// answering pings (service()), so the laptop never shows the tower as lost. F / J / Z / R that arrive mid-sequence are dropped.
//
// Pins: D2 test button to GND (optional) | D4..D7 ULN2003 IN1..IN4 (28BYJ-48 tilt stepper) | D9 push servo
//       D11 HC-SR04 TRIG | D12 HC-SR04 ECHO | D13 green laser through a 2N2222, held HIGH | 5 V HC-SR04 VCC
// Power: servo, stepper and laser on a second MB102 at 5 V, its GND joined to the UNO GND. Nothing joins the two + rails.
// Power the tower up with the beam pointing STRAIGHT UP: the sketch counts steps from there. Opening the serial port
// resets an UNO R3, so connect the laptop while the beam is up (it always is when the sky is quiet).
// The laser never blinks. Never aim it at a face; keep the idle beam on an empty ceiling or open space.
// MEASURE LASER_H_CM and tune LEAD_CM and HIT_TOL_CM on the real track. Libraries: Servo, AccelStepper.
#include <Servo.h>
#include <AccelStepper.h>
#define FW_VERSION 2

const int BTN_PIN = 2, SERVO_PIN = 9, TRIG = 11, ECHO = 12, LASER = 13;
const int REST = 45, JIG = 20;                   // servo centre and jiggle size

// Tilt geometry. Step 0 = beam horizontal, positive = up. 28BYJ-48 half-step = 4096 steps per turn.
const float STEPS_PER_DEG = 4096.0 / 360.0;
const long  UP_STEPS = (long)(90 * STEPS_PER_DEG);   // beam straight up: the idle position
const int   TILT_DIR = 1;                        // set to -1 if the beam swings the wrong way
const float LASER_H_CM = 20;                     // laser height above the floor: MEASURE THIS

const float MIN_CM = 10, MAX_CM = 150;           // track range the distance reading can be trusted in
const float LEAD_CM = 15;                        // how far ahead of the rover to mark
const int   AHEAD_DEFAULT = -1;                  // rover at rest: -1 = ahead is toward the tower, +1 = away
const float HIT_TOL_CM = 15;
const unsigned long COUNTDOWN_MS = 3000;

AccelStepper tilt(AccelStepper::HALF4WIRE, 4, 6, 5, 7);   // IN1, IN3, IN2, IN4
Servo push;
char rx[64];
byte rxLen = 0;
bool busy = false;                               // true while a sequence, a jiggle or a swing runs

void fireSequence();
void jiggleOnce();
void tiltTo(long steps);
float rangeCm();

void handleLine(char* s) {
  if (!strcmp(s, "I?")) Serial.println(F("I,tower,2"));
  else if (s[0] == 'P' && s[1] == ',') { Serial.print('Q'); Serial.println(s + 1); }     // P,seq,us -> Q,seq,us
  else if (busy) return;                                                                 // one thing at a time
  else if (!strcmp(s, "F")) fireSequence();
  else if (!strcmp(s, "J")) { busy = true; jiggleOnce(); busy = false; }
  else if (!strcmp(s, "Z")) { busy = true; tiltTo(UP_STEPS); busy = false; }
  else if (!strcmp(s, "R")) { Serial.print(F("R,")); Serial.println(rangeCm(), 0); }
}

void service() {                                 // read serial lines; called from every wait so pings are always answered
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { rx[rxLen] = 0; byte n = rxLen; rxLen = 0; if (n) handleLine(rx); }
    else if (c != '\r' && rxLen < sizeof(rx) - 1) rx[rxLen++] = c;
  }
}

void waitMs(unsigned long ms) {                  // a wait that keeps the link alive
  unsigned long t0 = millis();
  while (millis() - t0 < ms) service();
}

float pingCm() {
  digitalWrite(TRIG, LOW);  delayMicroseconds(2);
  digitalWrite(TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  long us = pulseIn(ECHO, HIGH, 25000);
  return us ? us / 58.0 : 999;
}

float rangeCm() {                                // median of 5 pings; 999 = nothing there
  float v[5];
  for (int i = 0; i < 5; i++) { v[i] = pingCm(); waitMs(30); }
  for (int i = 0; i < 4; i++)
    for (int j = i + 1; j < 5; j++)
      if (v[j] < v[i]) { float t = v[i]; v[i] = v[j]; v[j] = t; }
  return v[2];
}

void tiltTo(long steps) {
  tilt.moveTo(TILT_DIR * steps);
  unsigned long n = 0;
  while (tilt.distanceToGo() != 0) { tilt.run(); if ((++n & 63) == 0) service(); }
}

long stepsForTarget(float cm) {                  // beam angle below horizontal that lands cm out
  float deg = atan2(LASER_H_CM, cm) * 180.0 / PI;
  return (long)(-deg * STEPS_PER_DEG);
}

void jiggleOnce() {
  for (int i = 0; i < 4; i++) {
    push.write(REST + JIG); waitMs(80);
    push.write(REST - JIG); waitMs(80);
  }
  push.write(REST);
}

void fireSequence() {
  busy = true;
  float d1 = rangeCm();
  if (d1 < MIN_CM || d1 > MAX_CM) {              // no rover on the track: beam stays up
    Serial.println(F("W,3"));
    waitMs(COUNTDOWN_MS);
    Serial.println(F("K,0"));
    busy = false;
    return;
  }
  waitMs(250);
  float d2 = rangeCm();
  float dv = d2 - d1;                            // movement over about 0.25 s
  int dir = (fabs(dv) < 2) ? AHEAD_DEFAULT : (dv > 0 ? 1 : -1);
  float target = constrain(d2 + dir * LEAD_CM, MIN_CM, MAX_CM);

  tiltTo(stepsForTarget(target));                // beam swings down onto the floor ahead of the rover
  Serial.println(F("W,3"));                      // the countdown starts after the swing
  waitMs(COUNTDOWN_MS);

  float d = rangeCm();                           // is the rover in the marked spot?
  bool hit = (d < MAX_CM) && fabs(d - target) <= HIT_TOL_CM;
  Serial.println(hit ? F("K,1") : F("K,0"));
  if (hit) jiggleOnce();
  tiltTo(UP_STEPS);                              // back to idle
  busy = false;
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG, OUTPUT); pinMode(ECHO, INPUT);
  pinMode(LASER, OUTPUT); digitalWrite(LASER, HIGH);   // laser always on
  pinMode(BTN_PIN, INPUT_PULLUP);
  push.attach(SERVO_PIN); push.write(REST);
  tilt.setMaxSpeed(800); tilt.setAcceleration(400);
  tilt.setCurrentPosition(TILT_DIR * UP_STEPS);  // power up with the beam straight up
}

void loop() {
  static unsigned long tBtn = 0;
  service();
  if (digitalRead(BTN_PIN) == LOW && millis() - tBtn > 300) { fireSequence(); tBtn = millis(); }   // test button: the same sequence
}
