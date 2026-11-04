/* YUZU on the 3DS: her picture on the top screen, the conversation on the
 * bottom one, and the board doing everything else.
 *
 * THE 3DS IS A WINDOW, LIKE HIS PHONE AND THE CUBE. Her brain, memory,
 * ears (Whisper) and voice (Kokoro) all stay on the board; this asks for
 * them over WiFi, exactly as her page does, and as the same girl -- so
 * what she says here she remembers on his phone.
 *
 *   A, or a TAP on the bottom screen   the 3DS's own keyboard: type with
 *                                      the stylus, Send
 *   hold L or R                        talk; let go to send
 *   B                                  stop her (her voice and her reply)
 *   left / right                       the next girl
 *   up / down                          scroll back through what she said
 *   X                                  look for the board again
 *   Y                                  type the board's address
 *   SELECT                             her voice on or off
 *   START                              quit
 *
 * TWO THREADS. This one draws and reads the buttons; the worker does the
 * network, which can take seconds, so the screens never freeze while she
 * thinks. Only this thread ever draws. The worker changes state under
 * `lk` and says what changed.
 *
 * EVERYTHING THAT TALKS TO THE BOARD IS IN board.c, which the suite
 * compiles and drives against the real face server. This file is the 3DS
 * half and cannot be run anywhere but a 3DS: keep it thin.
 */
#include <3ds.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <malloc.h>
#include <arpa/inet.h>

#include "board.h"
#include "art.h"

#define TOP_W   50
#define BOT_W   40
#define WRAP    (BOT_W - 1)      /* a full row would wrap by itself */
#define LOG_ROWS 27
#define LOG_MAX 600
#define REMEMBER "sdmc:/3ds/yuzu3ds.txt"

/* The 3DS mic's real rate (libctru: "16364.479 Hz"). Whisper resamples. */
#define MIC_RATE 16364
#define MIC_RING 0x30000
#define REC_SECONDS 30
#define REC_MAX ((size_t)MIC_RATE * 2 * REC_SECONDS)

#define C_HIM   37
#define C_NOTE  33

/* ---- state the worker and the drawing share, under `lk` -------------- */

static LightLock lk;

typedef struct {
    char text[BOT_W];
    int colour;
    int girl;           /* whose conversation, or -1 for everyone's */
} Line;

static Line lines[LOG_MAX];
static int line_count;             /* how many are in the ring */
static int line_head;              /* the oldest */
static int scroll_back;            /* rows up from the newest */

static Girl girls[BOARD_MAX_GIRLS];
static int girl_count;
static int cur;                    /* the girl on screen */

static Board board;
static int have_board;
static char board_how[32];
static char stats_line[96];
static char status_line[64];

static volatile int dirty_log, dirty_top, dirty_art, dirty_status;

/* ---- the worker's orders --------------------------------------------- */

enum { T_NONE, T_FIND, T_TURN, T_LISTEN };

static volatile int task = T_NONE;
static volatile int busy;
static volatile int cancel;
static volatile int hush;
static volatile int running = 1;
static int task_girl;
static char task_text[1024];
static char typed_at[64];          /* an address he typed, for T_FIND */
static unsigned char *rec;         /* header + his voice */
static size_t rec_len;

static int ac_ok;                  /* the 3DS's WiFi status can be read */
static int voice_ok;               /* the sound firmware loaded */
static int voice_on = 1;
static int voice_told;             /* a missing voice is said once */
static int mic_ok, mic_tried;
static u8 *mic_ring;
static u32 mic_size, mic_pos;
static int recording, want_record;

/* ---- the conversation ------------------------------------------------ */

/* Under `lk`. */
static void push_line(const char *text, int colour, int girl)
{
    int at;
    if (line_count < LOG_MAX) {
        at = (line_head + line_count) % LOG_MAX;
        line_count++;
    } else {
        at = line_head;
        line_head = (line_head + 1) % LOG_MAX;
    }
    snprintf(lines[at].text, sizeof lines[at].text, "%s", text);
    lines[at].colour = colour;
    lines[at].girl = girl;
}

/* A message, wrapped to the bottom screen between words: `label` starts
 * its first row, a line break she wrote is kept, and a word too long for
 * a row is cut rather than lost. */
