"""Host test for src/ratls.c: verified HTTPS GET over the vendored mbedTLS (TLS 1.3 and 1.2).

The RA edition looks games up on retroachievements.org over HTTPS (ORBIT parity). This builds the
portable TLS + HTTP code (src/ratls.c) with the vendored mbedTLS and RiptOPL's configuration, then
drives it (tests/ratls/host_main.c) against local Python TLS servers using a throwaway test CA:
full GETs on TLS 1.3 and TLS 1.2, chunked and close-delimited bodies, refusal of oversize bodies,
wrong host names, expired and untrusted certificates, an unset clock (no connection at all), a
stalled server, a 404, plus the six real anchors, the RTC conversion and DRBG reseeding.
"""
import concurrent.futures
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MBED = ROOT / "third_party/mbedtls"
CC = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
FLAGS = ["-O1", "-I", str(ROOT), "-I", str(MBED / "include"), "-I", str(MBED),
         '-DMBEDTLS_CONFIG_FILE="riptopl_mbedtls_config.h"']
LIBS = ["-lws2_32", "-lbcrypt"] if sys.platform == "win32" else []
OPENSSL = shutil.which("openssl")
assert CC and OPENSSL, "needs a C compiler and the openssl CLI"

failures = []

# On the console the clock gate comes before any DNS lookup or connection.
_ps2 = (ROOT / "src/ratls_ps2.c").read_text(encoding="utf-8")
_get = _ps2[_ps2.index("int raHttpsGet("):]
assert _get.index("raTlsClockOk(") < _get.index("gethostbyname(") < _get.index("connect("), "clock check must precede DNS"
assert "raNetNicReserved()" in _get[:_get.index("gethostbyname(")]


def check(name, ok, detail=""):
    if not ok:
        failures.append(f"{name}: {detail}")
        print(f"FAIL {name}: {detail}")
    else:
        print(f"ok   {name}")


def build(tmp):
    objs = tmp / "obj"
    objs.mkdir()
    sources = sorted((MBED / "library").glob("*.c"))

    def compile_one(src):
        out = objs / (src.stem + ".o")
        subprocess.run([CC, "-c", *FLAGS, str(src), "-o", str(out)], check=True)
        return str(out)

    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        objects = list(pool.map(compile_one, sources))
    exe = tmp / ("host_main.exe" if sys.platform == "win32" else "host_main")
    subprocess.run([CC, *FLAGS, "-Wall", "-Werror", str(ROOT / "tests/ratls/host_main.c"), str(ROOT / "src/ratls.c"),
                    *objects, "-o", str(exe), *LIBS], check=True)
    return exe


def openssl(*args, cwd):
    subprocess.run([OPENSSL, *args], cwd=cwd, check=True, capture_output=True)


def make_pki(d):
    """A test CA plus leaves, all ECDSA P-256 (needed for the TLS 1.2 ECDHE-ECDSA suite)."""
    ec = ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes"]
    openssl("req", "-x509", *ec, "-keyout", "ca.key", "-out", "ca.pem", "-days", "3650",
            "-subj", "/CN=RiptOPL Test CA", "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign", cwd=d)
    openssl("x509", "-in", "ca.pem", "-outform", "der", "-out", "ca.der", cwd=d)
    for name, cn in (("leaf", "ra.test"), ("other", "other.test")):
        openssl("req", *ec, "-keyout", f"{name}.key", "-out", f"{name}.csr", "-subj", f"/CN={cn}", cwd=d)
        (d / f"{name}.ext").write_text(f"subjectAltName=DNS:{cn}\nbasicConstraints=CA:FALSE\n"
                                       "keyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n")
        openssl("x509", "-req", "-in", f"{name}.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
                "-out", f"{name}.pem", "-days", "30", "-extfile", f"{name}.ext", cwd=d)
    # An unrelated CA, for "untrusted root".
    openssl("req", "-x509", *ec, "-keyout", "stranger.key", "-out", "stranger.pem", "-days", "3650",
            "-subj", "/CN=Stranger CA", "-addext", "basicConstraints=critical,CA:TRUE", cwd=d)
    openssl("x509", "-in", "stranger.pem", "-outform", "der", "-out", "stranger.der", cwd=d)


class Server:
    """One-connection TLS (or silent TCP) server answering with a scripted HTTP response."""

    def __init__(self, d, cert="leaf", version=None, response=b"", tls=True):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.sock.settimeout(8)
        self.port = self.sock.getsockname()[1]
        self.accepts = 0
        self.request = b""
        self.response = response
        self.tls = tls
        self.ctx = None
        if tls:
            self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ctx.load_cert_chain(str(d / f"{cert}.pem"), str(d / f"{cert}.key"))
            if version == "1.3":
                self.ctx.minimum_version = self.ctx.maximum_version = ssl.TLSVersion.TLSv1_3
            elif version == "1.2":
                self.ctx.minimum_version = self.ctx.maximum_version = ssl.TLSVersion.TLSv1_2
                self.ctx.set_ciphers("ECDHE-ECDSA-AES128-GCM-SHA256")
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        self.accepts += 1
        if not self.tls:
            time.sleep(3)  # accept and say nothing
            conn.close()
            return
        try:
            with self.ctx.wrap_socket(conn, server_side=True) as tls:
                tls.settimeout(5)
                while b"\r\n\r\n" not in self.request:
                    chunk = tls.recv(4096)
                    if not chunk:
                        return
                    self.request += chunk
                tls.sendall(self.response)
                try:
                    tls.unwrap()
                except (ssl.SSLError, OSError):
                    pass
        except (ssl.SSLError, OSError):
            pass  # the client refused the certificate: expected in the negative cases

    def finish(self):
        self.thread.join(timeout=6)
        self.sock.close()


