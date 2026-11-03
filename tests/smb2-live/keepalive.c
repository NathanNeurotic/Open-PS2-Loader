/* Host harness for smb2man.c's keepalive: a session lost under open handles (a keepalive ECHO, an
   ECHO devctl, a read or a write that fails), the reconnect and its backoff, and LOGOFF /
   CLOSESHARE while the session is lost. It includes smb2man.c, so it can run keepalive passes by
   hand (on the host no thread or alarm runs) and see the driver's state. The connection is cut on
   the client's side: shutdown() both ways, so the next request fails as it does when a server goes
   away, or the socket swapped for a dead end that takes requests and never answers, so requests
   still go out and their replies never come.
   Wrappers around smb2_echo() and smb2_connect_share() can let alarm ticks fire while those calls
   wait, as they do when a request times out on the IOP.
   Built with AddressSanitizer, whose leak check at exit fails the run if a dropped session leaves a
   file handle or a directory listing allocated. Built and run by run.sh. */
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include <smb2/smb2.h>
#include <smb2/libsmb2.h>
#include <smb2/libsmb2-share-enum.h>
#include <smb2/libsmb2-raw.h>

/* Alarm ticks that fire while a request waits. On the IOP a failed echo or a refused reconnect can
   wait out the 15 s timeout, 5 ticks; on the host the alarm never fires by itself, so these wrappers
   run the alarm handler ticks_during_call times when the call returns. */
static int ticks_during_call;
static unsigned int smb2man_keepalive_alarm(void *arg);
static void ticks_while_waiting(void)
{
    int i;

    for (i = 0; i < ticks_during_call; i++)
        smb2man_keepalive_alarm(NULL);
}
static int slow_echo(struct smb2_context *s)
{
    int rv = smb2_echo(s);

    ticks_while_waiting();
    return rv;
}
static int slow_connect_share(struct smb2_context *s, const char *server, const char *share, const char *user)
{
    int rv = smb2_connect_share(s, server, share, user);

    ticks_while_waiting();
    return rv;
}
#define smb2_echo          slow_echo
#define smb2_connect_share slow_connect_share
#include "smb2man.c"
#undef smb2_echo
#undef smb2_connect_share

int AddDrv(iop_device_t *d)
{
    return d->ops->init(d);
}
int DelDrv(const char *n)
{
    (void)n;
    return 0;
}

static int fails;
#define CHECK(c, ...)         \
    do {                      \
        if (!(c)) {           \
            fails++;          \
            printf("FAIL: "); \
        } else {              \
            printf("ok: ");   \
        }                     \
        printf(__VA_ARGS__);  \
        printf("\n");         \
    } while (0)

#define OPS (&smb2man_ops)

static int logon(const char *ip, int port, const char *user, const char *pw)
{
    smbLogOn_in_t l;
    smbGetPasswordHashes_in_t in;
    smbGetPasswordHashes_out_t out;

    memset(&l, 0, sizeof(l));
    strcpy(l.serverIP, ip);
    l.serverPort = port;
    strcpy(l.User, user);
    strcpy(in.password, pw);
    if (OPS->devctl(NULL, "", SMB_DEVCTL_GETPASSWORDHASHES, &in, sizeof(in), &out, sizeof(out)) == 0) {
        l.PasswordType = HASHED_PASSWORD;
        memcpy(l.Password, &out, 32);
    } else {
        l.PasswordType = PLAINTEXT_PASSWORD;
        strcpy(l.Password, pw);
    }
    return OPS->devctl(NULL, "", SMB_DEVCTL_LOGON, &l, sizeof(l), NULL, 0);
}

static int openshare(const char *name)
{
    smbOpenShare_in_t o;

    memset(&o, 0, sizeof(o));
    strcpy(o.ShareName, name);
    o.PasswordType = NO_PASSWORD;
    return OPS->devctl(NULL, "", SMB_DEVCTL_OPENSHARE, &o, sizeof(o), NULL, 0);
}

static int echo(void)
{
    return OPS->devctl(NULL, "", SMB_DEVCTL_ECHO, NULL, 0, NULL, 0);
}

