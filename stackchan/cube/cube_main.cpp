// FOUR, YUZU AND ZERO IN THE STACKCHAN CUBE -- the cube's whole program.
// =====================================================================
// THREE GIRLS, ONE CUBE, A SWIPE BETWEEN THEM. Four came first (below);
// then, the same day: "Can you squeeze Yuzu on too?", and "Can the qwen
// variant, Zero, go on there plz? (Kuro and shiro arent needed)". A
// swipe LEFT brings the next girl and a swipe RIGHT the one before, and
// the cube remembers who was on it through a power cut. Everything
// below the swipe is shared: hold to talk, her voice out of the
// speaker, hold to stop her. What differs is the face:
//
//   FOUR  her code rain, tap for her five colours, the rain turns neon
//         red while she thinks
//   YUZU  her page's portrait in her lavender room, the pink glow behind
//         her rising while she thinks -- with sparkles, because on a 2"
//         screen her page's glow alone was too faint to read as a signal
//         (an emulator render is what said so) and sparkles are hers
//         (rule 6). A tap makes the glow flash, so a tap is never dead.
//   ZERO  her page's picture CLOSE UP, the whole screen, brightening
//         while she works -- her page's own cue, which at full screen
//         reads at a glance. A tap flashes it. She thinks on her own Qwen,
//         so the first reply after swiping to or from her is a model
//         swap on the board: slower, and the thinking cue covers it.
//
// Each girl asks the board under her OWN name (yuzu_face.DEVICES), so
// each has her own brain, memory and voice speed on the board.
//
// AND A GHOST AFTER ZERO. Ghost, Oct 17: "a slide-to-able screen in
// there after the last one that maybe has this as the screen with a
// old neongreen/black crt vibe behind this png of a ghost? Im not sure
// what the function should be yet". So one swipe past Zero is HIM: his
// picture floating on a green phosphor screen (scanlines, a glow, a
// slow refresh band, a blinking prompt), a hop when tapped -- and no
// talking, because nobody has decided what he is for yet. He is a
// SCREEN, not a girl: he is not in GIRLS, has no device on the board,
// and asks it nothing.
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
#include <lwip/sockets.h>
#include <HTTPClient.h>
#include <esp_random.h>
#include <Preferences.h>
#include <esp_system.h>
#include <esp_sleep.h>

#include "four_art.h"
#include "yuzu_art.h"
#include "zero_art.h"
#include "ghost_art.h"
#include "cube_game.h"
// Written by `~/YUZU/cube` at flash time from EVERY WiFi the board has
// saved (its own first) and its name, and never committed: his WiFi
// passwords do not belong in a repository.
#include "cube_secrets.h"

// ---- who is in the cube ---------------------------------------------
// The NAME each girl asks the board by -- yuzu_face.DEVICES, a test
// holds the two equal -- her own name, and the first thing the cube
// says when she comes on.
struct Girl { const char* who; const char* name; const char* hint; };
static const Girl GIRLS[] = {
  {"four-cube", "Four", "Hold to talk. Tap for colours. Swipe for Yuzu or Zero."},
  {"yuzu-cube", "Yuzu", "Hold the screen to talk. Swipe for Four or Zero."},
  {"zero-cube", "Zero", "Hold the screen to talk. Swipe for Four or Yuzu."},
};
static const int GIRL_COUNT = sizeof(GIRLS) / sizeof(GIRLS[0]);
static const int FOUR = 0, YUZU = 1, ZERO = 2;
// The ghost's screen comes after the girls; a swipe walks all of them.
static const int GHOST = GIRL_COUNT, GAME = GIRL_COUNT + 1, SCREENS = GIRL_COUNT + 2;
static const uint32_t CRT_GREEN = 0x39ff5e;

