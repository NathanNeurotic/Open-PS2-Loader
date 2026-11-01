"""The in-game SMB2 reader's hashing and NTLMv2 logon match the published test vectors.

modules/iopcore/cdvdman/smb2auth.c carries its own MD4, MD5, SHA-256 and HMAC (smb2_cdvdman has no
libc and every byte is resident in IOP RAM during the game). smb2.c builds the NTLMv2 logon and the
SMB 2.x signature from them. A wrong round constant would not crash: it would make every logon fail
with STATUS_LOGON_FAILURE, or every signed request be rejected, and only on a real server.

This compiles the real smb2auth.c on the host and checks it against:
- RFC 1320 (MD4), RFC 1321 (MD5) and FIPS 180-2 (SHA-256) test suites, plus Python's hashlib for
  random lengths around the 55/56/64-byte padding boundaries, fed in odd-sized pieces;
- RFC 2202 (HMAC-MD5) and RFC 4231 (HMAC-SHA256);
- MS-NLMP 4.2.4 (NTLMv2): NTOWFv2, the LMv2 and NTLMv2 responses and the session base key, computed
  the way smb2.c computes them.

It also pins the structure smb2.c relies on: smb2.c provides every function smb.c does (device-smb.c,
the oplutils exports and smb_mcemu bind to those names), smb_Close() never waits on smb_io_sema
(oplShutdown() calls it with the semaphore held), every function that waits on it signals it before
each return, and smbinit's SMB1 hash callback is never called.
This is a host regression check, not a console test. The end-to-end check against a real server is
tools/pc/smb2/run.sh (needs Samba).
"""
from pathlib import Path
import hashlib
import hmac
import random
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
cdvdman = root / 'modules/iopcore/cdvdman'
failures = []


def text(path):
    return Path(path).read_text(encoding='utf-8').replace('\r\n', '\n')


def check(cond, what):
    if not cond:
        failures.append(what)


HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "smb2auth.h"

static int unhex(const char *s, u8 *out)
{
    int n = 0;
    while (s[0] && s[1]) {
        unsigned v;
        sscanf(s, "%2x", &v);
        out[n++] = (u8)v;
        s += 2;
    }
    return n;
}

static void hex(const u8 *d, int n)
{
    for (int i = 0; i < n; i++)
        printf("%02x", d[i]);
    printf("\n");
}

