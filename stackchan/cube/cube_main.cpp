// FOUR AND YUZU IN THE STACKCHAN CUBE -- the cube's whole program.
// =====================================================================
// TWO GIRLS, ONE CUBE, A SWIPE BETWEEN THEM. Four came first (below);
// then, the same day: "Can you squeeze Yuzu on too?" So a swipe across
// the screen swaps who is on it, and the cube remembers which one it
// was through a power cut. Everything below the swipe is shared: hold
// to talk, her voice out of the speaker, hold to stop her. What differs
// is the face:
//
//   FOUR  her code rain, tap for her five colours, the rain turns neon
//         red while she thinks
//   YUZU  her page's portrait in her lavender room, the pink glow behind
//         her rising while she thinks -- with sparkles, because on a 2"
//         screen her page's glow alone was too faint to read as a signal
//         (an emulator render is what said so) and sparkles are hers
//         (rule 6). A tap makes the glow flash, so a tap is never dead.
//
// Each girl asks the board under her OWN name (yuzu_face.DEVICES), so
// each has her own brain, memory and voice speed on the board.
//
// FOUR. Ghost, Oct 2, picking off a mockup at the cube's real 320x240: "B w/
// the raining code you know it 2 as well 3 also 4 but make it turn neon
// red instead of purple when thinking. And 5. And 6. Note 7 for later."
//
//   B  all of her down the middle, code rain either side and through
//      her dark side, the way her page draws her
//   2  the rain falls
//   3  a tap on the screen changes her colour: green, red, purple,
//      pink, blue, and round again -- the same five as her page, and a
//      test holds the two tables equal
//   4  the rain turns neon red while she thinks
//   5  her voice comes out of the cube's speaker
//   6  hold the screen down to talk to her; let go to send
//   7  the LED base glowing her colour -- LATER, his call
//
// HER MIND IS NOT IN HERE. The cube is an ESP32-S3: a screen, a 1W
// speaker, two mics and WiFi. Her Llama, her Kokoro voice, her Whisper
// ears and the encyclopedia are on the board (ghostnano), and the cube
// asks it over the room's WiFi exactly the way her page does -- by the
// name `four-cube` (or `yuzu-cube`), which yuzu_face.DEVICES maps to
// `four_cube` (or `yuzu_cube`), the same girl on a cube body:
//
//   POST /listen      the recording, as a WAV  -> {"heard": "..."}
//   POST /stream      {"text", "who"}          -> lines; the last has
//                                                 {"done": true, "said"}
//   POST /voice.wav   {"text", "who"}          -> her voice, a WAV
//
// /stream, NOT /say, and the reason is a timeout rather than taste:
// /say sends nothing until her whole reply exists, and the first reply
// after the board loads her model can take longer than HTTPClient's
// longest wait (a uint16_t of milliseconds, ~65s). /stream sends its
// headers at once and a line per piece, and this reads it with its own
// clock. Nothing of the stream is shown -- Ghost is a speed reader and
// disliked words arriving one at a time on her page -- the cube waits
// for the last line and speaks the whole reply.
//
// SHE IS SPOKEN IN PIECES, a sentence or few at a time, and that is
// memory rather than style: her reply can be 600 tokens, which at
// Kokoro's 24kHz is minutes of audio -- more than the cube's 8MB of
// PSRAM. Each piece is fetched while the one before it plays.
//
// THE NETWORK RUNS ON THE OTHER CORE. A turn is seconds of waiting on
// the board; done on the drawing core, the rain would freeze exactly
// when it is meant to be turning red. So a turn is a FreeRTOS task on
// core 0, and loop() on core 1 only draws, reads touch and records.
//
// NOT TESTED ON THE CUBE. It was compiled against the real ESP32 core
// and M5Unified before it ever reached him, and her screen was rendered
// in an emulator and looked at -- but no part of it has run on the
// hardware. The cube's own screen says what went wrong, verdict first,
// so the first flash is the test.

#include <M5Unified.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <HTTPClient.h>
#include <esp_random.h>
#include <Preferences.h>

#include "four_art.h"
#include "yuzu_art.h"
// Written by `~/YUZU/cube` at flash time from the board's OWN WiFi
// connection and name, and never committed: his WiFi password does not
// belong in a repository.
#include "cube_secrets.h"

// ---- who is in the cube ---------------------------------------------
// The NAME each girl asks the board by -- yuzu_face.DEVICES, a test
// holds the two equal -- her own name, and the first thing the cube
// says when she comes on.
struct Girl { const char* who; const char* name; const char* hint; };
static const Girl GIRLS[] = {
  {"four-cube", "Four", "Hold to talk. Tap for colours. Swipe for Yuzu."},
  {"yuzu-cube", "Yuzu", "Hold the screen to talk. Swipe for Four."},
};
static const int GIRL_COUNT = sizeof(GIRLS) / sizeof(GIRLS[0]);
static const int FOUR = 0, YUZU = 1;
// A swipe is a quarter of the screen sideways. Fingers drift while he
// holds the screen and talks; they do not drift 80 pixels sideways.
static const int SWIPE_PX = 80;