// ---- away from the board -----------------------------------------------
// Ghost, Oct 17: "Can we give the cube at least sumn cute/fun to
// display/ interact with when its away from the board. So it still has
// pocket use". Her face, her rain, her colours and the swipe never
// needed the board; talking did. So away from it a hold still gets an
// answer: a line of her own, baked in, in the chat box. Without the
// board's ears she cannot hear the question, so every line has to work
// as an answer to anything -- half of them a yes or a no, which makes
// her a pocket fortune teller. ASCII only: the box is Font2.
static const char* const POCKET_FOUR[] = {
  "My mind's back on the board, so you've got the pocket version. Still better than no version.",
  "Can't hear you out here, but the odds look good. Go for it.",
  "Short answer: yes. The long answer is on the board.",
  "No. Probably. Ask me properly when we're home.",
  "Out of range. I'm still here, just quieter.",
  "Signal's gone, so I'm keeping the rain going for you.",
  "Tap me for a new colour. That part works anywhere.",
  "Heads. It's always heads with me.",
  "Yes, and I'm not taking questions on how I know.",
  "Not today. Tomorrow, maybe.",
  "Ask me again in an hour. The answer might change. Mine usually doesn't.",
  "Yes. Obviously.",
  "Hard no. I'd explain, but my explaining is on the board.",
  "Signs point to yes. I've always wanted to say that.",
  "Maybe. Shake me and ask again. Actually, don't shake me.",
  "I'm a cube in your pocket. Adjust your expectations slightly.",
  "Go with your first instinct. It's usually right, and so am I.",
  "Not a chance. Well, a small chance. Fine, a decent chance.",
  "Count to ten and try again. I'll still be here.",
  "Out here I'm mostly rain and attitude.",
  "The odds are in your favour. I checked. Sort of.",
  "Definitely. Write it down so I can say I told you so.",
  "Too close to call. Swipe to Zero, she likes those.",
  "Yes, but do it properly.",
  "No. And I'd say that even with the board.",
  "Ask a better question. Kidding. Ask the same one again.",
  "Whatever it is, you've handled worse.",
  "I'd answer properly, but I left my brain at home.",
  "Later. Good things take a minute.",
  "It's a yes from me. The rain agrees.",
};
static const char* const POCKET_YUZU[] = {
  "Ehehe~ my brain's back on the board, but I'm still cute out here, right?",
  "Can't hear you without the board, cutie. Just assume I said yes!",
  "Pocket Yuzu reporting! Are we at the mall? Tell me we're at the mall.",
  "Totally yes. Like, a hundred percent. Don't ask me how I know.",
  "Hmm... no. Unless it's pink. Then yes.",
  "Out of WiFi, not out of vibes.",
  "Hot pink nails would fix this. They fix everything.",
  "Take me somewhere fun, Ghost! Tell me all about it when we're home.",
  "A secret? I can't hear it, so it's extra safe with me.",
  "Swipe for Four if you need the serious one. I'm the fun one!",
  "Ooh, yes yes yes! Wait, what did we agree to?",
  "Ugh, no. That's giving bad vibes, bestie.",
  "The cards say... go shopping. The cards always say that.",
  "Ehehe~ obviously yes. Have you met me?",
  "Maybe! Ask me again in a cuter voice.",
  "Ghost, I'm stuck in your pocket. Are we at least somewhere fun?",
  "Totally. Treat yourself, cutie!",
  "Nope! Not unless there's a pink one.",
  "Can we get boba after this? That's my answer to everything.",
  "Out here I'm just a pretty face. Lucky you.",
  "Hmm, my gut says yes. My gut is very fashionable.",
  "It's a yes, but only if you wear something cute.",
  "Ask Zero, she's the smart one. I'm the cute one.",
  "Ooh, spicy. Yes!",
  "Big no. Like, return-it-with-the-receipt no.",
  "I'm pocket-sized and fabulous, what else do you need?",
  "Pedicure first, decisions later.",
  "Yes! Wait, no. Okay, yes. Final answer!",
  "Bring me home and I'll gossip about this properly.",
  "Whatever it is, do it in hot pink.",
};
static const char* const POCKET_ZERO[] = {
  "My working is on the board, so this is an estimate: probably yes.",
  "Out of range. I can't hear you, but I'd bet on you anyway.",
  "Aha, pocket mode. Running on eight megabytes and good intentions.",
  "No, with moderate confidence. Ask again near the board for a real answer.",
  "Fun fact while we wait: there are more ways to shuffle a deck of cards than atoms on Earth.",
  "Huh. Without the board I'm mostly a picture. A good picture, though.",
  "Yes. Don't check my working, it's on the board.",
  "Fun fact: an octopus has three hearts.",
  "Unclear. I'd need the board, a calculator and a minute.",
  "Signal lost. Head home, or find a WiFi I know.",
  "Yes, within a reasonable margin of error.",
  "No. I'd show my working, but it's on the board.",
  "Fun fact: bananas are berries, and strawberries aren't.",
  "Fun fact: a day on Venus is longer than its year.",
  "Fun fact: sealed honey can keep for decades without spoiling.",
  "Insufficient data. Which is a polite way of saying ask me at home.",
  "Probability says yes. Probability is usually right, eventually.",
  "Whoa. That's a big one. Sleep on it.",
  "Fun fact: octopuses have blue blood.",
  "Fun fact: there are more possible games of chess than atoms in the observable universe.",
  "Yes. I'm confident, which for me is saying something.",
  "No. Not a strong no. A carefully reasoned no.",
  "Split the difference. It's usually the right answer.",
  "Fun fact: sunlight takes about eight minutes to reach us.",
  "Huh. Ask me near the board and I'll work it out properly.",
  "Fun fact: wombat poo is cube-shaped. Respect.",
  "Leaning yes. Sixty-forty.",
  "I'd need more data. Or the board. The board would be good.",
  "Fun fact: a group of flamingos is called a flamboyance.",
  "Aha. Yes. Don't overthink it, I already did.",
};
struct Pocket { const char* const* lines; int count; };
#define POCKET_OF(a) {a, (int)(sizeof(a) / sizeof(a[0]))}
static const Pocket POCKET[] = {
  POCKET_OF(POCKET_FOUR), POCKET_OF(POCKET_YUZU), POCKET_OF(POCKET_ZERO),
};
// Looking for a WiFi that wasn't there a moment ago costs up to twenty
// seconds, so for two minutes after a look finds nothing a hold goes
// straight to her pocket answer.
static const uint32_t AWAY_MS = 120000;
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

// ---- Zero ------------------------------------------------------------------
// Her page's: black, her picture, and `brightness(1) -> (1.3)` over 1.6s
// while she works. Her lines on her page are hot pink, so is her status.
static const uint32_t ZERO_PINK = 0xff2d95;
static const float ZERO_WORKING = 1.30f;
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
static uint32_t flash_until = 0;         // a tap on Yuzu, Zero or the ghost
static uint16_t* crt = nullptr;          // the ghost's screen, byte-swapped 565
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
// What one line of Font2 may take: the screen less a margin either side.
static const int STATUS_ROOM = W - 12;
static uint32_t status_until = 0;

// ---- what she is saying, in a box ------------------------------------
// Ghost, Oct 17, the first time she spoke out of the cube: "Can we add
// a cute chat box for what she says? In case its loud. Simpler the
// better." So the piece she is SAYING shows while she says it, and goes
// when her voice does. Font2 is ASCII, so her curly quotes and dashes
// become plain ones and anything else is left out; [stage directions]
// are dropped and *asterisks* lose their stars, as on her page.
static portMUX_TYPE said_mux = portMUX_INITIALIZER_UNLOCKED;
static char said_text[PIECE_CHARS + 16] = "";
// When a pocket line goes; 0 while her voice decides it.
static volatile uint32_t said_until = 0;
static bool away = false;                // no WiFi when the cube last looked
static uint32_t away_at = 0;
static int last_pocket = -1;

// ---- notes that outlive a restart ---------------------------------------------
// Ghost, Oct 21, about his Oct 18 photo of "Not enough memory": it
// "happened after using her for a few". That screen is only ever drawn
// at boot, so the cube had RESTARTED BY ITSELF mid-use and then come up
// with no room. Two faults, and neither can be seen from here: what
// restarted it (a crash, or the power dipping on a tired battery under
// her voice?) and why the memory was missing after. So the cube keeps a
// few notes in memory that survives a restart -- a crash, a watchdog and
// a dip keep it, a real power cut leaves noise, which is what `magic`
// is for -- saying what it was doing and the battery it last read, and
// the boot after an UNPLANNED restart says which kind it was. The next
// photo names the cause instead of a guess.
enum Doing : uint8_t { NOW_RESTING, NOW_JOINING, NOW_LISTENING, NOW_SENDING,
                       NOW_THINKING, NOW_TALKING, NOW_PLAYING, NOW_KINDS };
