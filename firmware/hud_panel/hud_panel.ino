// T-Minus_6 HUD panel, protocol 2: a general output panel. Arduino UNO Q (MCU side), 3.3 V logic, USB serial 115200 baud.
// FLASH IT ONCE. It knows nothing about the game: the laptop draws every screen and sends text, LED bits, pixel colours,
// tones and OLED drawing commands as lines. Newline-framed, the same scheme as laptop/devio/protocol.py.
//
//   in : I?                      who are you                     -> I,hud,2
//        P,seq,us                ping                            -> Q,seq,us
//        ?                       report state                    -> S,oled,0
//        L,line1|line2           LCD 16x2, 16 characters a row ("L," alone clears)
//        LD,on,blink,ms          LEDs: bit 1 green (D3), 2 red (D5), 4 yellow (A0). "on" bits are lit. The "blink" bits
//                                toggle every ms (ms 0 = no blink)
//        N,r,g,b,ms              ARGB pixel (D4), 0..255 each. ms > 0 blinks it on and off every ms
//        BZ                      one 1200 Hz chirp, 120 ms (does not change a pattern that is playing)
//        BZ,hz,onMs,periodMs     buzzer (D7): hz 0 silent, period 0 one beep, else beep onMs every periodMs
//        OC                      clear the OLED frame
//        OT,x,y,size,text        text at x,y (text is the rest of the line)
//        OR,x,y,w,h,fill         rectangle, fill 1 solid, 0 outline
//        OH,x,y,size,fill        heart, about 4*size wide, fill 1 solid, 0 outline
//        OI,x,y                  the built-in 64x48 rover picture (rover_bmp.h)
//        OP                      push the frame to the OLED (at most 4 times a second)
//
// Safety: no line for 3 s -> LEDs, ARGB and buzzer go off and the LCD shows NO LINK / CHECK USB. The next line recovers.
// Nothing blocks: every output runs on millis() timers, so serial and pings are answered at any time.
//
// Pins: D3 green LED | D5 red LED | A0 yellow LED (each through 220 ohm) | D4 ARGB data through 330 ohm (one pixel, 3V3)
//       D7 passive buzzer | D8 D9 LCD RS E | D10 D11 D12 D13 LCD D4..D7 | SDA SCL OLED SSD1306 0x3C
//       The joystick is not wired to this sketch. Power the OLED and the ARGB pixel from 3V3. No 5 V on any input pin.
// Libraries: LiquidCrystal, Adafruit SSD1306, Adafruit GFX, Adafruit NeoPixel. Compiled for the UNO Q core, not yet flashed.
#include <LiquidCrystal.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_NeoPixel.h>
#include "rover_bmp.h"

const int LED_G = 3, LED_R = 5, LED_Y = A0, ARGB = 4, BUZZER = 7;
const unsigned long LINK_TIMEOUT_MS = 3000;

LiquidCrystal lcd(8, 9, 10, 11, 12, 13);
Adafruit_SSD1306 oled(128, 64, &Wire, -1);
Adafruit_NeoPixel pixel(1, ARGB, NEO_GRB + NEO_KHZ800);
bool oledOk = false;

char rx[65];
uint8_t rxLen = 0;
bool rxOver = false;
unsigned long lastRx = 0;
bool linkSeen = false, linkDown = false;

char lcdRow[2][17] = {"HUD PANEL", "WAITING..."};
uint8_t ledOn = 0, ledBlink = 0;
unsigned long ledMs = 0;
uint8_t pr = 0, pg = 0, pb = 0;
unsigned long pxMs = 0;
long bzHz = 0, bzOn = 0, bzPeriod = 0;
unsigned long bzNext = 0;
bool oledDirty = false;
unsigned long tFast = 0, tLcd = 0, tOled = 0;

// ---- field helpers: field 0 is the letters, field n is the text after the n-th comma
const char *nth(const char *s, int n) {
  for (int i = 0; i < n && s; i++) { s = strchr(s, ','); if (s) s++; }
  return s;
}
long num(const char *s, int n) { const char *p = nth(s, n); return p ? atol(p) : 0; }
uint8_t u8(long v) { return v < 0 ? 0 : (v > 255 ? 255 : (uint8_t)v); }

void setLcd(const char *body) {                  // "line1|line2", each row padded to 16
  for (int r = 0; r < 2; r++) { memset(lcdRow[r], ' ', 16); lcdRow[r][16] = 0; }
  const char *bar = strchr(body, '|');
  int n0 = bar ? (int)(bar - body) : (int)strlen(body);
  for (int i = 0; i < n0 && i < 16; i++) lcdRow[0][i] = body[i];
  if (bar) for (int i = 0; bar[1 + i] && i < 16; i++) lcdRow[1][i] = bar[1 + i];
}

void beep(const char *s) {
  if (s[2] == 0) { tone(BUZZER, 1200, 120); return; }        // "BZ" alone: the chirp
  long hz = num(s, 1), on = num(s, 2), period = num(s, 3);
  if (hz <= 0 || on <= 0) { bzHz = 0; noTone(BUZZER); return; }
  if (period <= 0) { bzHz = 0; tone(BUZZER, hz, on); return; }
  bzHz = hz; bzOn = on; bzPeriod = period; bzNext = millis();
}