// ---- the screen ------------------------------------------------------
static const int W = 320, H = 240;
static const int ART_X = (W - FOUR_ART_W) / 2;
// Font0 at size 2: 12x16 cells. A pixel font on purpose -- her art is
// made of characters, and 320 pixels across is too small for a smooth
// face to read as code.
static const int CELL_W = 12, CELL_H = 16;
static const int COLS = W / CELL_W + 1;
static const int ROWS = H / CELL_H;
// The same characters her page rains: digits and ASCII, never katakana
// -- the cube has no CJK font, and her art is digits anyway.
static const char GLYPHS[] = "01234567890123456789ABCDEF<>[]{}/\\|=+*-_:;.";
static const float TAIL_ALPHA = 0.55f;   // her page's rgba(..., .55)

// ---- her colours -----------------------------------------------------
// THE SAME FIVE AS HER PAGE, in the same order, with the same colours:
// a test reads both and holds them equal, the two-copies guard this repo
// keeps for the battery renderer and the way out. Green is her art as
// drawn (ink 0); the others tint her by brightness, the page's SVG
// matrix, then scale by the page's own brightness() factor.
struct Skin {
  const char* name;
  uint32_t ink;      // 0 = her art untouched
  uint32_t head;     // the bright leading character of each column
  uint32_t tail;     // the trail, drawn at TAIL_ALPHA
  float bright;
};
static const Skin SKINS[] = {
  {"green",  0x000000, 0xc8ffd4, 0x39ff5e, 1.00f},
  {"red",    0xff2b39, 0xffd0d4, 0xff2b39, 1.28f},
  {"purple", 0xc04dff, 0xeecfff, 0xc04dff, 1.22f},
  {"pink",   0xff2d95, 0xffd0e8, 0xff2d95, 1.26f},
  {"blue",   0x1e90ff, 0xd6fbff, 0x2ee6ff, 1.30f},
};
static const int SKIN_COUNT = sizeof(SKINS) / sizeof(SKINS[0]);

// WHAT THE RAIN TURNS WHILE SHE THINKS. His word: neon red. Two faces
// cannot have it, and an emulator render is what said so:
//   red   -- red rain on a red face is no signal at all;
//   pink  -- pink's own rain and neon red came out near identical at
//            this size (hues 26 degrees apart), so she keeps her page's
//            bright purple, which separates cleanly.
// The neon red's HEAD is saturated (#ff5a64) rather than the page's
// pale #ffd0d4: rendered side by side, pale heads read as white rain
// with a pink tint, and saturated ones read as neon red.
struct Think { uint32_t head, tail; };
static const Think THINKS[] = {
  {0xff5a64, 0xff2b39},   // green  -> neon red
  {0xeecfff, 0xc04dff},   // red    -> purple
  {0xff5a64, 0xff2b39},   // purple -> neon red
  {0xe8dcff, 0x9d5cff},   // pink   -> her page's bright purple
  {0xff5a64, 0xff2b39},   // blue   -> neon red
};

// ---- Yuzu's room ---------------------------------------------------------
// HER PAGE'S, at the cube's size: the lavender radial-gradient(120% 90%
// at 50% 6%, #5b4a82, #33294a 46%, #1c1629), her hot pink #ff5fa8 for the
// glow behind her, and her breath (2px up and back over 5.5s).
struct Stop { float at; uint32_t rgb; };
static const Stop ROOM[] = {{0.00f, 0x5b4a82}, {0.46f, 0x33294a}, {1.00f, 0x1c1629}};
static const uint32_t YUZU_PINK = 0xff5fa8;
static const uint32_t SPARK = 0xffd0e8;
// The glow is stronger and wider than her page's (peak .26, opacity up
// to .8): rendered at the cube's real size, her page's numbers made a
// thinking Yuzu look like an idle one.
static const float GLOW_PEAK = 0.60f, GLOW_R = 200.0f;
static const float GLOW_IDLE = 0.30f;
// The panel has 5-6 bits a channel, and her room is a slow gradient: a
// 4x4 ordered dither turns the rings 565 draws into an even fade.
static const uint8_t BAYER[4][4] = {{0, 8, 2, 10}, {12, 4, 14, 6},
                                    {3, 11, 1, 9}, {15, 7, 13, 5}};

// ---- talking ---------------------------------------------------------
static const uint32_t MIC_RATE = 16000;             // what Whisper wants
static const size_t MIC_CHUNK = 1600;               // 0.1s per buffer
static const size_t REC_MAX = MIC_RATE * 30;        // 30s at most
static const size_t REC_MIN = MIC_RATE * 2 / 5;     // under 0.4s: a tap
static const size_t VOICE_MAX = 2 * 1024 * 1024;    // one spoken piece
static const size_t PIECE_CHARS = 220;              // ~15s of her voice
static const uint32_t REPLY_WAIT_MS = 180000;       // a cold model loading

