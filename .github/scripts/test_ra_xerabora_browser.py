"""Xerabora-mode achievement browser (ORBIT parity) against the production code.

src/achievements.c is compiled with stubbed network calls. The documents mirror
xeRAbora's own JSON builders (client/src/webui.c build_library / build_game):
nested "base"/"subsets" members, an "achievements" member that is a number
inside subsets, escaped quotes/backslashes, \\u escapes and raw UTF-8.
raNetHttpGet in src/ranet.c is compiled separately against stubbed sockets.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]


def c_str(text):
    out = []
    for b in text.encode("utf-8"):
        ch = chr(b)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif 32 <= b < 127:
            out.append(ch)
        else:
            out.append("\\%03o" % b)
    return '"' + "".join(out) + '"'


library = json.dumps({"games": [
    {"id": 19040, "title": "Need for Speed: Underground 2", "console": "PlayStation 2", "icon": "/i.png",
     "award": "", "played": "2026-10-01 10:00:00", "total": 76, "awarded": 3, "hardcore": 1, "mastered": False},
    {"id": 11, "title": "Café \"Quoted\"", "console": "PlayStation", "icon": "", "award": "",
     "played": "", "total": 10, "awarded": 0, "hardcore": 0, "mastered": False},
]}, ensure_ascii=True)  # é and \" escapes, as xeRAbora's json_field emits
achievements = [
    {"id": i, "title": t, "description": d, "badge": "123", "type": "", "earned": e,
     "points": 5, "order": i, "players": 10, "median": 0}
    for i, t, d, e in [
        (1, 'First "Win"', "Win a race \\ any track", "2026-10-01 12:34:56"),
        (2, "Niño", "Raw UTF-8 日本", ""),
        (3, "Third", "Locked", ""),
        (4, "Fourth", "Earned", "2026-10-02 08:00:00"),
        (5, "Fifth", "Locked", ""),
    ]]
game = json.dumps({"id": 19040, "title": "Need for Speed: Underground 2", "console": "PlayStation 2",
                   "icon": "/x.png", "total": 5, "awarded": 2,
                   "base": {"id": 19040, "title": "Need for Speed: Underground 2"},
                   "subsets": [{"id": 5, "title": "Sub", "achievements": 3, "points": 10}],
                   "achievements": achievements}, ensure_ascii=False)

source = (root / "src/achievements.c").read_text(encoding="utf-8")
source = re.sub(r"^#include.*\n", "", source, flags=re.M)
prefix = r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "include/achievements.h"
#include "include/ratls.h"
#define RETROACHIEVEMENTS 1
#define IO_OK 0
#define IO_CUSTOM_SIMPLEACTION 1
#define O_RDONLY 0
#define RA_MODE_XERABORA 0
#define RA_MODE_CADUCEUS 1
static int gRAMode = RA_MODE_XERABORA;
static void (*worker)(void);
static int idRc, idCount = 40, httpFail, libraryGets, gameGets, hashed;
static char idTitle[64] = "Need for Speed: Underground 2";
static const char *libraryDoc = @LIBRARY@, *gameDoc = @GAME@;
static const char *nextDoc;
static int sbHashGameBusy(void) { return 0; }
static int discCheckBusy(void) { return 0; }
static int raNetNicReserved(void) { return 0; }
static int ethEnsureSMBShareConnected(void) { assert(!"Xerabora mode never needs the SMB share"); return 0; }
enum { NET_PROTO_OFF, NET_PROTO_SMB, NET_PROTO_UDPFS };
static int gNetworkProtocol = NET_PROTO_OFF;
static int udpfsGetModulesLoaded(void) { assert(!"Xerabora mode never needs the UDPFS share"); return 0; }
static const char *ethGetSMBPrefix(void) { return ""; }
static int open(const char *p, int f) { (void)p; (void)f; assert(!"no CADUCEUS.KEY in Xerabora mode"); return -1; }
static int read(int fd, void *o, int n) { (void)fd; (void)o; (void)n; return -1; }
static int close(int fd) { (void)fd; return 0; }
static int ioPutRequest(int type, void (*fn)(void)) { (void)type; worker = fn; return 0; }
static const char *hashOverride;
static int raHashIsoDirect(const char *p, const char *s, char *out)
{
    (void)p; (void)s; hashed++;
    if (hashOverride) { strcpy(out, hashOverride); return 0; }
    memset(out, 'b', 32); out[32] = 0; return 0;
}
/* retroachievements.org over HTTPS: fails (no internet) unless a test scripts a document. */
static int httpsRc = RATLS_ERR_NET, httpsCalls;
static const char *httpsDoc;
static char httpsPath[128];
int raHttpsGet(const char *host, const char *path, char *buf, int max, int *length)
{
    static const char head[] = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n";
    int h = (int)strlen(head), n;
    httpsCalls++;
    assert(!strcmp(host, "retroachievements.org"));
    snprintf(httpsPath, sizeof(httpsPath), "%s", path);
    if (httpsRc < 0)
        return httpsRc;
    n = (int)strlen(httpsDoc);
    assert(h + n < max);
    memcpy(buf, head, h);
    memcpy(buf + h, httpsDoc, n + 1);
    *length = h + n;
    return h;
}
static int raHashVcd(const char *p, char *boot, int max, char *out) { (void)p; snprintf(boot, max, "SLUS_000.00"); memset(out, 'c', 32); out[32] = 0; return 0; }
static int raCaduceusPage(const char *r, unsigned s, char *o, int n) { (void)r; (void)s; (void)o; (void)n; assert(!"no bridge in Xerabora mode"); return -1; }
static int raNetXeraboraIdentify(const char *hash, const char *serial, unsigned int *host, char *title, int tsz, int *count)
{
    (void)serial;
    *host = 0x0201a8c0;
    /* "RAA1 NO" (1) answers a hash query; the host-only query (hash NULL) never gets it. */
    if (idRc != 0 && (hash != NULL || idRc != 1))
        return idRc;
    snprintf(title, tsz, "%s", hash ? idTitle : "");
    *count = hash ? idCount : 0;
    return 0;
}
static int raNetHttpGet(unsigned int host, int port, const char *path, char *buf, int max, int *length)
{
    assert(host == 0x0201a8c0 && port == 18280);
    if (httpFail)
        return -2;
    if (!strcmp(path, "/library")) { libraryGets++; nextDoc = libraryDoc; }
    else { assert(!strcmp(path, "/game?id=19040")); gameGets++; nextDoc = gameDoc; }
    *length = (int)strlen(nextDoc);
    assert(*length < max);
    memcpy(buf, nextDoc, *length);
    return 0;
}
"""
tests = r"""
static achievement_page_t run(char kind, int page, int filter, const char *target)
{
    achievement_page_t p;
    assert(achievementsRequest(kind, page, filter, target));
    worker();
    achievementsSnapshot(&p);
    return p;
}
int main(void)
{
    achievement_page_t p;
    /* Account library: games with progress, escapes and \u decoding. */
    p = run('G', 0, 0, "0");
    assert(p.state == ACH_READY && p.kind == 'G' && p.total == 2 && p.count == 2);
    assert(p.entries[0].id == 19040 && p.entries[0].total == 76 && p.entries[0].earned == 3 && p.entries[0].hardcore == 1);
    assert(!strcmp(p.entries[1].title, "Caf\303\251 \"Quoted\""));
    /* One game's set: nested base/subsets are skipped, earned dates kept. */
    p = run('A', 0, 0, "19040");
    assert(p.state == ACH_READY && p.kind == 'A' && p.gameId == 19040 && p.total == 5 && p.count == 3);
    assert(p.earned == 2 && p.maximum == 5 && !strcmp(p.title, "Need for Speed: Underground 2"));
    assert(!strcmp(p.entries[0].title, "First \"Win\"") && !strcmp(p.entries[0].description, "Win a race \\ any track"));
    assert(p.entries[0].earned && !strcmp(p.entries[0].date, "2026-10-01 12:34:56") && p.entries[0].points == 5);
    assert(!strcmp(p.entries[1].title, "Ni\303\261o") && !p.entries[1].earned && !p.entries[1].date[0]);
    assert(!strcmp(p.entries[1].description, "Raw UTF-8 \346\227\245\346\234\254"));
    /* Paging and filters come from the cache: no further fetch. */
    p = run('A', 1, 0, "19040");
    assert(p.total == 5 && p.count == 2 && p.entries[0].id == 4);
    p = run('A', 0, 1, "19040"); assert(p.total == 2 && p.entries[1].id == 4);
    p = run('A', 0, 2, "19040"); assert(p.total == 3 && p.entries[0].id == 2);
    p = run('A', 0, 3, "19040"); assert(p.total == 0 && p.count == 0);
    assert(libraryGets == 1 && gameGets == 1);
    /* Select marks the cache stale: the next request refetches. */
    achievementsForget();
    p = run('A', 0, 0, "19040"); assert(p.state == ACH_READY && gameGets == 2);
    /* From a game card: RAQ1 title -> library ID -> the set. */
    assert(achievementsRequestImage("mass0:DVD/NFSU2.iso", "SLUS_210.65")); worker(); achievementsSnapshot(&p);
    assert(hashed == 1 && p.state == ACH_READY && p.gameId == 19040 && p.total == 5);
    /* Known to RetroAchievements but never played: say so, with title and count. */
    strcpy(idTitle, "Never Played Game");
    assert(achievementsRequestImage("mass0:DVD/X.iso", "SLUS_000.01")); worker(); achievementsSnapshot(&p);
    assert(p.state == ACH_NOT_PLAYED && !strcmp(p.title, "Never Played Game") && p.maximum == 40);
    /* Unknown image, unreachable PC, unreadable document. */
    idRc = 1; assert(achievementsRequestImage("mass0:DVD/X.iso", "SLUS_000.01")); worker(); achievementsSnapshot(&p);
    assert(p.state == ACH_UNSUPPORTED);
    idRc = -2; p = run('G', 0, 0, "0"); assert(p.state == ACH_OFFLINE); idRc = 0;
    /* xera_identify_codes (#1062): still identifying is a retry, a held NIC says so. */
    idRc = -7; achievementsForget(); p = run('G', 0, 0, "0"); assert(p.state == ACH_ERROR);
    idRc = -8; achievementsForget(); p = run('G', 0, 0, "0"); assert(p.state == ACH_NET_BUSY);
    idRc = -7; assert(achievementsRequestImage("mass0:DVD/X.iso", "SLUS_000.01")); worker(); achievementsSnapshot(&p);
    assert(p.state == ACH_ERROR);
    idRc = 0;
    achievementsForget(); httpFail = 1; p = run('G', 0, 0, "0"); assert(p.state == ACH_OFFLINE); httpFail = 0;
    /* gameid_parse: retroachievements.org's {"Success":true,"GameID":N}. */
    assert(achievementsParseGameId("{\"Success\":true,\"GameID\":2791}", (int)strlen("{\"Success\":true,\"GameID\":2791}")) == 2791);
    assert(achievementsParseGameId("{\"Success\":true,\"GameID\":0}", (int)strlen("{\"Success\":true,\"GameID\":0}")) == 0);
    assert(achievementsParseGameId("{\"Success\":false}", (int)strlen("{\"Success\":false}")) == -1);
    assert(achievementsParseGameId("{\"GameID\":5}", (int)strlen("{\"GameID\":5}")) == -1);
    assert(achievementsParseGameId("{\"Success\":true,\"GameID\":\"x\"}", (int)strlen("{\"Success\":true,\"GameID\":\"x\"}")) == -1);
    assert(achievementsParseGameId("{\"Success\":tr", (int)strlen("{\"Success\":tr")) == -1);
    assert(achievementsParseGameId("{\"Success\":true,\"GameID\":-3}", (int)strlen("{\"Success\":true,\"GameID\":-3}")) == -1);
    /* never_played_reaches_game: the ORBIT path, no library title match needed. */
    strcpy(idTitle, "Never Played Game");
    httpsRc = 0; httpsDoc = "{\"Success\":true,\"GameID\":19040}";
    achievementsForget();
    {
        int lib = libraryGets, games = gameGets;
        assert(achievementsRequestImage("mass0:DVD/X.iso", "SLUS_000.01")); worker(); achievementsSnapshot(&p);
        assert(p.state == ACH_READY && p.gameId == 19040 && gameGets == games + 1 && libraryGets == lib);
        assert(!strcmp(httpsPath, "/dorequest.php?r=gameid&m=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"));
    }
    /* gameid_zero_unsupported */
    httpsDoc = "{\"Success\":true,\"GameID\":0}";
    {
        int games = gameGets;
        assert(achievementsRequestImage("mass0:DVD/X.iso", "SLUS_000.01")); worker(); achievementsSnapshot(&p);
        assert(p.state == ACH_UNSUPPORTED && gameGets == games);
    }
    /* https_failure_falls_back: the #926 title match, unchanged. */
    httpsRc = RATLS_ERR_NET;
    assert(achievementsRequestImage("mass0:DVD/X.iso", "SLUS_000.01")); worker(); achievementsSnapshot(&p);
    assert(p.state == ACH_NOT_PLAYED && !strcmp(p.title, "Never Played Game") && !xeraClockNote);
    /* unreachable_once_per_session: no internet costs one attempt, not one per game card ... */
    {
        int calls = httpsCalls;
        assert(achievementsRequestImage("mass0:DVD/Y.iso", "SLUS_000.02")); worker(); achievementsSnapshot(&p);
        assert(p.state == ACH_NOT_PLAYED && httpsCalls == calls);
        httpsRc = RATLS_ERR_TIMEOUT;
        achievementsForget(); /* ... until Select asks again */
        assert(achievementsRequestImage("mass0:DVD/Y.iso", "SLUS_000.02")); worker();
        assert(httpsCalls == calls + 1);
        achievementsForget();
    }
    /* clock_unset_notes: fallback taken, and the browser says to set the clock. */
    httpsRc = RATLS_ERR_CLOCK;
    assert(achievementsRequestImage("mass0:DVD/X.iso", "SLUS_000.01")); worker(); achievementsSnapshot(&p);
    assert(p.state == ACH_NOT_PLAYED && xeraClockNote == 1 && achievementsClockUnset());
    /* gameid_rejects_bad_hash: nothing is sent for a malformed hash. */
    httpsRc = 0; httpsDoc = "{\"Success\":true,\"GameID\":19040}";
    {
        int calls = httpsCalls;
        hashOverride = "ABC";
        assert(achievementsRequestImage("mass0:DVD/X.iso", "SLUS_000.01")); worker();
        hashOverride = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbG";
        assert(achievementsRequestImage("mass0:DVD/X.iso", "SLUS_000.01")); worker();
        hashOverride = NULL;
        assert(httpsCalls == calls);
    }
    httpsRc = RATLS_ERR_NET;
    strcpy(idTitle, "Need for Speed: Underground 2");
    libraryDoc = "{\"games\":[{\"id\":1,\"title\":\"unterminated}]}";
    achievementsForget(); p = run('G', 0, 0, "0"); assert(p.state == ACH_ERROR);
    puts("PASS: xeRAbora library/game parsing, escapes and UTF-8, cached paging/filters, image lookup, not-played, failures and the HTTPS game-ID path");
    return 0;
}
"""
harness = prefix.replace("@LIBRARY@", c_str(library)).replace("@GAME@", c_str(game))
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / "test.c").write_text(harness + source + tests, encoding="utf-8")
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wno-unused-function", "-I", str(root),
                    str(path / "test.c"), "-o", str(path / "test.exe")], check=True)
    subprocess.run([str(path / "test.exe")], check=True)

