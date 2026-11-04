/* The part of the 3DS app that talks to the board. See board.h.
 *
 * Compiled twice: by devkitARM for the 3DS, and by the suite's own gcc
 * for this machine, where TestThe3DS drives it against the real face
 * server. So it uses nothing but BSD sockets, poll() and libc -- and
 * every socket is NON-BLOCKING and waited on with poll(), because a
 * blocking connect to a board that has moved can hang for twenty
 * seconds on a handheld whose HOME button must keep working.
 */
#include "board.h"

#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>

#ifdef __3DS__
#include <3ds.h>
static unsigned long long now_ms(void) { return osGetTime(); }
#else
#include <time.h>
static unsigned long long now_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (unsigned long long)t.tv_sec * 1000ULL + t.tv_nsec / 1000000;
}
#endif

#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif

/* A voice piece is ~15s of 24kHz speech, ~720KB. Nothing the board sends
 * is near this; it only stops a runaway from eating the 3DS's memory. */
#define REPLY_MAX (8u * 1024u * 1024u)

/* ---- sockets --------------------------------------------------------- */

static int would_block(void)
{
    return errno == EAGAIN || errno == EWOULDBLOCK || errno == EINPROGRESS
        || errno == EALREADY;
}

/* WHY THE LAST TRY FAILED, in words for his screen. Only the worker
 * thread talks to the board, so one buffer is enough. */
static char why[112];

const char *board_why(void) { return why; }

/* HOW A 3DS SAYS "CONNECTED" IS NOT HOW LINUX SAYS IT, and the two
 * obvious checks both turned away every connection that worked on his
 * 3DS (libctru issues #542 and #412):
 *   - a socket ready to send reports 0x08 as well as 0x10, and libctru's
 *     header names 0x08 POLLERR ("probably");
 *   - SO_ERROR answers -26, the 3DS's own "still connecting", after the
 *     connection has landed.
 * So poll() only says that something happened, and the PEER decides:
 * getpeername() answers only for a socket that has one, on both
 * machines, and a 3DS answers a second connect() with EISCONN once the
 * first has landed. A 3DS's poll is also reported never to wake for a
 * connect that failed, so the wait is short slices up to a deadline. */
static int has_peer(int fd, const struct sockaddr_in *a)
{
    struct sockaddr_in peer;
    socklen_t pl = sizeof peer;
    if (getpeername(fd, (struct sockaddr *)&peer, &pl) == 0)
        return 1;
    return connect(fd, (const struct sockaddr *)a, sizeof *a) < 0
        && errno == EISCONN;
}

static int open_to(const char *host, int port, int ms)
{
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons((unsigned short)port);
    if (!inet_aton(host, &a.sin_addr)) {
        snprintf(why, sizeof why, "\"%s\" is not an address", host);
        return -1;
    }
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        snprintf(why, sizeof why, "the 3DS would not open a connection");
        return -1;
    }
    int fl = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, (fl < 0 ? 0 : fl) | O_NONBLOCK);
    if (connect(fd, (struct sockaddr *)&a, sizeof a) == 0)
        return fd;
    if (!would_block()) {
        snprintf(why, sizeof why, "%s:%d %s", host, port,
                 errno == ECONNREFUSED ? "turned it away"
                 : "is not reachable from this WiFi");
        close(fd);
        return -1;
    }
    unsigned long long until = now_ms() + (unsigned long long)ms;
    for (;;) {
        struct pollfd p = { fd, POLLOUT, 0 };
        int r = poll(&p, 1, 100);
        if (r > 0 && p.revents) {
            if (has_peer(fd, &a))
                return fd;
            snprintf(why, sizeof why, "%s:%d turned it away", host, port);
            break;
        }
        if (r < 0 && errno != EINTR) {
            snprintf(why, sizeof why, "the 3DS could not wait for %s:%d",
                     host, port);
            break;
        }
        if (now_ms() >= until) {
            snprintf(why, sizeof why, "nothing answered at %s:%d in %d "
                     "seconds", host, port, (ms + 999) / 1000);
            break;
        }
    }
    close(fd);
    return -1;
}

static int stopped(volatile int *cancel, unsigned long long until)
{
    return (cancel && *cancel) || now_ms() >= until;
}

static int send_all(int fd, const void *buf, size_t len,
                    unsigned long long until, volatile int *cancel)
{
    const char *p = buf;
    while (len) {
        if (stopped(cancel, until))
            return 0;
        ssize_t n = send(fd, p, len, MSG_NOSIGNAL);
        if (n > 0) {
            p += n;
            len -= (size_t)n;
            continue;
        }
        if (n < 0 && would_block()) {
            struct pollfd q = { fd, POLLOUT, 0 };
            poll(&q, 1, 250);
            continue;
        }
        return 0;
    }
    return 1;
}