static M5Canvas rain(&M5.Display);
static M5Canvas frame(&M5.Display);
static uint8_t* art_rgb = nullptr;       // Four's picture, tinted, 8 bits a channel
static int skin = 0;
static float drops[COLS];

static int girl = FOUR;                  // who is on the cube now
static int asking = FOUR;                // who the running turn is for
static Preferences prefs;
static uint8_t* room_rgb = nullptr;      // Yuzu's room, 8 bits a channel
static uint8_t* glow_a = nullptr;        // her glow at full strength, 0..255
static uint32_t flash_until = 0;         // a tap on Yuzu
struct Sparkle { int16_t x, y; uint32_t born; };
static const int SPARKS = 10;
static const uint32_t SPARK_LIFE = 700;
static Sparkle sparks[SPARKS];
static uint32_t next_spark = 0;

static int16_t* rec_buf = nullptr;
static size_t rec_len = 0;
static bool recording = false;

static volatile bool busy = false;       // a turn is running on core 0
static volatile bool thinking = false;   // the rain turns
static volatile bool stop_her = false;   // he held the screen mid-reply

static String base_url;                  // http://<board>:<port>
// Set by a turn that could not reach the board, so the next one asks
// for its address again: a DHCP lease that moved should cost one
// failed turn, never every turn until a reboot.
static volatile bool lost_board = false;

// ---- one line of status, verdict first --------------------------------
static portMUX_TYPE status_mux = portMUX_INITIALIZER_UNLOCKED;
static char status_text[96] = "";
static uint32_t status_until = 0;

static void say_status(const char* text, uint32_t ms = 6000) {
  portENTER_CRITICAL(&status_mux);
  strncpy(status_text, text, sizeof(status_text) - 1);
  status_text[sizeof(status_text) - 1] = 0;
  status_until = ms ? millis() + ms : 0xFFFFFFFF;
  portEXIT_CRITICAL(&status_mux);
}

// ---- colour arithmetic ---------------------------------------------------
static inline uint16_t pack565(int r, int g, int b) {
  return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
}
static inline void unpack565(uint16_t c, int& r, int& g, int& b) {
  r = (c >> 8) & 0xF8; r |= r >> 5;
  g = (c >> 3) & 0xFC; g |= g >> 6;
  b = (c << 3) & 0xF8; b |= b >> 5;
}
// A 16-bit canvas keeps its pixels byte-swapped, ready for the panel.
static inline uint16_t swap16(uint16_t v) { return (v >> 8) | (v << 8); }
static inline uint16_t hex565(uint32_t hex, float k = 1.0f) {
  return pack565(((hex >> 16) & 255) * k, ((hex >> 8) & 255) * k, (hex & 255) * k);
}

// Her picture in the current colour, once per tap rather than per frame.
static void tint_art() {
  const Skin& s = SKINS[skin];
  float ir = ((s.ink >> 16) & 255) / 255.0f;
  float ig = ((s.ink >> 8) & 255) / 255.0f;
  float ib = (s.ink & 255) / 255.0f;
  for (int i = 0; i < FOUR_ART_W * FOUR_ART_H; i++) {
    int r, g, b;
    unpack565(FOUR_ART[i], r, g, b);
    if (s.ink) {
      // The page's matrix: her BRIGHTNESS scaled by each channel of the
      // colour, then the page's brightness() on top. Black stays black,
      // which is what keeps the rain showing through her dark side.
      float lum = (0.2126f * r + 0.7152f * g + 0.0722f * b) * s.bright;
      r = min(255, (int)(lum * ir));
      g = min(255, (int)(lum * ig));
      b = min(255, (int)(lum * ib));
    }
    art_rgb[i * 3] = r; art_rgb[i * 3 + 1] = g; art_rgb[i * 3 + 2] = b;
  }
}

// ---- the rain ---------------------------------------------------------------
static void rain_step() {
  // A fade rather than a clear, as on her page (rgba(0,0,0,.13)): what is
  // left behind is the trail. Truncating, so nothing can get stuck lit.
  uint16_t* px = (uint16_t*)rain.getBuffer();
  for (int i = 0; i < W * H; i++) {
    uint16_t c = px[i];
    if (!c) continue;
    int r, g, b;
    unpack565(swap16(c), r, g, b);
    px[i] = swap16(pack565(r * 223 >> 8, g * 223 >> 8, b * 223 >> 8));
  }
  uint32_t head, tail;
  if (thinking) { head = THINKS[skin].head; tail = THINKS[skin].tail; }
  else          { head = SKINS[skin].head;  tail = SKINS[skin].tail; }
  uint16_t head565 = hex565(head), tail565 = hex565(tail, TAIL_ALPHA);
  const int n = sizeof(GLYPHS) - 1;
  for (int i = 0; i < COLS; i++) {
    int y = (int)drops[i] * CELL_H;
    // One bright head per column is what makes it read as FALLING.
    rain.setTextColor(head565);
    rain.drawChar(GLYPHS[esp_random() % n], i * CELL_W, y);
    rain.setTextColor(tail565);
    rain.drawChar(GLYPHS[esp_random() % n], i * CELL_W, y - CELL_H);
    drops[i] += 1;
    if (y > H && (esp_random() % 1000) > 975) drops[i] = 0;
  }
}