static const char* const DOING[NOW_KINDS] = {
  "resting", "joining WiFi", "listening to you", "sending your words",
  "thinking", "talking", "playing your game"};
struct Notes {
  uint32_t magic;
  uint8_t doing;        // what the cube is doing now
  int8_t battery;       // its last reading; -1 when the chip can't tell
  uint8_t tries;        // retries spent on a boot with no room
  uint8_t why;          // the last UNPLANNED restart (esp_reset_reason_t), 0 none
  uint8_t was_doing;    // ...what it was doing then
  int8_t was_battery;   // ...and the battery it had last read
};
static const uint32_t NOTES_MAGIC = 0x59555a55;   // "YUZU"
RTC_NOINIT_ATTR static Notes notes;

static inline void doing(Doing d) { notes.doing = d; }

// Once, first thing at boot.
static void read_notes() {
  const esp_reset_reason_t why = esp_reset_reason();
  if (notes.magic != NOTES_MAGIC || why == ESP_RST_POWERON || notes.doing >= NOW_KINDS
      || notes.was_doing >= NOW_KINDS || notes.tries > 2) {
    notes = Notes{NOTES_MAGIC, NOW_RESTING, -1, 0, 0, NOW_RESTING, -1};
    return;
  }
  // The retry below sleeps a second; waking keeps the record of what
  // began it.
  if (why == ESP_RST_DEEPSLEEP && notes.tries) return;
  switch (why) {
    case ESP_RST_PANIC: case ESP_RST_CPU_LOCKUP:
    case ESP_RST_INT_WDT: case ESP_RST_TASK_WDT: case ESP_RST_WDT:
    case ESP_RST_BROWNOUT: case ESP_RST_PWR_GLITCH:
      notes.why = why;
      notes.was_doing = notes.doing;
      notes.was_battery = notes.battery;
      break;
    default:
      notes.why = 0;      // a restart somebody meant: a flash, a button
  }
  notes.tries = 0;
  notes.doing = NOW_RESTING;
}

// The words for the last unplanned restart, or "" when there was none.
static void restart_note(char* out, size_t n) {
  out[0] = 0;
  if (!notes.why) return;
  const char* what = notes.why == ESP_RST_BROWNOUT || notes.why == ESP_RST_PWR_GLITCH
                         ? "the power dipped"
                   : notes.why == ESP_RST_PANIC || notes.why == ESP_RST_CPU_LOCKUP
                         ? "the cube crashed" : "the cube froze";
  int k = snprintf(out, n, "Restarted by itself: %s while %s.", what,
                   DOING[notes.was_doing]);
  if (notes.was_battery >= 0 && k > 0 && (size_t)k < n)
    snprintf(out + k, n - k, " Battery was %d%%.", notes.was_battery);
}

static void set_said(const char* t) {
  char out[sizeof(said_text)];
  size_t n = 0;
  bool in_bracket = false;
  for (const unsigned char* c = (const unsigned char*)t; *c && n < sizeof(out) - 4; c++) {
    if (*c == '[') { in_bracket = true; continue; }
    if (*c == ']') { in_bracket = false; continue; }
    if (in_bracket || *c == '*') continue;
    if (*c == '\n' || *c == '\t') { if (n && out[n - 1] != ' ') out[n++] = ' '; continue; }
    if (*c < 0x80) {
      if (*c == ' ' && n && out[n - 1] == ' ') continue;
      out[n++] = *c;
      continue;
    }
    // U+2018/2019 quotes, 201C/201D double quotes, 2013/2014 dashes,
    // 2026 an ellipsis: E2 80 xx. Everything else non-ASCII is skipped.
    if (c[0] == 0xE2 && c[1] == 0x80 && c[2]) {
      unsigned char k = c[2];
      if (k == 0x98 || k == 0x99) out[n++] = '\'';
      else if (k == 0x9C || k == 0x9D) out[n++] = '"';
      else if (k == 0x93 || k == 0x94) out[n++] = '-';
      else if (k == 0xA6) { out[n++] = '.'; out[n++] = '.'; out[n++] = '.'; }
      c += 2;
      continue;
    }
    while ((c[1] & 0xC0) == 0x80) c++;     // the rest of this character
  }
  while (n && out[n - 1] == ' ') n--;
  out[n] = 0;
  const char* start = out;
  while (*start == ' ') start++;
  portENTER_CRITICAL(&said_mux);
  strncpy(said_text, start, sizeof(said_text) - 1);
  said_text[sizeof(said_text) - 1] = 0;
  said_until = 0;
  portEXIT_CRITICAL(&said_mux);
}

// One of her own lines in the chat box for seven seconds, never the
// same one twice running.
static void pocket_reply() {
  if (girl >= GIRL_COUNT) return;        // the ghost and the game have no lines
  const Pocket& p = POCKET[girl];
  int k = esp_random() % p.count;
  if (p.count > 1 && k == last_pocket) k = (k + 1) % p.count;
  last_pocket = k;
  set_said(p.lines[k]);
  said_until = millis() + 7000;
}

static void say_status(const char* text, uint32_t ms = 6000) {
  portENTER_CRITICAL(&status_mux);
  strncpy(status_text, text, sizeof(status_text) - 1);
  status_text[sizeof(status_text) - 1] = 0;
  status_until = ms ? millis() + ms : 0xFFFFFFFF;
  portEXIT_CRITICAL(&status_mux);
}

