// T-Minus_6 HUD panel, firmware v2. Arduino UNO Q, microcontroller side, 3.3 V logic. USB serial, 115200 baud.
// Protocol: laptop/devio/protocol.py (the same lines the triage suite uses). No delay() anywhere.
//
// Lines in : I?   P,seq,us (ping, answered Q,seq,us)   P (sample picked up)   BZ (chirp)   Z,state (0 normal 1 cold 2 hot)
//            V,tempC (simulated temperature when the DHT11 is dead)   M,pwr,o2,food,shield   H,hearts   E,samples
//            G (game over)   R (reset)   L,line1|line2 (text on the LCD; "L," clears it)
// Lines out: I,hud,2   Q,seq,us   W,temp,hum,state  every 2 s while the DHT11 reads fine
//            (when it does not and a V arrived in the last 4 s: W,<V value>,-1,state; hum -1 = "not a real reading")
//
// Pins: D2 DHT11 (3V3) | D3 green LED | D4 blue LED | D5 red LED | A0 yellow LED | D6 unused | D7 passive buzzer +
//       D8 D9 LCD RS E | D10..D13 LCD D4..D7 | SDA SCL OLED SSD1306 0x3C (3V3)
// Libraries: LiquidCrystal, DHT sensor library, Adafruit SSD1306, Adafruit GFX.
// UNTESTED on hardware: check that tone() works on the UNO Q core and that the LCD runs from its supply.
#include <LiquidCrystal.h>
#include <DHT.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define FW_VERSION 2
const int PIN_DHT = 2, GREEN = 3, BLUE = 4, RED = 5, YELLOW = A0, BUZZER = 7;
LiquidCrystal lcd(8, 9, 10, 11, 12, 13);          // RS, E, D4, D5, D6, D7
DHT dht(PIN_DHT, DHT11);
Adafruit_SSD1306 oled(128, 64, &Wire, -1);
bool oledOk = false;

enum State { NORMAL = 0, COLD = 1, HOT = 2 };
State state = NORMAL;
int meters[4] = {100, 100, 100, 100};            // power, oxygen, food, shield
int hearts = 15, samples = 0;
bool gameOver = false, showCustom = false, virtualOn = false;
char custom[2][17];
float virtualTemp = 0;
unsigned long tVirtual = 0, tSensor = 0, tLcd = 0, tOled = 0, tBlink = 0, tPickup = 0, tChirp = 0;
bool dirtyLcd = true, dirtyOled = true, blinkOn = false;
char rx[64];
byte rxLen = 0;

void printPadded(const char* s) {                 // always 16 characters, so no clear() flicker
  char buf[17];
  snprintf(buf, sizeof(buf), "%-16s", s);
  lcd.print(buf);
}

void showLcd() {
  char l1[20], l2[20];
  if (showCustom)        { snprintf(l1, 20, "%s", custom[0]); snprintf(l2, 20, "%s", custom[1]); }
  else if (gameOver)     { strcpy(l1, "OUTPOST LOST"); strcpy(l2, ""); }
  else if (state == HOT) { strcpy(l1, "!! HOT !!"); strcpy(l2, "COOLING"); }
  else if (state == COLD){ strcpy(l1, "!! COLD !!"); strcpy(l2, "HEATING"); }
  else {
    snprintf(l1, 20, "PWR %-3d O2 %-3d", meters[0], meters[1]);
    snprintf(l2, 20, "FOOD %-3d SHLD %-3d", meters[2], meters[3]);
  }
  lcd.setCursor(0, 0); printPadded(l1);
  lcd.setCursor(0, 1); printPadded(l2);
}

void showOled() {
  if (!oledOk) return;
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(2);
  oled.setCursor(0, 4);  oled.print("BASE "); oled.print(hearts); oled.print("/15");
  oled.setCursor(0, 36); oled.print("SAMPLES "); oled.print(samples);
  oled.display();
}

void setState(State s) {
  if (s != state) { state = s; dirtyLcd = true; }
}