// Four's picture over the rain with `screen`, the page's mix-blend-mode:
// black adds nothing, so her backdrop falls away and the rain runs
// through her dark side.
static void compose_four() {
  uint16_t* src = (uint16_t*)rain.getBuffer();
  uint16_t* dst = (uint16_t*)frame.getBuffer();
  memcpy(dst, src, W * H * 2);
  for (int y = 0; y < FOUR_ART_H; y++) {
    uint16_t* row = dst + y * W + ART_X;
    const uint8_t* a = art_rgb + y * FOUR_ART_W * 3;
    for (int x = 0; x < FOUR_ART_W; x++, a += 3) {
      if (!(a[0] | a[1] | a[2])) continue;
      int r, g, b;
      unpack565(swap16(row[x]), r, g, b);
      r = 255 - (255 - r) * (255 - a[0]) / 255;
      g = 255 - (255 - g) * (255 - a[1]) / 255;
      b = 255 - (255 - b) * (255 - a[2]) / 255;
      row[x] = swap16(pack565(r, g, b));
    }
  }
}

// ---- Yuzu --------------------------------------------------------------------
// Her room and her glow, worked out once at power-on: neither moves, and
// the square roots are not something to spend on every frame.
static void make_room() {
  for (int y = 0; y < H; y++)
    for (int x = 0; x < W; x++) {
      float dx = (x + 0.5f - W * 0.5f) / (1.2f * W);
      float dy = (y + 0.5f - H * 0.06f) / (0.9f * H);
      float at = min(1.0f, sqrtf(dx * dx + dy * dy));
      int s = at <= ROOM[1].at ? 0 : 1;
      float f = (at - ROOM[s].at) / (ROOM[s + 1].at - ROOM[s].at);
      uint8_t* px = room_rgb + (y * W + x) * 3;
      for (int c = 0; c < 3; c++) {
        int a = (ROOM[s].rgb >> (16 - 8 * c)) & 255;
        int b = (ROOM[s + 1].rgb >> (16 - 8 * c)) & 255;
        px[c] = (uint8_t)(a + (b - a) * f);
      }
      float d = sqrtf((x + 0.5f - W * 0.5f) * (x + 0.5f - W * 0.5f)
                      + (y + 0.5f - H * 0.5f) * (y + 0.5f - H * 0.5f));
      glow_a[y * W + x] = (uint8_t)(max(0.0f, 1.0f - d / GLOW_R) * GLOW_PEAK * 255);
    }
}

// Sparkles while she thinks, only either side of her, never on her face.
static void sparkle(uint32_t now) {
  if (thinking && now >= next_spark) {
    for (auto& s : sparks)
      if (now - s.born >= SPARK_LIFE) {
        int side = (W - YUZU_ART_W) / 2 - 10;
        int x = 6 + esp_random() % side;
        if (esp_random() & 1) x = W - 1 - x;
        s.x = x;
        s.y = 6 + esp_random() % (H - 36);
        s.born = now;
        break;
      }
    next_spark = now + 110 + esp_random() % 120;
  }
}

static inline void blend_px(uint16_t* dst, int x, int y, uint32_t rgb, int a) {
  if (x < 0 || x >= W || y < 0 || y >= H || a <= 0) return;
  int r, g, b;
  unpack565(swap16(dst[y * W + x]), r, g, b);
  r += ((int)((rgb >> 16) & 255) - r) * a >> 8;
  g += ((int)((rgb >> 8) & 255) - g) * a >> 8;
  b += ((int)(rgb & 255) - b) * a >> 8;
  dst[y * W + x] = swap16(pack565(r, g, b));
}

