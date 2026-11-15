// T-Minus_6 HUD panel, firmware v3. Arduino UNO Q, microcontroller side, 3.3 V logic. USB serial, 115200 baud.
// Protocol: plain ASCII lines, comma separated, one line per newline (the same encoding the triage suite uses).
//
// Lines in : M,power,oxygen,food,shield (the four meters, 0..100, on change, at most 5 a second)
//            H,hearts,samples (base integrity 0..15 and sample count)   V,tempC (once a second, keep-alive)
//            S,state (0 normal, 1 cold, 2 hot, 3 radiation storm, 4 asteroid incoming)
//            P (sample picked up)   B (run starts, intro finished)   G (game over)
// Lines out : J,x,y,sw every 33 ms (joystick: x right, y forward, -100..100, sw 1 while pressed)
//             HELLO,HUD,1 once at boot   HB heartbeat once a second
//
// The laptop holds all the game logic. This board only mirrors numbers and states and sends back the joystick.
//
// Pins: A1 joystick VRx | A2 joystick VRy | D6 joystick SW (INPUT_PULLUP, pressed = LOW) | D3 green LED
//       D5 red LED | A0 yellow LED | D4 ARGB data in through 330 ohm (one pixel, powered from 3V3)
//       D7 passive buzzer + | D8 D9 LCD RS E | D10 D11 D12 D13 LCD D4 D5 D6 D7 | SDA SCL OLED SSD1306 0x3C
//       Joystick, OLED and ARGB pixel power from 3V3. Never put 5 V on an input pin of this board.
// Libraries: LiquidCrystal, Adafruit SSD1306, Adafruit GFX, Adafruit NeoPixel.
// UNTESTED on hardware: check that all four libraries compile for the UNO Q core and that tone() works there.
#include <LiquidCrystal.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_NeoPixel.h>

#define HUD_PROTO 1
const int JOY_X = A1, JOY_Y = A2, JOY_SW = 6;
const int LED_G = 3, LED_R = 5, LED_Y = A0, BUZZER = 7, ARGB = 4;

LiquidCrystal lcd(8, 9, 10, 11, 12, 13);          // RS, E, D4, D5, D6, D7
Adafruit_SSD1306 oled(128, 64, &Wire, -1);
Adafruit_NeoPixel pixel(1, ARGB, NEO_GRB + NEO_KHZ800);
bool oledOk = false;

int power = 0, oxygen = 0, food = 0, shield = 0;  // the four meters
int hearts = 15, samples = 0, state = 0;
bool gameOver = false, gotData = false;           // gotData: at least one M line seen
bool chirpQueued = false;
unsigned long lastRx = 0, tJoy = 0, tHB = 0, tLcd = 0, tOled = 0, tPixel = 0, tPickup = 0;
bool linkSeen = false;                            // any line received since boot
int cx = 512, cy = 512;                           // joystick centre, measured untouched at power-up
String rxLine;

int norm(int raw, int center) {                   // ADC reading to -100..100 with an 8 percent dead zone
  int span = (raw >= center) ? (1023 - center) : center;
  if (span < 1) span = 1;
  int v = (int)((long)(raw - center) * 100 / span);
  return (abs(v) < 8) ? 0 : constrain(v, -100, 100);
}

bool linkLost() {                                 // no line for 3 s, or nothing ever arrived after boot grace
  unsigned long now = millis();
  if (!linkSeen) return now >= 3000;
  return now - lastRx >= 3000;
}

bool linkUp() { return !linkLost(); }

void handleLine(const String &l) {
  if (l.length() < 1) return;
  lastRx = millis(); linkSeen = true;
  char c = l.charAt(0);
  if (c == 'M' && l.charAt(1) == ',') {
    int m[4];
    if (sscanf(l.c_str(), "M,%d,%d,%d,%d", &m[0], &m[1], &m[2], &m[3]) == 4) {
      for (int i = 0; i < 4; i++) m[i] = constrain(m[i], 0, 100);
      power = m[0]; oxygen = m[1]; food = m[2]; shield = m[3];
      gotData = true;
    }
  }
  else if (c == 'H' && l.charAt(1) == ',') {
    int h = 0, s = 0;
    if (sscanf(l.c_str(), "H,%d,%d", &h, &s) == 2) { hearts = constrain(h, 0, 15); samples = max(s, 0); }
  }
  else if (c == 'V' && l.charAt(1) == ',') { }    // keep-alive only: the laptop holds the temperature
  else if (c == 'S' && l.charAt(1) == ',') { state = constrain(l.substring(2).toInt(), 0, 4); }
  else if (c == 'P') { tPickup = millis(); if (!tPickup) tPickup = 1; chirpQueued = true; }
  else if (c == 'B') { gameOver = false; chirpQueued = true; }
  else if (c == 'G') { gameOver = true; }
}

void readSerial() {                               // one line at a time, never blocks
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') { handleLine(rxLine); rxLine = ""; }
    else if (ch != '\r' && rxLine.length() < 48) rxLine += ch;
  }
}

void row(int r, const char *s) {                  // always 16 characters, so no clear() flicker
  char buf[17];
  snprintf(buf, sizeof(buf), "%-16s", s);
  lcd.setCursor(0, r); lcd.print(buf);
}

