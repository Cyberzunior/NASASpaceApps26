// T-Minus_6 asteroid tower, firmware v2. Arduino UNO R3 (5 V logic). USB serial, 115200 baud, wired to the laptop.
// A 28BYJ-48 stepper YAWS an always-on green laser (0 = straight ahead), a servo PITCHES it (straight up when idle).
// A fixed, level HC-SR04 reads the distance of the nearest target straight ahead. No ball, no launcher.
// Protocol: laptop/devio/protocol.py (newline-framed lines, the same scheme the triage suite uses).
//   in : I?   P,seq,us (ping -> Q,seq,us)   F,bearing (run one asteroid sequence; bare F = 0; clamped to -40..40, negative left)
//        Z (pitch up and yaw to 0: idle)   R (send one distance reading)
//   out: I,tower,2   Q,seq,us   W,3 (the beam is on the marked spot, impact in 3 s)
//        K,1 (impact, something was inside the marked spot: hit)   K,0 (nothing there, or the bearing is too far sideways to check)
//        R,cm (one distance reading; 999 = nothing there)
//
// One sequence: measure the target, yaw to the bearing, pitch the beam down onto the floor at target + LEAD_CM (DEFAULT_CM if
// nothing is in range), W,3, wait 3 s, check the spot (only within HIT_BEARING_DEG of straight ahead), K, then pitch up and yaw
// back to 0, then rests COOLDOWN_MS (20 s) from the K: an F or button press in that time is ignored. The test button on D2 runs the same sequence at bearing 0. The tower does one thing at a time; every wait and move
// keeps answering pings (service()), so the laptop never shows the tower as lost. F / Z / R that arrive mid-sequence are dropped.
//
// Pins: D2 test button to GND (optional) | D4..D7 ULN2003 IN1..IN4 (28BYJ-48 yaw stepper) | D9 pitch servo
//       D11 HC-SR04 TRIG | D12 HC-SR04 ECHO | D13 green laser through a 2N2222, held HIGH | 5 V HC-SR04 VCC
// Power: servo, stepper and laser on a second MB102 at 5 V, its GND joined to the UNO GND. Nothing joins the two + rails.
// Power the tower up with the beam pointing STRAIGHT UP and the stepper facing straight ahead: the sketch counts from there.
// Opening the serial port resets an UNO R3, so connect the laptop while the beam is up (it always is when the sky is quiet).
// The laser never blinks. Never aim it at a face; keep the idle beam on an empty ceiling or open space.
// MEASURE LASER_H_CM; tune LEAD_CM and HIT_TOL_CM on the real track; set YAW_DIR / PITCH_DIR to -1 if a move goes the wrong way.
// Libraries: Servo, AccelStepper.
#include <Servo.h>
#include <AccelStepper.h>
#define FW_VERSION 2

const int BTN_PIN = 2, SERVO_PIN = 9, TRIG = 11, ECHO = 12, LASER = 13;

// Yaw: 28BYJ-48 half-step = 4096 steps per turn. 0 = straight ahead.
const float STEPS_PER_DEG = 4096.0 / 360.0;
const int   YAW_DIR = 1;                         // -1 if positive bearings swing the wrong way
const float CONE_DEG = 40;                       // bearing limit either side

// Pitch: servo angle PITCH_LEVEL = beam horizontal. Up = level + 90 * PITCH_DIR.
const int PITCH_LEVEL = 90;
const int PITCH_DIR = 1;                         // -1 if raising the angle lowers the beam
const int PITCH_UP = PITCH_LEVEL + 90 * PITCH_DIR;
const float LASER_H_CM = 20;                     // laser height above the floor: MEASURE THIS

const float MIN_CM = 10, MAX_CM = 150;           // range the sensor can trust
const float LEAD_CM = 15;                        // how far ahead of the target to mark
const float DEFAULT_CM = 60;                     // mark here when nothing is seen
const int   AHEAD_DEFAULT = -1;                  // target at rest: -1 = ahead is toward the tower, +1 = away
const float HIT_TOL_CM = 15;
const float HIT_BEARING_DEG = 8;                 // the fixed sensor only checks near straight ahead (config.py TOWER_HIT_BEARING_DEG)
const unsigned long COUNTDOWN_MS = 3000;
const unsigned long COOLDOWN_MS = 20000;         // the tower rests this long after each K (laser, servo and stepper warm up); F is dropped meanwhile