static int lower_starts(const char *s, const char *prefix)
{
    for (; *prefix; s++, prefix++)
        if (tolower((unsigned char)*s) != *prefix)
            return 0;
    return 1;
}

/* Content-Length and Content-Type out of the header block, which ends at
 * `end`. A header's NAME is matched without regard to case; HTTP says so. */
static void read_headers(const char *head, const char *end, Reply *out,
                         long *length)
{
    *length = -1;
    const char *line = strstr(head, "\r\n");
    while (line && line < end) {
        line += 2;
        if (lower_starts(line, "content-length:"))
            *length = atol(line + 15);
        else if (lower_starts(line, "content-type:")) {
            const char *v = line + 13;
            while (*v == ' ')
                v++;
            size_t i = 0;
            while (v[i] && v[i] != '\r' && v[i] != ';'
                   && i < sizeof out->ctype - 1) {
                out->ctype[i] = (char)tolower((unsigned char)v[i]);
                i++;
            }
            out->ctype[i] = 0;
        }
        line = strstr(line, "\r\n");
    }
}

int board_http(const Board *b, const char *method, const char *path,
               const char *ctype, const void *body, size_t len,
               int connect_ms, int total_ms, volatile int *cancel,
               Reply *out)
{
    memset(out, 0, sizeof *out);
    unsigned long long until = now_ms() + (unsigned long long)total_ms;
    int fd = open_to(b->host, b->port, connect_ms);
    if (fd < 0)
        return 0;

    char head[512];
    int hl;
    if (body)
        hl = snprintf(head, sizeof head,
                      "%s %s HTTP/1.0\r\nHost: %s:%d\r\n"
                      "User-Agent: yuzu-3ds\r\nConnection: close\r\n"
                      "Content-Type: %s\r\nContent-Length: %lu\r\n\r\n",
                      method, path, b->host, b->port, ctype,
                      (unsigned long)len);
    else
        hl = snprintf(head, sizeof head,
                      "%s %s HTTP/1.0\r\nHost: %s:%d\r\n"
                      "User-Agent: yuzu-3ds\r\nConnection: close\r\n\r\n",
                      method, path, b->host, b->port);
    if (hl <= 0 || hl >= (int)sizeof head
        || !send_all(fd, head, (size_t)hl, until, cancel)
        || (body && len && !send_all(fd, body, len, until, cancel))) {
        snprintf(why, sizeof why, "%s:%d took the connection but not the "
                 "question", b->host, b->port);
        close(fd);
        return 0;
    }

    size_t cap = 16384, got = 0;
    char *buf = malloc(cap + 1);
    if (!buf) {
        close(fd);
        return 0;
    }
    int ok = 0;
    long want = -1;             /* the whole reply's size, once it is known */
    for (;;) {
        if (stopped(cancel, until))
            break;
        if (got == cap) {
            if (cap >= REPLY_MAX)
                break;
            size_t bigger = cap * 2 > REPLY_MAX ? REPLY_MAX : cap * 2;
            char *grown = realloc(buf, bigger + 1);
            if (!grown)
                break;
            buf = grown;
            cap = bigger;
        }
        /* recv decides, never poll's answer: a 3DS may not say that the
         * board hung up, and a recv on a non-blocking socket only waits
         * as long as the poll before it. */
        struct pollfd q = { fd, POLLIN, 0 };
        poll(&q, 1, 250);
        ssize_t n = recv(fd, buf + got, cap - got, 0);
        if (n > 0) {
            got += (size_t)n;
            buf[got] = 0;
            if (want < 0) {
                char *end = strstr(buf, "\r\n\r\n");
                if (end) {
                    Reply tmp;
                    long cl;
                    read_headers(buf, end, &tmp, &cl);
                    if (cl >= 0)
                        want = (long)(end + 4 - buf) + cl;
                }
            }
            /* A reply that has all of its Content-Length is whole. */
            if (want >= 0 && (long)got >= want) {
                ok = 1;
                break;
            }
            continue;
        }
        if (n == 0) {           /* the board closed it: the reply is whole */
            ok = 1;
            break;
        }
        if (would_block())
            continue;
        break;
    }
    close(fd);
    buf[got] = 0;

    char *split = strstr(buf, "\r\n\r\n");
    if (!ok || !split || strncmp(buf, "HTTP/", 5) != 0) {
        snprintf(why, sizeof why, "%s:%d %s", b->host, b->port,
                 !got ? "took the question and said nothing"
                 : !ok ? "stopped partway through its answer"
                 : "answered, but not like a web server");
        free(buf);
        return 0;
    }
    const char *sp = strchr(buf, ' ');
    out->status = sp ? atoi(sp + 1) : 0;
    long length;
    read_headers(buf, split, out, &length);
    size_t start = (size_t)(split + 4 - buf);
    size_t blen = got - start;
    /* SHORT IS NOT WHOLE. A voice piece cut off halfway would play as
     * half a sentence that looks like the whole one. */
    if (length >= 0 && (size_t)length > blen) {
        snprintf(why, sizeof why, "%s:%d stopped partway through its answer",
                 b->host, b->port);
        free(buf);
        memset(out, 0, sizeof *out);
        return 0;
    }
    memmove(buf, buf + start, blen);
    buf[blen] = 0;
    out->body = buf;
    out->len = blen;
    return 1;
}