# raNetHttpGet against stubbed sockets: 200 + close, non-200, cut off by the deadline, too large.
network = (root / "src/ranet.c").read_text(encoding="utf-8")
a = network.index("#define RA_HTTP_MS")
b = network.index("\n}", network.index("int raNetHttpGet(", a)) + 2
http = network[a:b]
t = network.index("int raNetTcpRecv(")
http = network[t:network.index("\n}", t) + 2] + "\n" + http
http_harness = r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef unsigned int u32;
#define AF_INET 2
#define SOCK_STREAM 1
#define RA_MSG_DONTWAIT 0x08
#define RA_MSG_PEEK 0x01
#define RA_POLL_MS 25
#define CLOCKS_PER_SEC 1000
typedef long clock_t;
struct sockaddr { int x; };
struct sockaddr_in { int sin_family, sin_port; struct { u32 s_addr; } sin_addr; };
static int nic, sent, closes, scriptPos, scriptOff, ticks;
static const char *script[8];
static int htons(int p) { return p; }
static int raNetNicReserved(void) { return nic; }
static int socket(int a, int b, int c) { (void)a; (void)b; (void)c; return 5; }
static int connect(int s, struct sockaddr *a, int l) { (void)s; (void)a; (void)l; return 0; }
static int send(int s, const char *b, int n, int f) { (void)s; (void)f; assert(!strncmp(b, "GET /library HTTP/1.0\r\nHost: 192.168.1.2\r\n", 41)); sent++; return n; }
static int lost;
/* Like ps2ips' do_recv into a 64-byte-aligned buffer: a tail past the last whole
   64-byte block that is longer than RESTS_EBUF_MAX (48) is cut from the returned
   length after lwIP has consumed it (#1062). A peek consumes nothing. */