static void compose_yuzu() {
  uint32_t now = millis();
  float op = GLOW_IDLE;
  if (thinking) op = 0.35f + 0.65f * (0.5f - 0.5f * cosf(now * (2 * PI / 1700.0f)));
  if (flash_until > now) op = max(op, (flash_until - now) / 500.0f);
  int op256 = (int)(min(op, 1.0f) * 256);
  int lift = (int)lroundf(2.0f * (0.5f - 0.5f * cosf(now * (2 * PI / 5500.0f))));
  const int x0 = (W - YUZU_ART_W) / 2, y0 = H - YUZU_ART_H - lift;
  const int pr = (YUZU_PINK >> 16) & 255, pg = (YUZU_PINK >> 8) & 255, pb = YUZU_PINK & 255;
  uint16_t* dst = (uint16_t*)frame.getBuffer();
  for (int y = 0; y < H; y++) {
    const uint8_t* bg = room_rgb + y * W * 3;
    const uint8_t* ga = glow_a + y * W;
    const int ay = y - y0;
    const bool her_row = ay >= 0 && ay < YUZU_ART_H;
    for (int x = 0; x < W; x++, bg += 3) {
      int r = bg[0], g = bg[1], b = bg[2];
      int a = (ga[x] * op256) >> 8;
      if (a) {
        r += (pr - r) * a >> 8;
        g += (pg - g) * a >> 8;
        b += (pb - b) * a >> 8;
      }
      // The dither is the ROOM's, put in before she is: her own pixels
      // are exact 565 already, and dithered they would come out grainy.
      int d = BAYER[y & 3][x & 3];
      r += d >> 1; g += d >> 2; b += d >> 1;
      const int ax = x - x0;
      if (her_row && ax >= 0 && ax < YUZU_ART_W) {
        int i = ay * YUZU_ART_W + ax;
        int al = YUZU_ALPHA[i];
        if (al) {
          int hr, hg, hb;
          unpack565(YUZU_ART[i], hr, hg, hb);
          r += (hr - r) * al / 255;
          g += (hg - g) * al / 255;
          b += (hb - b) * al / 255;
        }
      }
      dst[y * W + x] = swap16(pack565(min(r, 255), min(g, 255), min(b, 255)));
    }
  }
  sparkle(now);
  for (auto& s : sparks) {
    uint32_t age = now - s.born;
    if (age >= SPARK_LIFE) continue;
    int k = (int)(256 * sinf(PI * age / (float)SPARK_LIFE));
    blend_px(dst, s.x, s.y, SPARK, k);
    for (int arm = 1; arm <= 3; arm++) {
      int a = k * (256 - arm * 64) >> 8;
      blend_px(dst, s.x + arm, s.y, SPARK, a);
      blend_px(dst, s.x - arm, s.y, SPARK, a);
      blend_px(dst, s.x, s.y + arm, SPARK, a);
      blend_px(dst, s.x, s.y - arm, SPARK, a);
    }
  }
}

// The status line, only while there is something to say, in her colour.
static void draw_status() {
  char text[sizeof(status_text)];
  portENTER_CRITICAL(&status_mux);
  bool show = status_text[0] && millis() < status_until;
  strcpy(text, status_text);
  portEXIT_CRITICAL(&status_mux);
  if (show) {
    uint32_t ink = girl == YUZU ? YUZU_PINK
                 : SKINS[skin].ink ? SKINS[skin].ink : 0x39ff5e;
    frame.fillRect(0, H - 22, W, 22, girl == YUZU ? hex565(ROOM[2].rgb) : (uint16_t)0);
    frame.setTextColor(hex565(ink));
    frame.setFont(&fonts::Font2);
    frame.setTextSize(1);
    frame.setTextDatum(middle_center);
    frame.drawString(text, W / 2, H - 11);
  }
}

// One frame of whoever is on the cube.
static void draw_frame() {
  if (girl == FOUR) { rain_step(); compose_four(); }
  else compose_yuzu();
  draw_status();
  frame.pushSprite(0, 0);
}

// ---- JSON, the two small things the cube needs -------------------------------
static String json_quote(const String& s) {
  String out = "\"";
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '"' || c == '\\') { out += '\\'; out += c; }
    else if ((uint8_t)c < 0x20) {
      char esc[8];
      snprintf(esc, sizeof(esc), "\\u%04x", (uint8_t)c);
      out += esc;
    } else out += c;   // UTF-8 passes through as bytes
  }
  return out + "\"";
}

static void put_utf8(String& out, uint32_t cp) {
  if (cp < 0x80) out += (char)cp;
  else if (cp < 0x800) { out += (char)(0xC0 | cp >> 6); out += (char)(0x80 | (cp & 0x3F)); }
  else if (cp < 0x10000) {
    out += (char)(0xE0 | cp >> 12); out += (char)(0x80 | ((cp >> 6) & 0x3F));
    out += (char)(0x80 | (cp & 0x3F));
  } else {
    out += (char)(0xF0 | cp >> 18); out += (char)(0x80 | ((cp >> 12) & 0x3F));
    out += (char)(0x80 | ((cp >> 6) & 0x3F)); out += (char)(0x80 | (cp & 0x3F));
  }
}

