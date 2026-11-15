// T-Minus_6 asteroid tower, firmware v3: a general serial-driven pan/tilt laser. Arduino UNO R3 (5 V logic), USB serial, 115200 baud.
// FLASH IT ONCE. It knows nothing about the game: the laptop (the game, tests/triage_gui.py, or a terminal) works out every angle
// and decision and sends it as a line. Newline-framed lines, the same scheme the triage suite uses (laptop/devio/protocol.py).
//
//   in : I?                    who are you            -> I,tower,2
//        P,seq,us              ping                   -> Q,seq,us
//        Y,deg                 yaw to deg (float), 0 = where the stepper was at power-up or at the last H; clamped to +-YAW_MAX_DEG
//        T,deg                 servo to deg, raw 0..180 (the laptop maps beam elevation onto it)
//        L,0 / L,1             laser off / on (it is ON from power-up)
//        H                     here is yaw 0 (re-zero without resetting the board)
//        O                     release the stepper coils (cool down, turn the head by hand)
//        G,yawSps,yawAcc,ms    speeds: stepper steps/s (max 1000) and steps/s^2, servo ms per degree (0 = jump)
//        R                     one distance reading from the HC-SR04     -> R,cm (999 = nothing there)
//        ?                     report state                              -> S,yaw,servo,laser,moving
//   out: D,yaw,servo           sent once when both motors reach the last Y / T target
//        B,1                   the optional test button on D2 was pressed
//
// Moves never block: the stepper, the servo slew, serial and pings all run in one loop, so Y / T can stream at 10 Hz and the
// laptop never shows the tower as lost.
// Pins: D2 test button to GND (optional) | D4..D7 ULN2003 IN1..IN4 (28BYJ-48 yaw stepper) | D9 pitch servo
//       D11 HC-SR04 TRIG | D12 HC-SR04 ECHO | D13 green laser through a 2N2222 | 5 V HC-SR04 VCC
// Power: servo, stepper and laser on a second MB102, its GND joined to the UNO GND. Nothing joins the two + rails.
// Power-up: the stepper is taken as facing straight ahead (yaw 0) and the servo is written to SERVO_START (beam straight up
// with the default wiring). The laser is on from power-up. Never aim it at a face. Opening the serial port resets an UNO R3.
// Libraries: Servo, AccelStepper.
#include <Servo.h>
#include <AccelStepper.h>

const int BTN_PIN = 2, SERVO_PIN = 9, TRIG = 11, ECHO = 12, LASER = 13;
const float STEPS_PER_DEG = 4096.0 / 360.0;      // 28BYJ-48 half-step
const float YAW_MAX_DEG = 100;                   // the cable and the housing end somewhere
const int   SERVO_START = 180;                   // servo angle at power-up: beam straight up with PITCH_DIR = 1, PITCH_LEVEL = 90

AccelStepper yaw(AccelStepper::HALF4WIRE, 4, 6, 5, 7);   // IN1, IN3, IN2, IN4
Servo pitch;
int servoNow = SERVO_START, servoTarget = SERVO_START;
unsigned int servoMsPerDeg = 15;
unsigned long tServo = 0;
bool laserOn = true, arrivedSent = true;
char rx[64];
byte rxLen = 0;

float yawDeg() { return yaw.currentPosition() / STEPS_PER_DEG; }
bool moving() { return yaw.distanceToGo() != 0 || servoNow != servoTarget; }

void sendState() {
  Serial.print(F("S,")); Serial.print(yawDeg(), 1);
  Serial.print(','); Serial.print(servoNow);
  Serial.print(','); Serial.print(laserOn ? 1 : 0);
  Serial.print(','); Serial.println(moving() ? 1 : 0);
}

float rangeCm();

void handleLine(char* s) {
  if (!strcmp(s, "I?")) Serial.println(F("I,tower,2"));
  else if (s[0] == 'P' && s[1] == ',') { Serial.print('Q'); Serial.println(s + 1); }     // P,seq,us -> Q,seq,us
  else if (s[0] == 'Y' && s[1] == ',') {
    float d = constrain(atof(s + 2), -YAW_MAX_DEG, YAW_MAX_DEG);
    yaw.moveTo((long)(d * STEPS_PER_DEG));
    arrivedSent = false;
  }
  else if (s[0] == 'T' && s[1] == ',') {
    servoTarget = constrain((int)(atof(s + 2) + 0.5), 0, 180);
    arrivedSent = false;
  }
  else if (s[0] == 'L' && s[1] == ',') { laserOn = atoi(s + 2) != 0; digitalWrite(LASER, laserOn ? HIGH : LOW); }
  else if (!strcmp(s, "H")) { yaw.setCurrentPosition(0); yaw.moveTo(0); }
  else if (!strcmp(s, "O")) { yaw.moveTo(yaw.currentPosition()); yaw.disableOutputs(); }
  else if (s[0] == 'G' && s[1] == ',') {
    char* p = s + 2;
    float v = atof(p);
    if (v > 0) yaw.setMaxSpeed(constrain(v, 50, 1000));
    p = strchr(p, ','); if (!p) return;
    v = atof(++p);
    if (v > 0) yaw.setAcceleration(constrain(v, 50, 4000));
    p = strchr(p, ','); if (!p) return;
    servoMsPerDeg = constrain(atoi(p + 1), 0, 100);
  }
  else if (!strcmp(s, "R")) { Serial.print(F("R,")); Serial.println(rangeCm(), 0); }
  else if (!strcmp(s, "?")) sendState();
}

void service() {                                 // read serial lines
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { rx[rxLen] = 0; byte n = rxLen; rxLen = 0; if (n) handleLine(rx); }
    else if (c != '\r' && rxLen < sizeof(rx) - 1) rx[rxLen++] = c;
  }
}

void pump() {                                    // everything that must keep running, called from every wait
  service();
  yaw.run();
  unsigned long now = millis();
  if (servoNow != servoTarget && (servoMsPerDeg == 0 || now - tServo >= servoMsPerDeg)) {
    tServo = now;
    servoNow = servoMsPerDeg == 0 ? servoTarget : servoNow + (servoTarget > servoNow ? 1 : -1);
    pitch.write(servoNow);
  }
  if (!arrivedSent && !moving()) {
    arrivedSent = true;
    Serial.print(F("D,")); Serial.print(yawDeg(), 1); Serial.print(','); Serial.println(servoNow);
  }
}

void waitMs(unsigned long ms) {
  unsigned long t0 = millis();
  while (millis() - t0 < ms) pump();
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

void setup() {
  Serial.begin(115200);
  pinMode(TRIG, OUTPUT); pinMode(ECHO, INPUT);
  pinMode(LASER, OUTPUT); digitalWrite(LASER, HIGH);   // laser on from power-up
  pinMode(BTN_PIN, INPUT_PULLUP);
  pitch.attach(SERVO_PIN); pitch.write(SERVO_START);
  yaw.setMaxSpeed(800); yaw.setAcceleration(400);
  yaw.setCurrentPosition(0);                           // power up facing straight ahead
}

void loop() {
  static unsigned long tBtn = 0;
  pump();
  if (digitalRead(BTN_PIN) == LOW && millis() - tBtn > 300) { Serial.println(F("B,1")); tBtn = millis(); }
}
