/* The part of the 3DS app that talks to the board.
 *
 * PORTABLE ON PURPOSE. Nothing in here touches the 3DS's screens, mic or
 * speaker -- only BSD sockets, which the 3DS and Linux spell the same --
 * so the suite compiles THIS FILE with the ordinary gcc and drives it
 * against the real face server (TestThe3DS). Everything a 3DS-only file
 * would make untestable lives in main.c instead, kept thin.
 *
 * It speaks the CUBE'S PROTOCOL, routes the board already serves and a
 * second device already proved on his hardware:
 *
 *   UDP   "yuzu? where is the board"  ->  "yuzu-face <port>"
 *   GET   /boot.json                  is it really the face server
 *   GET   /characters.json            the roster: who is on the board
 *   GET   /stats                      the board's power mode, heat, watts
 *   POST  /listen     WAV             ->  {"heard"} -- his voice to text
 *   POST  /stream     {"text","who"}  ->  NDJSON, the last line the verdict
 *   POST  /voice.wav  {"text","who"}  ->  her voice, a WAV
 *
 * It asks as the girls' PAGE selves ("four", "yuzu"...), exactly like his
 * phone does, so the 3DS is one more window onto the same girl: same
 * memory, same /wiki, same everything, and no new persona to measure.
 */
#ifndef YUZU_BOARD_H
#define YUZU_BOARD_H

#include <stddef.h>

/* Held EQUAL to yuzu_face.CUBE_ASK / CUBE_ANSWER by a test. */
#define BOARD_ASK     "yuzu? where is the board"
#define BOARD_ANSWER  "yuzu-face "
#define BOARD_PORT    8081

/* The board's own WiFi always puts it here (own_wifi.sh, ipv4 shared). */
#define BOARD_OWN_WIFI_HOST  "10.42.0.1"

typedef struct {
    char host[48];
    int port;
} Board;

typedef struct {
    int status;          /* the HTTP status, or 0 when nothing came back */
    char ctype[64];      /* Content-Type, lower case */
    char *body;          /* malloc'd and NUL-terminated (binary too) */
    size_t len;
} Reply;

/* One girl on the roster, read off /characters.json -- never typed in
 * here. A roster that grows grows the 3DS with it. */
typedef struct {
    char who[24];        /* her NAME on the board, what she is asked as */
    char name[32];       /* what she is called */
    char blurb[48];
    char user[24];       /* what she calls him */
    int front;           /* whoever greets you */
    int sees;
} Girl;

#define BOARD_MAX_GIRLS 12

/* ---- the board itself ------------------------------------------------ */

int  board_http(const Board *b, const char *method, const char *path,
                const char *ctype, const void *body, size_t len,
                int connect_ms, int total_ms, volatile int *cancel,
                Reply *out);
void board_reply_free(Reply *r);

/* Ask by UDP. `to` may be a broadcast address. 1 and *found filled when
 * the board answered, else 0. */
int  board_ask(const char *to, int port, int wait_ms, Board *found);

/* 1 when the face server answers /boot.json at that address. */
int  board_alive(const Board *b, int ms);

/* Where the board is, cheapest first, the cube's order:
 *   1. `remembered`, "host" or "host:port" from last time ("" for none)
 *   2. the board's own WiFi, when `self` (the 3DS's address) is on it
 *   3. asking out loud: a broadcast, then the broadcast for self's /24
 *   4. the board's own WiFi address anyway
 * Every answer is checked with board_alive before it counts. 1 and *out
 * filled when found, and `how` says which way worked, for the screen. */
int  board_find(const char *remembered, const char *self, int port,
                volatile int *cancel, Board *out, char *how, size_t hn);

int  board_roster(const Board *b, Girl *girls, int max, volatile int *cancel);

/* "MAXN 51C 5.2W" or the throttle warning; "" when the board says nothing. */
int  board_stats(const Board *b, char *line, size_t n);

typedef struct {
    int ok;              /* she answered (else `shown` is the reason) */
    int reached;         /* the board answered at all */
    char *shown;         /* malloc'd: the words for the screen, ASCII */
    char *spoken;        /* malloc'd: what goes to her voice, UTF-8, or NULL */
} Turn;

int  board_turn(const Board *b, const char *who, const char *text,
                volatile int *cancel, Turn *t);
void board_turn_free(Turn *t);

/* His voice to text. 1 and `heard` filled, else 0 and `problem` says why. */
int  board_listen(const Board *b, const unsigned char *wav, size_t len,
                  volatile int *cancel, char *heard, size_t hn,
                  char *problem, size_t pn);

/* One piece of her voice. 1 and `wav` filled with a 200 audio/wav reply,
 * else 0 and `problem` says why (no voice installed, board gone). */
int  board_voice(const Board *b, const char *who, const char *text,
                 volatile int *cancel, Reply *wav, char *problem, size_t pn);

/* ---- small pieces, each tested on its own --------------------------- */

/* Where a voice piece ends: up to `max` bytes, at a sentence end, else a
 * comma, else a space -- never mid-word, never mid-character. Leading
 * space is skipped and counted in *skip. 0 means nothing left. */
size_t board_piece(const char *text, size_t max, size_t *skip);

/* The PCM inside a 16-bit WAV. 1 when it is one. */
int  board_wav_pcm16(const unsigned char *d, size_t len, int *rate,
                     int *channels, const unsigned char **pcm,
                     size_t *pcm_len);
void board_wav_header(unsigned char h[44], int rate, int channels,
                      unsigned long data_len);

/* A JSON value's start inside the object at `obj`, or NULL. Walks the
 * object's structure, so a key-looking string inside a VALUE never
 * matches. */
const char *json_find(const char *obj, const char *key);
const char *json_skip(const char *p);
int  json_string(const char *obj, const char *key, char *out, size_t n);
int  json_bool(const char *obj, const char *key, int *out);
int  json_number(const char *obj, const char *key, double *out);
/* His words as a JSON string body (no quotes). */
void json_escape(const char *in, char *out, size_t n);

/* UTF-8 folded IN PLACE to what an 8x8 console font can draw: curly
 * quotes and dashes become plain ones, the rest of what is not ASCII is
 * dropped. The cube's Font2 rule, for the same reason. */
void ascii_fold(char *s);

#endif