static void say(int girl, int colour, const char *label, const char *text)
{
    char *t = strdup(text ? text : "");
    if (!t)
        return;
    ascii_fold(t);
    LightLock_Lock(&lk);
    char row[BOT_W];
    size_t used = 0;
    row[0] = 0;
    if (label && *label) {
        used = (size_t)snprintf(row, sizeof row, "%s ", label);
        if (used > WRAP)
            used = WRAP;
    }
    const char *p = t;
    while (*p) {
        if (*p == '\n') {
            push_line(row, colour, girl);
            row[0] = 0;
            used = 0;
            p++;
            continue;
        }
        if (*p == ' ' && used == 0) {
            p++;
            continue;
        }
        size_t w = strcspn(p, " \n");
        if (w == 0) {                          /* a space between words */
            if (used < WRAP) {
                row[used++] = ' ';
                row[used] = 0;
            }
            p++;
            continue;
        }
        if (used + w > WRAP && used > 0) {     /* the next row */
            while (used && row[used - 1] == ' ')
                row[--used] = 0;
            push_line(row, colour, girl);
            row[0] = 0;
            used = 0;
            continue;
        }
        if (w > WRAP)                          /* longer than a row */
            w = WRAP - used;
        memcpy(row + used, p, w);
        used += w;
        row[used] = 0;
        p += w;
    }
    if (used || !*t)
        push_line(row, colour, girl);
    scroll_back = 0;
    dirty_log = 1;
    LightLock_Unlock(&lk);
    free(t);
}

static void note(const char *text)
{
    say(-1, C_NOTE, "", text);
}

static int colour_of(const char *who)
{
    for (int i = 0; i < ART_COUNT; i++)
        if (!strcmp(ARTS[i].who, who))
            return ARTS[i].colour;
    return 37;
}

static const Art *art_of(const char *who)
{
    for (int i = 0; i < ART_COUNT; i++)
        if (!strcmp(ARTS[i].who, who) && *ARTS[i].size == ART_BYTES)
            return &ARTS[i];
    return NULL;
}

static void upper(char *out, size_t n, const char *in)
{
    size_t i = 0;
    for (; in[i] && i + 1 < n; i++)
        out[i] = (in[i] >= 'a' && in[i] <= 'z') ? in[i] - 32 : in[i];
    out[i] = 0;
}

static void set_status(const char *s)
{
    LightLock_Lock(&lk);
    snprintf(status_line, sizeof status_line, "%s", s);
    dirty_status = 1;
    LightLock_Unlock(&lk);
}

/* ---- her voice (worker thread) --------------------------------------- */

typedef struct {
    ndspWaveBuf wb;
    void *mem;
} Slot;

static Slot slots[2];

static int slot_done(Slot *s)
{
    return ((volatile ndspWaveBuf *)&s->wb)->status == NDSP_WBUF_DONE;
}

/* Gives back what has finished playing, and everything on a hush. */
static void audio_service(void)
{
    if (!voice_ok)
        return;
    if (hush) {
        ndspChnWaveBufClear(0);
        svcSleepThread(40 * 1000000LL);
        for (int i = 0; i < 2; i++) {
            if (slots[i].mem)
                linearFree(slots[i].mem);
            slots[i].mem = NULL;
        }
        hush = 0;
        return;
    }
    for (int i = 0; i < 2; i++)
        if (slots[i].mem && slot_done(&slots[i])) {
            linearFree(slots[i].mem);
            slots[i].mem = NULL;
        }
}

/* One piece onto the speaker, after the one before it. Waits for a free
 * slot, so at most one piece plays while the next is fetched. */
static int queue_piece(Reply *wav)
{
    int rate, ch;
    const unsigned char *pcm;
    size_t len;
    if (!board_wav_pcm16((const unsigned char *)wav->body, wav->len, &rate,
                         &ch, &pcm, &len) || len < 4)
        return 0;
    Slot *s = NULL;
    while (!s) {
        if (cancel || hush || !running)
            return 0;
        audio_service();
        for (int i = 0; i < 2 && !s; i++)
            if (!slots[i].mem)
                s = &slots[i];
        if (!s)
            svcSleepThread(20 * 1000000LL);
    }
    s->mem = linearAlloc(len);
    if (!s->mem)
        return 0;
    memcpy(s->mem, pcm, len);
    DSP_FlushDataCache(s->mem, len);
    memset(&s->wb, 0, sizeof s->wb);
    s->wb.data_vaddr = s->mem;
    s->wb.nsamples = len / (2 * (size_t)ch);
    if (!slots[0].mem || !slots[1].mem) {   /* nothing else is queued */
        ndspChnSetFormat(0, ch == 2 ? NDSP_FORMAT_STEREO_PCM16
                                    : NDSP_FORMAT_MONO_PCM16);
        ndspChnSetRate(0, (float)rate);
    }
    ndspChnWaveBufAdd(0, &s->wb);
    return 1;
}