void board_reply_free(Reply *r)
{
    free(r->body);
    r->body = NULL;
    r->len = 0;
}

int board_ask(const char *to, int port, int wait_ms, Board *found)
{
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons((unsigned short)port);
    if (!inet_aton(to, &a.sin_addr))
        return 0;
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0)
        return 0;
    /* The 3DS's own header says broadcast needs no asking; Linux does.
     * Either way a refusal here only costs the broadcast, so it is not
     * checked. */
    int on = 1;
    setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &on, sizeof on);
    int fl = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, (fl < 0 ? 0 : fl) | O_NONBLOCK);
    int hit = 0;
    if (sendto(fd, BOARD_ASK, strlen(BOARD_ASK), 0, (struct sockaddr *)&a,
               sizeof a) >= 0) {
        unsigned long long until = now_ms() + (unsigned long long)wait_ms;
        while (!hit && now_ms() < until) {
            struct pollfd q = { fd, POLLIN, 0 };
            if (poll(&q, 1, 100) <= 0)
                continue;
            char got[64];
            struct sockaddr_in from;
            socklen_t fl2 = sizeof from;
            ssize_t n = recvfrom(fd, got, sizeof got - 1, 0,
                                 (struct sockaddr *)&from, &fl2);
            if (n <= 0)
                continue;
            got[n] = 0;
            size_t al = strlen(BOARD_ANSWER);
            if ((size_t)n > al && memcmp(got, BOARD_ANSWER, al) == 0) {
                int p = atoi(got + al);
                if (p > 0 && p < 65536) {
                    /* WHO ANSWERED is the board: its address is the
                     * sender's, never anything written in the packet. */
                    snprintf(found->host, sizeof found->host, "%s",
                             inet_ntoa(from.sin_addr));
                    found->port = p;
                    hit = 1;
                }
            }
        }
    }
    close(fd);
    return hit;
}

int board_alive(const Board *b, int ms)
{
    Reply r;
    if (!board_http(b, "GET", "/boot.json", NULL, NULL, 0, ms, ms + 1500,
                    NULL, &r))
        return 0;
    /* Something answering on 8081 is not enough: it has to be HER server. */
    int yes = r.status == 200 && json_find(r.body, "boot") != NULL;
    if (!yes)
        snprintf(why, sizeof why, "%s:%d answered, but it is not the "
                 "board (HTTP %d)", b->host, b->port, r.status);
    board_reply_free(&r);
    return yes;
}

/* ---- JSON: only what the board's replies need ------------------------ */

/* A remembered or typed "host" or "host:port" -- or the whole address
 * off the board's screen, "http://192.168.4.163:8081/", since that is
 * what he has in front of him. 0 when it is not one. */
static int parse_at(const char *at, int port, Board *b)
{
    if (!at)
        return 0;
    while (*at == ' ' || *at == '\t')
        at++;
    if (lower_starts(at, "http://"))
        at += 7;
    else if (lower_starts(at, "https://"))
        at += 8;
    if (!*at)
        return 0;
    size_t n = strcspn(at, ":/ \t\r\n");
    if (n == 0 || n >= sizeof b->host)
        return 0;
    memcpy(b->host, at, n);
    b->host[n] = 0;
    b->port = port;
    if (at[n] == ':') {
        int p = atoi(at + n + 1);
        if (p > 0 && p < 65536)
            b->port = p;
    }
    return 1;
}

static int found_at(Board *b, Board *out, char *how, size_t hn,
                    const char *why)
{
    if (!board_alive(b, 2500))
        return 0;
    *out = *b;
    snprintf(how, hn, "%s", why);
    return 1;
}

