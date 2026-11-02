/* Host harness for smb2man.c's keepalive: a session lost under open handles, the reconnect and its
   backoff, and LOGOFF / CLOSESHARE while the session is lost. It includes smb2man.c, so it can run
   keepalive passes by hand (on the host no thread or alarm runs) and see the driver's state. The
   connection is cut with shutdown() on the client's socket, so the next ECHO fails as it does when
   a server goes away. Built with AddressSanitizer, whose leak check at exit fails the run if a
   dropped session leaves a file handle or a directory listing allocated. Built and run by run.sh. */
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>

#include "smb2man.c"

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

// The server goes away: the next request on this session fails.
static void cut(void)
{
    shutdown(smb2_get_fd(smb2), SHUT_RDWR);
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
    iop_file_t f = {0}, d = {0}, d2 = {0};
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

    printf("%s (%d failures)\n", fails ? "FAILED" : "ALL PASSED", fails);
    return fails != 0;
}