/* Her words in pieces, the pages' rule: a short first piece so she starts
 * soon, longer after, cut where a sentence ends. */
static void speak(const char *who, const char *text)
{
    if (!voice_ok || !voice_on || !text || !*text)
        return;
    size_t pos = 0;
    int first = 1;
    while (!cancel && !hush && running) {
        size_t skip, n = board_piece(text + pos, first ? 120 : 220, &skip);
        if (!n)
            break;
        char piece[512];
        if (n >= sizeof piece)
            n = sizeof piece - 1;
        memcpy(piece, text + pos + skip, n);
        piece[n] = 0;
        pos += skip + n;
        Reply wav;
        char problem[200];
        if (!board_voice(&board, who, piece, &cancel, &wav, problem,
                         sizeof problem)) {
            if (!cancel && !voice_told) {
                note(problem);
                voice_told = 1;
            }
            return;
        }
        if (first)
            set_status("");
        first = 0;
        int ok = queue_piece(&wav);
        board_reply_free(&wav);
        if (!ok)
            return;
    }
}

/* ---- the worker ------------------------------------------------------ */

static void own_address(char *out, size_t n)
{
    out[0] = 0;
    u32 wifi = 0;
    if (ac_ok && (R_FAILED(ACU_GetWifiStatus(&wifi)) || !wifi))
        return;
    struct in_addr a;
    a.s_addr = (in_addr_t)gethostid();
    if (a.s_addr)
        snprintf(out, n, "%s", inet_ntoa(a));
}

static void remember(const Board *b)
{
    FILE *f = fopen(REMEMBER, "w");
    if (!f)
        return;
    fprintf(f, "%s:%d\n", b->host, b->port);
    fclose(f);
}

static void remembered(char *out, size_t n)
{
    out[0] = 0;
    FILE *f = fopen(REMEMBER, "r");
    if (!f)
        return;
    if (!fgets(out, (int)n, f))
        out[0] = 0;
    fclose(f);
    out[strcspn(out, "\r\n")] = 0;
}

static void refresh_stats(void)
{
    char line[96];
    if (!board_stats(&board, line, sizeof line))
        line[0] = 0;
    LightLock_Lock(&lk);
    snprintf(stats_line, sizeof stats_line, "%s", line);
    dirty_top = 1;
    LightLock_Unlock(&lk);
}

static void do_find(void)
{
    char self[24], last[64];
    own_address(self, sizeof self);
    if (!self[0]) {
        note("(This 3DS is not on a WiFi. Join ghostnano, or your home "
             "WiFi, in System Settings > Internet Settings, then press X.)");
        return;
    }
    if (typed_at[0]) {
        snprintf(last, sizeof last, "%s", typed_at);
        typed_at[0] = 0;
    } else {
        remembered(last, sizeof last);
    }
    set_status("Looking for the board...");
    Board found;
    char how[32];
    if (!board_find(last, self, BOARD_PORT, &cancel, &found, how,
                    sizeof how)) {
        set_status("");
        if (!cancel)
            note("(Can't find the board. Is it on, and is this 3DS on "
                 "ghostnano or the same WiFi? X looks again, Y types its "
                 "address.)");
        return;
    }
    Girl got[BOARD_MAX_GIRLS];
    int n = board_roster(&found, got, BOARD_MAX_GIRLS, &cancel);
    remember(&found);
    LightLock_Lock(&lk);
    char was[24];
    snprintf(was, sizeof was, "%s", girl_count ? girls[cur].who : "");
    board = found;
    have_board = 1;
    snprintf(board_how, sizeof board_how, "%s", how);
    girl_count = n > 0 ? n : 0;
    memcpy(girls, got, sizeof(Girl) * (size_t)girl_count);
    cur = 0;
    for (int i = 0; i < girl_count; i++)
        if (girls[i].front)
            cur = i;
    for (int i = 0; i < girl_count; i++)
        if (was[0] && !strcmp(girls[i].who, was))
            cur = i;
    dirty_top = dirty_art = dirty_log = 1;
    LightLock_Unlock(&lk);
    set_status("");
    char line[128];             /* room for any host and any `how` */
    snprintf(line, sizeof line, "(Found the board at %s -- %s.)",
             found.host, how);
    note(line);
    if (n <= 0)
        note("(The board answered, but listed nobody. Tap Update on "
             "his phone, then press X.)");
    refresh_stats();
}

