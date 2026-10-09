"""Production PS1 hashing, module ownership and IOP snapshots against host fixtures."""
from pathlib import Path
import hashlib
import re
import struct
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='ra-ps1-') as directory:
    tmp = Path(directory)

    def run(name, source, extra=()):
        path = tmp / (name + '.c')
        exe = tmp / (name + '.exe')
        path.write_text(source, encoding='utf-8')
        subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror',
                        '-Wno-pointer-to-int-cast', '-Wno-int-to-pointer-cast',
                        '-I', str(root), str(path), *map(str, extra), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], cwd=tmp, check=True)

    payload = bytearray((i % 251 for i in range(2048 * 3 + 17)))
    payload[:8] = b'PS-X EXE'
    struct.pack_into('<I', payload, 28, len(payload) - 2048)

    def record(name, lba, size):
        result = bytearray(34 + len(name))
        result[0] = len(result)
        struct.pack_into('<I', result, 2, lba)
        struct.pack_into('<I', result, 10, size)
        result[32] = len(name)
        result[33:33 + len(name)] = name.encode()
        return result

    def fixture(name, boot='SLUS_012.15', cnf=True, fallback=False, overflow=False):
        iso = bytearray(40 * 2048)
        iso[16*2048+1:16*2048+6] = b'CD001'
        struct.pack_into('<II', iso, 16*2048+158, 20, 0)
        struct.pack_into('<I', iso, 16*2048+166, 2048)
        entries = b''
        if cnf:
            text = ('BOOT = cdrom:\\' + boot + ';1\r\n').encode()
            iso[22*2048:22*2048+len(text)] = text
            entries += record('SYSTEM.CNF;1', 22, len(text))
        if '\\' in boot:
            entries += record('D;1', 21, 2048)
            nested = record('G.EXE;1', 24, len(payload))
            iso[21*2048:21*2048+len(nested)] = nested
        else:
            entries += record(('PSX.EXE' if fallback else boot) + ';1', 24, len(payload))
        iso[20*2048:20*2048+len(entries)] = entries
        data = bytearray(payload)
        if overflow:
            struct.pack_into('<I', data, 28, 0xfffff800)
        iso[24*2048:24*2048+len(data)] = data
        raw = bytearray(0x100000 + 40 * 2352)
        for lba in range(40):
            at = 0x100000 + lba * 2352 + 24
            raw[at:at+2048] = iso[lba*2048:(lba+1)*2048]
        (tmp / name).write_bytes(raw)

    fixture('retail.vcd')
    fixture('nested.vcd', 'D\\G.EXE')
    fixture('fallback.vcd', cnf=False, fallback=True)
    fixture('overflow.vcd', overflow=True)
    (tmp / 'truncated.vcd').write_bytes((tmp / 'retail.vcd').read_bytes()[:0x100000+26*2352])
    source = re.sub(r'^#include.*$', '', (root/'src/rahash.c').read_text(), flags=re.M)
    prefix = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <stdlib.h>
#endif
#include "include/md5.h"
typedef void (*ra_step_fn)(const char *);
typedef struct { unsigned char trycount, spindlctrl, datapattern, pad; } sceCdRMode;
enum { SCECdErNO=0, SCECdSecS2048=0, SCECdSpinNom=1, SCECdSpinStm=2 };
#define LOG(...) ((void)0)
#define lseek64 lseek
static int sceCdDiskReady(int m) {(void)m;return 0;}
static int sceCdRead(unsigned a,unsigned b,void *c,sceCdRMode *d) {(void)a;(void)b;(void)c;(void)d;return 0;}
static int sceCdSync(int m) {(void)m;return 0;}
static int sceCdGetError(void) {return 0;}
'''
    checks = '''