// One alarm tick and the keepalive pass it wakes.
static void tick(void)
{
    smb2man_keepalive_alarm(NULL);
    smb2man_keepalive_pass();
}

// The server goes away: the next request on this session fails. After an earlier failed check
// smb2 can be NULL: then there is nothing to cut, and the checks that follow report the state.
static void cut(void)
{
    if (smb2 != NULL)
        shutdown(smb2_get_fd(smb2), SHUT_RDWR);
}

/* Requests still go out, and their replies never come. The session's socket is swapped for one end
   of a socket pair whose other end takes the requests, never answers and has shut its sending side,
   so the client reads an end of file whatever the timing. A shutdown(SHUT_RD) of the TCP socket
   would not do: Linux still delivers a reply that arrives before the client reads, and on a busy or
   one-CPU machine the server can answer first, so the request would succeed. */
static int dead_end = -1;
static void cut_read(void)
{
    int sv[2];

    if (smb2 == NULL || socketpair(AF_UNIX, SOCK_STREAM, 0, sv) != 0)
        return;
    dup2(sv[0], smb2_get_fd(smb2)); // this also closes the TCP connection to the server
    close(sv[0]);
    shutdown(sv[1], SHUT_WR);
    if (dead_end >= 0)
        close(dead_end);
    dead_end = sv[1]; // kept open, so requests can still be written to it
}

static int lost(void)
{
    return smb2 == NULL && !share_open && session_lost;
}