static void do_turn(int g, const char *text)
{
    char who[24];
    LightLock_Lock(&lk);
    snprintf(who, sizeof who, "%s", girls[g].who);
    LightLock_Unlock(&lk);
    set_status("She's thinking...");
    Turn t;
    board_turn(&board, who, text, &cancel, &t);
    set_status("");
    if (cancel) {
        note("(Stopped.)");
    } else if (!t.reached) {
        note("(The board isn't answering. X looks for it again.)");
    } else if (!t.ok) {
        say(g, C_NOTE, "", t.shown);
    } else {
        char label[40];
        upper(label, sizeof label - 1, girls[g].name);
        strcat(label, ":");
        say(g, colour_of(who), label, t.shown);
        if (t.spoken && voice_on && voice_ok) {
            set_status("Her voice...");
            speak(who, t.spoken);
            set_status("");
        }
    }
    board_turn_free(&t);
}

static void his_line(int g, const char *text)
{
    char label[40];
    upper(label, sizeof label - 1, girls[g].user[0] ? girls[g].user : "you");
    strcat(label, ":");
    say(g, C_HIM, label, text);
}

static void do_listen(int g)
{
    set_status("Hearing you...");
    char heard[1024], problem[200];
    int ok = board_listen(&board, rec, rec_len, &cancel, heard, sizeof heard,
                          problem, sizeof problem);
    set_status("");
    if (cancel)
        return;
    if (!ok) {
        note(problem);
        return;
    }
    if (!heard[0]) {
        note("(Heard nothing. Hold L or R the whole time you talk.)");
        return;
    }
    his_line(g, heard);
    do_turn(g, heard);
}

static void worker(void *arg)
{
    u64 last_stats = osGetTime();
    while (running) {
        audio_service();
        int t = task;
        if (t == T_NONE) {
            if (have_board && osGetTime() - last_stats > 20000) {
                refresh_stats();
                last_stats = osGetTime();
            }
            svcSleepThread(30 * 1000000LL);
            continue;
        }
        cancel = 0;
        if (t == T_FIND)
            do_find();
        else if (t == T_TURN)
            do_turn(task_girl, task_text);
        else if (t == T_LISTEN)
            do_listen(task_girl);
        last_stats = osGetTime();
        task = T_NONE;
        busy = 0;
    }
}

static void order(int t)
{
    busy = 1;
    task = t;
}

/* ---- drawing (this thread only) -------------------------------------- */

static PrintConsole top_bar, top_mid, top_foot, bot_log, bot_status, bot_help;

/* One row, overwritten whole: home, the words, spaces to the end. Never a
 * newline, so a one-row window can never scroll. */
static void row(PrintConsole *c, int width, int colour, const char *text)
{
    consoleSelect(c);
    c->cursorX = c->cursorY = 0;    /* home, without trusting an escape */
    char buf[64];
    snprintf(buf, sizeof buf, "%-*.*s", width - 1, width - 1, text);
    printf("\x1b[%d;1m%s\x1b[0m", colour, buf);
}

static void draw_art(void)
{
    u8 *fb = gfxGetFramebuffer(GFX_TOP, GFX_LEFT, NULL, NULL);
    const Art *a = girl_count ? art_of(girls[cur].who) : NULL;
    if (a) {
        memcpy(fb, a->px, ART_BYTES);
        return;
    }
    /* A girl with no picture gets a plain screen and her name: absent
     * rather than wrong, never another girl's face. */
    memset(fb, 0, ART_BYTES);
    char mid[TOP_W];
    const char *name = girl_count ? girls[cur].name : "YUZU";
    int pad = (TOP_W - 1 - (int)strlen(name)) / 2;
    snprintf(mid, sizeof mid, "%*s%s", pad > 0 ? pad : 0, "", name);
    row(&top_mid, TOP_W, girl_count ? colour_of(girls[cur].who) : 35, mid);
}