int main(void) {
#ifdef _WIN32
    _set_fmode(_O_BINARY);
#endif
    char boot[16], hash[33], key[16], key2[16];
'''
    for file, boot in [('retail.vcd', 'SLUS_012.15'), ('nested.vcd', 'D\\G.EXE'), ('fallback.vcd', 'PSX.EXE')]:
        expected = hashlib.md5(boot.encode() + payload).hexdigest()
        escaped = boot.replace('\\', '\\\\')
        checks += f'assert(raHashVcd("{file}",boot,sizeof(boot),hash)==0);\n'
        checks += f'assert(!strcmp(boot,"{escaped}") && !strcmp(hash,"{expected}"));\n'
        checks += f'assert(raVcdBootName("{file}",boot,sizeof(boot))==0 && !strcmp(boot,"{escaped}"));\n'
    checks += r'''
    assert(raHashVcd("truncated.vcd",boot,sizeof(boot),hash)<0 && hash[0]==0);
    assert(raHashVcd("overflow.vcd",boot,sizeof(boot),hash)<0 && hash[0]==0);
    assert(raHashVcd("missing.vcd",boot,sizeof(boot),hash)<0 && hash[0]==0);
    assert(raVcdWatchKey("mass0:/POPS/First.VCD",key,sizeof(key))==0);
    assert(strlen(key)==15 && key[0]=='P');
    assert(raVcdWatchKey("mass0:/POPS/Second.VCD",key2,sizeof(key2))==0);
    assert(strcmp(key,key2)!=0); /* Both images can contain the same BOOT. */
    assert(raVcdWatchKey("MASS0:\\POPS\\FIRST.vcd",key2,sizeof(key2))==0);
    assert(!strcmp(key,key2)); /* Case and separator folding for FAT roots. */
    assert(raVcdWatchKey("mass1:/POPS/First.VCD",key2,sizeof(key2))==0);
    assert(strcmp(key,key2)!=0); /* A second simultaneously mounted USB. */
    assert(raVcdWatchKey("mass0:/POPS/First.VCD",key2,15)<0);
    assert(raVcdWatchKey("",key2,sizeof(key2))<0);
    /* A watch list's path key is not proof that its contents are unchanged. */
    assert(raVcdWatchGuardMatches("",key,hash)==0); /* Old pre-guard list. */
    assert(raVcdWatchGuardStore("",key,"bad")<0);
    assert(raHashVcd("retail.vcd",boot,sizeof(boot),hash)==0);
    assert(raVcdWatchGuardStore("",key,hash)<0); /* RA directory absent. */
    assert(mkdir("RA",0777)==0);
    assert(raVcdWatchGuardStore("",key,hash)==0);
    assert(raVcdWatchGuardMatches("",key,hash)==1);
    hash[0] = hash[0]=='a' ? 'b':'a';
    assert(raVcdWatchGuardMatches("",key,hash)==0); /* Different content. */
    assert(raHashVcd("retail.vcd",boot,sizeof(boot),hash)==0);
    FILE *guard=fopen("RA/P", "rb");
    assert(!guard); /* Only keyed sidecar is created. */
    assert(raVcdWatchGuardMatches("",key,hash)==1);
    assert(raVcdWatchGuardStore("",key2,hash)<0); /* bad key input */
    puts("PASS: PS1 hashes and stale-VCD guard, missing, mismatched and malformed sidecars");
}
'''
    run('hash_ps1', prefix + source + checks, [root/'src/md5.c'])

    (tmp/'POPS').mkdir()
    source = (root/'src/vcdsupport.c').read_text()
    source = source[source.index('static int vcdRaModuleStatus('):]
    run('ownership', '''