int board_find(const char *remembered, const char *self, int port,
               volatile int *cancel, Board *out, char *how, size_t hn)
{
    Board b;
    int tried_own = 0;
    /* What went wrong at the address HE named is the news; the guesses
     * after it failing too is not. Kept, and put back at the end. */
    char named[sizeof why];
    named[0] = why[0] = 0;
    if (parse_at(remembered, port, &b)) {
        if (found_at(&b, out, how, hn, "remembered"))
            return 1;
        snprintf(named, sizeof named, "%s", why);
    }
    if (cancel && *cancel)
        return 0;
    if (self && !strncmp(self, "10.42.0.", 8)) {
        snprintf(b.host, sizeof b.host, "%s", BOARD_OWN_WIFI_HOST);
        b.port = port;
        tried_own = 1;
        if (found_at(&b, out, how, hn, "its own WiFi"))
            return 1;
    }
    if (cancel && *cancel)
        return 0;
    if (board_ask("255.255.255.255", port, 1500, &b)
        && found_at(&b, out, how, hn, "asked"))
        return 1;
    if (cancel && *cancel)
        return 0;
    struct in_addr me;
    if (self && inet_aton(self, &me)) {
        unsigned long ip = ntohl(me.s_addr);
        struct in_addr all;
        all.s_addr = htonl((ip & 0xFFFFFF00UL) | 0xFF);
        char to[20];
        snprintf(to, sizeof to, "%s", inet_ntoa(all));
        if (board_ask(to, port, 1500, &b) && found_at(&b, out, how, hn, "asked"))
            return 1;
    }
    if (cancel && *cancel)
        return 0;
    if (!tried_own) {
        snprintf(b.host, sizeof b.host, "%s", BOARD_OWN_WIFI_HOST);
        b.port = port;
        if (found_at(&b, out, how, hn, "its own WiFi"))
            return 1;
    }
    if (named[0])
        snprintf(why, sizeof why, "%s", named);
    else
        snprintf(why, sizeof why, "nobody on this WiFi answered when it "
                 "asked");
    return 0;
}