static void draw_top(int frame)
{
    /* Wide enough for anything put in them; row() cuts to the screen. */
    char bar[160], foot[160];
    int colour = 35;
    if (girl_count) {
        Girl *g = &girls[cur];
        char name[32];
        upper(name, sizeof name, g->name);
        colour = colour_of(g->who);
        if (busy && task_girl == cur && task != T_FIND)
            snprintf(bar, sizeof bar, " %s  thinking%.*s", name,
                     (frame / 20) % 4, "...");
        else
            snprintf(bar, sizeof bar, " %s  %s", name, g->blurb);
        char where[32];
        snprintf(where, sizeof where, "< %d/%d >", cur + 1, girl_count);
        size_t bl = strlen(bar), wl = strlen(where);
        if (bl + wl + 1 < TOP_W - 1) {
            memset(bar + bl, ' ', TOP_W - 1 - wl - bl - 1);
            snprintf(bar + TOP_W - 1 - wl - 1, wl + 2, "%s", where);
        }
    } else {
        snprintf(bar, sizeof bar, " YUZU for 3DS");
    }
    row(&top_bar, TOP_W, colour, bar);
    if (have_board)
        snprintf(foot, sizeof foot, " board %s  %s", board.host, stats_line);
    else
        snprintf(foot, sizeof foot, " no board yet -- X looks for it");
    row(&top_foot, TOP_W, 37, foot);
}

static void draw_log(void)
{
    consoleSelect(&bot_log);
    consoleClear();
    int idx[LOG_MAX], n = 0;
    for (int i = 0; i < line_count; i++) {
        int at = (line_head + i) % LOG_MAX;
        if (lines[at].girl < 0 || lines[at].girl == cur)
            idx[n++] = at;
    }
    if (scroll_back > n - LOG_ROWS)
        scroll_back = n - LOG_ROWS > 0 ? n - LOG_ROWS : 0;
    int end = n - scroll_back;
    int start = end - LOG_ROWS > 0 ? end - LOG_ROWS : 0;
    for (int i = start; i < end; i++) {
        Line *l = &lines[idx[i]];
        printf("\x1b[%d%sm%s\x1b[0m%s", l->colour,
               l->colour == C_NOTE ? "" : ";1", l->text,
               i + 1 < end ? "\n" : "");
    }
}

static void draw_help(void)
{
    consoleSelect(&bot_help);
    bot_help.cursorX = bot_help.cursorY = 0;
    printf("\x1b[37m%-39s\n%-39s\x1b[0m",
           "A/tap:type  L/R hold:talk  B:stop  <>",
           voice_on ? "X:find  Y:addr  SEL:mute  START:quit"
                    : "X:find  Y:addr  SEL:unmute  START:quit");
}

static void draw_status(int frame)
{
    char s[64];
    if (recording)
        snprintf(s, sizeof s, "Listening%.*s let go to send",
                 (frame / 15) % 4, "...");
    else
        snprintf(s, sizeof s, "%s", status_line);
    row(&bot_status, BOT_W, 33, s);
}

static volatile int restored;

static void on_apt(APT_HookType hook, void *param)
{
    if (hook == APTHOOK_ONRESTORE || hook == APTHOOK_ONWAKEUP)
        restored = 1;
}

/* ---- his side -------------------------------------------------------- */

static int keyboard(const char *hint, const char *start, char *out,
                    size_t n)
{
    SwkbdState kb;
    swkbdInit(&kb, SWKBD_TYPE_NORMAL, 2, (int)n - 1);
    swkbdSetHintText(&kb, hint);
    if (start)
        swkbdSetInitialText(&kb, start);
    swkbdSetButton(&kb, SWKBD_BUTTON_LEFT, "Cancel", false);
    swkbdSetButton(&kb, SWKBD_BUTTON_RIGHT, "Send", true);
    swkbdSetValidation(&kb, SWKBD_NOTEMPTY_NOTBLANK, 0, 0);
    out[0] = 0;
    SwkbdButton b = swkbdInputText(&kb, out, n);
    restored = 1;
    return b == SWKBD_BUTTON_CONFIRM && out[0];
}

static int refuse_busy(void)
{
    if (!busy)
        return 0;
    note("(Wait for her to finish, or press B.)");
    return 1;
}

