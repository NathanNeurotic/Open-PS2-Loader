"""Replay real Neutrino C send/receive/IST against real Python UDPFS worker.
Only the IOP kernel, FIFO and wire are stubbed. No PS2/game execution claim.
"""

import argparse
import collections
import ctypes as ct
import importlib.util
import json
import queue
import re
import struct
import subprocess
import sys
import threading
import types
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--official-source", type=Path, required=True)
parser.add_argument("--fixed-source", type=Path, required=True)
parser.add_argument("--stable-source", type=Path)
parser.add_argument("--server-source", type=Path, required=True)
parser.add_argument("--server-before", default="c04106c")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
OUT = args.output.resolve()
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(args.server_source.resolve() / "udpfs_server"))
import udpfs_server as srv

ADDR = ("192.168.0.245", 62966)


def function(src, name):
    match = re.search(
        r"^(?:static )?(?:unsigned int|int|void) " + re.escape(name) + r"\(",
        src,
        re.MULTILINE,
    )
    assert match, name
    start = src.index("{", match.start())
    depth = 1
    end = start + 1
    while depth:
        depth += (src[end] == "{") - (src[end] == "}")
        end += 1
    return src[match.start() : end]


PRE = r"""
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#define M_DEBUG(...) ((void)0)
#define M_PRINTF(...) ((void)0)
#define WEF_OR 1
#define WEF_CLEAR 2
#define IP_ADDR(a,b,c,d) 0
#define ntohs(x) (x)
typedef struct { int unused; } udp_socket_t;
typedef struct {uint8_t a[14];} eth_header_t;
typedef struct {uint8_t a[12]; struct {uint8_t addr[4];} addr_src; uint8_t b[4];} ip_header_t;
typedef struct {uint16_t port_src; uint8_t a[6];} udp_header_t;
typedef struct {int unused;} udp_packet_t;
typedef int iop_sys_clock_t;
static uint32_t bits;
static uint8_t fifo[2048];
static void (*wire_send)(const void*,int);
static void (*wire_wait)(int);
static int SetEventFlag(int f,uint32_t b){bits|=b; return 0;}
#define iSetEventFlag SetEventFlag
static int ClearEventFlag(int f,uint32_t mask){bits&=mask;return 0;}
static int WaitEventFlag(int f,uint32_t mask,int mode,uint32_t*out){
 if(!(bits&mask)) wire_wait(mask);
 *out=bits&mask;
 if(!*out){fprintf(stderr,"empty event wait\n"); return -1;}
 if(mode&WEF_CLEAR) bits&=~mask;
 return 0;
}
static void USec2SysClock(uint32_t us,iop_sys_clock_t*c){*c=us;}
static int SetAlarm(iop_sys_clock_t*c,unsigned int(*cb)(void*),void*a){return 0;}
static int CancelAlarm(unsigned int(*cb)(void*),void*a){return 0;}
static void smap_fifo_read(int offset,void*target,int size){memcpy(target,fifo+offset,size);}
static int udp_packet_send(udp_socket_t*s,udp_packet_t*p,int size){wire_send((uint8_t*)p+42,size);return 0;}
static int udp_packet_send_ll(udp_socket_t*s,udp_packet_t*p,int hsize,const void*data,int size){
 uint8_t packet[2048];memcpy(packet,(uint8_t*)p+42,hsize);memcpy(packet+hsize,data,size);
 wire_send(packet,hsize+size);return 0;
}
"""
POST = r"""
static struct udprdma_socket test_socket;
void replay_init(void(*send)(const void*,int),void(*wait)(int),int tx,int rx){
 memset(&test_socket,0,sizeof(test_socket));bits=0;
 test_socket.state=STATE_CONNECTED;test_socket.tx_seq_nr=tx;
 test_socket.tx_seq_nr_acked=(tx-1)&4095;test_socket.rx_seq_nr_expected=rx;
 wire_send=send;wire_wait=wait;
}
void replay_deliver(const void*packet,int len){memset(fifo,0,sizeof(fifo));memcpy(fifo+42,packet,len);_ist(NULL,&test_socket,fifo,44);}
void replay_timeout(void){bits|=EF_TIMEOUT;}
int replay_read(void*buffer,int size,void*result,int scatter){
 uint8_t req[16]={0x20};
 udprdma_set_rx_app_header(&test_socket,result,8);
 udprdma_set_rx_buffer(&test_socket,buffer,size);
 int r=scatter?udprdma_send_ll(&test_socket,req,8,req+8,8):udprdma_send(&test_socket,req,16);
 if(r)return r;
 return udprdma_recv(&test_socket,buffer,size,30000);
}
int replay_connected(void){return test_socket.state==STATE_CONNECTED;}
"""


