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
    char boot[16], hash[33];
'''
    for file, boot in [('retail.vcd', 'SLUS_012.15'), ('nested.vcd', 'D\\G.EXE'), ('fallback.vcd', 'PSX.EXE')]:
        expected = hashlib.md5(boot.encode() + payload).hexdigest()
        escaped = boot.replace('\\', '\\\\')
        checks += f'assert(raHashVcd("{file}",boot,sizeof(boot),hash)==0);\n'
        checks += f'assert(!strcmp(boot,"{escaped}") && !strcmp(hash,"{expected}"));\n'
        checks += f'assert(raVcdBootName("{file}",boot,sizeof(boot))==0 && !strcmp(boot,"{escaped}"));\n'
    checks += '''
    assert(raHashVcd("truncated.vcd",boot,sizeof(boot),hash)<0 && hash[0]==0);
    assert(raHashVcd("overflow.vcd",boot,sizeof(boot),hash)<0 && hash[0]==0);
    assert(raHashVcd("missing.vcd",boot,sizeof(boot),hash)<0 && hash[0]==0);
    puts("PASS: PS1 hashes match independent MD5 fixtures, nested/fallback boot, truncated/overflow rejection");
}
'''
    run('hash_ps1', prefix + source + checks, [root/'src/md5.c'])

    (tmp/'POPS').mkdir()
    source = (root/'src/vcdsupport.c').read_text()
    source = source[source.index('int vcdRemoveRaModule('):]
    run('ownership', '''
#include <assert.h>
#include <stdio.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
''' + source + '''
int main(void) {
    assert(vcdRemoveRaModule("")==0);
    FILE *f=fopen("POPS/MODULE_9.IRX","wb");fputs("user module",f);fclose(f);
    assert(vcdRemoveRaModule("")==-1);
    assert(access("POPS/MODULE_9.IRX",0)==0);
    f=fopen("POPS/MODULE_9.IRX","wb");
    for(int i=0;i<4093;i++) fputc(0,f);
    fputs("RIPTRA01",f);fclose(f);
    assert(vcdRemoveRaModule("")==0);
    assert(access("POPS/MODULE_9.IRX",0)<0);
    puts("PASS: user module preserved; owned module spanning read boundary removed; absent module accepted");
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
#include "modules/network/common/rapops_cfg.h"
#define RETROACHIEVEMENTS
#define RA_MODE_CADUCEUS 1
static int gRATelemetry=1, gRAMode=1, count=1, network=1;
static unsigned char rapops_irx[sizeof(struct rapops_cfg)];
static unsigned int size_rapops_irx=sizeof(rapops_irx);
static int raVcdBootName(const char *p,char *s,int n) {(void)p;snprintf(s,n,"SLUS_012.15");return 0;}
static int sbLoadWatchList(const char *p,const char *s) {(void)p;(void)s;return count;}
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
static int fat_open(const char *p,int flags,int mode) {return open(p,flags & ~O_EXCL,mode);}
#define open fat_open
''' + source + r'''
int main(void) {
    memcpy(rapops_irx,RAPOPS_MAGIC,8);
    FILE *f=fopen("POPS/MODULE_9.IRX","wb");fputs("user module",f);fclose(f);
    assert(raPopsPrepare("","","game.vcd",0)<0);
    char buf[32]={0};f=fopen("POPS/MODULE_9.IRX","rb");fread(buf,1,sizeof(buf),f);fclose(f);
    assert(!strcmp(buf,"user module"));
    count=0;assert(raPopsPrepare("","","game.vcd",0)==0);
    count=1;gRATelemetry=0;assert(raPopsPrepare("","","game.vcd",0)==0);
    gRATelemetry=1;unlink("POPS/MODULE_9.IRX");
    assert(raPopsPrepare("","","game.vcd",1)==0);
    struct rapops_cfg cfg;f=fopen("POPS/MODULE_9.IRX","rb");
    assert(fread(&cfg,1,sizeof(cfg),f)==sizeof(cfg));fclose(f);
    assert(cfg.client_mode==1 && cfg.count==1 && cfg.bytes==4 && !strcmp(cfg.game_id,"SLUS_012.15"));
    unlink("POPS/MODULE_9.IRX");
    puts("PASS: occupied user slot preserved even when O_EXCL is ignored; untracked/disabled launch; embedded configuration");
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
