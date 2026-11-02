"""The in-game SMB2 reader logs on with the same user name, domain and password as the menu.

A server recomputes NTOWFv2 from the user name and the domain the client sends (MS-NLMP 3.3.2). If
the game's logon sends another user name or domain than the menu's, or hashes another one, a
password that works in the menu can fail at game start, and only on some servers: Samba, which the
live harness uses, accepts several domains for one account.

This builds both clients on the host and runs each against a fake SMB2 server that sends one fixed
CHALLENGE, then compares the AUTHENTICATE messages they send: UserName, DomainName, and the user,
domain and password their NTLMv2 proofs are computed from. The CHALLENGE's TargetName, ParityDom, is
in mixed case and differs from its MsvAvNbDomainName AV pair, so a logon that changes the domain's
case or takes it from the AV pair fails. The rest of the two messages is not compared, and differs:
the menu's NTLMv2 blob also names the server (MsvAvTargetName), its LM response is empty where the
game's is 24 zero bytes, and the flags differ. None of these is an input to the proof.
- The game: tests/smb2-live/ingame.c around the real modules/iopcore/cdvdman/smb2.c.
- The menu: the vendored libsmb2, set up the way smb2man_new_context() sets it up and connected the
  way smb2man.c connects. getlogin_r() fails as it does in libsmb2's IOP build, so a blank user is
  libsmb2's default, "Guest". smb2man.c itself needs the PS2SDK to build, so its calls are checked
  in its source (comments and the contents of literals ignored): the same setters as here, the
  password set once and always, no user and no domain set, and a blank user passed as NULL.
This is a host check, not a console test. tests/smb2-live/run.sh runs both against a real Samba.
"""
from pathlib import Path
import concurrent.futures
import hmac
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading

root = Path(__file__).resolve().parents[2]
live = root / 'tests/smb2-live'
cdvdman = root / 'modules/iopcore/cdvdman'
lib = root / 'modules/network/smb2man/libsmb2'
failures = []


def check(cond, what):
    if not cond:
        failures.append(what)


def strip_comments(src):
    """C source with each comment replaced by a space (its newlines kept) and the contents of each
    string and character literal dropped, so neither can pass for code. Lines that end in a
    backslash are joined first, as C joins them before it removes comments."""
    src = src.replace('\\\n', '')
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith('/*', i):
            j = src.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(' ' + '\n' * src.count('\n', i, j))
            i = j
        elif src.startswith('//', i):
            j = src.find('\n', i)
            out.append(' ')
            i = n if j < 0 else j
        elif src[i] in '"\'':
            j = i + 1
            while j < n and src[j] != src[i]:
                j += 2 if src[j] == '\\' else 1
            out.append(src[i] * 2)
            i = j + 1
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


def function_body(src, name):
    m = re.search(r'^\w[\w \*]*\b%s\([^)]*\)\n\{\n' % name, src, re.M)
    if not m:
        return ''
    return src[m.end():src.find('\n}\n', m.end())]


# ---- smb2man.c sets libsmb2 up and connects as the menu logon below does ---------------------------
smb2man = strip_comments((root / 'modules/network/smb2man/smb2man.c').read_text(encoding='utf-8').replace('\r\n', '\n'))
setup = function_body(smb2man, 'smb2man_new_context')
check(sorted(set(re.findall(r'\b(smb2_set_\w+)\s*\(', setup))) ==
      ['smb2_set_password', 'smb2_set_security_mode', 'smb2_set_timeout', 'smb2_set_version'] and
      re.search(r'\bsmb2_set_security_mode\(\s*ctx\s*,\s*SMB2_NEGOTIATE_SIGNING_ENABLED\s*\)\s*;', setup) and
      re.search(r'\bsmb2_set_version\(\s*ctx\s*,\s*SMB2_VERSION_ANY2\s*\)\s*;', setup),
      'smb2man_new_context() sets libsmb2 up differently: make the menu logon in this check do the same')
# The password is set once in all of smb2man.c: in smb2man_new_context(), at its top level, and the
# only return before it is the one for a failed allocation (without a password libsmb2 logs on
# anonymously).
setter = re.search(r'^    smb2_set_password\(\s*ctx\s*,\s*conn_password\s*\)\s*;', setup, re.M)
before = setup[:setter.start()] if setter else ''
check(setter is not None and len(re.findall(r'\bsmb2_set_password\s*\(', smb2man)) == 1 and
      len(re.findall(r'\breturn\b', before)) == 1 and
      re.search(r'\bif\s*\(\s*(?:ctx\s*==\s*NULL|!\s*ctx)\s*\)\s*return\s+NULL\s*;', before) is not None,
      'smb2man_new_context() no longer always sets the password (without one libsmb2 logs on anonymously): '
      'make the menu logon in this check do the same')