AccelStepper yaw(AccelStepper::HALF4WIRE, 4, 6, 5, 7);   // IN1, IN3, IN2, IN4
Servo pitch;
int pitchNow = PITCH_UP;
char rx[64];
byte rxLen = 0;
bool busy = false;                               // true while a sequence or a move runs
unsigned long tK = 0;                            // millis() when the last K went out (0 = none yet)
bool cooling() { return tK && millis() - tK < COOLDOWN_MS; }

void fireSequence(float bearing);
void goIdle();
float rangeCm();

void handleLine(char* s) {
  if (!strcmp(s, "I?")) Serial.println(F("I,tower,2"));
  else if (s[0] == 'P' && s[1] == ',') { Serial.print('Q'); Serial.println(s + 1); }     // P,seq,us -> Q,seq,us
  else if (busy) return;                                                                 // one thing at a time
  else if (s[0] == 'F' && (s[1] == 0 || s[1] == ',')) { if (!cooling()) fireSequence(s[1] ? atoi(s + 2) : 0); }
  else if (!strcmp(s, "Z")) { busy = true; goIdle(); busy = false; }
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

void pitchTo(int angle) {                        // slow sweep, one degree per 15 ms
  angle = constrain(angle, 0, 180);
  while (pitchNow != angle) {
    pitchNow += (angle > pitchNow) ? 1 : -1;
    pitch.write(pitchNow);
    waitMs(15);
  }
}

void yawTo(float deg) {
  yaw.moveTo((long)(YAW_DIR * deg * STEPS_PER_DEG));
  unsigned long n = 0;
  while (yaw.distanceToGo() != 0) { yaw.run(); if ((++n & 63) == 0) service(); }
}

int pitchForTarget(float cm) {                   // beam angle below horizontal that lands cm out
  float below = atan2(LASER_H_CM, cm) * 180.0 / PI;
  return PITCH_LEVEL - (int)(PITCH_DIR * below);
}

void goIdle() {
  pitchTo(PITCH_UP);                             // beam straight up
  yawTo(0);
}

void fireSequence(float bearing) {
  busy = true;
  bearing = constrain(bearing, -CONE_DEG, CONE_DEG);
  float d1 = rangeCm();
  float target = DEFAULT_CM;
  if (d1 >= MIN_CM && d1 <= MAX_CM) {
    waitMs(250);
    float d2 = rangeCm();
    float dv = d2 - d1;                          // movement over about 0.25 s
    int dir = (fabs(dv) < 2) ? AHEAD_DEFAULT : (dv > 0 ? 1 : -1);
    target = constrain(d2 + dir * LEAD_CM, MIN_CM, MAX_CM);
  }

  yawTo(bearing);                                // turn toward the bearing
  pitchTo(pitchForTarget(target));               // pitch the beam down onto the floor
  Serial.println(F("W,3"));                      // the countdown starts after the swing
  waitMs(COUNTDOWN_MS);

  bool hit = false;
  if (fabs(bearing) <= HIT_BEARING_DEG) {        // the sensor only sees straight ahead
    float d = rangeCm();
    hit = (d < MAX_CM) && fabs(d - target) <= HIT_TOL_CM;
  }
  Serial.println(hit ? F("K,1") : F("K,0"));
  tK = millis() | 1;                             // the cooldown starts at K (never 0)
  goIdle();
  busy = false;
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG, OUTPUT); pinMode(ECHO, INPUT);
  pinMode(LASER, OUTPUT); digitalWrite(LASER, HIGH);   // laser always on
  pinMode(BTN_PIN, INPUT_PULLUP);
  pitch.attach(SERVO_PIN); pitch.write(PITCH_UP);      // beam straight up
  yaw.setMaxSpeed(800); yaw.setAcceleration(400);
  yaw.setCurrentPosition(0);                           // power up facing straight ahead
}

void loop() {
  static unsigned long tBtn = 0;
  service();
  if (digitalRead(BTN_PIN) == LOW && millis() - tBtn > 300 && !cooling()) { fireSequence(0); tBtn = millis(); }   // test button: bearing 0
}
