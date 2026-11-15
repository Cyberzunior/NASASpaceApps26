// T-Minus_6 asteroid tower, firmware v2. Arduino UNO Q, microcontroller side, 3.3 V pins. USB serial, 115200 baud
// (the tower is wired to the laptop now). Protocol: laptop/devio/protocol.py.
//   in : I?   P,seq,us (ping -> Q,seq,us)   F (one shot)   A,angle (pan servo)   X (disarm)   R (arm)   T,rest,push,ms (tune the pusher)
//   out: I,tower,2   Q,seq,us   W,3 (warning: seconds until the ball is released)   K (ball released)
// One shot = warn, fire, release: W,3 -> 3 s wait -> push the ball -> K. The test-fire button on D2 runs the SAME sequence and
// sends the same lines, so the game shows the warning before the ball drops. F or the button is ignored when disarmed,
// during a shot, or within MIN_GAP_MS of the last one. No delay(): everything runs on millis().
// UNTESTED on hardware: check the Servo library on the UNO Q core and that D9 / D10 can drive servos.
#include <Servo.h>
#define FW_VERSION 2
#define HAS_PAN 1                         // 1 once the second SG90 (pan) is fitted

const int PUSH_PIN = 9, PAN_PIN = 10, LED = 13, BTN = 2;
const unsigned long MIN_GAP_MS = 1500, WARN_MS = 3000;
int restDeg = 20, pushDeg = 100;
unsigned long pushMs = 350;

Servo pusher;
#if HAS_PAN
Servo pan;
#endif
enum Phase { IDLE, WARNING, PUSHING } phase = IDLE;
bool armed = true;
unsigned long tPhase = 0, tFire = 0, tBtn = 0;
char rx[64];
byte rxLen = 0;

void startShot(unsigned long now) {
  if (!armed || phase != IDLE || (tFire != 0 && now - tFire < MIN_GAP_MS)) return;
  Serial.println("W,3");                    // warn first
  phase = WARNING; tPhase = now; tFire = now;
}

void handleLine(char* s) {
  if (!strcmp(s, "I?")) Serial.println("I,tower,2");
  else if (s[0] == 'P' && s[1] == ',') { Serial.print("Q"); Serial.println(s + 1); }
  else if (!strcmp(s, "F")) startShot(millis());
  else if (!strcmp(s, "X")) armed = false;
  else if (!strcmp(s, "R")) armed = true;
#if HAS_PAN
  else if (s[0] == 'A' && s[1] == ',') pan.write(constrain(atoi(s + 2), 0, 180));
#endif
  else if (s[0] == 'T' && s[1] == ',') {
    char* a = strchr(s + 2, ','); char* b = a ? strchr(a + 1, ',') : 0;
    if (a && b) { restDeg = constrain(atoi(s + 2), 0, 180); pushDeg = constrain(atoi(a + 1), 0, 180); pushMs = constrain(atol(b + 1), 100, 1500); if (phase != PUSHING) pusher.write(restDeg); }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED, OUTPUT); pinMode(BTN, INPUT_PULLUP);
  pusher.attach(PUSH_PIN); pusher.write(restDeg);
#if HAS_PAN
  pan.attach(PAN_PIN); pan.write(90);
#endif
}

void loop() {
  unsigned long now = millis();
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { rx[rxLen] = 0; if (rxLen) handleLine(rx); rxLen = 0; }
    else if (c != '\r' && rxLen < sizeof(rx) - 1) rx[rxLen++] = c;
  }
  if (phase == WARNING && now - tPhase >= WARN_MS) {          // warning over: release the ball
    pusher.write(pushDeg); phase = PUSHING; tPhase = now;
    Serial.println("K");
  } else if (phase == PUSHING && now - tPhase > pushMs) {
    pusher.write(restDeg); phase = IDLE;
  }
  if (digitalRead(BTN) == LOW && now - tBtn > 500) { tBtn = now; startShot(now); }   // test-fire: same warn, fire, release
  digitalWrite(LED, phase == WARNING ? (now / 150) % 2 : armed);                      // blinks during the warning
}