check(re.search(r'\bsmb2_set_(user|domain)\b', smb2man) is None,
      'smb2man.c now sets a user or an NTLM domain: make the menu logon in this check do the same')
connects = re.findall(r'\bsmb2_connect_share(?:_async)?\s*\(([^;]*)', smb2man)
check(len(connects) > 0 and all(re.search(r',\s*conn_user\[0\]\s*\?\s*conn_user\s*:\s*NULL\s*\)', c) for c in connects),
      'smb2man.c changed how it passes the user to smb2_connect_share(): make the menu logon in this check do the same')


# ---- MD4 (RFC 1320): hashlib has none under OpenSSL 3 ---------------------------------------------
def _rol(x, n):
    x &= 0xFFFFFFFF
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def md4(msg):
    msg = bytearray(msg)
    bits = len(msg) * 8
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += struct.pack('<Q', bits)
    h = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476]
    for i in range(0, len(msg), 64):
        x = struct.unpack('<16I', msg[i:i + 64])
        a, b, c, d = h
        for k in range(16):  # round 1
            f = (b & c) | (~b & d)
            a, b, c, d = d, _rol(a + f + x[k], (3, 7, 11, 19)[k % 4]), b, c
        for k in range(16):  # round 2
            g = (b & c) | (b & d) | (c & d)
            a, b, c, d = d, _rol(a + g + x[(k % 4) * 4 + k // 4] + 0x5A827999, (3, 5, 9, 13)[k % 4]), b, c
        for k in range(16):  # round 3
            j = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)[k]
            a, b, c, d = d, _rol(a + (b ^ c ^ d) + x[j] + 0x6ED9EBA1, (3, 9, 11, 15)[k % 4]), b, c
        h = [(v + w) & 0xFFFFFFFF for v, w in zip(h, (a, b, c, d))]
    return struct.pack('<4I', *h)


for _msg, _want in [(b'', '31d6cfe0d16ae931b73c59d7e0c089c0'), (b'abc', 'a448017aaf21d8525fc10ae87aa6729d'),
                    (b'1234567890' * 8, 'e33b4ddc9c38f2199c3e7b164fcc0536')]:
    assert md4(_msg).hex() == _want, 'the MD4 in this script is wrong (RFC 1320 A.5)'


def hmac_md5(key, data):
    return hmac.new(key, data, 'md5').digest()


def u16(s):
    return s.encode('utf-16-le')


# ---- the fake server -------------------------------------------------------------------------------
TARGET_NAME = 'ParityDom'  # mixed case: a logon that changes the domain's case must fail
SERVER_CHALLENGE = bytes.fromhex('0123456789abcdef')
TIMESTAMP = struct.pack('<Q', 133000000000000000)
STATUS_SUCCESS, STATUS_MORE_PROCESSING_REQUIRED = 0, 0xC0000016
STATUS_ACCESS_DENIED, STATUS_NOT_SUPPORTED = 0xC0000022, 0xC00000BB
NTLMSSP_NEGOTIATE_ANONYMOUS = 0x00000800


def recv_exact(conn, n):
    buf = b''
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def recv_msg(conn):
    while True:  # skip NetBIOS session messages other than data (type 0)
        hdr = recv_exact(conn, 4)
        body = recv_exact(conn, (hdr[1] << 16) | (hdr[2] << 8) | hdr[3])
        if hdr[0] == 0:
            return body


def send_msg(conn, msg):
    conn.sendall(struct.pack('>I', len(msg)) + msg)


def reply(req, status, body, session_id=0):
    h = bytearray(64)
    h[0:4] = b'\xfeSMB'
    struct.pack_into('<H', h, 4, 64)
    struct.pack_into('<I', h, 8, status)
    h[12:14] = req[12:14]  # command
    struct.pack_into('<H', h, 14, 64)  # credits granted
    struct.pack_into('<I', h, 16, 1)  # SMB2_FLAGS_SERVER_TO_REDIR
    h[24:32] = req[24:32]  # message id
    struct.pack_into('<Q', h, 40, session_id)
    return bytes(h) + bytes(body)


def error_body():
    return struct.pack('<H', 9) + b'\0' * 7


def challenge_message():
    tn = u16(TARGET_NAME)
    av = b''
    # MsvAvNbDomainName (2) differs from TargetName on purpose: both logons must take the domain from
    # TargetName, and a logon that read it from this AV pair would otherwise pass.
    for code, val in [(2, u16('PARITYNB')), (1, u16('FAKESRV')), (4, u16('paritydom.test')),
                      (3, u16('fakesrv.paritydom.test')), (7, TIMESTAMP)]:
        av += struct.pack('<HH', code, len(val)) + val
    av += struct.pack('<HH', 0, 0)
    # UNICODE, REQUEST_TARGET, SIGN, NTLM, ALWAYS_SIGN, TARGET_TYPE_DOMAIN, EXTENDED_SESSIONSECURITY,
    # TARGET_INFO, VERSION, 128, 56
    flags = 0x00000001 | 0x00000004 | 0x00000010 | 0x00000200 | 0x00008000 | 0x00010000 | 0x00080000 | \
        0x00800000 | 0x02000000 | 0x20000000 | 0x80000000
    m = b'NTLMSSP\0' + struct.pack('<I', 2)
    m += struct.pack('<HHI', len(tn), len(tn), 56)
    m += struct.pack('<I', flags) + SERVER_CHALLENGE + b'\0' * 8
    m += struct.pack('<HHI', len(av), len(av), 56 + len(tn))
    m += bytes([6, 1]) + struct.pack('<H', 7600) + b'\0\0\0\x0f'
    assert len(m) == 56
    return m + tn + av


def serve_one(sock, record):
    """Answer one client: NEGOTIATE (2.1 when offered), the two SESSION_SETUP legs, and a TREE_CONNECT
    that is refused, which ends both clients. Records the AUTHENTICATE_MESSAGE's fields."""
    try:
        sock.settimeout(60)
        conn, _ = sock.accept()
    except OSError as e:
        record['error'] = 'no client connected (%s)' % e
        return
    conn.settimeout(60)
    session_id = 0x0000400000000001
    try:
        while True:
            req = recv_msg(conn)
            if req[0:4] != b'\xfeSMB':
                record['error'] = 'not an SMB2 message: %s' % req[:4].hex()
                return
            cmd = struct.unpack_from('<H', req, 12)[0]
            body = req[64:]
            if cmd == 0:  # NEGOTIATE
                count = struct.unpack_from('<H', body, 2)[0]
                dialects = [struct.unpack_from('<H', body, 36 + 2 * i)[0] for i in range(count)]
                r = bytearray(65)
                struct.pack_into('<HHH', r, 0, 65, 0x01, 0x0210 if 0x0210 in dialects else 0x0202)
                r[8:24] = b'FAKESMB2SERVER!!'
                struct.pack_into('<IIIQ', r, 28, 65536, 65536, 65536, 133000000000000000)
                struct.pack_into('<HH', r, 56, 128, 0)
                send_msg(conn, reply(req, STATUS_SUCCESS, r))
            elif cmd == 1:  # SESSION_SETUP
                secoff, seclen = struct.unpack_from('<HH', body, 12)
                tok = req[secoff:secoff + seclen]
                i = tok.find(b'NTLMSSP\0')
                if i < 0:
                    record['error'] = 'a SESSION_SETUP without an NTLMSSP token'
                    return
                tok = tok[i:]
                mtype = struct.unpack_from('<I', tok, 8)[0]
                if mtype == 1:
                    ch = challenge_message()
                    send_msg(conn, reply(req, STATUS_MORE_PROCESSING_REQUIRED, struct.pack('<HHHH', 9, 0, 72, len(ch)) + ch,
                                         session_id))
                elif mtype == 3:
                    def field(off):
                        ln, _, at = struct.unpack_from('<HHI', tok, off)
                        return tok[at:at + ln]
                    record.update(lm=field(12), nt=field(20), domain=field(28), user=field(36),
                                  flags=struct.unpack_from('<I', tok, 60)[0])
                    send_msg(conn, reply(req, STATUS_SUCCESS, struct.pack('<HHHH', 9, 0, 72, 0), session_id))
            elif cmd == 3:  # TREE_CONNECT
                send_msg(conn, reply(req, STATUS_ACCESS_DENIED, error_body(), session_id))
                return
            else:
                send_msg(conn, reply(req, STATUS_NOT_SUPPORTED, error_body(), session_id))
    except (EOFError, OSError):
        pass
    finally:
        conn.close()


def logon(client):
    """Run one client (a function of the port) against a fresh fake server; return the AUTHENTICATE
    fields and the client's output."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(1)
    record = {}
    server = threading.Thread(target=serve_one, args=(sock, record), daemon=True)
    server.start()
    env = dict(os.environ)
    env.pop('NTLM_USER_FILE', None)  # libsmb2 on the host would read a password from it
    try:
        p = subprocess.run(client(sock.getsockname()[1]), capture_output=True, text=True, timeout=60, env=env)
        record['out'], record['rc'] = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        record['out'], record['rc'] = 'timed out', None
    server.join(10)
    sock.close()
    return record


def proof_inputs(rec, password, user_upper, domain):
    """Whether the client's NTProofStr was computed from this password, upper-cased user and domain."""
    nt = rec.get('nt', b'')
    if len(nt) < 16 + 28:
        return False
    ntowf = hmac_md5(md4(u16(password)), u16(user_upper) + domain)
    return hmac_md5(ntowf, SERVER_CHALLENGE + nt[16:]) == nt[:16]


# NTOWFv2 hashes UPPER(user). Both logons upper-case only ASCII letters today; what matters is that
# they do the same.
UPPER = [('full Unicode', str.upper), ('ASCII only', lambda s: ''.join(c.upper() if c < '\x80' else c for c in s))]


MENU = r'''
/* The menu's logon: libsmb2 set up as smb2man_new_context() sets it up (signing enabled, SMB 2.0.2
   and 2.1, a timeout, the password always set, no user and no domain set) and connected as
   smb2man.c connects (a blank user is passed as NULL). */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <smb2/smb2.h>
#include <smb2/libsmb2.h>

/* libsmb2's IOP build has no login name (lib/compat.c), so its default user is "Guest". */
int getlogin_r(char *buf, size_t size)
{
    (void)buf;
    (void)size;
    return ENXIO;
}

int main(int argc, char **argv)
{
    /* argv: server (ip:port) share user password */
    struct smb2_context *ctx;
    int rc;

    if (argc < 5 || (ctx = smb2_init_context()) == NULL)
        return 2;
    smb2_set_security_mode(ctx, SMB2_NEGOTIATE_SIGNING_ENABLED);
    smb2_set_version(ctx, SMB2_VERSION_ANY2);
    smb2_set_timeout(ctx, 10);
    smb2_set_password(ctx, argv[4]);
    rc = smb2_connect_share(ctx, argv[1], argv[2], argv[3][0] ? argv[3] : NULL);
    printf("connect %d: %s\n", rc, smb2_get_error(ctx));
    smb2_destroy_context(ctx);
    return 0;
}
'''

SAN = ['-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-fno-omit-frame-pointer', '-g', '-O1']
# libsmb2 for the host, with the configuration its CMake build finds on Linux (as tests/smb2-live/run.sh).
HOSTCFG = ['-D' + d for d in (
    'HAVE_ARPA_INET_H HAVE_FCNTL_H HAVE_INTTYPES_H HAVE_NETDB_H HAVE_NETINET_IN_H HAVE_NETINET_TCP_H HAVE_POLL_H '
    'HAVE_SOCKADDR_STORAGE HAVE_LINGER HAVE_STDINT_H HAVE_STDIO_H HAVE_STDLIB_H HAVE_STRINGS_H HAVE_STRING_H '
    'HAVE_SYS_IOCTL_H HAVE_SYS_POLL_H HAVE_SYS_SOCKET_H HAVE_SYS_STAT_H HAVE_SYS_TYPES_H HAVE_SYS_UIO_H HAVE_TIME_H '
    'HAVE_SYS_TIME_H HAVE_UNISTD_H HAVE_ERRNO_H STDC_HEADERS HAVE_GETRANDOM HAVE_SYS_RANDOM_H _FILE_OFFSET_BITS=64'
).split()] + ['-D_U_=__attribute__((unused))']


def cc(args, what):
    p = subprocess.run(['cc'] + args, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout + p.stderr)
        sys.exit('%s does not build on the host' % what)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    game = tmp / 'ingame'
    cc(SAN + ['-Wall', '-Wno-unused-parameter', '-I', str(live / 'inc-ingame'), '-I', str(cdvdman), '-I',
              str(root / 'modules/iopcore/common'), str(live / 'ingame.c'), str(cdvdman / 'smb2.c'),
              str(cdvdman / 'smb2auth.c'), '-o', str(game)], 'the in-game reader (smb2.c)')
    objs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
        jobs = []
        for src in sorted((lib / 'lib').glob('*.c')):
            obj = tmp / (src.stem + '.o')
            objs.append(str(obj))
            jobs.append(pool.submit(cc, SAN + ['-w'] + HOSTCFG + ['-I', str(lib / 'include'), '-I',
                                                                 str(lib / 'include/smb2'), '-I', str(lib / 'lib'),
                                                                 '-c', str(src), '-o', str(obj)], 'libsmb2 ' + src.name))
        for job in jobs:
            job.result()
    (tmp / 'menu.c').write_text(MENU)
    menu = tmp / 'menu'
    cc(SAN + ['-Wall', '-I', str(lib / 'include'), str(tmp / 'menu.c')] + objs + ['-o', str(menu)],
       "the menu's logon (libsmb2)")

    def name_of(field):
        return ascii(field.decode('utf-16-le', 'replace'))

    # (user, password) as configured on the console. Mixed case: the proof hashes UPPER(user), the
    # message sends it as typed. Blank: both log on as "Guest" (with the password, or an empty one).
    for user, password in [('ps2', 'secret'), ('MixedCase', 'Pass word'), ('José', 'Café'), ('', 'secret'),
                           ('', '')]:
        label = 'user %s, password %s' % (ascii(user), ascii(password))
        u8, p8 = user.encode('utf-8'), password.encode('utf-8')
        g = logon(lambda port: [str(game), '127.0.0.1', str(port), u8, p8, 'PS2SMB', '\\DVD\\TEST.iso', '\\VMC\\card.bin'])
        m = logon(lambda port: [str(menu), '127.0.0.1:%d' % port, 'PS2SMB', u8, p8])
        for name, rec in [('in-game', g), ('menu', m)]:
            check('error' not in rec, '%s, %s logon: %s' % (label, name, rec.get('error')))
            check('Sanitizer' not in rec['out'] and 'runtime error' not in rec['out'],
                  '%s, %s logon: a sanitizer report:\n%s' % (label, name, rec['out']))
            check('nt' in rec, '%s, %s logon: no AUTHENTICATE_MESSAGE reached the server (exit %s):\n%s' %
                  (label, name, rec['rc'], rec['out']))
        if 'nt' not in g or 'nt' not in m:
            continue
        want_user, domain = user or 'Guest', u16(TARGET_NAME)
        check(m['user'] == u16(want_user) and m['domain'] == domain,
              '%s: the menu (libsmb2) sends UserName %s and DomainName %s; this check expects %s and %s: '
              'libsmb2 or smb2man changed, update this check and smb2.c together' %
              (label, name_of(m['user']), name_of(m['domain']), ascii(want_user), ascii(TARGET_NAME)))
        check(g['user'] == m['user'], '%s: the in-game logon sends UserName %s, the menu sends %s' %
              (label, name_of(g['user']), name_of(m['user'])))
        check(g['domain'] == m['domain'], '%s: the in-game logon sends DomainName %s, the menu sends %s' %
              (label, name_of(g['domain']), name_of(m['domain'])))
        for name, rec in [('in-game', g), ('menu', m)]:
            check(not rec['flags'] & NTLMSSP_NEGOTIATE_ANONYMOUS, '%s: the %s logon is anonymous' % (label, name))
            # Not vacuous: the proof must not also match an empty domain (what a server that ignores
            # the domain would accept).
            check(not any(proof_inputs(rec, password, up(want_user), b'') for _, up in UPPER),
                  '%s: the %s proof matches an empty domain too' % (label, name))
        menu_upper = [how for how, up in UPPER if proof_inputs(m, password, up(want_user), domain)]
        game_upper = [how for how, up in UPPER if proof_inputs(g, password, up(want_user), domain)]
        check(menu_upper, "%s: the menu's NTLMv2 proof is not HMAC(NTOWFv2(password, UPPER(%s), %s), ...)" %
              (label, ascii(want_user), ascii(TARGET_NAME)))
        check(game_upper == menu_upper,
              '%s: the in-game NTLMv2 proof is computed from other inputs than the menu\'s: the menu\'s matches '
              'NTOWFv2(password, UPPER(%s), %s) upper-cased %s, the game\'s %s' %
              (label, ascii(want_user), ascii(TARGET_NAME), ' or '.join(menu_upper) or 'no way',
               ' or '.join(game_upper) or 'no way'))
        check('session setup 1' in g['out'], '%s: the in-game reader did not finish the logon:\n%s' % (label, g['out']))

if failures:
    print('SMB2 logon parity checks FAILED:')
    for failure in failures:
        print('  ' + failure)
    sys.exit(1)
print('smb2 logon parity: the in-game reader and the menu send the same UserName and DomainName, and compute '
      'their NTLMv2 proofs from the same user, domain and password (named, mixed-case, non-ASCII and blank users)')