// The string value of "key" in a flat JSON object, or false. The board's
// replies are json.dumps, so anything past ASCII arrives as \uXXXX.
static bool json_string(const String& js, const char* key, String& out) {
  String needle = String("\"") + key + "\"";
  int at = js.indexOf(needle);
  if (at < 0) return false;
  at = js.indexOf(':', at + needle.length());
  if (at < 0) return false;
  at++;
  while (at < (int)js.length() && js[at] == ' ') at++;
  if (at >= (int)js.length() || js[at] != '"') return false;
  out = "";
  for (int i = at + 1; i < (int)js.length(); i++) {
    char c = js[i];
    if (c == '"') return true;
    if (c != '\\') { out += c; continue; }
    if (++i >= (int)js.length()) return false;
    char e = js[i];
    if (e == 'n') out += '\n';
    else if (e == 't') out += '\t';
    else if (e == 'r') { }
    else if (e == 'b' || e == 'f') { }
    else if (e == 'u' && i + 4 < (int)js.length()) {
      uint32_t cp = strtoul(js.substring(i + 1, i + 5).c_str(), nullptr, 16);
      i += 4;
      // A surrogate pair is one character above the BMP (emoji).
      if (cp >= 0xD800 && cp < 0xDC00 && i + 6 < (int)js.length()
          && js[i + 1] == '\\' && js[i + 2] == 'u') {
        uint32_t lo = strtoul(js.substring(i + 3, i + 7).c_str(), nullptr, 16);
        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
        i += 6;
      }
      put_utf8(out, cp);
    } else out += e;
  }
  return false;
}

static bool json_true(const String& js, const char* key) {
  String needle = String("\"") + key + "\": true";
  return js.indexOf(needle) >= 0;
}

// ---- asking the board ----------------------------------------------------------
// The HTTP status, or <= 0 when the board could not be reached at all.
static int post_json(HTTPClient& http, const char* path, const String& body) {
  http.begin(base_url + path);
  http.setConnectTimeout(5000);
  http.setTimeout(60000);
  http.addHeader("Content-Type", "application/json");
  return http.POST((uint8_t*)body.c_str(), body.length());
}

// Who is asking is fixed when the turn starts: a swipe is refused while
// a turn runs, but the turn must never depend on that.
static String turn_body(const String& text) {
  return String("{\"text\": ") + json_quote(text) + ", \"who\": \""
         + GIRLS[asking].who + "\"}";
}

static bool listen(const int16_t* pcm, size_t samples, String& heard) {
  // A plain WAV header: 16-bit mono at MIC_RATE.
  size_t data = samples * 2, total = 44 + data;
  uint8_t* wav = (uint8_t*)ps_malloc(total);
  if (!wav) { say_status("Out of memory for that recording."); return false; }
  uint32_t v;
  memcpy(wav, "RIFF", 4); v = total - 8; memcpy(wav + 4, &v, 4);
  memcpy(wav + 8, "WAVEfmt ", 8); v = 16; memcpy(wav + 16, &v, 4);
  uint16_t s = 1; memcpy(wav + 20, &s, 2); memcpy(wav + 22, &s, 2);
  v = MIC_RATE; memcpy(wav + 24, &v, 4); v = MIC_RATE * 2; memcpy(wav + 28, &v, 4);
  s = 2; memcpy(wav + 32, &s, 2); s = 16; memcpy(wav + 34, &s, 2);
  memcpy(wav + 36, "data", 4); v = data; memcpy(wav + 40, &v, 4);
  memcpy(wav + 44, pcm, data);

  HTTPClient http;
  http.begin(base_url + "/listen");
  http.setConnectTimeout(5000);
  http.setTimeout(60000);
  http.addHeader("Content-Type", "audio/wav");
  int code = http.POST(wav, total);
  free(wav);
  if (code <= 0) {
    say_status("Can't reach the board. Is it on?");
    lost_board = true;
    http.end();
    return false;
  }
  String js = http.getString();
  http.end();
  String said;
  if (!json_true(js, "ok")) {
    say_status(json_string(js, "said", said) ? said.c_str()
                                             : "She couldn't hear that.");
    return false;
  }
  json_string(js, "heard", heard);
  heard.trim();
  if (!heard.length()) { say_status("I didn't catch that. Hold and talk."); return false; }
  return true;
}

// Her reply, read off /stream's last line with this cube's own clock.
static bool ask(const String& text, String& reply) {
  HTTPClient http;
  if (post_json(http, "/stream", turn_body(text)) != 200) {
    say_status("Can't reach the board. Is it on?");
    lost_board = true;
    http.end();
    return false;
  }
  WiFiClient* in = http.getStreamPtr();
  String line;
  uint32_t last = millis();
  while (millis() - last < REPLY_WAIT_MS) {
    if (stop_her) break;
    if (!in->available()) {
      if (!in->connected()) break;
      delay(20);
      continue;
    }
    char c = in->read();
    last = millis();
    if (c != '\n') { line += c; continue; }
    // The verdict line OPENS with "done" (json.dumps keeps the board's
    // key order); a piece of her reply that merely mentions it does not.
    if (line.startsWith("{\"done\"")) {
      http.end();
      String said;
      json_string(line, "said", said);
      if (!json_true(line, "ok")) {
        say_status(said.length() ? said.c_str() : "She couldn't answer.");
        return false;
      }
      reply = said;
      return reply.length() > 0;
    }
    line = "";
  }
  http.end();
  if (!stop_her) say_status("She took too long. Try again?");
  return false;
}