void showLcd() {
  char l1[20], l2[20];
  if (linkLost())       { strcpy(l1, "NO LINK");         strcpy(l2, "CHECK USB"); }
  else if (gameOver)    { strcpy(l1, "GAME OVER");       strcpy(l2, "PRESS START"); }
  else if (!gotData)    { strcpy(l1, "OUTPOST ONLINE");  strcpy(l2, "WAITING..."); }
  else if (state == 1)  { strcpy(l1, "COLD SNAP");       strcpy(l2, "HEATING ON"); }
  else if (state == 2)  { strcpy(l1, "HOT SPELL");       strcpy(l2, "COOLING ON"); }
  else if (state == 3)  { strcpy(l1, "RADIATION STORM"); strcpy(l2, "BOOST SHIELD"); }
  else if (state == 4)  { strcpy(l1, "ASTEROID");        strcpy(l2, "DRIVE CLEAR!"); }
  else {
    snprintf(l1, 20, "PWR %-3d  O2 %-3d", power, oxygen);
    snprintf(l2, 20, "FOOD%-3d SHLD%-3d", food, shield);
  }
  row(0, l1); row(1, l2);
}

void showOled() {
  if (!oledOk) return;
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(2);
  oled.setCursor(0, 0);
  oled.print("BASE "); oled.print(hearts); oled.print("/15");
  oled.drawRect(0, 24, 128, 12, SSD1306_WHITE);
  oled.fillRect(2, 26, (124 * hearts) / 15, 8, SSD1306_WHITE);
  oled.setCursor(0, 44);
  oled.print("SAMPLES "); oled.print(samples);
  oled.display();
}

void showLeds() {                                 // cheap digitalWrites: every pass is fine
  unsigned long now = millis();
  bool up = linkUp();
  digitalWrite(LED_G, up && !gameOver && state == 0);
  bool warn = up && !gameOver && state >= 1 && state <= 3;
  bool blinkFast = up && !gameOver && state == 4 && (now / 150) % 2;
  digitalWrite(LED_R, warn || blinkFast);
  digitalWrite(LED_Y, tPickup && now - tPickup < 1000 && ((now - tPickup) / 100) % 2 == 0);
}

void showPixel() {
  unsigned long now = millis();
  uint32_t col = 0;
  if (linkLost()) {                               // dim white breathing, 1.2 s cycle
    unsigned long ph = now % 1200;
    int b = (ph < 600) ? (int)(30L * ph / 600) : (int)(30L * (1200 - ph) / 600);
    col = pixel.Color(b, b, b);
  }
  else if (gameOver)   col = pixel.Color(60, 0, 0);
  else if (state == 0) col = pixel.Color(0, 40, 0);
  else if (state == 1) col = pixel.Color(0, 0, 60);
  else if (state == 2) col = pixel.Color(60, 0, 0);
  else if (state == 3) col = pixel.Color(40, 0, 50);
  else if (state == 4) col = ((now / 150) % 2) ? pixel.Color(60, 25, 0) : 0;
  pixel.setPixelColor(0, col); pixel.show();
}

void buzzerTick() {
  static unsigned long tBeep = 0;
  unsigned long now = millis();
  if (chirpQueued) { tone(BUZZER, 1200, 120); chirpQueued = false; tBeep = now; return; }
  if (!linkUp()) return;
  int f = 0; unsigned long period = 0;
  if (gameOver)        { f = 300;  period = 1500; }
  else if (state == 1) { f = 400;  period = 300; }
  else if (state == 2) { f = 2000; period = 300; }
  else if (state == 3) { f = 800;  period = 700; }
  else if (state == 4) { f = 1600; period = 200; }
  if (f && now - tBeep >= period) { tone(BUZZER, f, 80); tBeep = now; }
}

void sendJoystick() {                             // every 33 ms, even with the link down
  Serial.print("J,");
  Serial.print(norm(analogRead(JOY_X), cx)); Serial.print(',');
  Serial.print(-norm(analogRead(JOY_Y), cy)); Serial.print(',');   // flip so forward is positive
  Serial.println(digitalRead(JOY_SW) == LOW ? 1 : 0);
}

void setupJoystick() {                            // the stick must be untouched at power-up: this is its centre
  analogReadResolution(10);
  pinMode(JOY_SW, INPUT_PULLUP);
  long sx = 0, sy = 0;
  for (int i = 0; i < 16; i++) { sx += analogRead(JOY_X); sy += analogRead(JOY_Y); delay(5); }
  cx = sx / 16; cy = sy / 16;
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_G, OUTPUT); pinMode(LED_R, OUTPUT); pinMode(LED_Y, OUTPUT); pinMode(BUZZER, OUTPUT);
  lcd.begin(16, 2);
  Wire.begin();
  oledOk = oled.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  pixel.begin(); pixel.setBrightness(255); pixel.show();
  setupJoystick();
  Serial.print("HELLO,HUD,"); Serial.println(HUD_PROTO);
  showLcd(); showOled();
}

void loop() {
  readSerial();
  unsigned long now = millis();
  if (now - tJoy >= 33)   { tJoy = now;  sendJoystick(); }   // 30 times a second
  if (now - tHB >= 1000)  { tHB = now;   Serial.println("HB"); }
  if (now - tLcd >= 150)  { tLcd = now;  showLcd(); }        // fixed rates, never per loop pass
  if (now - tOled >= 250) { tOled = now; showOled(); }
  if (now - tPixel >= 50) { tPixel = now; showPixel(); }
  showLeds();
  buzzerTick();
}
