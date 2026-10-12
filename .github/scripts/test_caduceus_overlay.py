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
static int race_mode;
static void mock_after_snapshot(struct ra_event *copy, volatile struct ra_event *live) {
 if (race_mode==1) { live->seq++; live->commit=live->seq; live->kind=RA_EVENT_RESET; }
 if (race_mode==2) copy->commit=0; /* DMA finished after a torn copy */
 race_mode=0;
}
"""
source=source.replace('struct ra_event notice = *e;',
 'struct ra_event notice = *e; mock_after_snapshot(&notice, (volatile struct ra_event *)e);')
tests=r"""
struct ra_gs_source_regs GSMSourceGSRegs;
static unsigned char packet[30848+128] __attribute__((aligned(64)));
int main(void) {
 assert(sizeof(struct ra_event)==128);
 assert(RA_OverlayEventBuffer()==pulse_buffer);
 RA_OverlayOnVblank(1);assert(pulses==1);
 g_ee_core_config.raClientMode=1;
 assert(RA_OverlayEventBuffer()==pulse_buffer); /* opt-out / no room */
 RA_OverlaySetPacketBuffer(packet+64);
 struct ra_event *event=RA_OverlayEventBuffer();
 assert(event!=(struct ra_event *)pulse_buffer);
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
 /* An empty FIFO is insufficient: refuse masked, paused, interrupted and
    reverse-direction transfers as well as queued/active paths. */
 GIF_D2_CHCR=0;
 const unsigned blocked_bits[]={0,1,3,5,6,7,8,9,10,11,12,24,25,26,27,28};
 for(unsigned b=0;b<sizeof(blocked_bits)/sizeof(blocked_bits[0]);b++) {
  GIF_STAT=1u<<blocked_bits[b];GIF_D2_QWC=0;
  assert(draw_card()==1 && GIF_D2_QWC==0 && GIF_D2_CHCR==0);
 }
 GIF_STAT=0;assert(draw_card()==1 && GIF_D2_QWC==1926 && GIF_D2_CHCR==0x101);
 GIF_D2_CHCR=0;GSMSourceGSRegs.dispfb1=(10ull<<9)|(2ull<<15);
 for(unsigned f=14;f<24;f++) { GIF_D2_CHCR=0;RA_OverlayOnVblank(f); }
 assert(GIF_D2_QWC==966);
 RA_OverlayOnVblank(214);assert(!ra_ovl_running);
 event->seq=2;event->commit=2;event->kind=RA_EVENT_RESET;RA_OverlayOnVblank(215);assert(resets==1);
 RA_OverlayOnVblank(216);assert(resets==1);
 event->seq=3;event->commit=3;event->kind=RA_EVENT_RESET;race_mode=1;
 RA_OverlayOnVblank(217);assert(resets==1 && ra_ovl_seen==2);
 RA_OverlayOnVblank(218);assert(resets==2 && ra_ovl_seen==4);
 event->seq=5;event->commit=5;race_mode=2;
 RA_OverlayOnVblank(219);assert(resets==2 && ra_ovl_seen==4);
 RA_OverlayOnVblank(220);assert(resets==3 && ra_ovl_seen==5);
 RA_OverlaySetPacketBuffer(NULL);assert(!draw_card());
 assert(RA_OverlayEventBuffer()==pulse_buffer);
 RA_OverlayOnVblank(221);assert(pulses==2);
 puts("PASS: card bounds, sliced rasterization, GIF state refusal, CT32/CT16 packet lengths, torn events, reset and Xerabora dispatch");
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
  ('opt_out',prefix,fallback_tests),
  ('compile_disabled',prefix.replace('#define RA_EXPERIMENTAL_CARD_DMA 1','#define RA_EXPERIMENTAL_CARD_DMA 0'),fallback_tests),
 ]:
  (path/'test.c').write_text(headers+source+body)
  subprocess.run(['cc','-std=gnu99','-Wno-pointer-to-int-cast','-I',str(root),str(path/'test.c'),'-o',str(path/'test.exe')],check=True)
  subprocess.run([str(path/'test.exe')],check=True)

# Exercise the production pulse itself, including unknown and uncommitted events.
pulse = (root / 'ee_core/src/ra_pulse.c').read_text()
pulse = re.sub(r'^#include .*$', '', pulse, flags=re.M)
pulse = pulse.replace('#define GS_PMODE (*(volatile u64 *)0x12000000)',
                      'static u64 GS_PMODE;')
pulse_prefix = r"""
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#define RETROACHIEVEMENTS 1
typedef uint64_t u64;
#include "modules/network/common/ra_snap.h"
#define UNCACHED_SEG(p) (p)
#define BGCOLND(c) ((void)(c))
static int resets;
static void IGR_RequestReset(void) { resets++; }
static int race_mode;
static void mock_after_snapshot(struct ra_event *copy, volatile struct ra_event *live) {
 if (race_mode==1) { live->seq++; live->commit=live->seq; live->kind=RA_EVENT_RESET; }
 if (race_mode==2) copy->commit=0;
 race_mode=0;
}
"""
pulse=pulse.replace('struct ra_event notice = *e;',
 'struct ra_event notice = *e; mock_after_snapshot(&notice, (volatile struct ra_event *)e);')
pulse_tests = r"""
int main(void) {
 struct ra_event *e=RA_PulseEventBuffer();
 e->magic=RA_EVENT_MAGIC; e->seq=1; e->commit=1; e->kind=0xFE;
 RA_PulseOnVblank(1); assert(!ra_ovl_running);
 e->seq=2; e->kind=RA_EVENT_MAKE_UNLOCK(25);
 RA_PulseOnVblank(2); assert(!ra_ovl_running);
 e->commit=2; RA_PulseOnVblank(3); assert(ra_ovl_running && ra_ovl_start==3);
 e->seq=3; e->commit=3; e->kind=0xFE;
 RA_PulseOnVblank(4); assert(ra_ovl_running && ra_ovl_start==3);
 e->seq=4; e->commit=4; e->kind=RA_EVENT_MAKE_UNLOCK(50);
 RA_PulseOnVblank(5); assert(ra_ovl_start==5);
 RA_PulseOnVblank(65); assert(!ra_ovl_running);
 e->seq=5; e->commit=5; e->kind=RA_EVENT_RESET;
 RA_PulseOnVblank(66); RA_PulseOnVblank(67); assert(resets==1 && !ra_ovl_running);
 e->seq=6; e->commit=6; e->kind=RA_EVENT_MAKE_UNLOCK(10); race_mode=1;
 RA_PulseOnVblank(68); assert(resets==1 && !ra_ovl_running && ra_ovl_seen==5);
 RA_PulseOnVblank(69); assert(resets==2 && ra_ovl_seen==7);
 e->seq=8; e->commit=8; race_mode=2;
 RA_PulseOnVblank(70); assert(resets==2 && ra_ovl_seen==7);
 RA_PulseOnVblank(71); assert(resets==3 && ra_ovl_seen==8);
 puts("PASS: production pulse ignores unknown/torn events, restarts unlocks and preserves reset");
}
"""
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp)
 (path/'pulse.c').write_text(pulse_prefix+pulse+pulse_tests)
 subprocess.run(['cc','-std=gnu99','-I',str(root),str(path/'pulse.c'),'-o',str(path/'pulse.exe')],check=True)
 subprocess.run([str(path/'pulse.exe')],check=True)
