/* What a REAL 3DS's sockets do that Linux's do not, so TestThe3DS can
 * drive board.c the way his 3DS does. Built into a second harness, with
 * board.c compiled under -Dpoll=yuzu_3ds_poll -Dgetsockopt=yuzu_3ds_getsockopt.
 *
 * The first two are REPORTED (libctru issues #542 and #412), and are
 * what turned away every connection on his 3DS on Nov 4 while the
 * suite, on Linux, was green:
 *   - a socket ready to send reports 0x08 as well as the send bit; in
 *     Linux's numbers 0x08 IS POLLERR, the very name libctru's header
 *     gives it, so board.c reads it here exactly as it does there;
 *   - SO_ERROR answers -26, the 3DS's own "still connecting", after the
 *     connection has landed.
 * The third is NOT reported, and is defended against anyway because it
 * costs nothing: a poll that never says the board hung up. board.c must
 * still see the end of a reply. */
#undef poll
#undef getsockopt

#include <poll.h>
#include <sys/socket.h>

int yuzu_3ds_poll(struct pollfd *f, nfds_t n, int ms)
{
    int r = poll(f, n, ms);
    for (nfds_t i = 0; r > 0 && i < n; i++) {
        if (f[i].revents & POLLOUT)
            f[i].revents |= POLLERR;
        char c;
        if ((f[i].events & POLLIN) && (f[i].revents & (POLLIN | POLLHUP))
            && recv(f[i].fd, &c, 1, MSG_PEEK | MSG_DONTWAIT) == 0)
            f[i].revents &= ~(POLLIN | POLLHUP);
    }
    if (r > 0) {
        r = 0;
        for (nfds_t i = 0; i < n; i++)
            r += f[i].revents != 0;
    }
    return r;
}

int yuzu_3ds_getsockopt(int fd, int level, int name, void *v, socklen_t *l)
{
    int r = getsockopt(fd, level, name, v, l);
    if (r == 0 && level == SOL_SOCKET && name == SO_ERROR
        && *l >= (socklen_t)sizeof(int))
        *(int *)v = -26;
    return r;
}