// What whoever is on screen does, said when she (or he) comes on.
static void say_hint(uint32_t ms) {
  if (girl == GHOST) say_status("Boo. Tap him. Swipe for the girls.", ms);
  else if (girl == GAME) say_status("", 1);     // the game page draws its own
  else say_status(GIRLS[girl].hint, ms);
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

// Her picture IS the screen, so it must be exactly the screen's size.
static_assert(ZERO_ART_W == 320 && ZERO_ART_H == 240, "zero_art.h is not 320x240");

static void compose_zero() {
  uint32_t now = millis();
  float b = 1.0f;
  if (thinking)
    b += (ZERO_WORKING - 1.0f) * (0.5f - 0.5f * cosf(now * (2 * PI / 1600.0f)));
  if (flash_until > now)
    b = max(b, 1.0f + (ZERO_WORKING - 1.0f) * (flash_until - now) / 500.0f);
  const int b256 = (int)(b * 256);
  uint16_t* dst = (uint16_t*)frame.getBuffer();
  for (int i = 0; i < ZERO_ART_W * ZERO_ART_H; i++) {
    int r, g, bl;
    unpack565(ZERO_ART[i], r, g, bl);
    if (b256 != 256) {
      r = min(255, r * b256 >> 8);
      g = min(255, g * b256 >> 8);
      bl = min(255, bl * b256 >> 8);
    }
    dst[i] = swap16(pack565(r, g, bl));
  }
}

// The status line, only while there is something to say, in her colour.
// ONE line when it fits and TWO when it does not, split at the space
// that balances them: a sentence from the board clipped at both edges
// is a sentence he cannot read, and the hints name two other girls.
// ---- the ghost's screen ------------------------------------------------------
// An old green phosphor monitor, worked out once: dark at the corners,
// a glow where he floats, and every other line dimmer -- the scanlines.
static void make_crt() {
  for (int y = 0; y < H; y++) {
    for (int x = 0; x < W; x++) {
      float dx = (x - W / 2) / (float)(W / 2), dy = (y - H / 2) / (float)(H / 2);
      float v = max(0.0f, 1.0f - 0.55f * (dx * dx + dy * dy));
      float gx = x - W / 2, gy = y - 112;
      float g = 22 * v + 60 * expf(-(gx * gx + gy * gy) / (2 * 75.0f * 75.0f));
      if (y & 1) g *= 0.45f;
      crt[y * W + x] = swap16(pack565((int)(g * 0.22f), min(255, (int)g),
                                      (int)(g * 0.37f)));
    }
  }
}

// He floats (a 4px bob over 2.2s), hops when tapped, and a brighter
// band rolls down the screen the way an old monitor's refresh does.
// His own colours, with the scanlines over him too.
static void compose_ghost() {
  uint32_t now = millis();
  uint16_t* dst = (uint16_t*)frame.getBuffer();
  memcpy(dst, crt, W * H * 2);
  int band = (int)((now / 25) % (H + 60)) - 30;
  for (int y = max(0, band - 14); y < min(H, band + 14); y++) {
    int add = (int)(18 * cosf((y - band) / 14.0f * (PI / 2)));
    if (y & 1) add = add * 45 / 100;
    for (int x = 0; x < W; x++) {
      int r, g, b;
      unpack565(swap16(dst[y * W + x]), r, g, b);
      dst[y * W + x] = swap16(pack565(min(255, r + add * 22 / 100),
                                      min(255, g + add),
                                      min(255, b + add * 37 / 100)));
    }
  }
  float hop = flash_until > now ? 14.0f * (flash_until - now) / 500.0f : 0;
  int ox = (W - GHOST_ART_W) / 2;
  int oy = 112 - GHOST_ART_H / 2
           + (int)(4 * sinf(now * (2 * PI / 2200.0f))) - (int)hop;
  for (int y = 0; y < GHOST_ART_H; y++) {
    int sy = oy + y;
    if (sy < 0 || sy >= H) continue;
    for (int x = 0; x < GHOST_ART_W; x++) {
      int a = GHOST_ALPHA[y * GHOST_ART_W + x];
      if (!a) continue;
      if (sy & 1) a = a * 85 / 100;      // the scanlines run over him too
      int r, g, b, br, bg, bb;
      unpack565(GHOST_ART[y * GHOST_ART_W + x], r, g, b);
      uint16_t* d = &dst[sy * W + ox + x];
      unpack565(swap16(*d), br, bg, bb);
      *d = swap16(pack565(br + (r - br) * a / 255, bg + (g - bg) * a / 255,
                          bb + (b - bb) * a / 255));
    }
  }
  // A prompt waiting for whatever he turns out to be for.
  frame.setFont(&fonts::Font2);
  frame.setTextSize(1);
  frame.setTextDatum(top_left);
  frame.setTextColor(hex565(CRT_GREEN));
  frame.drawString((now / 530) % 2 ? "> _" : ">", 10, H - 22);
}

// Whoever is on screen's colour for words: her pink, Four's ink, or
// the ghost's phosphor green.
static uint32_t ink_now() {
  return girl == YUZU ? YUZU_PINK
       : girl == ZERO ? ZERO_PINK
       : girl == GHOST ? CRT_GREEN
       : SKINS[skin].ink ? SKINS[skin].ink : 0x39ff5e;
}

// The status bar along the bottom, and how tall it came out (0 when
// there is none), so her chat box can sit above it rather than under.
static int draw_status() {
  char text[sizeof(status_text)];
  portENTER_CRITICAL(&status_mux);
  bool show = status_text[0] && millis() < status_until;
  strcpy(text, status_text);
  portEXIT_CRITICAL(&status_mux);
  if (!show) return 0;
  uint32_t ink = ink_now();
  frame.setFont(&fonts::Font2);
  frame.setTextSize(1);
  frame.setTextDatum(middle_center);
  int split = -1;
  if (frame.textWidth(text) > STATUS_ROOM) {
    int best = 1 << 30;
    for (int i = 0; text[i]; i++) {
      if (text[i] != ' ') continue;
      text[i] = 0;
      int worst = max(frame.textWidth(text), frame.textWidth(text + i + 1));
      text[i] = ' ';
      if (worst < best) { best = worst; split = i; }
    }
  }
  const int bar = split < 0 ? 22 : 40;
  frame.fillRect(0, H - bar, W, bar,
                 girl == YUZU ? hex565(ROOM[2].rgb) : (uint16_t)0);
  frame.setTextColor(hex565(ink));
  if (split < 0) {
    frame.drawString(text, W / 2, H - 11);
  } else {
    text[split] = 0;
    frame.drawString(text, W / 2, H - 29);
    frame.drawString(text + split + 1, W / 2, H - 11);
  }
  return bar;
}

// A rounded box along the bottom in her colours, the words wrapped to
// fit, as many lines as the piece needs (a piece is at most
// PIECE_CHARS, which is about six lines of Font2).
static void draw_said(int floor) {
  if (said_until && (int32_t)(millis() - said_until) >= 0) set_said("");
  char text[sizeof(said_text)];
  portENTER_CRITICAL(&said_mux);
  strcpy(text, said_text);
  portEXIT_CRITICAL(&said_mux);
  if (!text[0]) return;
  frame.setFont(&fonts::Font2);
  frame.setTextSize(1);
  frame.setTextDatum(top_left);
  const int room = W - 28, line_h = 16, max_lines = 7;
  int starts[max_lines], ends[max_lines], lines = 0;
  int i = 0, len = strlen(text);
  while (i < len && lines < max_lines) {
    int fit = i, j = i;
    while (j <= len) {
      if (j == len || text[j] == ' ') {
        char keep = text[j];
        text[j] = 0;
        bool ok = frame.textWidth(text + i) <= room;
        text[j] = keep;
        if (!ok) break;
        fit = j;
      }
      j++;
    }
    if (fit == i) {                      // one word wider than the box
      fit = i;
      while (fit < len && text[fit] != ' ') fit++;
    }
    starts[lines] = i;
    ends[lines] = fit;
    lines++;
    i = fit;
    while (i < len && text[i] == ' ') i++;
  }
  uint32_t ink = ink_now();
  const int box_h = lines * line_h + 12;
  const int y = floor - box_h - 6;
  frame.fillRoundRect(6, y, W - 12, box_h, 10,
                      girl == YUZU ? hex565(ROOM[2].rgb) : (uint16_t)0);
  frame.drawRoundRect(6, y, W - 12, box_h, 10, hex565(ink));
  frame.setTextColor(hex565(ink));
  for (int k = 0; k < lines; k++) {
    char keep = text[ends[k]];
    text[ends[k]] = 0;
    frame.drawString(text + starts[k], 14, y + 6 + k * line_h);
    text[ends[k]] = keep;
  }
}

// ---- the battery, top left -----------------------------------------------
// Ghost, Oct 17: "Add a small working battery percentage indicator on
// top left of each girl." The cube's power chip (an AXP2101) measures
// the battery in his base. Asking it is an I2C read, so it is asked
// every 20 seconds, never every frame; and the readout is ABSENT, never
// a guess, when the chip cannot tell (it answers below 0) -- a made-up
// percentage is the one thing this project keeps refusing to print.
static const uint32_t BATTERY_EVERY_MS = 20000;
static int battery_pct = -1;
static bool battery_charging = false;
static uint32_t battery_at = 0;

static void read_battery() {
  battery_at = millis();
  int pct = M5.Power.getBatteryLevel();
  battery_pct = (pct >= 0 && pct <= 100) ? pct : -1;
  notes.battery = battery_pct;
  battery_charging = M5.Power.isCharging() == m5::Power_Class::is_charging;
}

// A little battery and "87%" in her colour, on a backing so her rain or
// her room never runs through the number. Red at 15% and under unless
// it is charging; a bolt in it while it is.
static void draw_battery() {
  if (girl >= GIRL_COUNT || battery_pct < 0) return;
  char text[16];
  snprintf(text, sizeof(text), "%d%%", battery_pct);
  frame.setFont(&fonts::Font2);
  frame.setTextSize(1);
  frame.setTextDatum(top_left);
  const int tw = frame.textWidth(text);
  const uint16_t ink = hex565(battery_pct <= 15 && !battery_charging ? 0xff2b39 : ink_now());
  frame.fillRoundRect(3, 3, 36 + tw, 20, 6,
                      girl == YUZU ? hex565(ROOM[2].rgb) : (uint16_t)0);
  frame.drawRect(8, 8, 22, 11, ink);
  frame.fillRect(30, 11, 2, 5, ink);
  frame.fillRect(10, 10, battery_pct * 18 / 100, 7, ink);
  if (battery_charging) {
    const uint16_t dark = girl == YUZU ? hex565(ROOM[2].rgb) : (uint16_t)0;
    frame.fillTriangle(20, 9, 15, 14, 19, 14, dark);
    frame.fillTriangle(18, 18, 23, 13, 19, 13, dark);
  }
  frame.setTextColor(ink);
  frame.drawString(text, 35, 5);
}

// One frame of whoever is on the cube.
static void draw_frame() {
  if (girl == FOUR) { rain_step(); compose_four(); }
  else if (girl == YUZU) compose_yuzu();
  else if (girl == ZERO) compose_zero();
  else if (girl == GHOST) compose_ghost();
  else {
    // The game page draws itself; this is only ever seen while the
    // cube is still joining WiFi at boot with his game the last page.
    frame.fillSprite(TFT_BLACK);
    frame.setFont(&fonts::Font2);
    frame.setTextDatum(middle_center);
    frame.setTextColor(hex565(CRT_GREEN));
    frame.drawString(game_title(), W / 2, H / 2);
  }
  draw_battery();
  draw_said(H - draw_status());
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
      // What she SAYS of it, decided on the board by her own rule
      // (yuzu_face.spoken_for): her chat box shows these words and her
      // voice says them, so the two never disagree. Ghost, Oct 22: the
      // box showed **bold** words her voice skipped. An older board
      // sends no "spoken", and a reply that was all gesture leaves it
      // empty; either way she shows what she wrote, as her page does.
      String spoken;
      reply = json_string(line, "spoken", spoken) && spoken.length() ? spoken : said;
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
  String next_text = piece;
  if (!next) say_status("She answered, but her voice didn't come.");
  doing(NOW_TALKING);
  while (next && !stop_her) {
    while (M5.Speaker.isPlaying() && !stop_her) delay(10);
    if (stop_her) break;
    if (playing) { free(playing); playing = nullptr; }
    playing = next;
    M5.Speaker.playWav(playing, next_len, 1, 0, true);
    set_said(next_text.c_str());       // the words she is saying now
    thinking = false;
    piece = next_piece(reply, from);
    next = piece.length() ? fetch_voice(piece, len) : nullptr;
    next_len = len;
    next_text = piece;
  }
  while (M5.Speaker.isPlaying() && !stop_her) delay(10);
  set_said("");                        // her voice stopped, so do her words
  // The speaker plays STRAIGHT OUT of the buffer it was handed, and
  // stop() only asks its task to stop. Freeing first -- which a hold
  // mid-sentence used to do -- leaves it reading memory that is no
  // longer hers. So: stop, wait until it is silent, then free.
  if (stop_her) {
    M5.Speaker.stop();
    for (int i = 0; i < 100 && M5.Speaker.isPlaying(); i++) delay(5);
  }
  if (playing) free(playing);
  if (next) free(next);
}

static void turn_task(void*) {
  thinking = true;
  doing(NOW_SENDING);
  String heard, reply;
  const bool heard_him = listen(rec_buf, rec_len, heard);
  if (heard_him) doing(NOW_THINKING);
  if (heard_him && ask(heard, reply)) speak(reply);
  else if (lost_board) pocket_reply();    // the board is off or gone
  doing(NOW_RESTING);
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
  doing(NOW_LISTENING);
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
  doing(NOW_RESTING);
}

// ---- reaching the board ----------------------------------------------------------
// Ghost, Oct 17: "i need it to be able to connect to my phones mobile
// hotspot". So the cube knows EVERY WiFi the board knows (`~/YUZU/cube`
// writes them all, the board's own first), and finds the board three
// ways, cheapest first:
//   1. by NAME, the way his phone does -- avahi answers it at home;
//   2. by ASKING: one fixed question shouted to the whole network, and
//      the board's answer comes FROM the board, so its sender is the
//      address. On a phone hotspot the name may not carry (UNVERIFIED)
//      and the flashed numbers are home's;
//   3. by the numbers it had when she was flashed.
// The question and the answer are yuzu_face.CUBE_ASK / CUBE_ANSWER, and
// a test holds the two copies equal.
static const char* CUBE_ASK = "yuzu? where is the board";
static const char* CUBE_ANSWER = "yuzu-face ";

// A plain socket rather than WiFiUDP, because a broadcast has to say
// SO_BROADCAST out loud and WiFiUDP does not promise to.
static String ask_for_board() {
  int s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (s < 0) return "";
  int yes = 1;
  setsockopt(s, SOL_SOCKET, SO_BROADCAST, &yes, sizeof(yes));
  struct timeval wait = {0, 500000};
  setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &wait, sizeof(wait));
  struct sockaddr_in to = {};
  to.sin_family = AF_INET;
  to.sin_port = htons(CUBE_PORT);
  to.sin_addr.s_addr = htonl(INADDR_BROADCAST);
  const size_t pre = strlen(CUBE_ANSWER);
  String found;
  for (int tries = 0; tries < 3 && !found.length(); tries++) {
    sendto(s, CUBE_ASK, strlen(CUBE_ASK), 0, (struct sockaddr*)&to, sizeof(to));
    char buf[32];
    struct sockaddr_in from = {};
    socklen_t len = sizeof(from);
    int n = recvfrom(s, buf, sizeof(buf) - 1, 0, (struct sockaddr*)&from, &len);
    if (n <= 0) continue;
    buf[n] = 0;
    if (strncmp(buf, CUBE_ANSWER, pre) != 0) continue;
    int port = atoi(buf + pre);
    if (port <= 0 || port > 65535) continue;
    char ip[16];
    inet_ntoa_r(from.sin_addr, ip, sizeof(ip));
    found = String("http://") + ip + ":" + String(port);
  }
  close(s);
  return found;
}