def build(name, source):
    src = (source / "udprdma.c").read_text(encoding="utf-8")
    packet = (
        (source / "udprdma_packet.h")
        .read_text(encoding="utf-8")
        .replace('#include "ministack_udp.h"', "")
    )
    public = (
        (source / "udprdma.h")
        .read_text(encoding="utf-8")
        .replace('#include "udprdma_packet.h"', "")
    )
    definitions = src[
        src.index("/* Event flag bits */") : src.index(
            "/* Maximum number of sockets */"
        )
    ]
    funcs = [
        "_timeout_cb",
        "_ist",
        "_send_ack",
        "_send_data",
        "_send_data_ll",
        "udprdma_send",
        "udprdma_send_ll",
        "udprdma_recv",
        "udprdma_set_rx_buffer",
        "udprdma_set_rx_app_header",
    ]
    header = ""
    if '#include "udprdma_seq.h"' in src:
        header = (source / "udprdma_seq.h").read_text(encoding="utf-8")
    c = OUT / (name + ".c")
    dll = OUT / (name + ".dll")
    c.write_text(
        PRE
        + packet
        + public
        + header
        + definitions
        + "\n".join(function(src, f) for f in funcs)
        + POST,
        encoding="utf-8",
    )
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O0", "-g", "-o", str(dll), str(c)],
        check=True,
        timeout=60,
    )
    lib = ct.CDLL(str(dll))
    lib.replay_read.argtypes = [ct.c_void_p, ct.c_int, ct.c_void_p, ct.c_int]
    lib.replay_deliver.argtypes = [ct.c_void_p, ct.c_int]
    return lib


def run(lib, drop=False, stale=False, scatter=False, tx=57, rx=653):
    server = object.__new__(srv.UdpfsServer)
    server._local = threading.local()
    server.verbose = True
    sess = types.SimpleNamespace(
        queue=queue.Queue(),
        pushback=collections.deque(),
        tx_seq_nr=rx,
        tx_seq_nr_acked=(rx - 1) & 4095,
        rx_seq_nr_expected=tx,
        tx_buffer=[],
        tx_start_seq=0,
    )
    server._local.session = sess
    responses = queue.Queue()
    events = []
    attempts = []
    accepted = []
    controls = []
    errors = []
    server._sendto = lambda packet, addr: responses.put(packet)
    server._print_event = events.append
    expected = bytes(i % 251 for i in range(16384))

    def bread(addr, payload):
        accepted.append(srv.Header.unpack(current[0]).seq_nr)
        server._send_raw_data_with_header(
            addr, struct.pack("<BBBBi", 0x11, 0, 0, 0, len(expected)), expected
        )

    # Only file I/O is replaced by deterministic bytes; wire sender and waits are production.
    server._handle_bread = bread
    # Route any request type to BREAD fixture without changing transport handling.
    original = server._handle_data
    current = [None]

    def worker():
        server._local.session = sess
        try:
            while True:
                item = server._queue_get(sess, timeout=3)
                if item is None:
                    break
                current[0] = item[0]
                original(item[0], ADDR)
        except queue.Empty:
            pass
        except Exception as e:  # noqa: BLE001 - surface worker failures in the main test
            errors.append(repr(e))

    def send(ptr, size):
        packet = ct.string_at(ptr, size)
        h = srv.Header.unpack(packet)
        d = srv.DataHeader.unpack(packet[2:6])
        if d.data_byte_count or d.hdr_word_count:
            attempts.append(h.seq_nr)
            # req fixture uses actual enum value; preserve all transport bits/lengths.
            packet = packet[:6] + bytes([srv.MsgType.BREAD_REQ]) + packet[7:]
            if len(attempts) == 1:
                if stale:
                    old = (
                        srv.Header(
                            packet_type=srv.PacketType.DATA, seq_nr=(rx - 1) & 4095
                        ).pack()
                        + srv.DataHeader(
                            seq_nr_ack=(tx - 1) & 4095,
                            flags=srv.DataFlags.ACK | srv.DataFlags.FIN,
                            hdr_word_count=0,
                            data_byte_count=4,
                        ).pack()
                        + b"OLD!"
                    )
                    for _ in range(6):
                        responses.put(old)
                if drop:
                    return
        else:
            controls.append({"ack": d.seq_nr_ack, "flags": int(d.flags)})
        sess.queue.put((packet, ADDR, "data"))

    def wait(mask):
        while True:
            try:
                packet = responses.get(timeout=0.3)
            except queue.Empty:
                lib.replay_timeout()
                return
            lib.replay_deliver(packet, len(packet))
            # C WaitEventFlag rechecks matching bits; returning after an ACK-only packet
            # during recv is incorrect, so drain until the production IST signals mask.
            if lib.replay_bits() & mask:
                return

    SEND = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_int)
    WAIT = ct.CFUNCTYPE(None, ct.c_int)
    scb = SEND(send)
    wcb = WAIT(wait)
    lib.replay_init(scb, wcb, tx, rx)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    buffer = ct.create_string_buffer(16384)
    result = ct.create_string_buffer(8)
    ret = lib.replay_read(buffer, 16384, result, int(scatter))
    stop = srv.Header(packet_type=srv.PacketType.DISCOVERY, seq_nr=0).pack() + bytes(4)
    sess.queue.put((stop, ADDR, "data"))
    sess.queue.put(None)
    thread.join(3)
    assert not thread.is_alive(), "server worker failed to terminate"
    assert not errors, errors
    return {
        "returned": ret,
        "bytes_match": buffer.raw[:16384] == expected,
        "connected": bool(lib.replay_connected()),
        "request_attempts": attempts,
        "requests_accepted": accepted,
        "controls": controls,
        "events": events,
    }