static const char *ws(const char *p)
{
    while (p && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r'))
        p++;
    return p;
}

static const char *skip_string(const char *p)
{
    if (*p != '"')
        return NULL;
    for (p++; *p; p++) {
        if (*p == '\\') {
            if (!p[1])
                return NULL;
            p++;
        } else if (*p == '"')
            return p + 1;
    }
    return NULL;
}

const char *json_skip(const char *p)
{
    p = ws(p);
    if (!p || !*p)
        return NULL;
    if (*p == '"')
        return skip_string(p);
    if (*p == '{' || *p == '[') {
        int depth = 0;
        while (*p) {
            if (*p == '"') {
                p = skip_string(p);
                if (!p)
                    return NULL;
                continue;
            }
            if (*p == '{' || *p == '[')
                depth++;
            else if (*p == '}' || *p == ']') {
                if (--depth == 0)
                    return p + 1;
            }
            p++;
        }
        return NULL;
    }
    while (*p && *p != ',' && *p != '}' && *p != ']' && *p != ' '
           && *p != '\n' && *p != '\r' && *p != '\t')
        p++;
    return p;
}

const char *json_find(const char *obj, const char *key)
{
    const char *p = ws(obj);
    if (!p || *p != '{')
        return NULL;
    p++;
    size_t kl = strlen(key);
    for (;;) {
        p = ws(p);
        if (*p != '"')
            return NULL;
        const char *kend = skip_string(p);
        if (!kend)
            return NULL;
        /* Keys on this board are plain words, so a raw compare is exact. */
        int match = (size_t)(kend - p - 2) == kl
                    && memcmp(p + 1, key, kl) == 0;
        p = ws(kend);
        if (*p != ':')
            return NULL;
        p = ws(p + 1);
        if (match)
            return p;
        p = json_skip(p);
        if (!p)
            return NULL;
        p = ws(p);
        if (*p == ',') {
            p++;
            continue;
        }
        return NULL;
    }
}

static void put_utf8(char **o, char *end, unsigned cp)
{
    char b[4];
    int n;
    if (cp < 0x80) { b[0] = (char)cp; n = 1; }
    else if (cp < 0x800) {
        b[0] = (char)(0xC0 | (cp >> 6)); b[1] = (char)(0x80 | (cp & 0x3F));
        n = 2;
    } else if (cp < 0x10000) {
        b[0] = (char)(0xE0 | (cp >> 12));
        b[1] = (char)(0x80 | ((cp >> 6) & 0x3F));
        b[2] = (char)(0x80 | (cp & 0x3F)); n = 3;
    } else {
        b[0] = (char)(0xF0 | (cp >> 18));
        b[1] = (char)(0x80 | ((cp >> 12) & 0x3F));
        b[2] = (char)(0x80 | ((cp >> 6) & 0x3F));
        b[3] = (char)(0x80 | (cp & 0x3F)); n = 4;
    }
    if (*o + n > end)
        return;                     /* never half a character */
    memcpy(*o, b, (size_t)n);
    *o += n;
}

static unsigned hex4(const char *p, int *ok)
{
    unsigned v = 0;
    for (int i = 0; i < 4; i++) {
        char c = p[i];
        v <<= 4;
        if (c >= '0' && c <= '9') v |= (unsigned)(c - '0');
        else if (c >= 'a' && c <= 'f') v |= (unsigned)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') v |= (unsigned)(c - 'A' + 10);
        else { *ok = 0; return 0; }
    }
    return v;
}

int json_string(const char *obj, const char *key, char *out, size_t n)
{
    if (!n)
        return 0;
    out[0] = 0;
    const char *p = json_find(obj, key);
    if (!p || *p != '"')
        return 0;
    char *o = out, *end = out + n - 1;
    for (p++; *p && *p != '"'; p++) {
        if (*p != '\\') {
            if (o < end)
                *o++ = *p;
            continue;
        }
        p++;
        switch (*p) {
        case 'n': if (o < end) *o++ = '\n'; break;
        case 't': if (o < end) *o++ = '\t'; break;
        case 'r': break;
        case 'b': case 'f': break;
        case 'u': {
            int ok = 1;
            unsigned cp = hex4(p + 1, &ok);
            if (!ok)
                return 0;
            p += 4;
            if (cp >= 0xD800 && cp < 0xDC00 && p[1] == '\\' && p[2] == 'u') {
                unsigned lo = hex4(p + 3, &ok);
                if (ok && lo >= 0xDC00 && lo < 0xE000) {
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                    p += 6;
                }
            }
            put_utf8(&o, end, cp);
            break;
        }
        case 0: return 0;
        default: if (o < end) *o++ = *p; break;      /* \" \\ \/ */
        }
    }
    /* A cut in the middle of a character leaves a broken one at the end;
     * take it off rather than hand the screen half a letter. */
    char *lead = o;
    while (lead > out && ((unsigned char)lead[-1] & 0xC0) == 0x80)
        lead--;
    if (lead > out && (unsigned char)lead[-1] >= 0xC0) {
        unsigned char c = (unsigned char)lead[-1];
        int need = c >= 0xF0 ? 4 : c >= 0xE0 ? 3 : 2;
        if (o - (lead - 1) < need)
            o = lead - 1;
    }
    *o = 0;
    return 1;
}

int json_bool(const char *obj, const char *key, int *out)
{
    const char *p = json_find(obj, key);
    if (!p)
        return 0;
    if (!strncmp(p, "true", 4)) { *out = 1; return 1; }
    if (!strncmp(p, "false", 5)) { *out = 0; return 1; }
    return 0;
}

int json_number(const char *obj, const char *key, double *out)
{
    const char *p = json_find(obj, key);
    if (!p || !(*p == '-' || (*p >= '0' && *p <= '9')))
        return 0;
    *out = strtod(p, NULL);
    return 1;
}

void json_escape(const char *in, char *out, size_t n)
{
    size_t o = 0;
    for (; *in && o + 7 < n; in++) {
        unsigned char c = (unsigned char)*in;
        if (c == '"' || c == '\\') {
            out[o++] = '\\';
            out[o++] = (char)c;
        } else if (c == '\n') {
            out[o++] = '\\';
            out[o++] = 'n';
        } else if (c < 0x20) {
            o += (size_t)snprintf(out + o, n - o, "\\u%04x", c);
        } else
            out[o++] = (char)c;
    }
    out[o] = 0;
}

void ascii_fold(char *s)
{
    unsigned char *r = (unsigned char *)s, *w = (unsigned char *)s;
    while (*r) {
        unsigned c = *r, cp, len;
        if (c < 0x80) {
            if (c == '\t') *w++ = ' ';
            else if (c != '\r') *w++ = (unsigned char)c;
            r++;
            continue;
        }
        if (c >= 0xF0) { cp = c & 0x07; len = 4; }
        else if (c >= 0xE0) { cp = c & 0x0F; len = 3; }
        else if (c >= 0xC0) { cp = c & 0x1F; len = 2; }
        else { r++; continue; }             /* a stray continuation byte */
        unsigned i;
        for (i = 1; i < len && (r[i] & 0xC0) == 0x80; i++)
            cp = (cp << 6) | (r[i] & 0x3F);
        r += i;
        if (i < len)
            continue;
        const char *swap = NULL;
        switch (cp) {
        case 0x2018: case 0x2019: case 0x201A: case 0x2032: swap = "'"; break;
        case 0x201C: case 0x201D: case 0x201E: case 0x2033: swap = "\""; break;
        case 0x2013: case 0x2014: case 0x2015: case 0x2212: swap = "-"; break;
        case 0x2026: swap = "..."; break;
        case 0x00A0: swap = " "; break;
        case 0x00D7: swap = "x"; break;
        case 0x2022: case 0x00B7: swap = "*"; break;
        default: break;                     /* emoji and the rest: dropped */
        }
        /* In place, so a swap may never be longer than what it replaces:
         * every one above is, at most, as long as its UTF-8. */
        if (swap && strlen(swap) <= i) {
            size_t sl = strlen(swap);
            memcpy(w, swap, sl);
            w += sl;
        }
    }
    *w = 0;
}

/* ---- the board's answers --------------------------------------------- */

int board_roster(const Board *b, Girl *girls, int max, volatile int *cancel)
{
    Reply r;
    if (!board_http(b, "GET", "/characters.json", NULL, NULL, 0, 3000,
                    8000, cancel, &r))
        return -1;
    int n = 0;
    const char *p = r.status == 200 ? ws(r.body) : NULL;
    if (p && *p == '[') {
        p++;
        while (n < max) {
            p = ws(p);
            if (*p != '{')
                break;
            Girl *g = &girls[n];
            memset(g, 0, sizeof *g);
            json_string(p, "who", g->who, sizeof g->who);
            json_string(p, "name", g->name, sizeof g->name);
            json_string(p, "blurb", g->blurb, sizeof g->blurb);
            json_string(p, "user", g->user, sizeof g->user);
            json_bool(p, "front", &g->front);
            json_bool(p, "sees", &g->sees);
            ascii_fold(g->name);
            ascii_fold(g->blurb);
            ascii_fold(g->user);
            if (g->who[0]) {
                if (!g->name[0])
                    snprintf(g->name, sizeof g->name, "%s", g->who);
                n++;
            }
            p = json_skip(p);
            if (!p)
                break;
            p = ws(p);
            if (*p == ',')
                p++;
        }
    }
    board_reply_free(&r);
    return n;
}

int board_stats(const Board *b, char *line, size_t n)
{
    line[0] = 0;
    Reply r;
    if (!board_http(b, "GET", "/stats", NULL, NULL, 0, 2000, 4000, NULL, &r))
        return 0;
    if (r.status == 200) {
        char power[32] = "", throttled[64] = "";
        double temp = 0, watts = 0, percent = 0;
        json_string(r.body, "throttled", throttled, sizeof throttled);
        json_string(r.body, "power", power, sizeof power);
        int has_temp = json_number(r.body, "temp", &temp);
        int has_watts = json_number(r.body, "watts", &watts);
        int has_pct = json_number(r.body, "percent", &percent);
        /* THE THROTTLE REMINDER WINS THE LINE: the Orin ships throttled,
         * and a slow girl with no visible cause is the fault it exists
         * to end. It is the board's own sentence, never one typed here. */
        if (throttled[0])
            snprintf(line, n, "%s", throttled);
        else {
            size_t o = 0;
            if (power[0])
                o += (size_t)snprintf(line + o, n - o, "%s", power);
            if (has_temp && o < n)
                o += (size_t)snprintf(line + o, n - o, "%s%.0fC",
                                      o ? " " : "", temp);
            if (has_watts && o < n)
                o += (size_t)snprintf(line + o, n - o, "%s%.1fW",
                                      o ? " " : "", watts);
            else if (has_pct && o < n)
                o += (size_t)snprintf(line + o, n - o, "%s%.0f%%",
                                      o ? " " : "", percent);
        }
    }
    board_reply_free(&r);
    return line[0] != 0;
}

static char *dupe(const char *s)
{
    size_t l = strlen(s);
    char *d = malloc(l + 1);
    if (d)
        memcpy(d, s, l + 1);
    return d;
}

int board_turn(const Board *b, const char *who, const char *text,
               volatile int *cancel, Turn *t)
{
    memset(t, 0, sizeof *t);
    size_t cap = strlen(text) * 6 + 128;
    char *esc = malloc(cap), *body = malloc(cap + 96);
    if (!esc || !body) {
        free(esc);
        free(body);
        return 0;
    }
    json_escape(text, esc, cap);
    int bl = snprintf(body, cap + 96, "{\"text\": \"%s\", \"who\": \"%s\"}",
                      esc, who);
    free(esc);
    Reply r;
    /* THREE MINUTES, the cube's own clock: a cold model's first reply,
     * or a swap to Zero's Qwen, is the slow one, and /stream sends its
     * headers at once so a long wait is never mistaken for a dead board. */
    int got = board_http(b, "POST", "/stream", "application/json", body,
                         (size_t)bl, 3000, 180000, cancel, &r);
    free(body);
    if (!got)
        return 0;
    t->reached = 1;
    /* THE LAST LINE CARRIES THE VERDICT. Pieces before it are her words
     * as they came, which this screen does not show one at a time -- he
     * reads fast, and a reply that types itself out made him wait. */
    const char *verdict = NULL;
    for (char *line = r.body; line && *line;) {
        char *nl = strchr(line, '\n');
        if (nl)
            *nl = 0;
        int done = 0;
        if (json_bool(line, "done", &done) && done)
            verdict = line;
        line = nl ? nl + 1 : NULL;
    }
    if (!verdict) {
        t->shown = dupe("(Her reply stopped halfway. Ask her again.)");
        board_reply_free(&r);
        return 1;
    }
    size_t vl = strlen(verdict) + 1;
    char *said = malloc(vl), *spoken = malloc(vl);
    if (!said || !spoken) {
        free(said);
        free(spoken);
        board_reply_free(&r);
        return 0;
    }
    json_string(verdict, "said", said, vl);
    json_string(verdict, "spoken", spoken, vl);
    int ok = 0;
    json_bool(verdict, "ok", &ok);
    t->ok = ok;
    if (ok) {
        /* WHAT SHE SAYS is what the screen shows, the cube's rule: the box
         * and the voice can never disagree about a word. Except code,
         * which her voice drops and the screen must not. */
        int code = strstr(said, "```") != NULL;
        t->shown = dupe(spoken[0] && !code ? spoken : said);
        t->spoken = dupe(spoken[0] ? spoken : said);
    } else
        t->shown = dupe(said[0] ? said : "(She couldn't answer.)");
    free(said);
    free(spoken);
    if (t->shown)
        ascii_fold(t->shown);
    board_reply_free(&r);
    return 1;
}

void board_turn_free(Turn *t)
{
    free(t->shown);
    free(t->spoken);
    t->shown = t->spoken = NULL;
}

int board_listen(const Board *b, const unsigned char *wav, size_t len,
                 volatile int *cancel, char *heard, size_t hn,
                 char *problem, size_t pn)
{
    heard[0] = problem[0] = 0;
    Reply r;
    /* Whisper on the board's CPU: a minute of him is a while to hear. */
    if (!board_http(b, "POST", "/listen", "audio/wav", wav, len, 3000, 90000,
                    cancel, &r)) {
        snprintf(problem, pn, "The board didn't answer.");
        return 0;
    }
    int ok = 0;
    json_bool(r.body, "ok", &ok);
    json_string(r.body, "heard", heard, hn);
    if (!ok || !heard[0]) {
        if (!json_string(r.body, "said", problem, pn) || !problem[0])
            snprintf(problem, pn, "She didn't catch that.");
        ascii_fold(problem);
        heard[0] = 0;
    }
    board_reply_free(&r);
    return heard[0] != 0;
}

int board_voice(const Board *b, const char *who, const char *text,
                volatile int *cancel, Reply *wav, char *problem, size_t pn)
{
    problem[0] = 0;
    size_t cap = strlen(text) * 6 + 128;
    char *esc = malloc(cap), *body = malloc(cap + 96);
    if (!esc || !body) {
        free(esc);
        free(body);
        return 0;
    }
    json_escape(text, esc, cap);
    int bl = snprintf(body, cap + 96, "{\"text\": \"%s\", \"who\": \"%s\"}",
                      esc, who);
    free(esc);
    int got = board_http(b, "POST", "/voice.wav", "application/json", body,
                         (size_t)bl, 3000, 120000, cancel, wav);
    free(body);
    if (!got) {
        snprintf(problem, pn, "Her voice didn't come through.");
        return 0;
    }
    if (wav->status != 200 || strcmp(wav->ctype, "audio/wav") != 0) {
        /* A SENTENCE WITH A REAL STATUS, never a 200 pretending to be
         * sound: the board says why she has no voice. */
        if (!json_string(wav->body, "said", problem, pn) || !problem[0])
            snprintf(problem, pn, "Her voice didn't come through.");
        ascii_fold(problem);
        board_reply_free(wav);
        return 0;
    }
    return 1;
}

/* ---- her voice, and his ---------------------------------------------- */

size_t board_piece(const char *text, size_t max, size_t *skip)
{
    size_t i = 0;
    while (text[i] == ' ' || text[i] == '\n' || text[i] == '\t'
           || text[i] == '\r')
        i++;
    *skip = i;
    const char *s = text + i;
    size_t n = strlen(s);
    if (n <= max)
        return n;
    size_t cut = 0, k;
    /* Where a sentence ends: punctuation THEN a space, so 3.14 stays whole. */
    for (k = 0; k + 1 < max; k++)
        if ((s[k] == '.' || s[k] == '!' || s[k] == '?')
            && (s[k + 1] == ' ' || s[k + 1] == '\n'))
            cut = k + 1;
        else if (s[k] == '\n' && k > 0)
            cut = k;
    if (!cut)
        for (k = 0; k + 1 < max; k++)
            if (s[k] == ',' && s[k + 1] == ' ')
                cut = k + 1;
    if (!cut)
        for (k = 1; k < max; k++)
            if (s[k] == ' ')
                cut = k;
    if (!cut) {
        cut = max;
        while (cut > 1 && ((unsigned char)s[cut] & 0xC0) == 0x80)
            cut--;
    }
    return cut;
}

static unsigned le16(const unsigned char *p) { return p[0] | (p[1] << 8); }
static unsigned long le32(const unsigned char *p)
{
    return (unsigned long)p[0] | ((unsigned long)p[1] << 8)
         | ((unsigned long)p[2] << 16) | ((unsigned long)p[3] << 24);
}

int board_wav_pcm16(const unsigned char *d, size_t len, int *rate,
                    int *channels, const unsigned char **pcm, size_t *pcm_len)
{
    if (len < 12 || memcmp(d, "RIFF", 4) || memcmp(d + 8, "WAVE", 4))
        return 0;
    int have_fmt = 0;
    size_t at = 12;
    while (at + 8 <= len) {
        unsigned long size = le32(d + at + 4);
        const unsigned char *c = d + at + 8;
        if (!memcmp(d + at, "fmt ", 4) && size >= 16 && at + 8 + 16 <= len) {
            unsigned tag = le16(c);
            /* PCM, or the extensible header around PCM. 16-bit only. */
            if ((tag != 1 && tag != 0xFFFE) || le16(c + 14) != 16)
                return 0;
            *channels = (int)le16(c + 2);
            *rate = (int)le32(c + 4);
            if (*channels < 1 || *channels > 2 || *rate < 4000)
                return 0;
            have_fmt = 1;
        } else if (!memcmp(d + at, "data", 4)) {
            if (!have_fmt)
                return 0;
            size_t avail = len - (at + 8);
            *pcm = c;
            *pcm_len = size < avail ? size : avail;
            *pcm_len -= *pcm_len % (size_t)(2 * *channels);
            return *pcm_len > 0;
        }
        at += 8 + size + (size & 1);
    }
    return 0;
}

void board_wav_header(unsigned char h[44], int rate, int channels,
                      unsigned long data_len)
{
    unsigned long byte_rate = (unsigned long)rate * channels * 2;
    unsigned long riff = 36 + data_len;
    memcpy(h, "RIFF", 4);
    h[4] = riff & 255; h[5] = (riff >> 8) & 255;
    h[6] = (riff >> 16) & 255; h[7] = (riff >> 24) & 255;
    memcpy(h + 8, "WAVEfmt ", 8);
    h[16] = 16; h[17] = h[18] = h[19] = 0;
    h[20] = 1; h[21] = 0;                       /* PCM */
    h[22] = (unsigned char)channels; h[23] = 0;
    h[24] = rate & 255; h[25] = (rate >> 8) & 255;
    h[26] = (rate >> 16) & 255; h[27] = (rate >> 24) & 255;
    h[28] = byte_rate & 255; h[29] = (byte_rate >> 8) & 255;
    h[30] = (byte_rate >> 16) & 255; h[31] = (byte_rate >> 24) & 255;
    h[32] = (unsigned char)(channels * 2); h[33] = 0;
    h[34] = 16; h[35] = 0;
    memcpy(h + 36, "data", 4);
    h[40] = data_len & 255; h[41] = (data_len >> 8) & 255;
    h[42] = (data_len >> 16) & 255; h[43] = (data_len >> 24) & 255;
}
