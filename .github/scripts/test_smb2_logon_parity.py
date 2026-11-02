"""The in-game SMB2 reader logs on with the same user name, domain, password and AV pairs as the menu.

A server recomputes NTOWFv2 from the user name and the domain the client sends (MS-NLMP 3.3.2). If
the game's logon sends another user name or domain than the menu's, or hashes another one, a
password that works in the menu can fail at game start, and only on some servers: Samba, which the
live harness uses, accepts several domains for one account. The AV pairs in the NTLMv2 blob are the
CHALLENGE's TargetInfo as the client sends it back, and libsmb2 puts an MsvAvTargetName that names
the server in front of each MsvAvEOL: "cifs/<ip>", or "cifs/<ip>:<port>" off port 445. A server set
to check it (on Windows, "Server SPN target name validation level") can refuse a logon without it.

This builds both clients on the host and runs them against one fake SMB2 server, on one port, that
sends both the same CHALLENGE, then compares the AUTHENTICATE messages they send: UserName,
DomainName, the user, domain and password their NTLMv2 proofs are computed from, and the AV pairs
of their NTLMv2 blobs, byte for byte. The CHALLENGE's TargetName, ParityDom, is in mixed case and
differs from its MsvAvNbDomainName AV pair, so a logon that changes the domain's case or takes it
from the AV pair fails. The menu's AV pairs are also checked against with_target_name() below, so a
libsmb2 that rewrites TargetInfo another way fails here as well.
Both clients are linked with connect() wrapped: every IPv4 connect goes to the fake server, and the
address and port it was meant for are printed, and checked. So the clients can be told any server:
the fake server's own port; port 445, which the name leaves out (no privileged port is opened);
port 1111, the menu's default; port 0, which both take as 445 (and name without a port); and
192.168.100.200 on port 65535, the longest name there is.
TargetInfo lists that break MS-NLMP's rules (no EOL, pairs after the EOL, two EOLs, an EOL that
claims a value or more than the list holds, a pair that overruns the list, a stray byte, a list as
long as the game takes, a TargetName after the list) must come back the same way from both. Lists
that leave libsmb2 no AV pairs to send back (empty, at the end of the CHALLENGE; a stray 3 bytes; a
first pair that overruns the list) must make both refuse the logon. Lists of many EOLs, which the
two stop at different limits by design, run on the game alone, under AddressSanitizer as every run
here: its AV pairs must be the same rewrite stopped at smb2.c's SMB2_TI_MAX.
The game's LM response and NTLMv2 timestamp are checked on their own, as libsmb2 sends neither
(its LM response is empty and its timestamp is its own clock): Z(24) and the server's timestamp
when the AV pairs it kept have an MsvAvTimestamp, else LMv2 and no timestamp (the IOP has no
clock). The rest of the two messages is not compared, and differs: the flags, neither of them an
input to the proof, and each blob's client challenge.
- The game: tests/smb2-live/ingame.c around the real modules/iopcore/cdvdman/smb2.c.
- The menu: the vendored libsmb2, set up the way smb2man_new_context() sets it up and connected the
  way smb2man.c connects. getlogin_r() fails as it does in libsmb2's IOP build, so a blank user is
  libsmb2's default, "Guest". smb2man.c itself needs the PS2SDK to build, so its calls are checked
  in its source (comments ignored, and the contents of literals but for the server's formats): the
  same setters as here, the password set once and always, no user and no domain set, the server
  named as here and passed to every connect, and a blank user passed as NULL.
The EE (its ethsupport source) gives smb2man's LOGON and the game the same address, as
"%u.%u.%u.%u", and the same port; this check does not look at that.
That smb2.c names the server by its address and port as the EE gives them is checked here; that it
logs on to a real server is checked by tests/smb2-live/run.sh.
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


# The most TargetInfo bytes smb2.c keeps, AV pairs and names; its walk ends at a pair past it.
_ti_max = re.search(r'^#define\s+SMB2_TI_MAX\s+(\d+)\b', (cdvdman / 'smb2.c').read_text(encoding='utf-8'), re.M)
check(_ti_max is not None, 'SMB2_TI_MAX is not defined in modules/iopcore/cdvdman/smb2.c: update this check')
TI_MAX = int(_ti_max.group(1)) if _ti_max else 512


def strip_comments(src, keep_literals=False):
    """C source with each comment replaced by a space (its newlines kept) and, unless keep_literals,
    the contents of each string and character literal dropped, so neither can pass for code. Lines
    that end in a backslash are joined first, as C joins them before it removes comments."""
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
            out.append(src[i:j + 1] if keep_literals else src[i] * 2)
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
smb2man_src = (root / 'modules/network/smb2man/smb2man.c').read_text(encoding='utf-8').replace('\r\n', '\n')
smb2man = strip_comments(smb2man_src)
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
# The server libsmb2 connects to is the one it names in the NTLMv2 blob ("cifs/" and the server).
# smb2man.c's LOGON writes it, "<ip>", or "<ip>:<port>" off port 445, nothing else writes it, and
# every connect passes it.
logon_case = re.search(r'\bcase\s+SMB_DEVCTL_LOGON\s*:(.*?)\bcase\s+SMB_DEVCTL_\w+\s*:',
                       strip_comments(smb2man_src, keep_literals=True), re.S)
check(logon_case is not None and re.search(
    r'\bif\s*\(\s*logon->serverPort\s*>\s*0\s*&&\s*logon->serverPort\s*!=\s*445\s*\)\s*'
    r'sprintf\(\s*conn_server\s*,\s*"%\.15s:%d"\s*,\s*logon->serverIP\s*,\s*logon->serverPort\s*\)\s*;\s*'
    r'else\s+sprintf\(\s*conn_server\s*,\s*"%\.15s"\s*,\s*logon->serverIP\s*\)\s*;', logon_case.group(1)) is not None,
    'smb2man.c\'s LOGON names the server another way than "<ip>", or "<ip>:<port>" off port 445: make the menu '
    "logon in this check and smb2.c's spn do the same")
check(len(re.findall(r'\bconn_server\b', smb2man)) == 3 + len(connects) and
      all(re.match(r'\s*\w+\s*,\s*conn_server\s*,', c) for c in connects),
      'smb2man.c now writes conn_server elsewhere, or connects to another server: make the menu logon in this check '
      "and smb2.c's spn do the same")


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


# ---- AV pairs (MS-NLMP 2.2.2.1) --------------------------------------------------------------------
MSV_AV_EOL, MSV_AV_TIMESTAMP, MSV_AV_TARGET_NAME = 0, 7, 9


def av(code, value):
    return struct.pack('<HH', code, len(value)) + value


def with_target_name(ti, spn, cap=None):
    """The AV pairs libsmb2 sends for a CHALLENGE's TargetInfo (lib/ntlmssp.c,
    ntlm_decode_challenge_message()): each pair copied, and in front of each MsvAvEOL an
    MsvAvTargetName that names the server by spn, in UTF-16LE. An EOL is copied without a value, and
    what it claims as one is read as pairs; the walk ends at a pair that overruns the list, which is
    dropped with whatever follows. (libsmb2 also stops at the end of its buffer, the CHALLENGE's
    length + 400 bytes, which the lists compared with it are far from.) With cap, the walk also ends
    at a pair that would end more than cap bytes in, names included, as smb2.c's ends at SMB2_TI_MAX."""
    out, off = b'', 0
    while off + 4 <= len(ti):
        code, length = struct.unpack_from('<HH', ti, off)
        if off + 4 + length > len(ti) or (cap is not None and len(out) + 4 + length > cap):
            break
        if code == MSV_AV_EOL:
            out += av(MSV_AV_TARGET_NAME, u16(spn)) + av(MSV_AV_EOL, b'')
            off += 4
        else:
            out += ti[off:off + 4 + length]
            off += 4 + length
    return out