if __name__ == "__main__":
    # Getter is harness-only; production bodies above remain unchanged.
    POST += "\nuint32_t replay_bits(void){return bits;}\n"
    results = {}
    current_server = srv
    old = OUT / "server-before-236.py"
    old.write_bytes(
        subprocess.check_output(
            [
                "git",
                "-C",
                str(args.server_source.resolve()),
                "show",
                args.server_before + ":udpfs_server/udpfs_server.py",
            ]
        )
    )
    spec = importlib.util.spec_from_file_location("server_before_236", old)
    previous_server = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = previous_server
    spec.loader.exec_module(previous_server)
    clients = [
        ("official", args.official_source),
        ("fixed", args.fixed_source),
    ]
    if args.stable_source:
        clients.append(("stable", args.stable_source))
    for name, folder in clients:
        lib = build(name, folder.resolve() / "iop/udpfs/src")
        for server_name, server_module in [
            ("before236", previous_server),
            ("after236", current_server),
        ]:
            srv = server_module
            for scatter in [False, True]:
                for tx, rx in [(57, 653), (0, 0), (4095, 4091)]:
                    for scenario, drop, stale in [
                        ("clean", False, False),
                        ("lost_request", True, False),
                        ("late_previous_fin", False, True),
                        ("lost_request_late_previous_fin", True, True),
                    ]:
                        key = f"{name}/{server_name}/{'send_ll' if scatter else 'send'}/{tx}-{rx}/{scenario}"
                        result = run(lib, drop, stale, scatter, tx, rx)
                        results[key] = result
                        should_fail = name in ("official", "stable") and drop and stale
                        if should_fail:
                            assert (
                                result["returned"] == -1
                                and not result["connected"]
                                and result["request_attempts"] == [tx]
                                and not result["requests_accepted"]
                            ), (key, result)
                        else:
                            assert (
                                result["returned"] == 16384
                                and result["bytes_match"]
                                and result["connected"]
                            ), (key, result)
                            assert len(result["requests_accepted"]) == 1, (key, result)
                        print(
                            key,
                            "EXPECTED FAILURE REPRODUCED" if should_fail else "PASS",
                            flush=True,
                        )
    (OUT / "transport-replay-results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(f"{len(results)} replay expectations passed")