static void type_to_her(void)
{
    if (refuse_busy())
        return;
    if (!have_board || !girl_count) {
        note("(No board yet. X looks for it.)");
        return;
    }
    char text[501];             /* the keyboard's own limit, his page's is 2000 */
    if (!keyboard("Say something, or /wiki cats", NULL, text, sizeof text))
        return;
    task_girl = cur;
    snprintf(task_text, sizeof task_text, "%s", text);
    his_line(cur, text);
    order(T_TURN);
}

static void start_recording(void)
{
    if (!mic_tried) {
        mic_tried = 1;
        mic_ring = memalign(0x1000, MIC_RING);
        rec = malloc(44 + REC_MAX);
        Result r = mic_ring && rec ? micInit(mic_ring, MIC_RING) : -1;
        mic_ok = R_SUCCEEDED(r);
        if (mic_ok) {
            mic_size = micGetSampleDataSize();
        } else {
            char line[80];
            snprintf(line, sizeof line, "(The mic would not start: 0x%08lX.)",
                     (unsigned long)r);
            note(line);
        }
    }
    if (!mic_ok)
        return;
    rec_len = 44;
    mic_pos = 0;
    if (R_FAILED(MICU_StartSampling(MICU_ENCODING_PCM16_SIGNED,
                                    MICU_SAMPLE_RATE_16360, 0, mic_size,
                                    true))) {
        note("(The mic would not listen.)");
        return;
    }
    recording = 1;
}

static void keep_recording(void)
{
    u32 from = mic_pos;
    mic_pos = micGetLastSampleOffset();
    while (from != mic_pos && rec_len < 44 + REC_MAX) {
        rec[rec_len++] = mic_ring[from];
        from = (from + 1) % mic_size;
    }
}

static void stop_recording(void)
{
    MICU_StopSampling();
    recording = 0;
    want_record = 0;            /* a held button never starts a second one */
    size_t pcm = rec_len - 44;
    if (pcm < (size_t)MIC_RATE * 2 * 4 / 10) {
        note("(Too short -- hold L or R the whole time you talk.)");
        return;
    }
    pcm &= ~(size_t)1;
    board_wav_header(rec, MIC_RATE, 1, (unsigned long)pcm);
    rec_len = 44 + pcm;
    task_girl = cur;
    order(T_LISTEN);
}

/* ---- the app --------------------------------------------------------- */