def get(exe, server_port, d, *, host="ra.test", path="/dorequest.php?r=gameid&m=abc", max_=4096,
        deadline=5000, now="sys", anchors=("ca.der",)):
    args = [str(exe), "get", host, str(server_port), path, str(max_), str(deadline), now] + [str(d / a) for a in anchors]
    out = subprocess.run(args, capture_output=True, timeout=30).stdout
    head, _, body = out.partition(b"--BODY--\n")
    rc = int(re.search(rb"rc=(-?\d+)", head).group(1))
    return rc, body


def http(body, extra=b""):
    return b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + \
        b"\r\n" + extra + b"Connection: close\r\n\r\n" + body


def main():
    json_body = b'{"Success":true,"GameID":2791}'
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        exe = build(tmp)
        d = tmp / "pki"
        d.mkdir()
        make_pki(d)

        for version in ("1.3", "1.2"):
            s = Server(d, version=version, response=http(json_body))
            rc, body = get(exe, s.port, d)
            s.finish()
            check(f"tls{version.replace('.', '')}_get", rc > 0 and body == json_body, f"rc={rc} body={body!r}")
            if version == "1.3":
                check("request_line", s.request.startswith(b"GET /dorequest.php?r=gameid&m=abc HTTP/1.1\r\n")
                      and b"\r\nHost: ra.test\r\n" in s.request and b"\r\nUser-Agent: RiptOPL/host-test\r\n" in s.request,
                      repr(s.request))

        chunked = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
                   b"a\r\n{\"Success\"\r\n14\r\n:true,\"GameID\":2791}\r\n0\r\n\r\n")
        s = Server(d, version="1.3", response=chunked)
        rc, body = get(exe, s.port, d)
        s.finish()
        check("chunked_body", rc > 0 and body == json_body, f"rc={rc} body={body!r}")

        s = Server(d, version="1.3", response=b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n" + json_body)
        rc, body = get(exe, s.port, d)
        s.finish()
        check("no_length_until_close", rc > 0 and body == json_body, f"rc={rc} body={body!r}")

        s = Server(d, version="1.3", response=http(b"x" * 3000))
        rc, _ = get(exe, s.port, d, max_=512)
        s.finish()
        check("oversize_refused", rc == -5, f"rc={rc}")

        s = Server(d, cert="other", version="1.3", response=http(json_body))
        rc, _ = get(exe, s.port, d)
        s.finish()
        check("wrong_host", rc == -4, f"rc={rc}")

        s = Server(d, version="1.3", response=http(json_body))
        rc, _ = get(exe, s.port, d, now=str(int(time.time()) + 400 * 86400))
        s.finish()
        check("expired", rc == -4, f"rc={rc}")

        s = Server(d, version="1.3", response=http(json_body))
        rc, _ = get(exe, s.port, d, anchors=("stranger.der",))
        s.finish()
        check("untrusted_root", rc == -4, f"rc={rc}")

        s = Server(d, version="1.3", response=http(json_body))
        rc, _ = get(exe, s.port, d, now="unset")
        time.sleep(0.3)
        accepts = s.accepts
        s.sock.close()
        check("clock_unset", rc == -2 and accepts == 0, f"rc={rc} accepts={accepts}")

        s = Server(d, tls=False)
        t0 = time.monotonic()
        rc, _ = get(exe, s.port, d, deadline=1000)
        elapsed = time.monotonic() - t0
        s.finish()
        check("stall_deadline", rc == -6 and elapsed < 2.5, f"rc={rc} elapsed={elapsed:.2f}")

        s = Server(d, version="1.3", response=b"HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\nConnection: close\r\n\r\nno")
        rc, _ = get(exe, s.port, d)
        s.finish()
        check("http_404", rc == -5, f"rc={rc}")

        roots = sorted((ROOT / "third_party/ca-roots").glob("*.der"))
        out = subprocess.run([str(exe), "anchors", *map(str, roots)], capture_output=True, text=True).stdout
        check("anchors_parse", len(roots) == 6 and "anchors bad=0" in out, out.strip())

        # ps2sdk's ps2time() (ee/rpc/cdvd/src/scmd.c) reads the RTC as JST: UTC = RTC - 9 h.
        out = subprocess.run([str(exe), "rtc", "2026", "10", "12", "9", "0", "0"], capture_output=True, text=True).stdout
        check("rtc_to_utc", out.strip() == "1791763200", out.strip())

        lines = []
        for _ in range(2):
            lines += subprocess.run([str(exe), "drbg"], capture_output=True, text=True).stdout.split()
        check("drbg_distinct", len(lines) == 4 and all(re.fullmatch(r"[0-9a-f]{64}", x) for x in lines)
              and len(set(lines)) == 4, repr(lines))

    if failures:
        print(f"{len(failures)} failure(s)")
        sys.exit(1)
    print("PASS: ratls host tests (15 checks)")


if __name__ == "__main__":
    main()