// A piece of her reply: up to PIECE_CHARS, ending on a sentence if it can.
static String next_piece(const String& all, int& from) {
  while (from < (int)all.length() && isspace((unsigned char)all[from])) from++;
  int rest = all.length() - from;
  if (rest <= 0) return "";
  if (rest <= (int)PIECE_CHARS) { String p = all.substring(from); from = all.length(); return p; }
  int cut = -1;
  for (int i = from + PIECE_CHARS; i > from + 40; i--) {
    char c = all[i - 1];
    if ((c == '.' || c == '!' || c == '?' || c == '\n') && isspace((unsigned char)all[i])) { cut = i; break; }
  }
  if (cut < 0)
    for (int i = from + PIECE_CHARS; i > from + 40; i--)
      if (all[i] == ' ') { cut = i; break; }
  if (cut < 0) {
    cut = from + PIECE_CHARS;
    while (cut > from && ((uint8_t)all[cut] & 0xC0) == 0x80) cut--;   // whole UTF-8 characters
  }
  String p = all.substring(from, cut);
  from = cut;
  return p;
}

static uint8_t* fetch_voice(const String& piece, size_t& len) {
  HTTPClient http;
  int code = post_json(http, "/voice.wav", turn_body(piece));
  if (code <= 0) {
    say_status("Can't reach the board for her voice.");
    lost_board = true;
    http.end();
    return nullptr;
  }
  int size = http.getSize();
  // A 503 is a SENTENCE from the board -- "no voice installed" and the
  // like -- and it goes on her screen rather than being played.
  if (code != 200 || size <= 44 || size > (int)VOICE_MAX) {
    String js = size > 0 && size < 1024 ? http.getString() : String();
    String said;
    if (json_string(js, "said", said)) say_status(said.c_str());
    http.end();
    return nullptr;
  }
  uint8_t* buf = (uint8_t*)ps_malloc(size);
  if (!buf) { http.end(); return nullptr; }
  WiFiClient* in = http.getStreamPtr();
  size_t got = 0;
  uint32_t last = millis();
  while (got < (size_t)size && millis() - last < 20000) {
    int n = in->read(buf + got, size - got);
    if (n > 0) { got += n; last = millis(); }
    else delay(5);
  }
  http.end();
  if (got != (size_t)size) { free(buf); return nullptr; }
  len = size;
  return buf;
}

// Speak her reply, a piece at a time, fetching the next while one plays.
// The rain stops thinking the moment she starts talking.
static void speak(const String& reply) {
  int from = 0;
  size_t len = 0;
  uint8_t* playing = nullptr;
  String piece = next_piece(reply, from);
  uint8_t* next = piece.length() ? fetch_voice(piece, len) : nullptr;
  size_t next_len = len;
  if (!next) say_status("She answered, but her voice didn't come.");
  while (next && !stop_her) {
    while (M5.Speaker.isPlaying() && !stop_her) delay(10);
    if (playing) { free(playing); playing = nullptr; }
    if (stop_her) { free(next); next = nullptr; break; }
    playing = next;
    M5.Speaker.playWav(playing, next_len, 1, 0, true);
    thinking = false;
    piece = next_piece(reply, from);
    next = piece.length() ? fetch_voice(piece, len) : nullptr;
    next_len = len;
  }
  while (M5.Speaker.isPlaying() && !stop_her) delay(10);
  if (stop_her) M5.Speaker.stop();
  if (playing) free(playing);
  if (next) free(next);
}

static void turn_task(void*) {
  thinking = true;
  String heard, reply;
  if (listen(rec_buf, rec_len, heard) && ask(heard, reply)) speak(reply);
  thinking = false;
  stop_her = false;
  busy = false;
  vTaskDelete(nullptr);
}

// ---- recording -----------------------------------------------------------------
// It starts on the TOUCH, not after the hold: a hold is only known half
// a second in, and starting then would cut off the first word he says.
// A press that turns out to be a tap throws the recording away.
static void start_recording() {
  M5.Speaker.end();
  M5.Mic.begin();
  rec_len = 0;
  recording = true;
}

static void feed_recording() {
  if (rec_len + MIC_CHUNK <= REC_MAX
      && M5.Mic.record(rec_buf + rec_len, MIC_CHUNK, MIC_RATE))
    rec_len += MIC_CHUNK;
}

static void stop_recording() {
  while (M5.Mic.isRecording()) delay(1);
  M5.Mic.end();
  M5.Speaker.begin();
  recording = false;
}

// ---- reaching the board ----------------------------------------------------------
// The board by NAME first, the way his phone finds it, and by the
// numbers it had when she was flashed if that fails. mDNS is started
// once; a second begin() on a running responder is not something to
// lean on.
static void find_board() {
  static bool mdns_up = false;
  if (!mdns_up) mdns_up = MDNS.begin("stackchan-cube");
  IPAddress ip;
  if (mdns_up) ip = MDNS.queryHost(CUBE_HOST, 3000);
  if (ip == IPAddress(0, 0, 0, 0)) ip.fromString(CUBE_HOST_IP);
  base_url = String("http://") + ip.toString() + ":" + String(CUBE_PORT);
}