def pairs(avs):
    """AV pairs as AvId=value, names decoded from UTF-16LE, then any bytes left over."""
    out, off = [], 0
    while off + 4 <= len(avs):
        code, length = struct.unpack_from('<HH', avs, off)
        value = avs[off + 4:off + 4 + length]
        out.append('%d=%s' % (code, ascii(value.decode('utf-16-le', 'replace')) if code in (1, 2, 3, 4, 5, 9) else
                              value.hex()))
        off += 4 + length
    if off < len(avs):
        out.append('then ' + avs[off:].hex())
    return '[' + ', '.join(out) + ']'


# ---- the fake server -------------------------------------------------------------------------------
TARGET_NAME = 'ParityDom'  # mixed case: a logon that changes the domain's case must fail
SERVER_CHALLENGE = bytes.fromhex('0123456789abcdef')
TIMESTAMP = struct.pack('<Q', 133000000000000000)
STATUS_SUCCESS, STATUS_MORE_PROCESSING_REQUIRED = 0, 0xC0000016
STATUS_ACCESS_DENIED, STATUS_NOT_SUPPORTED = 0xC0000022, 0xC00000BB
NTLMSSP_NEGOTIATE_ANONYMOUS = 0x00000800

# MsvAvNbDomainName (2) differs from TargetName on purpose: both logons must take the domain from
# TargetName, and a logon that read it from this AV pair would otherwise pass.
PAIRS = (av(2, u16('PARITYNB')) + av(1, u16('FAKESRV')) + av(4, u16('paritydom.test')) +
         av(3, u16('fakesrv.paritydom.test')) + av(MSV_AV_TIMESTAMP, TIMESTAMP))
