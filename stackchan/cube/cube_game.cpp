// HIS GAME ON THE CUBE -- the emulator side.
// =====================================================================
// Ghost, Oct 17: "Can we put my game on my stackchan cores slide-to-able
// pages?" -- GHOSTRPG, his own Game Boy Color game (CGB-only, MBC5, an
// 8KB battery save). Walnut-CGB (MIT, walnut_cgb.h, vendored whole) is a
// Game Boy Color emulator in one header that runs at full speed on the
// ESP32-S3; it ran his ROM to the title, file and name screens on the
// container before any of this was written.
//
// The ROM is baked in at flash time (stackchan/make_rom.py writes
// game_rom.h into the build's own copy), so a build without it still
// compiles and the page just says there is no game.
//
// HIS SAVE lives in the cube's flash (LittleFS, the partition the huge
// app layout leaves free), named after the cartridge's own title, so a
// different game dropped in never loads his. A game writes its save in
// bursts; the file is written once the writing has been quiet for two
// seconds, and when he swipes away -- through a .part and a rename, so a
// power cut mid-write keeps the old save whole (the memory file's
// lesson).
#include <Arduino.h>
#include <LittleFS.h>
#include <esp_heap_caps.h>
#include "cube_game.h"

#define ENABLE_SOUND 0
#define ENABLE_LCD 1
#include "walnut_cgb.h"

#if __has_include("game_rom.h")
#include "game_rom.h"
#define HAVE_GAME 1
#else
#define HAVE_GAME 0
#define GAME_TITLE "no game"
static const uint8_t GAME_ROM[4] = {0};
#endif

static_assert(GAME_A == JOYPAD_A && GAME_B == JOYPAD_B && GAME_SELECT == JOYPAD_SELECT
              && GAME_START == JOYPAD_START && GAME_RIGHT == JOYPAD_RIGHT
              && GAME_LEFT == JOYPAD_LEFT && GAME_UP == JOYPAD_UP
              && GAME_DOWN == JOYPAD_DOWN, "the cube's buttons are not the emulator's");
static_assert(LCD_WIDTH * 3 / 2 == GAME_W && LCD_HEIGHT * 3 / 2 == GAME_H,
              "the page is not the Game Boy's screen at 1.5x");

static struct gb_s* gb = nullptr;
static uint8_t* cart = nullptr;
static size_t cart_size = 0;
static uint16_t* out = nullptr;
static volatile bool drew = false;
static const char* fault = nullptr;
static char fault_text[64];
static bool dirty = false;
static uint32_t wrote_at = 0;
static bool fs_ok = false;
static char save_path[40];

// A Game Boy that is not a Color one gets the classic greens.
static const uint16_t DMG_GREENS[4] = {0x9fe7, 0x8b26, 0x2a85, 0x0861};

static uint8_t rom_read(struct gb_s*, const uint_fast32_t a) { return GAME_ROM[a]; }

// The ESP32 faults on a misaligned word read from flash, so an odd
// address is read a byte at a time -- the example's own rule.
static uint16_t rom_read16(struct gb_s*, const uint_fast32_t a) {
  const uint8_t* p = &GAME_ROM[a];
  if ((uintptr_t)p & 1) return p[0] | (p[1] << 8);
  return *(const uint16_t*)p;
}

