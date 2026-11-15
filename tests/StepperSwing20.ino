// StepperSwing20.ino: swings a 28BYJ-48 (ULN2003 driver) from 0 to +20, then to -20, then back to 0,
// one degree at a time. Pauses at every degree so the motion can be checked by eye.
//
// ULN2003 wiring: IN1 = D4, IN2 = D7, IN3 = D8, IN4 = D12.
// AccelStepper FULL4WIRE takes the pins in coil order 1, 3, 2, 4.

#include <AccelStepper.h>

const int PIN_IN1 = 4;
const int PIN_IN2 = 7;
const int PIN_IN3 = 8;
const int PIN_IN4 = 12;

const float STEPS_PER_REV = 2048.0;     // 28BYJ-48 output shaft, full-step
const int SWEEP_DEG = 20;               // swing to +20 and -20
const unsigned long PAUSE_MS = 300;     // pause at every degree
const unsigned long CYCLE_PAUSE_MS = 2000;

AccelStepper stepper(AccelStepper::FULL4WIRE, PIN_IN1, PIN_IN3, PIN_IN2, PIN_IN4);

long stepsFor(int deg) {
  return lround(deg * STEPS_PER_REV / 360.0);
}

void goDegree(int deg) {
  stepper.moveTo(stepsFor(deg));
  stepper.runToPosition();              // blocks until the shaft is at this angle
  Serial.print(F("angle "));
  Serial.println(deg);
  delay(PAUSE_MS);
}

void setup() {
  Serial.begin(115200);
  stepper.setMaxSpeed(300.0);
  stepper.setAcceleration(150.0);
  stepper.setCurrentPosition(0);        // wherever the shaft sits at power-up is 0 degrees
  Serial.println(F("Swing test: 0 -> +20 -> -20 -> 0, 1 degree steps"));
}

void loop() {
  stepper.enableOutputs();
  for (int d = 0; d <= SWEEP_DEG; d++) goDegree(d);                // 0 to +20
  for (int d = SWEEP_DEG; d >= -SWEEP_DEG; d--) goDegree(d);       // +20 to -20
  for (int d = -SWEEP_DEG; d <= 0; d++) goDegree(d);               // -20 to 0
  stepper.disableOutputs();             // coils off between cycles: no heating
  delay(CYCLE_PAUSE_MS);
}
