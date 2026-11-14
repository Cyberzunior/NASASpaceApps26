// T-Minus_6 weather station, firmware v2. ELEGOO UNO R3 (5 V). Protocol: see laptop/devio/protocol.py.
// Lines in : I?   Z,state   V,temp   H,lives   G   R   BZ   L,text   Y,swing     (state 0 normal, 1 cold, 2 hot)
//            BZ = 0.5 s test beep. L,line1|line2 pins custom text on the LCD until R or an empty L,
//            Y,swing = orbit temperature swing in C from the laptop (NASA solar flare data); Y,-1 = the pot decides
// Lines out: I,weather,2   W,temp,hum,state  (every 2 s AND at once on every state change)
//            N,pot,swing10  (every 2 s: pot on A1 0-1023, swing in tenths of a C)
// No DHT11: the temperature is simulated. temp = BASE_C + swing * sin(orbit phase), one 60 s "orbit" through sunlight and
// Earth's shadow. The swing is the pot on A1 (0-12 C), or the laptop's Y when it has a NASA flare for the pot position.
// W's humidity field is always 0 (kept so the protocol stays the same).
// Effective state = the more severe of (that temp with 1 C hysteresis, the game's zone Z). V overrides it for tests.
// No delay() anywhere: the loop never waits.
#include <LiquidCrystal.h>                 // the 16-pin weather LCD (built in)

#define FW_VERSION 2
#define HAS_POT 1                          // 10k pot on A1 (outer legs 5V / GND, wiper A1); 0 = no pot, no swing
#define HAS_LIVES_LCD 0                    // set to 1 when the I2C 16x2 lives display is fitted (needs LiquidCrystal_I2C)
#if HAS_LIVES_LCD
#include <Wire.h>
#include <LiquidCrystal_I2C.h>             // Frank de Brabander's library
#endif

const float COLD_C = 18.0, HOT_C = 30.0, HYST = 1.0;
const float BASE_C = 24.0;                        // temperature with no swing
const float POT_SWING_MAX = 12.0;                  // C of swing with the pot fully right and no laptop
const unsigned long ORBIT_MS = 60000;              // one sunlit + shadow cycle
enum State { NORMAL = 0, COLD = 1, HOT = 2 };      // numbers match the protocol, and a bigger number is more severe
State sensorState = NORMAL, zoneState = NORMAL, state = NORMAL;

// Pins (do not change: they match docs/pin_map.md and the wiring diagrams)
const int GREEN = 3, BLUE = 4, RED = 5, HIT_LED = A0, BUZZER = 6;   // one active buzzer on D6, D7 is free
const int PIN_POT = A1;
LiquidCrystal weatherLcd(8, 9, 10, 11, 12, 13);    // RS, E, D4, D5, D6, D7

unsigned long tSensor = 0, tLcd = 0, tBlink = 0, tHit = 0, tBuzz = 0, tPot = 0;
float temp = BASE_C, virtualTemp = 0.0;           // temp = what we report: BASE_C + orbit swing
const int hum = 0;                                 // no humidity sensor any more
float pot = 0, laptopSwing = -1;                   // laptopSwing < 0: no Y yet, the pot sets the swing alone
bool useVirtual = false, blinkOn = false, gameOver = false, showCustom = false;
char custom[2][17];                                // L,text for testing the LCD
int lives = 15;
char rx[40];
byte rxLen = 0;

#if HAS_LIVES_LCD
LiquidCrystal_I2C livesLcd(0x27, 16, 2);
byte heartFull[8]  = {0x00, 0x0A, 0x1F, 0x1F, 0x1F, 0x0E, 0x04, 0x00};
byte heartEmpty[8] = {0x00, 0x0A, 0x15, 0x11, 0x11, 0x0A, 0x04, 0x00};
bool livesLcdOk = false;
bool i2cPresent(byte addr) { Wire.beginTransmission(addr); return Wire.endTransmission() == 0; }
void showLives() {
  if (!livesLcdOk) return;
  livesLcd.setCursor(0, 0);
  for (int i = 0; i < 15; i++) livesLcd.write(byte(i < lives ? 0 : 1));
  livesLcd.write(' ');
  livesLcd.setCursor(0, 1);
  if (gameOver) { livesLcd.print("GAME OVER       "); return; }
  char line[17];
  snprintf(line, sizeof(line), "T-Minus_6 L%2d/15", lives);
  livesLcd.print(line);
}
#else
void showLives() {}
#endif