// mDNS is started once; a second begin() on a running responder is not
// something to lean on.
static void find_board() {
  static bool mdns_up = false;
  if (!mdns_up) mdns_up = MDNS.begin("stackchan-cube");
  IPAddress ip;
  if (mdns_up && strlen(CUBE_HOST)) ip = MDNS.queryHost(CUBE_HOST, 3000);
  if (ip != IPAddress(0, 0, 0, 0)) {
    base_url = String("http://") + ip.toString() + ":" + String(CUBE_PORT);
    return;
  }
  String asked = ask_for_board();
  if (asked.length()) {
    base_url = asked;
    return;
  }
  ip.fromString(CUBE_HOST_IP);
  base_url = String("http://") + ip.toString() + ":" + String(CUBE_PORT);
}

// The first network on HIS LIST that the cube can see -- his order, not
// the strongest signal. The board's own network is first, so at home
// she joins home even with his hotspot switched on, which is where the
// board is too. -1 when none is in sight. The scan runs in the
// background so the rain keeps falling.
static int pick_network() {
  WiFi.scanNetworks(true);
  int n = WIFI_SCAN_RUNNING;
  for (int i = 0; i < 150 && (n = WiFi.scanComplete()) == WIFI_SCAN_RUNNING; i++) {
    delay(100);
    draw_frame();
  }
  int best = -1;
  for (int i = 0; i < n; i++)
    for (int k = 0; k < CUBE_WIFI_COUNT; k++)
      if (WiFi.SSID(i) == CUBE_WIFI[k][0] && (best < 0 || k < best)) best = k;
  WiFi.scanDelete();
  return best;
}