void oledCmd(const char *s) {                    // s[0] == 'O'
  if (s[1] == 'C' && s[2] == 0) { oled.clearDisplay(); return; }
  if (s[1] == 'P' && s[2] == 0) { oledDirty = true; return; }
  if (s[2] != ',') return;
  int x = num(s, 1), y = num(s, 2);
  if (s[1] == 'T') {
    const char *t = nth(s, 4);
    oled.setTextSize(max(1L, num(s, 3)));
    oled.setTextColor(SSD1306_WHITE);
    oled.setCursor(x, y);
    oled.print(t ? t : "");
  } else if (s[1] == 'R') {
    int w = num(s, 3), h = num(s, 4);
    if (num(s, 5)) oled.fillRect(x, y, w, h, SSD1306_WHITE);
    else oled.drawRect(x, y, w, h, SSD1306_WHITE);
  } else if (s[1] == 'I') {
    oled.drawBitmap(x, y, ROVER_BMP, 64, 48, SSD1306_WHITE);
  } else if (s[1] == 'H') {
    int r = max(1L, num(s, 3)), cy = y + r;
    if (num(s, 4)) {
      oled.fillCircle(x + r, cy, r, SSD1306_WHITE);
      oled.fillCircle(x + 3 * r, cy, r, SSD1306_WHITE);
      oled.fillTriangle(x, cy, x + 4 * r, cy, x + 2 * r, y + 4 * r, SSD1306_WHITE);
    } else {
      oled.drawCircle(x + r, cy, r, SSD1306_WHITE);
      oled.drawCircle(x + 3 * r, cy, r, SSD1306_WHITE);
      oled.drawTriangle(x, cy, x + 4 * r, cy, x + 2 * r, y + 4 * r, SSD1306_WHITE);
    }
  }
}

void handleLine(char *s) {
  lastRx = millis(); linkSeen = true;
  if (!strcmp(s, "I?")) { Serial.println(F("I,hud,2")); return; }
  if (!strcmp(s, "?")) { Serial.print(F("S,")); Serial.print(oledOk ? 1 : 0); Serial.println(F(",0")); return; }
  if (s[0] == 'P' && s[1] == ',') { Serial.print(F("Q,")); Serial.println(s + 2); return; }
  if (s[0] == 'L' && s[1] == 'D' && s[2] == ',') {
    ledOn = u8(num(s, 1)); ledBlink = u8(num(s, 2)); ledMs = max(0L, num(s, 3));
    return;
  }
  if (s[0] == 'L' && (s[1] == ',' || s[1] == 0)) { setLcd(s[1] == ',' ? s + 2 : ""); return; }
  if (s[0] == 'N' && s[1] == ',') {
    pr = u8(num(s, 1)); pg = u8(num(s, 2)); pb = u8(num(s, 3)); pxMs = max(0L, num(s, 4));
    return;
  }
  if (s[0] == 'B' && s[1] == 'Z') { beep(s); return; }
  if (s[0] == 'O') oledCmd(s);
}

void readSerial() {                              // one byte at a time, never blocks
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') {
      if (!rxOver && rxLen) { rx[rxLen] = 0; handleLine(rx); }
      rxLen = 0; rxOver = false;
    } else if (ch == '\r') {
    } else if (rxLen < 64) rx[rxLen++] = ch;
    else rxOver = true;
  }
}

void checkLink(unsigned long now) {              // silence for 3 s = link down, and every output goes quiet
  bool down = linkSeen ? (now - lastRx >= LINK_TIMEOUT_MS) : (now >= LINK_TIMEOUT_MS);
  if (down == linkDown) return;
  linkDown = down;
  if (down) {
    bzHz = 0; noTone(BUZZER);
    strcpy(lcdRow[0], "NO LINK         "); strcpy(lcdRow[1], "CHECK USB       ");
  }
}

void showLcd() {
  lcd.setCursor(0, 0); lcd.print(lcdRow[0]);
  lcd.setCursor(0, 1); lcd.print(lcdRow[1]);
}

void showLedsAndPixel(unsigned long now) {       // 50 ms rate
  uint8_t lit = ledOn;
  if (ledMs && ((now / ledMs) & 1)) lit ^= ledBlink;
  if (linkDown) lit = 0;
  digitalWrite(LED_G, (lit & 1) ? HIGH : LOW);
  digitalWrite(LED_R, (lit & 2) ? HIGH : LOW);
  digitalWrite(LED_Y, (lit & 4) ? HIGH : LOW);
  uint32_t c = 0;
  if (!linkDown && (pxMs == 0 || ((now / pxMs) & 1) == 0)) c = pixel.Color(pr, pg, pb);
  pixel.setPixelColor(0, c); pixel.show();
}

void showOled(unsigned long now) {               // at most every 250 ms, and only after OP
  if (!oledOk || !oledDirty || now - tOled < 250) return;
  oledDirty = false; tOled = now;
  oled.display();
}

void buzzerTick(unsigned long now) {             // a pattern restarts only when BZ,hz,on,period arrives
  if (bzHz && now >= bzNext) { tone(BUZZER, bzHz, bzOn); bzNext = now + bzPeriod; }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_G, OUTPUT); pinMode(LED_R, OUTPUT); pinMode(LED_Y, OUTPUT);
  lcd.begin(16, 2); showLcd();
  Wire.begin();
  oledOk = oled.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  if (oledOk) { oled.clearDisplay(); oled.display(); }
  pixel.begin(); pixel.show();
  Serial.println(F("HELLO,hud,2"));
}

void loop() {
  readSerial();
  unsigned long now = millis();
  checkLink(now);
  if (now - tFast >= 50) { tFast = now; showLedsAndPixel(now); }
  if (now - tLcd >= 150) { tLcd = now; showLcd(); }
  showOled(now);
  buzzerTick(now);
}