EOL = av(MSV_AV_EOL, b'')
TARGET_INFO = PAIRS + EOL  # as servers send it
# TargetInfo lists that break MS-NLMP 2.2.2.1. Both logons must send them back the same way.
ODD_TARGET_INFO = [
    ('without an EOL', PAIRS),
    ('of only an EOL', EOL),
    ('with a pair after the EOL', TARGET_INFO + av(5, u16('paritydom.test'))),
    ('with two EOLs', av(2, u16('PARITYNB')) + EOL + av(1, u16('FAKESRV')) + av(MSV_AV_TIMESTAMP, TIMESTAMP) + EOL),
    ('with an EOL that claims a value', PAIRS + struct.pack('<HH', MSV_AV_EOL, 8) + av(1, u16('XY'))),
    ('with a pair that overruns the list and the EOL', PAIRS + struct.pack('<HH', 1, 50) + u16('short') + EOL),
    ('with a pair that overruns the list after the EOL', TARGET_INFO + struct.pack('<HH', 1, 50) + u16('short')),
    ('with a stray byte after the EOL', TARGET_INFO + b'\x01'),
    ('with an EOL that claims more than the list holds', PAIRS + struct.pack('<HH', MSV_AV_EOL, 50)),
    # As long as smb2.c takes, with its EOL at the end: the name goes in past SMB2_TI_MAX bytes.
    ('of SMB2_TI_MAX bytes, its EOL at the end', PAIRS + av(5, u16('t' * ((TI_MAX - len(PAIRS) - 8) // 2))) + EOL),
]
assert len(ODD_TARGET_INFO[-1][1]) == TI_MAX
# The same with the CHALLENGE's TargetName after its TargetInfo (as Windows lays them out), so a
# pair that overruns the list ends in TargetName, not at the end of the message. Even lengths only:
# an odd one puts TargetName at an odd offset, where the vendored libsmb2 reads it misaligned.
TN_LAST_TARGET_INFO = [
    ('with a pair that overruns it into TargetName', TARGET_INFO + struct.pack('<HH', 1, 12) + u16('ab')),
    ('empty, its offset inside the CHALLENGE', b''),
]
# Lists that leave libsmb2 no AV pairs to send back, so that it refuses the logon (lib/ntlmssp.c,
# encode_ntlm_auth()): the game must refuse it too.
REFUSED_TARGET_INFO = [
    ('empty, its offset at the end of the CHALLENGE', b''),
    ('of a stray 3 bytes', b'\x01\x00\x00'),
    ('whose first pair overruns it', struct.pack('<HH', 1, 50) + u16('short')),
]
# Lists that the two stop at different limits by design (SMB2_TI_MAX in the game, the CHALLENGE's
# length + 400 in libsmb2): run on the game alone, against with_target_name() capped as smb2.c caps.
CAPPED_TARGET_INFO = [
    ('of 20 EOLs', EOL * 20),
    ('of SMB2_TI_MAX bytes of EOLs', EOL * (TI_MAX // 4)),
]


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


def challenge_message(ti, tn_last=False):
    tn = u16(TARGET_NAME)
    tn_off, ti_off = (56 + len(ti), 56) if tn_last else (56, 56 + len(tn))
    # UNICODE, REQUEST_TARGET, SIGN, NTLM, ALWAYS_SIGN, TARGET_TYPE_DOMAIN, EXTENDED_SESSIONSECURITY,
    # TARGET_INFO, VERSION, 128, 56
    flags = 0x00000001 | 0x00000004 | 0x00000010 | 0x00000200 | 0x00008000 | 0x00010000 | 0x00080000 | \
        0x00800000 | 0x02000000 | 0x20000000 | 0x80000000
    m = b'NTLMSSP\0' + struct.pack('<I', 2)
    m += struct.pack('<HHI', len(tn), len(tn), tn_off)
    m += struct.pack('<I', flags) + SERVER_CHALLENGE + b'\0' * 8
    m += struct.pack('<HHI', len(ti), len(ti), ti_off)
    m += bytes([6, 1]) + struct.pack('<H', 7600) + b'\0\0\0\x0f'
    assert len(m) == 56
    return m + (ti + tn if tn_last else tn + ti)


def serve_one(sock, ti, tn_last, record):
    """Answer one client: NEGOTIATE (2.1 when offered), the two SESSION_SETUP legs, with this
    TargetInfo in the CHALLENGE (before TargetName with tn_last), and a TREE_CONNECT that is refused,
    which ends both clients. Records the AUTHENTICATE_MESSAGE's fields."""
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
                    ch = challenge_message(ti, tn_last)
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


def proof_inputs(rec, password, user_upper, domain):
    """Whether the client's NTProofStr was computed from this password, upper-cased user and domain."""
    nt = rec.get('nt', b'')
    if len(nt) < 16 + 28:
        return False
    ntowf = hmac_md5(md4(u16(password)), u16(user_upper) + domain)
    return hmac_md5(ntowf, SERVER_CHALLENGE + nt[16:]) == nt[:16]


def av_pairs(rec):
    """The AV pairs of the client's NTLMv2 blob: NtChallengeResponse is NTProofStr (16 bytes), the
    blob's 28-byte header, the AV pairs and Z(4)."""
    return rec['nt'][16 + 28:len(rec['nt']) - 4]


# NTOWFv2 hashes UPPER(user). Both logons upper-case only ASCII letters today; what matters is that
# they do the same.
UPPER = [('full Unicode', str.upper), ('ASCII only', lambda s: ''.join(c.upper() if c < '\x80' else c for c in s))]


MENU = r'''
/* The menu's logon: libsmb2 set up as smb2man_new_context() sets it up (signing enabled, SMB 2.0.2
   and 2.1, a timeout, the password always set, no user and no domain set) and connected as
   smb2man.c connects: to the server as its LOGON names it, "<ip>", or "<ip>:<port>" off port 445,
   with a blank user passed as NULL. */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
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
    /* argv: ip port share user password */
    struct smb2_context *ctx;
    char server[64];
    int rc, port;

    if (argc < 6 || (ctx = smb2_init_context()) == NULL)
        return 2;
    port = atoi(argv[2]);
    if (port > 0 && port != 445)
        sprintf(server, "%.15s:%d", argv[1], port);
    else
        sprintf(server, "%.15s", argv[1]);
    smb2_set_security_mode(ctx, SMB2_NEGOTIATE_SIGNING_ENABLED);
    smb2_set_version(ctx, SMB2_VERSION_ANY2);
    smb2_set_timeout(ctx, 10);
    smb2_set_password(ctx, argv[5]);
    rc = smb2_connect_share(ctx, server, argv[3], argv[4][0] ? argv[4] : NULL);
    printf("connect %d: %s\n", rc, smb2_get_error(ctx));
    smb2_destroy_context(ctx);
    return 0;
}
'''

# Linked into both clients with -Wl,--wrap=connect: every IPv4 connect goes to the fake server
# (127.0.0.1, port CONNECT_TO) instead, and prints the address and port it was meant for. So a client
# can be told any address and port, 445 included, without anything listening there.
WRAP = r'''
#include <stdio.h>
#include <stdlib.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>

int __real_connect(int fd, const struct sockaddr *sa, socklen_t len);

int __wrap_connect(int fd, const struct sockaddr *sa, socklen_t len)
{
    const char *to = getenv("CONNECT_TO");

    if (to != NULL && sa->sa_family == AF_INET) {
        struct sockaddr_in a = *(const struct sockaddr_in *)sa;
        char ip[INET_ADDRSTRLEN];

        inet_ntop(AF_INET, &a.sin_addr, ip, sizeof(ip));
        fprintf(stderr, "wrapped connect to %s:%u\n", ip, (unsigned)ntohs(a.sin_port));
        a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        a.sin_port = htons((unsigned short)atoi(to));
        return __real_connect(fd, (const struct sockaddr *)&a, sizeof(a));
    }
    return __real_connect(fd, sa, len);
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
    (tmp / 'wrap.c').write_text(WRAP)
    wrap = [str(tmp / 'wrap.c'), '-Wl,--wrap=connect']
    game = tmp / 'ingame'
    cc(SAN + ['-Wall', '-Wno-unused-parameter', '-I', str(live / 'inc-ingame'), '-I', str(cdvdman), '-I',
              str(root / 'modules/iopcore/common'), str(live / 'ingame.c'), str(cdvdman / 'smb2.c'),
              str(cdvdman / 'smb2auth.c')] + wrap + ['-o', str(game)], 'the in-game reader (smb2.c)')
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
    cc(SAN + ['-Wall', '-I', str(lib / 'include'), str(tmp / 'menu.c')] + objs + wrap + ['-o', str(menu)],
       "the menu's logon (libsmb2)")

    def logon(ti, user, password, ip, port, tn_last, game_only):
        """Run the game's logon, then the menu's (unless game_only), against one fake server (one
        port, so both name the same server) that sends both this TargetInfo. Both are told this
        address and port (the fake server's own port if None), and the wrapped connect() takes them
        to the fake server. Returns the port the clients were told and each client's AUTHENTICATE
        fields and output (None for the menu with game_only)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        sock.listen(2)
        port = sock.getsockname()[1] if port is None else port
        env = dict(os.environ)
        env.pop('NTLM_USER_FILE', None)  # libsmb2 on the host would read a password from it
        env['CONNECT_TO'] = str(sock.getsockname()[1])
        u8, p8 = user.encode('utf-8'), password.encode('utf-8')
        records = []
        argvs = [[str(game), ip, str(port), u8, p8, 'PS2SMB', '\\DVD\\TEST.iso', '\\VMC\\card.bin']]
        if not game_only:
            argvs.append([str(menu), ip, str(port), 'PS2SMB', u8, p8])
        for argv in argvs:
            record = {}
            server = threading.Thread(target=serve_one, args=(sock, ti, tn_last, record), daemon=True)
            server.start()
            try:
                p = subprocess.run(argv, capture_output=True, text=True, timeout=60, env=env)
                record['out'], record['rc'] = p.stdout + p.stderr, p.returncode
            except subprocess.TimeoutExpired:
                record['out'], record['rc'] = 'timed out', None
            server.join(10)
            records.append(record)
        sock.close()
        return port, records[0], None if game_only else records[1]

    def name_of(field):
        return ascii(field.decode('utf-16-le', 'replace'))

    def spn_of(ip, port):
        """The server as smb2man.c names it to libsmb2, and so as both name it in the NTLMv2 blob."""
        return 'cifs/%s:%d' % (ip, port) if port > 0 and port != 445 else 'cifs/%s' % ip

    def common_checks(label, ip, port, clients):
        """No sanitizer report, no server error, and every connect to the address and port told
        (port 0 is 445, as in libsmb2)."""
        want = '%s:%d' % (ip, port if port > 0 else 445)
        for name, rec in clients:
            check('error' not in rec, '%s, %s logon: %s' % (label, name, rec.get('error')))
            check('Sanitizer' not in rec['out'] and 'runtime error' not in rec['out'],
                  '%s, %s logon: a sanitizer report:\n%s' % (label, name, rec['out']))
            connects = re.findall(r'^wrapped connect to (\S+)$', rec['out'], re.M)
            check(connects and all(c == want for c in connects), '%s, %s logon: connected to %s, not only to %s' %
                  (label, name, ', '.join(connects) or 'nothing', want))

    def lm_and_timestamp(label, rec, password, user_upper):
        """The game's LM response and NTLMv2 timestamp (MS-NLMP 3.3.2): with a server timestamp
        among the AV pairs it kept, Z(24) and that timestamp; without, LMv2 over the blob's client
        challenge, and no timestamp."""
        kept, off, avs = [], 0, av_pairs(rec)
        while off + 4 <= len(avs):
            code, length = struct.unpack_from('<HH', avs, off)
            if code == MSV_AV_TIMESTAMP and length == 8:
                kept.append(avs[off + 4:off + 12])
            off += 4 + length
        lm, blob = rec['lm'], rec['nt'][16:]
        if kept:
            check(lm == bytes(24) and blob[8:16] == kept[-1],
                  '%s: the in-game logon sends LM %s and timestamp %s; with the server\'s timestamp among the AV pairs '
                  'it should send Z(24) and %s' % (label, lm.hex(), blob[8:16].hex(), kept[-1].hex()))
        else:
            ntowf = hmac_md5(md4(u16(password)), u16(user_upper) + u16(TARGET_NAME))
            check(len(lm) == 24 and lm[16:] == blob[16:24] and lm[:16] == hmac_md5(ntowf, SERVER_CHALLENGE + lm[16:]) and
                  blob[8:16] == bytes(8),
                  '%s: the in-game logon sends LM %s and timestamp %s; without a server timestamp it should send '
                  'LMv2 over the blob\'s client challenge %s, and no timestamp' %
                  (label, lm.hex(), blob[8:16].hex(), blob[16:24].hex()))

    def run(label, user='ps2', password='secret', ti=TARGET_INFO, ip='127.0.0.1', port=None, tn_last=False):
        port, g, m = logon(ti, user, password, ip, port, tn_last, False)
        common_checks(label, ip, port, [('in-game', g), ('menu', m)])
        for name, rec in [('in-game', g), ('menu', m)]:
            check('nt' in rec, '%s, %s logon: no AUTHENTICATE_MESSAGE reached the server (exit %s):\n%s' %
                  (label, name, rec['rc'], rec['out']))
        if 'nt' not in g or 'nt' not in m:
            return
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
        # The AV pairs, byte for byte: the menu's are the CHALLENGE's TargetInfo with the server named
        # as smb2man.c names it, and the game's are the menu's.
        for name, rec in [('in-game', g), ('menu', m)]:
            check(len(rec['nt']) >= 16 + 28 + 4 and rec['nt'][-4:] == bytes(4),
                  '%s: the %s NTLMv2 blob does not end in Z(4)' % (label, name))
        want = with_target_name(ti, spn_of(ip, port))
        check(av_pairs(m) == want,
              '%s: the menu (libsmb2) sends the AV pairs %s; this check expects %s: libsmb2 or smb2man changed, '
              'update this check and smb2.c together' % (label, pairs(av_pairs(m)), pairs(want)))
        check(av_pairs(g) == av_pairs(m), '%s: the in-game logon sends the AV pairs %s, the menu sends %s' %
              (label, pairs(av_pairs(g)), pairs(av_pairs(m))))
        if game_upper:
            lm_and_timestamp(label, g, password, dict(UPPER)[game_upper[0]](want_user))
        check('session setup 1' in g['out'], '%s: the in-game reader did not finish the logon:\n%s' % (label, g['out']))

    def refused(label, ti, tn_last=False):
        """Both clients refuse the logon: neither sends an AUTHENTICATE_MESSAGE."""
        port, g, m = logon(ti, 'ps2', 'secret', '127.0.0.1', None, tn_last, False)
        common_checks(label, '127.0.0.1', port, [('in-game', g), ('menu', m)])
        check(re.search(r'^connect -\d+:', m['out'], re.M) and 'nt' not in m,
              '%s: the menu (libsmb2) logs on; this check expects it to refuse: libsmb2 changed, update this check and '
              'smb2.c together:\n%s' % (label, m['out']))
        check('session setup -1000' in g['out'] and 'nt' not in g,
              '%s: the in-game logon does not refuse, as the menu does:\n%s' % (label, g['out']))

    def capped(label, ti, ip, port):
        """The game alone: its AV pairs are the rewrite stopped at SMB2_TI_MAX, without a sanitizer report."""
        port, g, _ = logon(ti, 'ps2', 'secret', ip, port, False, True)
        common_checks(label, ip, port, [('in-game', g)])
        check('nt' in g, '%s, in-game logon: no AUTHENTICATE_MESSAGE reached the server (exit %s):\n%s' %
              (label, g['rc'], g['out']))
        if 'nt' not in g:
            return
        want = with_target_name(ti, spn_of(ip, port), TI_MAX)
        check(av_pairs(g) == want, '%s: the in-game logon sends the AV pairs %s; with SMB2_TI_MAX %d it should send %s' %
              (label, pairs(av_pairs(g)), TI_MAX, pairs(want)))
        check('session setup 1' in g['out'], '%s: the in-game reader did not finish the logon:\n%s' % (label, g['out']))

    # (user, password) as configured on the console. Mixed case: the proof hashes UPPER(user), the
    # message sends it as typed. Blank: both log on as "Guest" (with the password, or an empty one).
    for user, password in [('ps2', 'secret'), ('MixedCase', 'Pass word'), ('José', 'Café'), ('', 'secret'),
                           ('', '')]:
        run('user %s, password %s' % (ascii(user), ascii(password)), user, password)
    # The server as the EE can give it: on port 445 and port 0 (which both take as 445) both name it
    # without the port; 1111 is the menu's default; 192.168.100.200:65535 is the longest name.
    run('port 445', port=445)
    run('port 0', port=0)
    run('port 1111', port=1111)
    run('192.168.100.200 on port 65535', ip='192.168.100.200', port=65535)
    for what, ti in ODD_TARGET_INFO:
        run('TargetInfo ' + what, ti=ti)
    run('TargetInfo of SMB2_TI_MAX bytes, 192.168.100.200 on port 65535', ti=ODD_TARGET_INFO[-1][1],
        ip='192.168.100.200', port=65535)
    for what, ti in TN_LAST_TARGET_INFO:
        run('TargetInfo before TargetName, ' + what, ti=ti, tn_last=True)
    for what, ti in REFUSED_TARGET_INFO:
        refused('TargetInfo ' + what, ti)
    for what, ti in CAPPED_TARGET_INFO:
        capped('TargetInfo ' + what + ', 192.168.100.200 on port 65535', ti, '192.168.100.200', 65535)

if failures:
    print('SMB2 logon parity checks FAILED:')
    for failure in failures:
        print('  ' + failure)
    sys.exit(1)
print('smb2 logon parity: the in-game reader and the menu connect to the same server and send the same UserName, '
      'DomainName and NTLMv2 AV pairs (the server named on its own port, 445, 0, 1111 and the longest name, and '
      'TargetInfo lists that break the rules sent back alike, or refused alike), and compute their NTLMv2 proofs '
      'from the same user, domain and password (named, mixed-case, non-ASCII and blank users); the game keeps '
      'within SMB2_TI_MAX and sends its LM response and timestamp as MS-NLMP asks')