int main(int argc, char **argv)
{
    gfxInitDefault();
    LightLock_Init(&lk);

    /* Three windows on the top screen: the name bar, the middle (only
     * for a girl with no picture) and the foot. Her picture goes under
     * them; a one-row window never scrolls, so it never moves her. */
    consoleInit(GFX_TOP, &top_bar);
    consoleInit(GFX_TOP, &top_mid);
    consoleInit(GFX_TOP, &top_foot);
    consoleSetWindow(&top_bar, 0, 0, TOP_W, 1);
    consoleSetWindow(&top_mid, 0, 14, TOP_W, 1);
    consoleSetWindow(&top_foot, 0, 29, TOP_W, 1);
    consoleInit(GFX_BOTTOM, &bot_log);
    consoleInit(GFX_BOTTOM, &bot_status);
    consoleInit(GFX_BOTTOM, &bot_help);
    consoleSetWindow(&bot_log, 0, 0, BOT_W, LOG_ROWS);
    consoleSetWindow(&bot_status, 0, 27, BOT_W, 1);
    consoleSetWindow(&bot_help, 0, 28, BOT_W, 2);

    aptHookCookie cookie;
    aptHook(&cookie, on_apt, NULL);

    ac_ok = R_SUCCEEDED(acInit());
    u32 *soc_mem = memalign(0x1000, 0x100000);
    if (!soc_mem || R_FAILED(socInit(soc_mem, 0x100000)))
        note("(The 3DS's network would not start. Restart the app.)");

    voice_ok = R_SUCCEEDED(ndspInit());
    if (voice_ok) {
        ndspSetOutputMode(NDSP_OUTPUT_STEREO);
        ndspChnSetInterp(0, NDSP_INTERP_LINEAR);
        float mix[12] = { 1.0f, 1.0f };
        ndspChnSetMix(0, mix);
    } else {
        note("(No sound: this 3DS's sound firmware is not dumped. Run DSP1 "
             "once from the Homebrew Launcher. She still talks in text.)");
    }

    note("YUZU for 3DS. A or a tap types to her, hold L or R to talk.");

    s32 prio = 0x30;
    svcGetThreadPriority(&prio, CUR_THREAD_HANDLE);
    Thread th = threadCreate(worker, NULL, 64 * 1024, prio - 1, -2, false);
    order(T_FIND);

    int frame = 0;
    dirty_art = dirty_top = dirty_log = dirty_status = 1;
    while (aptMainLoop()) {
        hidScanInput();
        u32 down = hidKeysDown(), held = hidKeysHeld(), up = hidKeysUp();
        frame++;

        if (down & KEY_START)
            break;
        if (down & KEY_B) {
            cancel = 1;
            hush = 1;
        }
        if (down & KEY_SELECT) {
            voice_on = !voice_on;
            if (!voice_on)
                hush = 1;
            draw_help();
        }
        if (down & KEY_X) {
            if (!refuse_busy())
                order(T_FIND);
        }
        if (down & KEY_Y) {
            if (!refuse_busy()) {
                char at[64];
                if (keyboard("The board's address, like 10.42.0.1",
                             have_board ? board.host : BOARD_OWN_WIFI_HOST,
                             at, sizeof at)) {
                    snprintf(typed_at, sizeof typed_at, "%s", at);
                    order(T_FIND);
                }
            }
        }
        if (down & (KEY_DLEFT | KEY_DRIGHT | KEY_CPAD_LEFT | KEY_CPAD_RIGHT)) {
            if (girl_count > 1 && !refuse_busy()) {
                LightLock_Lock(&lk);
                int step = (down & (KEY_DRIGHT | KEY_CPAD_RIGHT)) ? 1 : -1;
                cur = (cur + step + girl_count) % girl_count;
                scroll_back = 0;
                dirty_art = dirty_top = dirty_log = 1;
                LightLock_Unlock(&lk);
                hush = 1;
            }
        }
        if (down & (KEY_DUP | KEY_CPAD_UP)) {
            scroll_back += 3;
            dirty_log = 1;
        }
        if (down & (KEY_DDOWN | KEY_CPAD_DOWN)) {
            scroll_back = scroll_back > 3 ? scroll_back - 3 : 0;
            dirty_log = 1;
        }
        if ((down & KEY_A) || (down & KEY_TOUCH))
            type_to_her();

        /* Hold to talk. A hold while she answers stops her first, and the
         * recording starts the moment she has stopped. */
        if (down & (KEY_L | KEY_R)) {
            if (!have_board || !girl_count) {
                note("(No board yet. X looks for it.)");
            } else {
                want_record = 1;
                hush = 1;
                if (busy)
                    cancel = 1;
            }
        }
        if (want_record && !recording && !busy && (held & (KEY_L | KEY_R)))
            start_recording();
        if (recording) {
            keep_recording();
            if (!(held & (KEY_L | KEY_R)) || rec_len >= 44 + REC_MAX)
                stop_recording();
        }
        if ((up & (KEY_L | KEY_R)) && !(held & (KEY_L | KEY_R)))
            want_record = 0;

        if (restored) {
            restored = 0;
            dirty_art = dirty_top = dirty_log = dirty_status = 1;
        }
        LightLock_Lock(&lk);
        if (dirty_art) {
            dirty_art = 0;
            dirty_top = 1;
            draw_art();
        }
        if (dirty_top || (busy && frame % 20 == 0)) {
            dirty_top = 0;
            draw_top(frame);
        }
        if (dirty_log) {
            dirty_log = 0;
            draw_log();
            draw_help();
        }
        if (dirty_status || recording || frame % 15 == 0) {
            dirty_status = 0;
            draw_status(frame);
        }
        LightLock_Unlock(&lk);

        gfxFlushBuffers();
        gfxSwapBuffers();
        gspWaitForVBlank();
    }

    running = 0;
    cancel = 1;
    hush = 1;
    if (recording)
        MICU_StopSampling();
    threadJoin(th, 5000000000ULL);
    threadFree(th);
    if (voice_ok) {
        ndspChnWaveBufClear(0);
        for (int i = 0; i < 2; i++)
            if (slots[i].mem)
                linearFree(slots[i].mem);
        ndspExit();
    }
    if (mic_ok)
        micExit();
    free(mic_ring);
    free(rec);
    socExit();
    free(soc_mem);
    if (ac_ok)
        acExit();
    aptUnhook(&cookie);
    gfxExit();
    return 0;
}