int main(int argc, char **argv)
{
    /* argv: ip port user password share */
    const char *ip, *user, *pw, *share;
    unsigned char buf[64];
    iox_dirent_t de;
    iop_file_t f = {0}, f2 = {0}, d = {0}, d2 = {0};
    char server[sizeof(conn_server)];
    u32 retry;
    int port = 0, i, attempts;

    if (argc < 6) {
        fprintf(stderr, "usage: keepalive ip port user password share\n");
        return 2;
    }
    ip = argv[1];
    user = argv[3];
    pw = argv[4];
    share = argv[5];
    for (i = 0; argv[2][i] >= '0' && argv[2][i] <= '9'; i++)
        port = port * 10 + (argv[2][i] - '0');
    signal(SIGPIPE, SIG_IGN);         // a write on the cut socket must fail, not end the process
    setvbuf(stdout, NULL, _IONBF, 0); // the leak check ends the process without flushing stdout

    CHECK(smb2man_start(0, NULL) == 0, "module start");
    CHECK(logon(ip, port, user, pw) == 0 && openshare(share) == 0, "logon + openshare");

    /* A live session: the pass echoes and keeps it */
    tick();
    CHECK(smb2 != NULL && share_open && !session_lost && echo() == 0, "a pass on a live session keeps it");

    /* Lost with a file and a directory open */
    CHECK(OPS->open(&f, "\\DVD\\TEST.iso", FIO_O_RDONLY, 0) >= 0 && OPS->read(&f, buf, 16) == 16, "open + read");
    CHECK(OPS->dopen(&d, "\\DVD") == 0 && OPS->dread(&d, &de) == 1, "dopen + one dread");
    cut();
    tick();
    CHECK(lost(), "a failed keepalive echo drops the session");
    CHECK(echo() == -EIO, "ECHO reports the lost session");
    CHECK(OPS->read(&f, buf, 16) == -EBADF && OPS->close(&f) == -EBADF, "the file handle is stale");
    CHECK(OPS->dread(&d, &de) == -EBADF, "the directory handle is stale");
    CHECK(OPS->dclose(&d) == 0 && d.privdata == NULL, "dclose of the stale directory handle");

    /* The first reconnect waits for the next tick: ticks that came during the failed echo have
       already signalled the thread, so it runs another pass at once, and a reconnect the menu
       starts after ECHO reported the loss must go first. */
    smb2man_keepalive_pass();
    CHECK(lost(), "no reconnect in the pass right after the drop");
    tick();
    CHECK(smb2 != NULL && share_open && !session_lost, "reconnected on the next tick");
    CHECK(echo() == 0, "ECHO after the reconnect");
    CHECK(OPS->open(&f, "\\DVD\\TEST.iso", FIO_O_RDONLY, 0) >= 0 && OPS->read(&f, buf, 16) == 16 && buf[1] == 10,
          "open + read after the reconnect");
    CHECK(OPS->close(&f) == 0, "close");
    CHECK(OPS->dopen(&d, "\\DVD") == 0 && OPS->dread(&d, &de) == 1 && OPS->dclose(&d) == 0, "list after the reconnect");

    /* A failed reconnect is retried only after the backoff */
    cut();
    tick();
    CHECK(lost(), "dropped again");
    memcpy(server, conn_server, sizeof(server));
    strcpy(conn_server, "127.0.0.1:9"); // nothing listens there: the reconnect is refused
    tick();
    retry = keepalive_retry_at;
    CHECK(lost() && retry == keepalive_ticks + KEEPALIVE_RETRY_SECONDS / KEEPALIVE_SECONDS, "a refused reconnect sets the backoff");
    for (attempts = 0, i = 1; i < KEEPALIVE_RETRY_SECONDS / KEEPALIVE_SECONDS; i++) {
        tick();
        if (keepalive_retry_at != retry || !lost())
            attempts++;
    }
    CHECK(attempts == 0, "no attempt during the backoff (%d)", attempts);
    memcpy(conn_server, server, sizeof(server));
    tick();
    CHECK(smb2 != NULL && share_open && !session_lost, "reconnected when the backoff ran out");

    /* LOGOFF while lost: nothing reconnects */
    cut();
    tick();
    CHECK(lost(), "dropped again");
    CHECK(OPS->devctl(NULL, "", SMB_DEVCTL_LOGOFF, NULL, 0, NULL, 0) == 0, "logoff while lost");
    for (i = 0; i < KEEPALIVE_RETRY_SECONDS / KEEPALIVE_SECONDS + 2; i++)
        tick();
    CHECK(smb2 == NULL && !share_open && !session_lost && echo() == -ENODEV, "no reconnect after logoff");

    /* CLOSESHARE while lost: nothing reconnects, the logon stays */
    CHECK(logon(ip, port, user, pw) == 0 && openshare(share) == 0, "logon + openshare");
    cut();
    tick();
    CHECK(lost(), "dropped again");
    CHECK(OPS->devctl(NULL, "", SMB_DEVCTL_CLOSESHARE, NULL, 0, NULL, 0) == 0, "closeshare while lost");
    for (i = 0; i < KEEPALIVE_RETRY_SECONDS / KEEPALIVE_SECONDS + 2; i++)
        tick();
    CHECK(!share_open && !session_lost && echo() == 0, "no reconnect after closeshare");
    CHECK(openshare(share) == 0 && echo() == 0, "openshare again");

    /* A share change and a logoff free the listings of directories still open */
    CHECK(OPS->dopen(&d, "\\DVD") == 0 && OPS->dopen(&d2, "\\") == 0, "two directories open");
    CHECK(OPS->devctl(NULL, "", SMB_DEVCTL_CLOSESHARE, NULL, 0, NULL, 0) == 0 && openshare(share) == 0, "share closed and opened again");
    CHECK(OPS->dread(&d, &de) == -EBADF && OPS->dclose(&d) == 0, "a directory open across the share change is stale");
    CHECK(OPS->dopen(&d, "\\DVD") == 0, "a third directory");
    CHECK(OPS->devctl(NULL, "", SMB_DEVCTL_LOGOFF, NULL, 0, NULL, 0) == 0, "logoff with two directories open");
    CHECK(OPS->dread(&d, &de) == -EBADF && OPS->dclose(&d) == 0 && OPS->dclose(&d2) == 0, "both are stale and close");

    /* An ECHO that fails drops the session too, with a file open */
    CHECK(logon(ip, port, user, pw) == 0 && openshare(share) == 0, "logon + openshare");
    CHECK(OPS->open(&f, "\\DVD\\TEST.iso", FIO_O_RDONLY, 0) >= 0, "open");
    cut();
    CHECK(echo() == -EIO && lost(), "a failed ECHO drops the session");
    smb2man_keepalive_pass();
    CHECK(lost(), "no reconnect in the pass right after the drop");
    CHECK(OPS->close(&f) == -EBADF, "the file handle is stale");
    CHECK(OPS->devctl(NULL, "", SMB_DEVCTL_LOGOFF, NULL, 0, NULL, 0) == 0, "logoff");

    /* A read or a write that fails drops the session too. After cut_read(), the request and the
       closes queued for the open files have gone out when the context goes, so destroying it
       completes them from libsmb2's wait queue (the cases above complete them from its send queue);
       the leak check sees whether every handle was freed. */
    CHECK(logon(ip, port, user, pw) == 0 && openshare(share) == 0, "logon + openshare");
    CHECK(OPS->open(&f, "\\DVD\\TEST.iso", FIO_O_RDONLY, 0) >= 0 && OPS->open(&f2, "\\VMC\\card.bin", FIO_O_RDONLY, 0) >= 0,
          "two files open");
    CHECK(OPS->dopen(&d, "\\DVD") == 0 && OPS->dread(&d, &de) == 1, "dopen + one dread");
    cut_read();
    CHECK(OPS->read(&f, buf, 16) == -EIO && lost(), "a failed read drops the session");
    CHECK(OPS->read(&f2, buf, 16) == -EBADF && OPS->close(&f) == -EBADF && OPS->close(&f2) == -EBADF,
          "both file handles are stale");
    CHECK(OPS->dread(&d, &de) == -EBADF && OPS->dclose(&d) == 0, "the directory handle is stale");
    smb2man_keepalive_pass();
    CHECK(lost(), "no reconnect in the pass right after the drop");
    tick();
    CHECK(smb2 != NULL && share_open && !session_lost && echo() == 0, "reconnected on the next tick");
    CHECK(OPS->open(&f, "\\VMC\\ka.bin", FIO_O_RDWR | FIO_O_CREAT | FIO_O_TRUNC, 0666) >= 0 && OPS->write(&f, buf, 16) == 16,
          "a file open for writing");
    cut_read();
    CHECK(OPS->write(&f, buf, 16) == -EIO && lost(), "a failed write drops the session");
    CHECK(OPS->close(&f) == -EBADF, "the file handle is stale");
    tick();
    CHECK(smb2 != NULL && share_open && !session_lost && echo() == 0, "reconnected on the next tick");
    CHECK(OPS->devctl(NULL, "", SMB_DEVCTL_LOGOFF, NULL, 0, NULL, 0) == 0, "logoff");

    /* Ticks that fire while a request waits: the first reconnect still waits for the tick after the
       drop, and the backoff runs from the end of the refused reconnect, not from its start. */
    CHECK(logon(ip, port, user, pw) == 0 && openshare(share) == 0, "logon + openshare");
    memcpy(server, conn_server, sizeof(server));
    ticks_during_call = 5;
    cut();
    tick();
    CHECK(lost() && keepalive_retry_at == keepalive_ticks + 1, "a drop after a slow echo waits for the next tick");
    smb2man_keepalive_pass();
    CHECK(lost(), "no reconnect in the pass right after a slow drop");
    strcpy(conn_server, "127.0.0.1:9"); // refused
    tick();
    CHECK(lost() && keepalive_retry_at == keepalive_ticks + KEEPALIVE_RETRY_SECONDS / KEEPALIVE_SECONDS,
          "the backoff runs from the end of a slow refused reconnect");
    ticks_during_call = 0;
    memcpy(conn_server, server, sizeof(server));
    for (i = 0; i < KEEPALIVE_RETRY_SECONDS / KEEPALIVE_SECONDS && lost(); i++)
        tick();
    CHECK(smb2 != NULL && share_open && !session_lost && i == KEEPALIVE_RETRY_SECONDS / KEEPALIVE_SECONDS,
          "reconnected when the backoff ran out (%d ticks)", i);
    CHECK(OPS->devctl(NULL, "", SMB_DEVCTL_LOGOFF, NULL, 0, NULL, 0) == 0, "logoff");

    printf("%s (%d failures)\n", fails ? "FAILED" : "ALL PASSED", fails);
    return fails != 0;
}
