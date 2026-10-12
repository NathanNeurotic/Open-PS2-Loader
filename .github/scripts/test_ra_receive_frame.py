"""Execute the actual raw SMAP receiver with truncated and complete notices."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'modules/network/raudp/raudp.c').read_text(encoding='utf-8')
start = source.index('static void ra_drain_rx(void)')
function = source[start:source.index('\n}', start) + 2]
program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef struct { u16 ctrl_stat, length, pointer; } smap_bd_t;
#define USE_SMAP_REGS
#define USE_SMAP_RX_BD
#define SMAP_BD_MAX_ENTRY 1
#define SMAP_BD_RX_EMPTY 0x8000
#define SMAP_BD_RX_ERROR 0x4000
#define SMAP_R_RXFIFO_FRAME_CNT 0
#define SMAP_R_RXFIFO_FRAME_DEC 1
#define SMAP_R_RXFIFO_RD_PTR 0
#define SMAP_R_RXFIFO_DATA 0
#define RA_SRC_PORT 18195
#define RA_HDR_LEN 42
#define RA_UDP_HLEN 8
static u8 regs8[2];
static u16 regs16[1];
#define SMAP_REG8(x) regs8[x]
#define SMAP_REG16(x) regs16[x]
static u8 incoming[256], ra_rxfrm[256];
static unsigned offset, calls;
static int ra_rx_bdi, received;
static smap_bd_t rx_bd[1];
static u32 read_word(void) {
    u32 word;
    memcpy(&word, incoming + offset, 4);
    offset += 4;
    /* Simulate no further frames after this one, while allowing its cleanup. */
    if (offset >= ((rx_bd[0].length + 3u) & ~3u)) regs8[0] = 0;
    return word;
}
#define SMAP_REG32(x) read_word()
static void ra_handle_pc(char *payload, int length) {
    assert(payload == (char *)ra_rxfrm + RA_HDR_LEN);
    assert(payload[length] == 0);
    calls++;
    received = length;
}
@FUNCTION@
static void frame(unsigned wire_length, unsigned payload_length, int expected) {
    memset(incoming, 0, sizeof(incoming));
    /* Stale prior bytes can contain a valid unlock beyond the new short frame. */
    memset(ra_rxfrm, 'X', sizeof(ra_rxfrm));
    memcpy(ra_rxfrm + RA_HDR_LEN, "RAU1 1234567890 25 Stale title", 28);
    incoming[12]=8; incoming[14]=0x45; incoming[23]=17;
    incoming[36]=RA_SRC_PORT >> 8; incoming[37]=RA_SRC_PORT & 255;
    incoming[38]=(payload_length+8) >> 8; incoming[39]=(payload_length+8) & 255;
    rx_bd[0]=(smap_bd_t){0, wire_length, 0};
    regs8[0]=1; offset=calls=0; ra_rx_bdi=0; received=-1;
    ra_drain_rx();
    assert(calls == (unsigned)expected);
    if (expected) assert(received == (int)payload_length);
    assert(rx_bd[0].ctrl_stat == SMAP_BD_RX_EMPTY);
    assert(ra_rx_bdi == 1);
}
int main(void) {
    frame(60, 30, 0);  /* declared UDP payload extends past received Ethernet frame */
    frame(73, 32, 0);  /* one byte short, including rounded FIFO reads */
    frame(74, 32, 1);  /* exactly complete payload */
    frame(80, 32, 1);  /* valid trailing Ethernet padding */
    frame(60, 0, 0);
    frame(256, 214, 0); /* no space for the parser's NUL terminator */
    frame(255, 213, 1);
    frame(60, 65527, 0);
    puts("PASS: raw RA notices reject truncated frames and stale tails; complete/padded frames pass");
}
'''.replace('@FUNCTION@', function)
with tempfile.TemporaryDirectory(prefix='ra-receive-') as work:
    path, exe = Path(work) / 'receive.c', Path(work) / 'receive'
    path.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