/* argv: mode kind key-hex data-hex. mode h = hash, m = hmac. Data is fed in 7-byte pieces. */
int main(int argc, char **argv)
{
    static u8 key[256], data[100000], d[32];
    int kind = atoi(argv[2]);
    int klen = unhex(argv[3], key), dlen = unhex(argv[4], data), out = (kind == SMB2AUTH_SHA256) ? 32 : 16;
    if (argv[1][0] == 'h') {
        smb2auth_hash_t h;
        smb2auth_init(&h, kind);
        for (int i = 0; i < dlen; i += 7)
            smb2auth_update(&h, data + i, (dlen - i) < 7 ? (dlen - i) : 7);
        smb2auth_final(&h, d);
    } else {
        smb2auth_hmac_t m;
        smb2auth_hmac_init(&m, kind, key, klen);
        for (int i = 0; i < dlen; i += 7)
            smb2auth_hmac_update(&m, data + i, (dlen - i) < 7 ? (dlen - i) : 7);
        smb2auth_hmac_final(&m, d);
    }
    hex(d, out);
    return 0;
}
'''

MD4, MD5, SHA256 = 0, 1, 2

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / 'tamtypes.h').write_text(
        '#include <stdint.h>\n#include <stddef.h>\n'
        'typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;\n')
    (tmp / 'h.c').write_text(HARNESS)
    exe = tmp / 'h'
    build = subprocess.run(['cc', '-O1', '-Wall', '-Werror', '-I', str(tmp), '-I', str(cdvdman), str(tmp / 'h.c'),
                            str(cdvdman / 'smb2auth.c'), '-o', str(exe)], capture_output=True, text=True)
    if build.returncode != 0:
        print(build.stdout + build.stderr)
        sys.exit('smb2auth.c does not build on the host')

    def run(mode, kind, data, key=b''):
        return subprocess.run([str(exe), mode, str(kind), key.hex(), data.hex()], capture_output=True,
                              text=True, check=True).stdout.strip()

    def H(kind, data):
        return run('h', kind, data)

    def M(kind, key, data):
        return run('m', kind, data, key)

    # RFC 1320 appendix A.5.
    for msg, want in [(b'', '31d6cfe0d16ae931b73c59d7e0c089c0'), (b'a', 'bde52cb31de33e46245e05fbdbd6fb24'),
                      (b'abc', 'a448017aaf21d8525fc10ae87aa6729d'), (b'message digest', 'd9130a8164549fe818874806e1c7014b'),
                      (b'abcdefghijklmnopqrstuvwxyz', 'd79e1c308aa5bbcdeea8ed63df412da9'),
                      (b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', '043f8582f241db351ce627e153e7f0e4'),
                      (b'1234567890' * 8, 'e33b4ddc9c38f2199c3e7b164fcc0536')]:
        check(H(MD4, msg) == want, 'MD4(%r) = %s, want %s' % (msg[:16], H(MD4, msg), want))
    # RFC 1321 appendix A.5 and FIPS 180-2 appendix B.
    check(H(MD5, b'') == 'd41d8cd98f00b204e9800998ecf8427e', 'MD5("")')
    check(H(MD5, b'1234567890' * 8) == '57edf4a22be3c955ac49da2e2107b67a', 'MD5(RFC 1321 #7)')
    check(H(SHA256, b'abc') == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad', 'SHA-256("abc")')
    check(H(SHA256, b'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq') ==
          '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1', 'SHA-256(448-bit message)')
    rnd = random.Random(1320)
    for n in [0, 1, 55, 56, 57, 63, 64, 65, 119, 120, 127, 128, 129, 1000] + [rnd.randrange(0, 4000) for _ in range(12)]:
        data = bytes(rnd.randrange(256) for _ in range(n))
        check(H(MD5, data) == hashlib.md5(data).hexdigest(), 'MD5 of %d bytes' % n)
        check(H(SHA256, data) == hashlib.sha256(data).hexdigest(), 'SHA-256 of %d bytes' % n)
        key = bytes(rnd.randrange(256) for _ in range(16))
        check(M(MD5, key, data) == hmac.new(key, data, 'md5').hexdigest(), 'HMAC-MD5 of %d bytes' % n)
        check(M(SHA256, key, data) == hmac.new(key, data, 'sha256').hexdigest(), 'HMAC-SHA256 of %d bytes' % n)
    # RFC 2202 test case 2 and RFC 4231 test case 2.
    check(M(MD5, b'Jefe', b'what do ya want for nothing?') == '750c783e6ab0b503eaa86e310a5db738', 'HMAC-MD5 RFC 2202 #2')
    check(M(SHA256, b'Jefe', b'what do ya want for nothing?') ==
          '5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843', 'HMAC-SHA256 RFC 4231 #2')

    # MS-NLMP 4.2.4: User "User", domain "Domain", password "Password", time 0, client challenge aa*8.
    u16 = lambda s: s.encode('utf-16-le')
    nthash = H(MD4, u16('Password'))
    check(nthash == 'a4f49c406510bdcab6824ee7c30fd852', 'MS-NLMP 4.2.2.1.2 NTOWFv1 (MD4 of the password)')
    ntowf = M(MD5, bytes.fromhex(nthash), u16('USER') + u16('Domain'))
    check(ntowf == '0c868a403bfd7a93a3001ef22ef02e3f', 'MS-NLMP 4.2.4.1.1 NTOWFv2: %s' % ntowf)
    sc, cc = bytes.fromhex('0123456789abcdef'), b'\xaa' * 8
    lm = M(MD5, bytes.fromhex(ntowf), sc + cc)
    check(lm == '86c35097ac9cec102554764a57cccc19', 'MS-NLMP 4.2.4.2.1 LMv2: %s' % lm)
    av = bytes.fromhex('02000c0044006f006d00610069006e00' '01000c0053006500720076006500720000000000')
    blob = bytes.fromhex('0101000000000000') + b'\0' * 8 + cc + b'\0' * 4 + av + b'\0' * 4
    proof = M(MD5, bytes.fromhex(ntowf), sc + blob)
    check(proof == '68cd0ab851e51c96aabc927bebef6a1c', 'MS-NLMP 4.2.4.2.2 NTProofStr: %s' % proof)
    sbk = M(MD5, bytes.fromhex(ntowf), bytes.fromhex(proof))
    check(sbk == '8de40ccadbc14a82f15cb0ad0de95ca3', 'MS-NLMP 4.2.4.1.2 session base key: %s' % sbk)

# smb2.c composes them in the same order (the blob layout and the HMAC inputs).
smb2 = text(cdvdman / 'smb2.c')
check('blob[0] = 1;' in smb2 and 'blob[1] = 1;' in smb2 and 'memcpy(blob + 8, timestamp, 8);' in smb2 and
      'memcpy(blob + 16, client_challenge, 8);' in smb2 and 'memcpy(blob + 28, ntlm_ti, tilen);' in smb2,
      'smb2.c: the NTLMv2 blob layout (MS-NLMP 2.2.2.7) changed')
check(re.search(r'smb2auth_hmac_update\(&mac, pw16, ulen\);\s*smb2auth_hmac_update\(&mac, domain, domlen\);', smb2) is not None,
      'smb2.c: NTOWFv2 must hash UPPER(user) then the domain')
check('put_utf16(pw16, user_name, 1)' in smb2, 'smb2.c: NTOWFv2 must upper-case the user name')

# The same entry points as smb.c, which device-smb.c, exports.tab and smb_mcemu bind to by name.
smb1 = text(cdvdman / 'smb.c')
for fn in ['smb_NegotiateProtocol', 'smb_SessionSetupAndX', 'smb_TreeConnectAndX', 'smb_OpenAndX', 'smb_Close',
           'smb_ReadFile', 'smb_WriteFile', 'smb_ReadCD', 'smb_CloseAll', 'smb_Disconnect']:
    sig = re.compile(r'^\w[\w \*]*\b%s\(' % fn, re.M)
    check(sig.search(smb1) is not None and sig.search(smb2) is not None, '%s must be defined in smb.c and smb2.c' % fn)
check(re.search(r'^int smb_io_sema = -1;', smb2, re.M) is not None, 'smb2.c must define smb_io_sema (device-smb.c locks it)')
check('hash_callback(' not in smb2, "smb2.c must not call smbinit's SMB1 hash callback (smbinit is unloaded)")


def function_body(src, name):
    m = re.search(r'^\w[\w \*]*\b%s\([^)]*\)\n\{\n' % name, src, re.M)
    if not m:
        return ''
    end = src.find('\n}\n', m.end())
    return src[m.end():end]


check('WaitSema' not in function_body(smb2, 'smb_Close'), 'smb2.c: smb_Close must not wait on smb_io_sema')
for fn in ['smb_OpenAndX', 'smb_ReadFile', 'smb_WriteFile']:
    body = function_body(smb2, fn)
    after = body[body.find('WaitSema(smb_io_sema);'):] if 'WaitSema(smb_io_sema);' in body else ''
    check(after != '', 'smb2.c: %s must take smb_io_sema' % fn)
    for ret in re.finditer(r'return [^;]*;', after):
        before = re.sub(r'(\s*//[^\n]*)+$', '', after[:ret.start()].rstrip()).rstrip()  # skip comment lines
        check(before.endswith('SignalSema(smb_io_sema);'), 'smb2.c: %s returns without signalling smb_io_sema: %s' % (fn, ret.group(0)))

if failures:
    print('SMB2 auth checks FAILED:')
    for failure in failures:
        print('  ' + failure)
    sys.exit(1)
print('smb2auth: MD4/MD5/SHA-256/HMAC and MS-NLMP NTLMv2 vectors match; smb2.c keeps smb.c\'s interface')