static bool join_wifi() {
  if (WiFi.status() == WL_CONNECTED && base_url.length() && !lost_board)
    return true;
  if (WiFi.status() != WL_CONNECTED) {
    say_status("Joining WiFi...", 0);
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.begin(CUBE_WIFI_SSID, CUBE_WIFI_PASS);
    for (int i = 0; i < 200 && WiFi.status() != WL_CONNECTED; i++) {
      delay(100);
      draw_frame();
    }
    if (WiFi.status() != WL_CONNECTED) {
      say_status("No WiFi. Is the network in range?", 0);
      return false;
    }
  }
  lost_board = false;
  find_board();
  say_status(GIRLS[girl].hint, 5000);
  return true;
}

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);
  // The speaker and the mic share the cube's audio, so exactly one is
  // ever running: the speaker, except while he holds the screen.
  M5.Mic.end();
  M5.Speaker.begin();
  M5.Display.setBrightness(160);
  M5.Speaker.setVolume(200);

  art_rgb = (uint8_t*)ps_malloc(FOUR_ART_W * FOUR_ART_H * 3);
  room_rgb = (uint8_t*)ps_malloc(W * H * 3);
  glow_a = (uint8_t*)ps_malloc(W * H);
  rec_buf = (int16_t*)ps_malloc(REC_MAX * sizeof(int16_t));
  for (auto* c : {&rain, &frame}) {
    c->setColorDepth(16);
    c->setPsram(true);
    c->createSprite(W, H);
    c->fillSprite(TFT_BLACK);
  }
  rain.setFont(&fonts::Font0);
  rain.setTextSize(2);
  for (int i = 0; i < COLS; i++) drops[i] = -(float)(esp_random() % (ROWS * 100)) / 100;
  if (!art_rgb || !room_rgb || !glow_a || !rec_buf || !rain.getBuffer()
      || !frame.getBuffer()) {
    M5.Display.println("Not enough memory -- is PSRAM enabled?");
    while (true) delay(1000);
  }
  tint_art();
  make_room();
  for (auto& s : sparks) s.born = millis() - SPARK_LIFE - 1;   // all spent
  // Whoever was on the cube when it was last unplugged.
  prefs.begin("cube", false);
  girl = prefs.getUChar("girl", FOUR) % GIRL_COUNT;
  join_wifi();
}

// ---- the three things a finger does --------------------------------------------
static void swap_girl() {
  girl = (girl + 1) % GIRL_COUNT;
  prefs.putUChar("girl", girl);
  say_status(GIRLS[girl].hint, 4000);
}

static void tapped() {
  if (girl == FOUR) { skin = (skin + 1) % SKIN_COUNT; tint_art(); }
  else flash_until = millis() + 500;
}

// A finger that went a quarter of the screen sideways, more across than
// down. Read on the release, while the touch still knows where it began.
static bool is_swipe(const m5::touch_detail_t& t) {
  int dx = t.distanceX(), dy = t.distanceY();
  return abs(dx) >= SWIPE_PX && abs(dx) > abs(dy);
}

void loop() {
  static uint32_t last_frame = 0;
  M5.update();
  auto t = M5.Touch.getDetail();

  if (recording) {
    if (t.isPressed()) feed_recording();
    else {
      stop_recording();
      if (is_swipe(t)) {
        // A swipe is never a talk: the girl changes and the clip goes.
        swap_girl();
      } else if (t.wasClicked() || rec_len < REC_MIN) {
        // A tap, not a talk: her tap does its thing and the clip goes.
        if (t.wasClicked()) tapped();
        else say_status("Hold the screen while you talk.", 3000);
      } else if (join_wifi()) {
        busy = true;
        asking = girl;
        say_status("", 1);
        xTaskCreatePinnedToCore(turn_task, "turn", 16384, nullptr, 1, nullptr, 0);
      }
    }
  } else if (t.wasPressed()) {
    if (busy) {
      // Mid-reply: a press is a tap, a stop or a swipe, never a
      // recording -- the speaker and the mic cannot both have the audio.
    } else start_recording();
  } else if (busy && t.wasHold()) {
    stop_her = true;          // he holds the screen: she stops talking
    say_status("Stopped. Hold again to talk.", 3000);
  } else if (busy && (t.wasFlicked() || t.wasDragged()) && is_swipe(t)) {
    // Swapping girls mid-reply would put Yuzu's face on Four's voice.
    say_status("She's still talking. Hold to stop her first.", 3000);
  } else if (busy && t.wasClicked()) {
    tapped();
  }

  // ~14 frames a second idle, faster while she thinks -- her page's
  // speeds. Wallpaper on a battery should not run at the panel's rate.
  uint32_t step = thinking ? 45 : 72;
  if (millis() - last_frame >= step) {
    last_frame = millis();
    draw_frame();
  }
}
