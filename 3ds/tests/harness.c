/* The suite's way into board.c. NOT part of the 3DS build (it lives
 * outside source/): TestThe3DS compiles board.c with this, with the
 * ordinary gcc, and drives the real face server through it. One verb per
 * run, one answer per line, so Python reads it without guessing. */
#include "../source/board.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

static Board at(char **argv)
{
    Board b;
    snprintf(b.host, sizeof b.host, "%s", argv[2]);
    b.port = atoi(argv[3]);
    return b;
}

int main(int argc, char **argv)
{
    if (argc < 2)
        return 2;
    const char *verb = argv[1];

    if (!strcmp(verb, "ask") && argc == 5) {
        Board f;
        if (board_ask(argv[2], atoi(argv[3]), atoi(argv[4]), &f))
            printf("FOUND %s %d\n", f.host, f.port);
        else
            printf("NONE\n");
        return 0;
    }
    if (!strcmp(verb, "find") && argc == 5) {
        /* find <remembered> <self> <port>, "-" for an empty one */
        Board f;
        char how[32];
        const char *last = strcmp(argv[2], "-") ? argv[2] : "";
        const char *self = strcmp(argv[3], "-") ? argv[3] : "";
        if (board_find(last, self, atoi(argv[4]), NULL, &f, how, sizeof how))
            printf("FOUND %s %d %s\n", f.host, f.port, how);
        else
            printf("NONE\n");
        return 0;
    }
    if (!strcmp(verb, "wav") && argc == 5) {
        /* wav <path> <rate> <seconds>: the mic's WAV, written to a file */
        int rate = atoi(argv[3]);
        unsigned long n = (unsigned long)(rate * atof(argv[4]));
        unsigned char h[44];
        board_wav_header(h, rate, 1, n * 2);
        FILE *f = fopen(argv[2], "wb");
        if (!f)
            return 1;
        fwrite(h, 1, 44, f);
        for (unsigned long i = 0; i < n; i++) {
            short v = (short)(8000 * sin(2 * 3.14159265 * 440 * i / rate));
            fputc(v & 255, f);
            fputc((v >> 8) & 255, f);
        }
        fclose(f);
        printf("WROTE %lu\n", n);
        return 0;
    }
    if (!strcmp(verb, "alive") && argc == 4) {
        Board b = at(argv);
        printf("ALIVE %d\n", board_alive(&b, 1500));
        return 0;
    }
    if (!strcmp(verb, "roster") && argc == 4) {
        Board b = at(argv);
        Girl g[BOARD_MAX_GIRLS];
        int n = board_roster(&b, g, BOARD_MAX_GIRLS, NULL);
        printf("COUNT %d\n", n);
        for (int i = 0; i < n; i++)
            printf("GIRL %s|%s|%s|%s|%d|%d\n", g[i].who, g[i].name,
                   g[i].blurb, g[i].user, g[i].front, g[i].sees);
        return 0;
    }
    if (!strcmp(verb, "stats") && argc == 4) {
        Board b = at(argv);
        char line[96];
        board_stats(&b, line, sizeof line);
        printf("STATS %s\n", line);
        return 0;
    }
    if (!strcmp(verb, "turn") && argc == 6) {
        Board b = at(argv);
        Turn t;
        int got = board_turn(&b, argv[4], argv[5], NULL, &t);
        printf("GOT %d OK %d REACHED %d\n", got, t.ok, t.reached);
        printf("SHOWN %s\n", t.shown ? t.shown : "(null)");
        printf("SPOKEN %s\n", t.spoken ? t.spoken : "(null)");
        board_turn_free(&t);
        return 0;
    }
    if (!strcmp(verb, "listen") && argc == 6) {
        /* What the 3DS's mic hands over: PCM16 mono at its own odd rate,
         * here a second of a 440Hz tone behind the header board.c writes. */
        Board b = at(argv);
        int rate = atoi(argv[4]);
        unsigned long n = (unsigned long)(rate * atof(argv[5]));
        unsigned char *wav = malloc(44 + n * 2);
        board_wav_header(wav, rate, 1, n * 2);
        for (unsigned long i = 0; i < n; i++) {
            short s = (short)(8000 * sin(2 * 3.14159265 * 440 * i / rate));
            wav[44 + 2 * i] = s & 255;
            wav[45 + 2 * i] = (s >> 8) & 255;
        }
        char heard[512], problem[256];
        int ok = board_listen(&b, wav, 44 + n * 2, NULL, heard, sizeof heard,
                              problem, sizeof problem);
        printf(ok ? "HEARD %s\n" : "PROBLEM %s\n", ok ? heard : problem);
        free(wav);
        return 0;
    }
    if (!strcmp(verb, "voice") && argc == 6) {
        Board b = at(argv);
        Reply r;
        char problem[256];
        if (!board_voice(&b, argv[4], argv[5], NULL, &r, problem,
                         sizeof problem)) {
            printf("PROBLEM %s\n", problem);
            return 0;
        }
        int rate = 0, ch = 0;
        const unsigned char *pcm;
        size_t pl = 0;
        int ok = board_wav_pcm16((unsigned char *)r.body, r.len, &rate, &ch,
                                 &pcm, &pl);
        printf("WAV %d %d %d %lu\n", ok, rate, ch, (unsigned long)pl);
        board_reply_free(&r);
        return 0;
    }
    if (!strcmp(verb, "pieces") && argc == 4) {
        size_t max = (size_t)atoi(argv[2]), pos = 0, skip;
        const char *text = argv[3];
        for (;;) {
            size_t n = board_piece(text + pos, max, &skip);
            if (!n)
                break;
            printf("PIECE %.*s\n", (int)n, text + pos + skip);
            pos += skip + n;
        }
        printf("END\n");
        return 0;
    }
    if (!strcmp(verb, "fold") && argc == 3) {
        char *s = strdup(argv[2]);
        ascii_fold(s);
        printf("FOLD %s\n", s);
        free(s);
        return 0;
    }
    if (!strcmp(verb, "json") && argc == 4) {
        char out[256];
        int ok = json_string(argv[2], argv[3], out, sizeof out);
        printf("JSON %d %s\n", ok, out);
        return 0;
    }
    if (!strcmp(verb, "escape") && argc == 3) {
        char out[1024];
        json_escape(argv[2], out, sizeof out);
        printf("ESC %s\n", out);
        return 0;
    }
    return 2;
}