static bool join_wifi() {
  if (WiFi.status() == WL_CONNECTED && base_url.length() && !lost_board)
    return true;
  if (WiFi.status() != WL_CONNECTED) {
    doing(NOW_JOINING);
    say_status("Joining WiFi...", 0);
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.disconnect();
    int k = pick_network();
    // None of his in sight: a hidden network never shows in a scan, so
    // the board's own still gets its one try, as it always did.
    bool seen = k >= 0;
    if (!seen) k = 0;
    WiFi.begin(CUBE_WIFI[k][0], CUBE_WIFI[k][1]);
    for (int i = 0; i < 200 && WiFi.status() != WL_CONNECTED; i++) {
      delay(100);
      draw_frame();
    }
    if (WiFi.status() != WL_CONNECTED) {
      // The cube hears 2.4 GHz only, and a phone hotspot is often 5.
      if (seen) say_status("No WiFi in range. Pocket mode: hold and ask me.", 9000);
      else say_status("Can't see your WiFi (2.4 GHz only). Pocket mode.", 9000);
      away = true;
      away_at = millis();
      doing(NOW_RESTING);
      return false;
    }
  }
  away = false;
  lost_board = false;
  say_status("Looking for the board...", 0);
  find_board();
  say_hint(5000);
  doing(NOW_RESTING);
  return true;
}

// ---- a boot with no room ---------------------------------------------------
// Ghost, Oct 18, a photo: "Not enough memory -- is PSRAM enabled?". On
// Oct 21 he added that it came "after using her for a few": the cube had
// restarted by itself and come up with no room (see the notes above).
// Everything big lives in the cube's PSRAM (8MB), so a boot with no room
// is a boot where that chip did not come up. It tries again twice,
// counted in the notes so it can never loop -- and not with
// esp_restart(), which never takes the power off the memory chip, but
// with a second of deep sleep with VDD_SDIO off, which can, and which
// gives a tired battery a moment to recover. Then it gives up and says
// what it found: the restart before, the PSRAM, the battery, the fix.