#include <assert.h>
#include <stdio.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
static char vcdSep(const char *p) {(void)p;return '/';}
static int replies[3], replypos, fail_remove;
static int module_unlink(const char *p) {if(fail_remove) {errno=EACCES;return -1;}return unlink(p);}
#define unlink module_unlink
static int guiMsgBox(const char *s,int confirm,void *unused) {(void)s;(void)unused;return confirm?replies[replypos++]:0;}
''' + source + '''
int main(void) {
    assert(vcdRemoveRaModule("")==0);
    FILE *f=fopen("POPS/MODULE_9.IRX","wb");fputs("user module",f);fclose(f);
    assert(vcdRemoveRaModule("")==-1);
    assert(access("POPS/MODULE_9.IRX",0)==0);
    f=fopen("POPS/MODULE_9.IRX","wb");
    for(int i=0;i<4093;i++) fputc(0,f);
    fputs("RIPTRA01",f);fclose(f);
    replies[0]=0;replies[1]=0;replypos=0;
    assert(vcdConfirmCleanLaunch("")==0 && access("POPS/MODULE_9.IRX",0)==0);
    replies[0]=0;replies[1]=1;replypos=0;
    assert(vcdConfirmCleanLaunch("")==1 && access("POPS/MODULE_9.IRX",0)==0);
    replies[0]=1;replypos=0;
    assert(vcdConfirmCleanLaunch("")==1);
    assert(access("POPS/MODULE_9.IRX",0)<0);
    f=fopen("POPS/MODULE_9.IRX","wb");fputs("RIPTRA01",f);fclose(f);
    fail_remove=1;replies[0]=1;replies[1]=0;replypos=0;
    assert(vcdConfirmCleanLaunch("")==0 && access("POPS/MODULE_9.IRX",0)==0);
    replies[0]=1;replies[1]=1;replypos=0;
    assert(vcdConfirmCleanLaunch("")==1 && access("POPS/MODULE_9.IRX",0)==0);
    fail_remove=0;assert(vcdRemoveRaModule("")==0);
    puts("PASS: user module preserved; owned module across read boundary; delete, continue anyway and cancel choices");
}
''')

    source = re.sub(r'^#include.*$', '', (root/'src/rapopslaunch.c').read_text(), flags=re.M)
    run('prepare', r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include "modules/network/common/rapops_cfg.h"
#define RETROACHIEVEMENTS
#define RA_MODE_CADUCEUS 1
static int gRATelemetry=1, gRAMode=1, count=1, network=1;
static unsigned char rapops_irx[sizeof(struct rapops_cfg)];
static unsigned int size_rapops_irx=sizeof(rapops_irx);
static int raVcdBootName(const char *p,char *s,int n) {(void)p;snprintf(s,n,"SLUS_012.15");return 0;}
static int raVcdWatchKey(const char *p,char *s,int n) {(void)p;snprintf(s,n,"P123456789abcde");return 0;}
static int good_guard=1;
static int raHashVcd(const char *p,char *boot,int n,char *hash)
    {(void)p;snprintf(boot,n,"SLUS_012.15");snprintf(hash,33,"123456789abcdef0123456789abcdef0");return 0;}
static int raVcdWatchGuardMatches(const char *r,const char *k,const char *h)
    {(void)r;(void)k;(void)h;return good_guard;}
static char loaded_key[16];
static int sbLoadWatchList(const char *p,const char *s) {(void)p;snprintf(loaded_key,sizeof(loaded_key),"%s",s);return count;}
static int GetWatchCount(void) {return count;}
static int GetWatchBytes(void) {return 4;}
static int GetNodeCount(void) {return 0;}
static unsigned int *GetWatchList(void) {static unsigned int w=RA_WATCH_PACK(15,4);return &w;}
static struct ra_node *GetNodeList(void) {return NULL;}
static unsigned int raNetPeerIP(void) {return 0;}
static int ethGetNetConfig(unsigned char *ip,unsigned char *m,unsigned char *g) {
    ip[0]=192;ip[1]=168;ip[2]=1;ip[3]=2;memset(m,255,4);memset(g,0,4);return network ? 0 : -1;
}
/* Match PS2 FAT's actual behavior: exclusive creation is ignored. */
static int fail_create, fail_write;
static int fat_open(const char *p,int flags,int mode) {
    if (fail_create) { errno=EACCES; return -1; }
    return open(p,flags & ~O_EXCL,mode);
}
static ssize_t fat_write(int fd,const void *data,size_t count) {
    if (fail_write) { errno=ENOSPC; return -1; }
    return write(fd,data,count);
}
#define open fat_open
#define write fat_write
''' + source + r'''
int main(void) {
    memcpy(rapops_irx,RAPOPS_MAGIC,8);
    FILE *f=fopen("POPS/MODULE_9.IRX","wb");fputs("user module",f);fclose(f);
    assert(raPopsPrepare("","","game.vcd",0)<0);
    char buf[32]={0};f=fopen("POPS/MODULE_9.IRX","rb");fread(buf,1,sizeof(buf),f);fclose(f);
    assert(!strcmp(buf,"user module"));
    count=0;assert(raPopsPrepare("","","game.vcd",0)==0);
    count=1;gRATelemetry=0;assert(raPopsPrepare("","","game.vcd",0)==0);
    gRATelemetry=1;good_guard=0;
    assert(raPopsPrepare("","","game.vcd",0)==0); /* Stale list never blocks normal launch. */
    good_guard=1;
    gRATelemetry=1;unlink("POPS/MODULE_9.IRX");
    network=0;assert(raPopsPrepare("","","game.vcd",1)==0);
    assert(access("POPS/MODULE_9.IRX",0)!=0); /* Offline plays without tracking. */
    network=1;
    assert(raPopsPrepare("","","game.vcd",1)==0);
    struct rapops_cfg cfg;f=fopen("POPS/MODULE_9.IRX","rb");
    assert(fread(&cfg,1,sizeof(cfg),f)==sizeof(cfg));fclose(f);
    assert(cfg.client_mode==1 && cfg.count==1 && cfg.bytes==4 && !strcmp(cfg.game_id,"P123456789abcde"));
    assert(!strcmp(loaded_key,cfg.game_id));
    unlink("POPS/MODULE_9.IRX");
    fail_create=1;
    assert(raPopsPrepare("","","game.vcd",1)==0);
    assert(access("POPS/MODULE_9.IRX",0)<0);
    fail_create=0;
    fail_write=1;
    assert(raPopsPrepare("","","game.vcd",1)==0);
    assert(access("POPS/MODULE_9.IRX",0)<0); /* Partial module removed. */
    fail_write=0;
    memset(rapops_irx,0,sizeof(rapops_irx));
    assert(raPopsPrepare("","","game.vcd",1)==0); /* Absent embedded magic. */
    assert(access("POPS/MODULE_9.IRX",0)<0);
    puts("PASS: occupied user slot preserved even when O_EXCL ignored; optional create/write/embedded-config errors fail open");
}
''')

    source = re.sub(r'^#include.*$', '', (root/'modules/network/rapull/rapull.c').read_text(), flags=re.M)
    source = source[:source.index('static void rp_thread(')]
    run('snapshot', r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include "modules/network/common/ra_snap.h"
typedef uint32_t u32;
typedef uint8_t u8;
typedef int SifRpcReceiveData_t;
#define IRX_ID(a,b,c)
#define ALLOC_FIRST 0
static unsigned char ram[0x200000];
static int fail;
static void *AllocSysMemory(int a,int b,void *c) {(void)a;(void)c;return calloc(1,b);}
static void FreeSysMemory(void *p) {free(p);}
static int sceSifGetOtherData(void *a,void *b,void *c,int d,int e) {
    (void)a;(void)e;
    if(fail)return -1;
    memcpy(c,ram+((uintptr_t)b-0x1000000),d);return 0;
}
''' + source + r'''
int main(void) {
    u32 entries[]={RA_WATCH_PACK(15,4), RA_WATCH_PACK(0x1fffff,1)};
    unsigned char snap[RA_SNAP_TOTAL]={0};
    rp_snap=(void *)snap;rp_list=entries;rp_count=2;rp_bytes=5;
    assert(rp_hex_at("0000000f",0,8)==15);
    assert(rp_setup());
    ram[15]=1;ram[16]=2;ram[17]=3;ram[18]=4;ram[0x1fffff]=7;
    rp_frames=1;rp_frame_values(1);
    assert(rp_snap->magic==RA_SNAP_MAGIC && rp_snap->bytes==5);
    assert(!memcmp(snap+RA_SNAP_HDR,"\1\2\3\4\7",5));
    u32 seq=rp_snap->seq;
    fail=1;rp_frame_values(1);
    assert(rp_snap->seq==seq && rp_fail==1);
    fail=0;ram[15]=8;rp_frame_values(1);
    assert(rp_snap->seq==seq+1 && snap[RA_SNAP_HDR]==8);
    assert(*(u32 *)(snap+RA_SNAP_TRAILER_OFF(5))==rp_snap->seq);
    puts("PASS: PS1 read windows, unaligned and last-byte reads, failed read suppresses frame, recovery and trailer");
}
''')

    # Exercise the actual console header builder with the unmodified upstream parser.
    fixture = root/'.github/scripts/fixtures/xerabora-alpha16'
    sender = (root/'modules/network/raudp/raudp.c').read_text()
    sender = sender[sender.index('struct ra_field\n'):sender.index('/* ---- Formatting helpers')]
    parser = re.sub(r'^#include.*$', '', (fixture/'snapshot.c').read_text(), flags=re.M)
    run('upstream_client', r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include ".github/scripts/fixtures/xerabora-alpha16/ra_snap.h"
#include ".github/scripts/fixtures/xerabora-alpha16/snapshot.h"
typedef unsigned char u8;
typedef unsigned int u32;
#define RA_PAYLOAD 1472
static u8 ra_payload[RA_PAYLOAD];
static char ra_game_id[16]="P123456789abcde";
static unsigned char values[RA_SNAP_MAX_BYTES];
static int have, nodes;
static unsigned char *watchlist_values(void) {return values;}
static int watchlist_count(void) {return 1;}
static int watchlist_bytes(void) {return 4;}
static int watchlist_snapshot_bytes(void) {return 12;}
static void watchlist_set_have_nodes(int v) {nodes=v;}
static void watchlist_set_have_values(int v) {have=v;}
''' + sender + parser + r'''
static void field(int id,unsigned int value) {
    for(int i=ra_fields[id].width-1;i>=0;i--) {
        ra_payload[RA_OFF(id)+i]='0'+value%10;value/=10;
    }
}
int main(void) {
    char serial[16];
    ra_head_build();
    assert(ra_chunk==RA_SNAP_CHUNK_BYTES);
    assert(snapshot_serial((char*)ra_payload,serial,sizeof(serial)));
    assert(!strcmp(serial,ra_game_id));
    field(RA_F_N,1);field(RA_F_VB,4);field(RA_F_NP,1);field(RA_F_SQ,1);
    memcpy(ra_payload+ra_head_len,"\x11\x22\x33\x44",4);
    snapshot_reset();
    assert(snapshot_feed((char*)ra_payload,ra_head_len+4)==1);
    assert(have && !nodes && !memcmp(values,"\x11\x22\x33\x44",4));
    assert(snapshot_feed((char*)ra_payload,ra_head_len+4)==0);
    field(RA_F_SQ,2);field(RA_F_VB,12);
    memset(ra_payload+ra_head_len,0x55,12);
    assert(snapshot_feed((char*)ra_payload,ra_head_len+12)==1 && nodes);
    field(RA_F_SQ,3);field(RA_F_N,2);
    assert(snapshot_feed((char*)ra_payload,ra_head_len+12)==0 && snapshot_stale());
    puts("PASS: production sender accepted by upstream alpha.16 parser; serial, direct values, pointer nodes, duplicates and stale lists");
}
''')

    # Compile the production RA badge cache against real directories. PS1
    # metadata still uses the VCD filename; only RA watch files use the P key.
    badge_source = re.sub(r'^#include.*$', '', (root/'src/rabadge.c').read_text(), flags=re.M)
    run('badge_ps1', r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>
#define RETROACHIEVEMENTS 1
#define MODE_COUNT 105
#define FAV_MODE 99
#define LIB_VIEW_PS1 1
#define ISO_GAME_NAME_MAX 160
#define FAV_KIND_VCD 1
typedef struct item_list item_list_t;
typedef struct { char extension[8]; } base_game_info_t;
struct item_list {
    int mode;
    char *(*itemGetName)(item_list_t *, int);
    char *(*itemGetStartup)(item_list_t *, int);
    char *(*itemGetPrefix)(item_list_t *);
    void *(*itemGet)(item_list_t *, int);
};
static int gRATelemetry=1, gRABadges=1, view=1, favkind=1, favmode=0;
static char name[32]="First", startup[32]="First", full[256];
static base_game_info_t game={".VCD"};
static char *getname(item_list_t *x,int i){(void)x;(void)i;return name;}
static char *getstartup(item_list_t *x,int i){(void)x;(void)i;return startup;}
static char *getprefix(item_list_t *x){(void)x;return "mass0:/games/";}
static void *getgame(item_list_t *x,int i){(void)x;(void)i;return &game;}
static int libListRowView(item_list_t *x,int i){(void)x;(void)i;return view;}
static int favGetItemKind(int i){(void)i;return favkind;}
static int favGetItemSourceMode(int i){(void)i;return favmode;}
static char *favGetItemPrefix(int i){(void)i;return "mass0:/games/";}
static int bdmModeIsUSB(int m){return m==0;}
static int raVcdWatchKey(const char *p,char *out,int sz) {
    snprintf(full,sizeof(full),"%s",p);
    return snprintf(out,sz,"P123456789abcde")==15?0:-1;
}
''' + badge_source + r'''
int main(void) {
    mkdir("mass0:",0700);
    mkdir("mass0:/games",0700);
    mkdir("mass0:/games/RA",0700);
    FILE *f=fopen("mass0:/games/RA/P123456789abcde.wl","wb");
    assert(f); fputs("watch",f);fclose(f);

    item_list_t usb={0,getname,getstartup,getprefix,getgame};
    raBadgeRefresh(&usb,1);
    assert(raBadgeText(&usb,0) && !strcmp(raBadgeText(&usb,0),"RA First"));
    assert(!strcmp(full,"mass0:/POPS/First.VCD"));

    item_list_t favorite={FAV_MODE,getname,getstartup,NULL,NULL};
    raBadgeRefresh(&favorite,1);
    assert(raBadgeText(&favorite,0) && !strcmp(raBadgeText(&favorite,0),"RA First"));

    favkind=2; /* Ember CUE cannot be tracked by the POPStarter bridge. */
    raBadgeRefresh(&favorite,1);
    assert(raBadgeText(&favorite,0)==NULL);

    /* An SMB-only PS1 watch list cannot be loaded by USB POPStarter and
       must not trigger remote probes or a false local achievement badge. */
    assert(unlink("mass0:/games/RA/P123456789abcde.wl")==0);
    assert(mkdir("smb0:RA",0700)==0);
    f=fopen("smb0:RA/P123456789abcde.wl","wb");
    assert(f);fputs("remote",f);fclose(f);
    favkind=FAV_KIND_VCD;
    raBadgeRefresh(&usb,1);
    assert(raBadgeText(&usb,0)==NULL);
    raBadgeRefresh(&favorite,1);
    assert(raBadgeText(&favorite,0)==NULL);

    view=0; strcpy(startup,"SLUS_210.65");
    f=fopen("mass0:/games/RA/SLUS_210.65.wl","wb");
    assert(f);fputs("watch",f);fclose(f);
    raBadgeRefresh(&usb,1);
    assert(raBadgeText(&usb,0) && !strcmp(raBadgeText(&usb,0),"RA First"));

    gRABadges=0;raBadgeRefresh(&usb,1);
    assert(raBadgeText(&usb,0)==NULL);
    puts("PASS: USB PS1/Favorites per-VCD badges, excluded Ember, and unchanged PS2 badges");
}
''')
