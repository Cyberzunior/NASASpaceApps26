// Asteroid tower test suite (UNO R3)
// Push servo: D9   Pan stepper (ULN2003): D4,D5,D6,D7   Test button: D2 to GND
#include <Servo.h>
#include <AccelStepper.h>

const int SERVO_PIN = 9, BTN_PIN = 2;
const int REST = 0, FIRE = 90;                  // adjust to your arm
AccelStepper pan(AccelStepper::HALF4WIRE, 4, 6, 5, 7);   // IN1, IN3, IN2, IN4
Servo push;

void menu() {
  Serial.println(F("\n--- Tower tests ---"));
  Serial.println(F("1 servo sweep    2 servo fire/return"));
  Serial.println(F("3 pan left/right 4 pan 360 spin"));
  Serial.println(F("5 button (5 s)   6 full sequence"));
}

void servoSweep() {
  for (int a = REST; a <= 180; a += 5) { push.write(a); delay(30); }
  for (int a = 180; a >= REST; a -= 5) { push.write(a); delay(30); }
  Serial.println(F("servo sweep done"));
}

void servoFire() {
  push.write(FIRE); delay(400);
  push.write(REST); delay(400);
  Serial.println(F("servo fire done"));
}

void runTo(long target) {
  pan.moveTo(target);
  while (pan.distanceToGo() != 0) pan.run();
}

void panLR() {
  runTo(512);  delay(300);          // about 45 degrees
  runTo(-512); delay(300);
  runTo(0);
  Serial.println(F("pan left/right done"));
}

void panSpin() {
  runTo(pan.currentPosition() + 4096);   // one full turn
  runTo(0);
  Serial.println(F("pan spin done"));
}

void buttonTest() {
  Serial.println(F("press the test button..."));
  unsigned long t = millis();
  bool last = HIGH;
  while (millis() - t < 5000) {
    bool now = digitalRead(BTN_PIN);
    if (now != last) { Serial.println(now == LOW ? F("PRESSED") : F("released")); last = now; delay(30); }
  }
  Serial.println(F("button test done"));
}

void setup() {
  Serial.begin(115200);
  pinMode(BTN_PIN, INPUT_PULLUP);
  push.attach(SERVO_PIN);
  push.write(REST);
  pan.setMaxSpeed(800);
  pan.setAcceleration(400);
  menu();
}

void loop() {
  if (!Serial.available()) return;
  char c = Serial.read();
  switch (c) {
    case '1': servoSweep(); break;
    case '2': servoFire(); break;
    case '3': panLR(); break;
    case '4': panSpin(); break;
    case '5': buttonTest(); break;
    case '6': panLR(); servoFire(); buttonTest(); break;
    default: return;
  }
  menu();
}