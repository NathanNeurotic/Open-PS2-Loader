"""Exercise the actual card rasterizer/event handling without claiming GS timing."""
from pathlib import Path
import re, subprocess, tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'ee_core/src/ra_overlay.c').read_text()
source=re.sub(r'^#include.*\n','',source,flags=re.M)
for name in ('GIF_D2_CHCR','GIF_D2_MADR','GIF_D2_QWC','GIF_STAT'):
 source=re.sub(r'^#define '+name+r' .*$', 'static u32 '+name+';',source,flags=re.M)
prefix=r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define RETROACHIEVEMENTS 1
#define RA_EXPERIMENTAL_CARD_DMA 1
#include "include/ra_features.h"
#define UNCACHED_SEG(p) (p)
typedef uint64_t u64;
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
#include "modules/network/common/ra_snap.h"
static struct {int raClientMode;} g_ee_core_config;
static unsigned syncs, resets, pulses;
static void iSyncDCache(void *a,void*b) { assert(b>=a); syncs++; }
static void IGR_RequestReset(void) { resets++; }
static char pulse_buffer[128];
static void *RA_PulseEventBuffer(void) { return pulse_buffer; }
static void RA_PulseOnVblank(unsigned frame) { pulses++; }
"""
tests=r"""
struct ra_gs_source_regs GSMSourceGSRegs;
static unsigned char packet[30848+128] __attribute__((aligned(64)));
int main(void) {
 assert(sizeof(struct ra_event)==128);
 assert(RA_OverlayEventBuffer()==pulse_buffer);
 RA_OverlayOnVblank(1);assert(pulses==1);
 g_ee_core_config.raClientMode=1;
 struct ra_event *event=RA_OverlayEventBuffer();
 RA_OverlaySetPacketBuffer(packet+64);
 memset(packet,0xCD,sizeof(packet));
 GSMSourceGSRegs.pmode=1;
 GSMSourceGSRegs.dispfb1=(10ull<<9);
 GSMSourceGSRegs.display1=(639ull<<32)|(479ull<<44);
 event->magic=RA_EVENT_MAGIC;event->seq=1;event->commit=0;event->kind=RA_EVENT_MAKE_UNLOCK(25);event->arg=123;
 strcpy(event->title,"Test achievement");
 RA_OverlayOnVblank(2);assert(!ra_ovl_running);
 event->commit=1;GIF_D2_CHCR=0x100;RA_OverlayOnVblank(3);assert(ra_ovl_running && ra_build_row==0);
 GIF_D2_CHCR=0;
 for(unsigned f=4;f<13;f++) { RA_OverlayOnVblank(f);assert(!GIF_D2_QWC); }
 RA_OverlayOnVblank(13);assert(GIF_D2_QWC==1926 && ra_ovl_points==25 && !strcmp(ra_ovl_title,event->title));
 for(int i=0;i<64;i++) assert(packet[i]==0xCD);
 for(unsigned i=64+30816;i<sizeof(packet);i++) assert(packet[i]==0xCD);
 assert(syncs>=10);
 GIF_D2_CHCR=0;GSMSourceGSRegs.dispfb1=(10ull<<9)|(2ull<<15);
 for(unsigned f=14;f<24;f++) { GIF_D2_CHCR=0;RA_OverlayOnVblank(f); }
 assert(GIF_D2_QWC==966);
 RA_OverlayOnVblank(214);assert(!ra_ovl_running);
 event->seq=2;event->commit=2;event->kind=RA_EVENT_RESET;RA_OverlayOnVblank(215);assert(resets==1);
 RA_OverlayOnVblank(216);assert(resets==1);
 RA_OverlaySetPacketBuffer(NULL);assert(!draw_card());
 puts("PASS: card bounds, sliced rasterization, GIF busy guard, CT32/CT16 packet lengths, torn events, reset and Xerabora dispatch");
}
"""
fallback_tests=r"""
struct ra_gs_source_regs GSMSourceGSRegs;
int main(void) {
 g_ee_core_config.raClientMode=1;
 assert(RA_OverlayEventBuffer()==pulse_buffer);
 RA_OverlayOnVblank(1);
 assert(pulses==1 && GIF_D2_QWC==0);
 puts("PASS: Caduceus production fallback uses pulse without GIF DMA");
}
"""
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp)
 for name, headers, body in [
  ('experimental',prefix,tests),
  ('production',prefix.replace('#define RA_EXPERIMENTAL_CARD_DMA 1\n',''),fallback_tests),
 ]:
  (path/'test.c').write_text(headers+source+body)
  subprocess.run(['cc','-std=gnu99','-Wno-pointer-to-int-cast','-I',str(root),str(path/'test.c'),'-o',str(path/'test.exe')],check=True)
  subprocess.run([str(path/'test.exe')],check=True)