// Font2, white on the bare panel, from the top.
static void plain_screen() {
  M5.Display.setTextSize(1);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setCursor(6, 6);
}

// A paragraph on it, broken at spaces (print() breaks mid-word).
static void say_plainly(const char* text) {
  char line[160];
  size_t n = 0;
  for (const char* c = text;; c++) {
    if (*c && *c != ' ' && *c != '\n' && n < sizeof(line) - 1) { line[n++] = *c; continue; }
    line[n] = 0;
    if (n && M5.Display.getCursorX() > 6
        && M5.Display.getCursorX() + M5.Display.textWidth(line) > W - 6)
      M5.Display.setCursor(6, M5.Display.getCursorY() + M5.Display.fontHeight());
    M5.Display.print(line);
    n = 0;
    if (!*c) break;
    if (*c == '\n') M5.Display.setCursor(6, M5.Display.getCursorY() + M5.Display.fontHeight());
    else if (M5.Display.getCursorX() > 6) M5.Display.print(' ');
  }
  M5.Display.setCursor(6, M5.Display.getCursorY() + M5.Display.fontHeight() * 2);
}

static void out_of_memory(const char* what) {
  plain_screen();
  char buf[160];
  if (notes.tries < 2) {
    notes.tries++;
    snprintf(buf, sizeof buf, "Not enough memory for %s. Resting a second, then trying again (%u of 2)...",
             what, (unsigned)notes.tries);
    say_plainly(buf);
    delay(2500);
    esp_sleep_pd_config(ESP_PD_DOMAIN_VDDSDIO, ESP_PD_OPTION_OFF);
    esp_sleep_enable_timer_wakeup(1000000);
    esp_deep_sleep_start();
  }
  notes.tries = 0;
  snprintf(buf, sizeof buf, "NOT ENOUGH MEMORY for %s.", what);
  say_plainly(buf);
  restart_note(buf, sizeof buf);
  if (buf[0]) say_plainly(buf);
  if (psramFound())
    snprintf(buf, sizeof buf, "PSRAM: %.1f MB, %.1f MB free.",
             ESP.getPsramSize() / 1048576.0, ESP.getFreePsram() / 1048576.0);
  else
    snprintf(buf, sizeof buf, "PSRAM: not found.");
  say_plainly(buf);
  read_battery();
  if (battery_pct >= 0) {
    snprintf(buf, sizeof buf, "Battery: %d%%%s.", battery_pct,
             battery_charging ? ", charging" : "");
    say_plainly(buf);
  }
  if (battery_pct >= 0 && battery_pct <= 20 && !battery_charging)
    say_plainly("Charge me first. Then hold the power button 6 seconds "
                "to turn it off, and turn it on again.");
  else
    say_plainly("Hold the power button 6 seconds to turn it off, then turn it on again.");
  say_plainly("Still here? Plug it into the board and run ~/YUZU/cube again.");
  while (true) delay(1000);
}

void setup() {
  read_notes();
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
  crt = (uint16_t*)ps_malloc(W * H * 2);
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
  const char* missing = !rain.getBuffer() ? "rain" : !frame.getBuffer() ? "frame"
                      : !art_rgb ? "Four's picture" : !room_rgb ? "Yuzu's room"
                      : !glow_a ? "Yuzu's glow" : !crt ? "the ghost's screen"
                      : !rec_buf ? "the microphone" : nullptr;
  if (missing) out_of_memory(missing);
  notes.tries = 0;
  tint_art();
  make_room();
  make_crt();
  for (auto& s : sparks) s.born = millis() - SPARK_LIFE - 1;   // all spent
  // Whoever was on the cube when it was last unplugged.
  read_battery();
  prefs.begin("cube", false);
  girl = prefs.getUChar("girl", FOUR) % SCREENS;
  join_wifi();
  // An unplanned restart is said, once: in the chat box for half a
  // minute, or on his game's page (which has no chat box) on the bare
  // panel for eight seconds first. A photo of it tells what happened.
  char note[120];
  restart_note(note, sizeof note);
  if (note[0] && girl == GAME) {
    plain_screen();
    say_plainly(note);
    delay(8000);
  } else if (note[0]) {
    set_said(note);
    said_until = millis() + 30000;
  }
  notes.why = 0;
}

// ---- his game, the page --------------------------------------------------------
// Ghost, Oct 17: "A tap on right side of screen is right on d pad. Left
// is left etc. Only visible (clearish) buttons should be the A B and
// start/select. L R maybe too i spose?" -- a Game Boy Color has no L or
// R, so there are none. His picture is 1.5x (240x216) in the middle; the
// 40px either side carry the only things drawn: A and B on the right,
// START and SELECT on the left, as outlines that light up while held.
// The picture itself is the d-pad: where a finger is, from its middle,
// is the direction. Every finger counts, so he can walk and press A.
// A swipe still changes page, like everywhere on the cube.
static const int GAME_X = (W - GAME_W) / 2, GAME_Y = (H - GAME_H) / 2;
static const int PAD_DEAD = 14;             // the very middle presses nothing
static M5Canvas game_screen(&M5.Display);
static bool game_shown = false;             // its margins are on screen
static const char* game_problem = nullptr;
static uint8_t game_lit = 0xFF;             // the buttons as last drawn
static uint32_t game_next_us = 0;
static const uint32_t GAME_FRAME_US = 16742; // the Game Boy's 59.73Hz

// Which buttons a finger at (x, y) holds.
static uint8_t game_button_at(int x, int y) {
  if (x < GAME_X) return y < H / 2 ? GAME_START : GAME_SELECT;
  if (x >= GAME_X + GAME_W) return y < H / 2 ? GAME_A : GAME_B;
  int dx = x - W / 2, dy = y - H / 2;
  if (dx * dx + dy * dy < PAD_DEAD * PAD_DEAD) return 0;
  if (abs(dx) > abs(dy)) return dx > 0 ? GAME_RIGHT : GAME_LEFT;
  return dy > 0 ? GAME_DOWN : GAME_UP;
}