static int recv(int s, char *b, int n, int f)
{
    const char *part;
    int left, take, tail;
    (void)s;
    assert((f & ~RA_MSG_PEEK) == RA_MSG_DONTWAIT && ((size_t)b & 63) == 0 && n <= 960);
    part = script[scriptPos];
    if (part == NULL)
        return -1;          /* nothing yet */
    if (!*part)
        return 0;           /* closed */
    /* Like a real recv: never more than n; the rest of a part comes next call. */
    left = (int)strlen(part) - scriptOff, take = left < n ? left : n;
    tail = take > 64 ? take % 64 : 0;
    if (f & RA_MSG_PEEK)
        return tail > 48 ? take - (tail - 48) : take;
    memcpy(b, part + scriptOff, take);
    scriptOff += take;
    if (scriptOff == (int)strlen(part))
        scriptPos++, scriptOff = 0;
    if (tail > 48) {
        lost += tail - 48;
        take -= tail - 48;
    }
    return take;
}
static void disconnect(int s) { (void)s; closes++; }
static void DelayThread(int us) { (void)us; ticks += 25; }
static clock_t clock(void) { return ticks; }
"""
http_tests = r"""
static int get(char *buf, int max, int *len)
{
    scriptPos = scriptOff = 0;
    return raNetHttpGet(0x0201a8c0, 18280, "/library", buf, max, len);
}
int main(void)
{
    static char buf[256];
    int len, body;
    script[0] = "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{\"games\":"; script[1] = "[]}"; script[2] = ""; script[3] = NULL;
    body = get(buf, sizeof(buf), &len);
    assert(body > 0 && len == 12 && !strcmp(buf + body, "{\"games\":[]}"));
    script[0] = "HTTP/1.0 404 Not Found\r\n\r\nno"; script[1] = ""; script[2] = NULL;
    assert(get(buf, sizeof(buf), &len) < 0);
    script[0] = "HTTP/1.0 200 OK\r\n\r\n{\"games\":["; script[1] = NULL; /* never closes */
    ticks = 0; assert(get(buf, sizeof(buf), &len) < 0 && ticks >= RA_HTTP_MS);
    script[0] = "HTTP/1.0 200 OK\r\n\r\n0123456789012345678901234567890123456789012345678901234567890123456789"; script[1] = NULL;
    assert(get(buf, 64, &len) < 0); /* larger than the buffer */
    nic = 1; assert(get(buf, sizeof(buf), &len) < 0); nic = 0;
    assert(closes == 4);
    /* tcp_tail_not_lost: reads that would end in a 49-63 byte tail keep every byte (#1062). */
    {
        static char doc[1200], head[114], out[2048];
        int i;
        i = snprintf(doc, sizeof(doc), "HTTP/1.0 200 OK\r\n\r\n");
        for (; i < 1100; i++)
            doc[i] = 'a' + i % 26;
        doc[i] = 0;
        memcpy(head, doc, 113);
        head[113] = 0;
        script[0] = doc; script[1] = ""; script[2] = NULL;
        lost = 0;
        body = get(out, sizeof(out), &len);
        assert(body > 0 && lost == 0 && len == 1100 - body && !strcmp(out, doc));
        /* Odd part sizes as well: 1100 split into a 113-byte head and the rest. */
        script[0] = head; script[1] = doc + 113; script[2] = ""; script[3] = NULL;
        lost = 0;
        body = get(out, sizeof(out), &len);
        assert(body > 0 && lost == 0 && len == 1100 - body && !strcmp(out, doc));
    }
    puts("PASS: raNetHttpGet status, body offset, deadline, oversize, NIC guard and ps2ips tail loss");
    return 0;
}
"""
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / "http.c").write_text(http_harness + http + http_tests, encoding="utf-8")
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wno-unused-function", str(path / "http.c"),
                    "-o", str(path / "http.exe")], check=True)
    subprocess.run([str(path / "http.exe")], check=True)
print("PASS: Xerabora achievement browser")

# The browser's messages name an unset clock when the HTTPS lookup could not run.
menu = (root / "src/menusys.c").read_text(encoding="utf-8")
assert "achievementsClockUnset() ? _STR_XERA_SET_CLOCK : _STR_XERA_NOT_PLAYED" in menu
unsupported = menu[menu.index("page.state == ACH_UNSUPPORTED ?"):menu.index("page.state == ACH_NOT_PLAYED")]
assert "SET_CLOCK" not in unsupported, "an unsupported game is not a clock problem"
# #1062: a held NIC is named as such, discovery takes only a full "RAO1 OK ", and the
# link test's RA_TEST_NO_ANSWER2 is a format string everywhere.
assert "page.state == ACH_NET_BUSY    ? _l(_STR_RA_NET_BUSY)" in menu
assert 'strncmp(g_rx, "RAO1 OK ", 8) == 0) {\n        raNetRememberPeer(g_raReplyIP);' in network
assert 'strncmp(g_rx, "RAO1", 4)' not in network
assert '"%s", _l(_STR_RA_TEST_NO_ANSWER2)' not in network
base_yml = (root / "lng_tmpl/_base.yml").read_text(encoding="utf-8")
clock_text = base_yml[base_yml.index("- label: XERA_SET_CLOCK"):]
clock_text = clock_text[:clock_text.index("\n\n") if "\n\n" in clock_text else len(clock_text)]
assert "Showing your library" not in clock_text and "library yet" in clock_text and "clock" in clock_text
assert "- label: XERA_SET_CLOCK" in (root / "lng_tmpl/_base.yml").read_text(encoding="utf-8")
print("PASS: HTTPS game-ID messages")

# clock() is a 32-bit microsecond counter on the EE: RA_HTTP_MS * CLOCKS_PER_SEC overflows (8 s
# became ~3.7 s) and an absolute deadline breaks at the wrap. raNetHttpGet compares elapsed time.
http_get = network[network.index("int raNetHttpGet("):]
http_get = http_get[:http_get.index("\n}\n")]
assert "RA_HTTP_MS * CLOCKS_PER_SEC /" not in http_get and "clock_t deadline" not in http_get
assert "(clock_t)(clock() - start) < (clock_t)RA_HTTP_MS * (CLOCKS_PER_SEC / 1000)" in http_get
print("PASS: raNetHttpGet budget is wrap-safe elapsed time")