void handleLine(char* s) {
  if (!strcmp(s, "I?"))                   { Serial.println("I,hud,2"); }
  else if (s[0] == 'P' && s[1] == ',')    { Serial.print("Q"); Serial.println(s + 1); }           // P,seq,us -> Q,seq,us
  else if (!strcmp(s, "P"))               { tPickup = millis(); if (!tPickup) tPickup = 1; tChirp = millis(); }
  else if (!strcmp(s, "BZ"))              { tChirp = millis(); if (!tChirp) tChirp = 1; }
  else if (s[0] == 'Z' && s[1] == ',')    { setState((State)constrain(atoi(s + 2), 0, 2)); }
  else if (s[0] == 'V' && s[1] == ',')    { virtualOn = true; virtualTemp = atof(s + 2); tVirtual = millis(); }
  else if (s[0] == 'M' && s[1] == ',') {
    char* p = s + 2;
    for (int i = 0; i < 4; i++) { meters[i] = constrain(atoi(p), 0, 100); p = strchr(p, ','); if (!p) break; p++; }
    dirtyLcd = true;
  }
  else if (s[0] == 'H' && s[1] == ',')    { hearts = constrain(atoi(s + 2), 0, 15); dirtyOled = true; }
  else if (s[0] == 'E' && s[1] == ',')    { samples = atoi(s + 2); dirtyOled = true; }
  else if (!strcmp(s, "G"))               { gameOver = true; dirtyLcd = true; }
  else if (!strcmp(s, "R"))               { gameOver = false; showCustom = false; virtualOn = false; state = NORMAL; hearts = 15; samples = 0; dirtyLcd = dirtyOled = true; }
  else if (s[0] == 'L' && s[1] == ',') {
    const char* bar = strchr(s + 2, '|');
    int n1 = bar ? bar - (s + 2) : strlen(s + 2);
    snprintf(custom[0], 17, "%.*s", n1, s + 2);
    snprintf(custom[1], 17, "%s", bar ? bar + 1 : "");
    showCustom = s[2] != 0;
    dirtyLcd = true;
  }
}

void readSerial() {                               // one line at a time, never blocks
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { rx[rxLen] = 0; if (rxLen) handleLine(rx); rxLen = 0; }
    else if (c != '\r' && rxLen < sizeof(rx) - 1) rx[rxLen++] = c;
  }
}

void sendW(float t, int hum) {
  Serial.print("W,"); Serial.print(t, 1); Serial.print(','); Serial.print(hum); Serial.print(','); Serial.println((int)state);
}

void outputs(unsigned long now) {
  if (now - tBlink >= 100) { tBlink = now; blinkOn = !blinkOn; }
  digitalWrite(GREEN, state == NORMAL && !gameOver);
  digitalWrite(BLUE, state == COLD && blinkOn && !gameOver);
  digitalWrite(RED, state == HOT && blinkOn && !gameOver);
  // yellow: 5 blinks in 1 s after a pickup (100 ms on, 100 ms off)
  digitalWrite(YELLOW, tPickup && now - tPickup < 1000 && ((now - tPickup) / 100) % 2 == 0);
  // one passive buzzer on D7: chirp 1200 Hz, hot 2000 Hz fast beeps, cold 400 Hz fast beeps, else silent
  static int playing = 0;
  int want = 0;
  if (tChirp && now - tChirp < 150) want = 1200;
  else if (!gameOver && state == HOT && blinkOn) want = 2000;
  else if (!gameOver && state == COLD && blinkOn) want = 400;
  if (want != playing) { if (want) tone(BUZZER, want); else noTone(BUZZER); playing = want; }
}

void setup() {
  Serial.begin(115200);
  pinMode(GREEN, OUTPUT); pinMode(BLUE, OUTPUT); pinMode(RED, OUTPUT); pinMode(YELLOW, OUTPUT); pinMode(BUZZER, OUTPUT);
  lcd.begin(16, 2);
  dht.begin();
  Wire.begin();
  oledOk = oled.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  showLcd(); showOled();
}

void loop() {
  unsigned long now = millis();
  readSerial();
  if (now - tSensor >= 2000) {                    // the DHT11 reading goes to the laptop every 2 s
    tSensor = now;
    float t = dht.readTemperature(), h = dht.readHumidity();
    if (!isnan(t) && !isnan(h)) sendW(t, (int)h);
    else if (virtualOn && now - tVirtual < 4000) sendW(virtualTemp, -1);
  }
  if (dirtyLcd && now - tLcd >= 200)   { tLcd = now; dirtyLcd = false; showLcd(); }     // at most 5 redraws a second
  if (dirtyOled && now - tOled >= 250) { tOled = now; dirtyOled = false; showOled(); }
  outputs(now);
}