void printPadded(const char* s) {                  // always writes 16 characters, so no clear() flicker
  char buf[17];
  snprintf(buf, sizeof(buf), "%-16s", s);
  weatherLcd.print(buf);
}
float swing() {                                    // C of orbit swing right now
  if (!HAS_POT) return 0;
  return laptopSwing >= 0 ? laptopSwing : pot / 1023.0 * POT_SWING_MAX;
}
float orbitOffset(unsigned long now) {             // + in sunlight, - in Earth's shadow
  return swing() * sin(6.2832 * (now % ORBIT_MS) / ORBIT_MS);
}
void showWeather() {                               // called every 5 s and at once on every state change
  char l1[20], l2[20];
  if (showCustom)         { strcpy(l1, custom[0]); strcpy(l2, custom[1]); }
  else if (gameOver)      { strcpy(l1, "SIGNAL LOST"); strcpy(l2, "GAME OVER"); }
  else if (state == HOT)  { strcpy(l1, "!! HOT ZONE !!"); strcpy(l2, "MOVE AWAY NOW!"); }
  else if (state == COLD) { strcpy(l1, "!! COLD ZONE !!"); strcpy(l2, "MOVE AWAY NOW!"); }
  else {
    char t[10];
    dtostrf(temp, 4, 1, t);
    snprintf(l1, sizeof(l1), "T %sC NORMAL", t);
    snprintf(l2, sizeof(l2), "ORBIT SWING %dC", (int)(swing() + 0.5));
  }
  weatherLcd.setCursor(0, 0); printPadded(l1);
  weatherLcd.setCursor(0, 1); printPadded(l2);
}
void sendW() {
  Serial.print("W,"); Serial.print(temp, 1); Serial.print(','); Serial.print((int)hum); Serial.print(','); Serial.println((int)state);
}
void sendN() {
  Serial.print("N,"); Serial.print((int)pot); Serial.print(','); Serial.println((int)(swing() * 10 + 0.5));
}
void updateState() {
  float t = useVirtual ? virtualTemp : temp;
  State s = sensorState;
  if (s == NORMAL)    { if (t > HOT_C) s = HOT; else if (t < COLD_C) s = COLD; }
  else if (s == HOT)  { if (t < HOT_C - HYST) s = NORMAL; }
  else if (s == COLD) { if (t > COLD_C + HYST) s = NORMAL; }
  sensorState = s;
  State eff = (State)max((int)sensorState, (int)zoneState);       // the more severe state wins
  if (eff != state) {
    state = eff;
    showWeather(); tLcd = millis();                // the warning shows at once, not at the next 5 s update
    sendW();                                       // and the laptop hears about it at once
  }
}
void outputs(unsigned long now) {
  if (now - tBlink >= 100) { tBlink = now; blinkOn = !blinkOn; }  // about 5 blinks a second
  bool quiet = gameOver;
  digitalWrite(GREEN, state == NORMAL && !gameOver);
  digitalWrite(BLUE, state == COLD && blinkOn && !quiet);
  digitalWrite(RED,  state == HOT  && blinkOn && !quiet);
  bool hotBeep = (now / 100) % 2, coldBeep = (now / 200) % 2;   // hot: 100 ms on / off, cold: 200 ms on / off
  bool buzz = (tBuzz && now - tBuzz < 500)                       // BZ test beep, even in game over
           || (!quiet && state == HOT && hotBeep) || (!quiet && state == COLD && coldBeep);
  digitalWrite(BUZZER, buzz);
  digitalWrite(HIT_LED, now - tHit < 1000);                       // 1 second hit flash
}
void handleLine(const char* s) {
  if (!strcmp(s, "I?"))             { Serial.println("I,weather,2"); }
  else if (s[0] == 'Z' && s[1] == ',') { int z = atoi(s + 2); zoneState = (State)constrain(z, 0, 2); updateState(); }
  else if (s[0] == 'V' && s[1] == ',') { useVirtual = true; virtualTemp = atof(s + 2); temp = virtualTemp; updateState(); }
  else if (s[0] == 'H' && s[1] == ',') { int n = atoi(s + 2); if (n < lives) tHit = millis(); lives = n; showLives(); }
  else if (!strcmp(s, "G"))         { gameOver = true; lives = 0; showLives(); showWeather(); }
  else if (s[0] == 'L' && s[1] == ',') {                  // L,line1|line2 (empty text: back to the weather)
    const char* bar = strchr(s + 2, '|');
    int n1 = bar ? bar - (s + 2) : strlen(s + 2);
    snprintf(custom[0], 17, "%.*s", n1, s + 2);
    snprintf(custom[1], 17, "%s", bar ? bar + 1 : "");
    showCustom = s[2] != 0; showWeather(); tLcd = millis();
  }
  else if (s[0] == 'Y' && s[1] == ',') { float y = atof(s + 2); laptopSwing = y < 0 ? -1 : min(y, 20.0); }
  else if (!strcmp(s, "BZ"))        { tBuzz = millis(); if (!tBuzz) tBuzz = 1; }
  else if (!strcmp(s, "R"))         { showCustom = false; gameOver = false; lives = 15; useVirtual = false; zoneState = NORMAL; updateState(); showLives(); showWeather(); }
}
void readSerial() {                                // collects one line at a time, never blocks
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { rx[rxLen] = 0; if (rxLen) handleLine(rx); rxLen = 0; }
    else if (c != '\r' && rxLen < sizeof(rx) - 1) rx[rxLen++] = c;
  }
}
void setup() {
  Serial.begin(115200);
  weatherLcd.begin(16, 2);
  pinMode(GREEN, OUTPUT); pinMode(BLUE, OUTPUT); pinMode(RED, OUTPUT);
  pinMode(HIT_LED, OUTPUT); pinMode(BUZZER, OUTPUT);
#if HAS_LIVES_LCD
  Wire.begin();
  byte addr = i2cPresent(0x27) ? 0x27 : (i2cPresent(0x3F) ? 0x3F : 0);   // the I2C scanner: try both addresses
  if (addr) {
    livesLcd = LiquidCrystal_I2C(addr, 16, 2);
    livesLcd.init(); livesLcd.backlight();
    livesLcd.createChar(0, heartFull); livesLcd.createChar(1, heartEmpty);
    livesLcdOk = true;
  }
#endif
  showWeather(); showLives();
}
void loop() {
  unsigned long now = millis();
  if (now - tSensor >= 2000) {                     // new temperature and a W line every 2 s
    tSensor = now;
    if (!useVirtual) temp = BASE_C + orbitOffset(now);
    updateState();
    sendW();
    if (HAS_POT) sendN();
  }
  if (HAS_POT && now - tPot >= 50) { tPot = now; pot += (analogRead(PIN_POT) - pot) * 0.2; }   // smoothed
  if (now - tLcd >= 5000) { tLcd = now; showWeather(); }          // the temperature shows every 5 s
  readSerial();
  outputs(now);
}