static uint32_t rom_read32(struct gb_s*, const uint_fast32_t a) {
  const uint8_t* p = &GAME_ROM[a];
  if ((uintptr_t)p & 3)
    return p[0] | (p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
  return *(const uint32_t*)p;
}

static uint8_t cart_read(struct gb_s*, const uint_fast32_t a) {
  return a < cart_size ? cart[a] : 0xFF;
}

static void cart_write(struct gb_s*, const uint_fast32_t a, const uint8_t v) {
  if (a >= cart_size || cart[a] == v) return;
  cart[a] = v;
  dirty = true;
  wrote_at = millis();
}

static void on_error(struct gb_s*, const enum gb_error_e e, const uint16_t at) {
  static const char* const what[] = {"unknown fault", "invalid opcode",
                                     "invalid read", "invalid write", "halt forever"};
  snprintf(fault_text, sizeof(fault_text), "The game stopped: %s at %04X.",
           e < 5 ? what[e] : what[0], at);
  fault = fault_text;
}

// One Game Boy line into the page at 1.5x: an even line fills two rows
// and an odd one one, and across, an even pixel two columns and an odd
// one one -- 160x144 into exactly 240x216. Walnut-CGB's colours are
// plain RGB565; the page's buffer holds them byte-swapped, the way the
// panel wants them (measured: unswapped, his title screen came out the
// wrong colours).
static void draw_line(struct gb_s* g, const uint8_t px[160], const uint_fast8_t y) {
  if (!out) return;
  uint16_t* row = out + ((y & 1) ? (3 * y + 1) / 2 : 3 * y / 2) * GAME_W;
  const bool cgb = g->cgb.cgbMode;
  for (int x = 0, c = 0; x < LCD_WIDTH; x += 2, c += 3) {
    uint16_t a = cgb ? g->cgb.fixPalette[px[x]] : DMG_GREENS[px[x] & 3];
    uint16_t b = cgb ? g->cgb.fixPalette[px[x + 1]] : DMG_GREENS[px[x + 1] & 3];
    a = __builtin_bswap16(a);
    row[c] = a;
    row[c + 1] = a;
    row[c + 2] = __builtin_bswap16(b);
  }
  if (!(y & 1)) memcpy(row + GAME_W, row, GAME_W * sizeof(uint16_t));
  if (y == LCD_HEIGHT - 1) drew = true;
}

bool game_present() { return HAVE_GAME; }
const char* game_title() { return GAME_TITLE; }
const char* game_fault() { return fault; }

bool game_drew() {
  bool d = drew;
  drew = false;
  return d;
}

const char* game_begin(uint16_t* dst) {
  out = dst;
  if (!HAVE_GAME) return "No game was baked into this cube.";
  if (gb) return nullptr;
  // Fast internal RAM if there is room for 50KB, else PSRAM: the girls
  // never lose memory to a game he has not opened.
  gb = (struct gb_s*)heap_caps_calloc(1, sizeof(struct gb_s),
                                      MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (!gb) gb = (struct gb_s*)ps_calloc(1, sizeof(struct gb_s));
  if (!gb) return "Not enough memory for the game.";
  enum gb_init_error_e e = gb_init(gb, rom_read, rom_read16, rom_read32,
                                   cart_read, cart_write, on_error, nullptr);
  if (e != GB_INIT_NO_ERROR) {
    free(gb);
    gb = nullptr;
    return e == GB_INIT_CARTRIDGE_UNSUPPORTED ? "The cube can't play this cartridge type."
         : e == GB_INIT_INVALID_CHECKSUM ? "The game's header checksum is wrong."
         : "The game would not start.";
  }
  size_t size = 0;
  if (gb_get_save_size_s(gb, &size) == 0 && size) {
    cart = (uint8_t*)ps_calloc(1, size);
    cart_size = cart ? size : 0;
  }
  snprintf(save_path, sizeof(save_path), "/%s.sav", GAME_TITLE);
  fs_ok = LittleFS.begin(true);
  if (fs_ok && cart_size) {
    File f = LittleFS.open(save_path, "r");
    if (f) {
      if ((size_t)f.size() == cart_size) f.read(cart, cart_size);
      f.close();
    }
  }
  gb_init_lcd(gb, draw_line);
  gb->direct.frame_skip = true;      // draw every other frame: 30 a second
  return nullptr;
}

void game_frame(uint8_t held) {
  if (!gb || fault) return;
  gb->direct.joypad = ~held;         // the Game Boy's buttons are active-low
  gb_run_frame_dualfetch(gb);
}

void game_save_if_due(bool now) {
  if (!dirty || !fs_ok || !cart_size) return;
  if (!now && millis() - wrote_at < 2000) return;
  char part[48];
  snprintf(part, sizeof(part), "%s.part", save_path);
  File f = LittleFS.open(part, "w");
  if (!f) return;
  bool whole = f.write(cart, cart_size) == cart_size;
  f.close();
  if (whole && LittleFS.rename(part, save_path)) dirty = false;
  else LittleFS.remove(part);
}