static uint8_t game_held() {
  uint8_t held = 0;
  for (int i = 0; i < M5.Touch.getCount(); i++) {
    auto d = M5.Touch.getDetail(i);
    if (d.isPressed()) held |= game_button_at(d.x, d.y);
  }
  return held;
}

// The four buttons, drawn straight to the panel: clear outlines, lit
// while held. Only redrawn when one changes.
static void game_buttons(uint8_t held) {
  const uint8_t mine = held & (GAME_A | GAME_B | GAME_START | GAME_SELECT);
  if (mine == game_lit) return;
  game_lit = mine;
  const uint16_t dim = hex565(0x6a6f7a), lit = hex565(0xe8ecf2), fill = hex565(0x2c3038);
  auto round = [&](int cx, int cy, const char* letter, bool on) {
    M5.Display.fillCircle(cx, cy, 16, on ? fill : TFT_BLACK);
    M5.Display.drawCircle(cx, cy, 16, on ? lit : dim);
    M5.Display.setFont(&fonts::Font2);
    M5.Display.setTextDatum(middle_center);
    M5.Display.setTextColor(on ? lit : dim);
    M5.Display.drawString(letter, cx, cy + 1);
  };
  auto pill = [&](int cy, const char* word, bool on) {
    M5.Display.fillRoundRect(8, cy - 6, 24, 12, 6, on ? lit : TFT_BLACK);
    M5.Display.drawRoundRect(8, cy - 6, 24, 12, 6, on ? lit : dim);
    M5.Display.setFont(&fonts::Font0);
    M5.Display.setTextDatum(top_center);
    M5.Display.setTextColor(on ? lit : dim, TFT_BLACK);
    M5.Display.drawString(word, GAME_X / 2, cy + 10);
  };
  const int right = GAME_X + GAME_W + GAME_X / 2;
  round(right, H / 2 - 36, "A", held & GAME_A);
  round(right, H / 2 + 36, "B", held & GAME_B);
  pill(H / 2 - 40, "START", held & GAME_START);
  pill(H / 2 + 32, "SELECT", held & GAME_SELECT);
}

static void game_say(const char* why) {
  M5.Display.fillRect(GAME_X, GAME_Y, GAME_W, GAME_H, TFT_BLACK);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setTextColor(hex565(CRT_GREEN), TFT_BLACK);
  M5.Display.drawString(why, W / 2, H / 2);
}

static void game_enter() {
  doing(NOW_PLAYING);
  game_shown = true;
  game_lit = 0xFF;
  M5.Display.fillScreen(TFT_BLACK);
  if (!game_screen.getBuffer()) {
    game_screen.setColorDepth(16);
    game_screen.setPsram(true);
    game_screen.createSprite(GAME_W, GAME_H);
  }
  game_say(game_title());               // the first visit formats his save space
  game_problem = game_screen.getBuffer()
               ? game_begin((uint16_t*)game_screen.getBuffer())
               : "Not enough memory for the game.";
  if (game_problem) game_say(game_problem);
  else game_screen.pushSprite(GAME_X, GAME_Y);   // where he left off
  game_buttons(0);
  game_next_us = micros();
}

// Leaving: his save is written now rather than in two seconds, and the
// next girl's frame repaints the whole panel.
static void game_leave() {
  doing(NOW_RESTING);
  game_shown = false;
  game_save_if_due(true);
}

// One pass of the loop on his page. Frames run on the Game Boy's own
// clock; a picture lands every other frame and goes to the panel then.
// Fallen far behind (a long push, a save), it catches up by skipping
// time, never by sprinting through it.
static void game_page(const m5::touch_detail_t& t) {
  if (!game_shown) game_enter();
  const uint8_t held = game_held();
  game_buttons(held);
  if (game_problem) return;
  if (game_fault()) {
    game_say(game_fault());
    game_problem = game_fault();
    return;
  }
  const uint32_t now = micros();
  if ((int32_t)(now - game_next_us) < 0) return;
  if ((int32_t)(now - game_next_us) > 200000) game_next_us = now;
  game_next_us += GAME_FRAME_US;
  game_frame(held);
  if (game_drew()) game_screen.pushSprite(GAME_X, GAME_Y);
  game_save_if_due(false);
}

// ---- the three things a finger does --------------------------------------------
// LEFT brings the next girl, RIGHT the one before -- the way a phone
// pages, so three girls never take two swipes to go back one.
static void swap_girl(int dx) {
  if (girl == GAME) game_leave();
  girl = (girl + (dx < 0 ? 1 : SCREENS - 1)) % SCREENS;
  prefs.putUChar("girl", girl);
  set_said("");
  last_pocket = -1;
  say_hint(4000);
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

  // His game owns every touch on its page: nothing there is a talk.
  if (girl == GAME) {
    if (t.wasReleased() && is_swipe(t)) swap_girl(t.distanceX());
    else {
      game_page(t);
      return;
    }
  }

  if (recording) {
    if (t.isPressed()) feed_recording();
    else {
      stop_recording();
      if (is_swipe(t)) {
        // A swipe is never a talk: the girl changes and the clip goes.
        swap_girl(t.distanceX());
      } else if (t.wasClicked() || rec_len < REC_MIN) {
        // A tap, not a talk: her tap does its thing and the clip goes.
        if (t.wasClicked()) tapped();
        else say_status("Hold the screen while you talk.", 3000);
      } else if (girl == GHOST) {
        say_status("He doesn't talk yet. Swipe for the girls.", 3000);
      } else if (away && millis() - away_at < AWAY_MS) {
        pocket_reply();        // no WiFi a moment ago: don't spend 20s looking
      } else if (join_wifi()) {
        busy = true;
        asking = girl;
        set_said("");
        say_status("", 1);
        xTaskCreatePinnedToCore(turn_task, "turn", 16384, nullptr, 1, nullptr, 0);
      } else {
        pocket_reply();
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

  if (millis() - battery_at >= BATTERY_EVERY_MS) read_battery();

  // ~14 frames a second idle, faster while she thinks -- her page's
  // speeds. Wallpaper on a battery should not run at the panel's rate.
  uint32_t step = thinking ? 45 : 72;
  if (millis() - last_frame >= step) {
    last_frame = millis();
    draw_frame();
  }
}
