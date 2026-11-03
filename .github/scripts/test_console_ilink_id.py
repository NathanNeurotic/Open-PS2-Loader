"""Exercise the real parser, UI normalizer, CDVDMAN response and launch layout."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
gui_path = root / ('src/ui/guigame.cpp' if (root / 'src/ui/guigame.cpp').exists() else 'src/guigame.c')
gui = gui_path.read_text()
support = (root / ('src/sources/supportbase.cpp' if (root / 'src/sources/supportbase.cpp').exists() else 'src/supportbase.c')).read_text()
scmd = (root / 'modules/iopcore/cdvdman/scmd.c').read_text()

def function(source, signature):
    match = re.search(r'^' + re.escape(signature) + r'.*?\n\}', source, re.M | re.S)
    assert match, signature
    return match.group(0)

save = function(gui, 'int guiGameSaveConfig(')
assert save.index('guiGameReadILinkID') < save.index('guiGamePrepareParentalLock') < save.index('guiGameApplyConfig')
reset = function(gui, 'void guiGameRemoveSettings(')
assert 'configRemoveKey(configSet, CONFIG_ITEM_ILINK_ID)' in reset
assert 'COMPAT_ILINK_ID, !neutrino && ilinkIdNativeCapable' in gui
assert 'ilinkIdNativeCapable = support == NULL || libViewActive(support->mode) != LIB_VIEW_PS1' in gui
assert 'oplParseILinkID(consoleID, settings->ilink_id)' in function(support, 'int sbPrepare(')
assert 'sizeof(struct cdvdman_settings_common)' in function(support, 'void sbUnprepare(')

code = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>
#include <ilinkid.h>
#include <cdvd_config.h>
#define COMPAT_ILINK_ID 280
static int diaCompatConfig;
static const char *edit;
static void diaGetString(int d,int id,char *out,int n){(void)d;assert(id==COMPAT_ILINK_ID);snprintf(out,n,"%s",edit);}
static struct {struct cdvdman_settings_common common;} cdvdman_settings;
static int hardware_calls;
static void cdvdman_sendSCmd(int cmd,void *in,int n,void *out,int length){
 (void)in;assert(cmd==0x12&&n==0&&length==9);hardware_calls++;
 unsigned char *p=out;p[0]=0x25;for(int i=0;i<8;i++)p[i+1]=0x10+i;
}
'''
code += function(gui, 'static int guiGameReadILinkID(')
code += function(scmd, 'int sceCdRI(')
# readID uses sceCdRI; compile after its declaration as in the production header.
code += function(scmd, 'int cdvdman_readID(')
code += function(scmd, 'int sceCdReadGUID(')
code += function(scmd, 'int sceCdReadModelID(')
code += r'''
int main(void){
 const u8 wanted[8]={0x01,0x23,0x45,0x67,0x89,0xAB,0xCD,0xEF};u8 id[8],out[8];u32 status;
 const char *invalid[]={"0","0123456789ABCDE","0123456789ABCDEF0","0123456789ABCDEG"," 123456789ABCDEF","01-23456789ABCDEF","0123456789ABCDEF\n"};
 memset(id,0xFF,8);assert(oplParseILinkID(NULL,id)==0&&!memcmp(id,(u8[8]){0},8));
 for(unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++){
  memset(id,0xFF,8);assert(oplParseILinkID(invalid[i],id)==-1&&!memcmp(id,(u8[8]){0},8));
 }
 assert(oplParseILinkID("0123456789abcdef",id)==1&&!memcmp(id,wanted,8));
 assert(oplParseILinkID("0123456789ABCDEF",id)==1&&!memcmp(id,wanted,8));
 char normalized[17];edit="0123456789abcdef";assert(guiGameReadILinkID(normalized)==1&&!strcmp(normalized,"0123456789ABCDEF"));
 edit="bad";assert(guiGameReadILinkID(normalized)==-1&&!normalized[0]);
 edit="0000000000000000";assert(guiGameReadILinkID(normalized)==0&&!normalized[0]);
 edit="";assert(guiGameReadILinkID(normalized)==0&&!normalized[0]);
 /* The real module's zero/default path forwards the hardware status and bytes. */
 memset(&cdvdman_settings,0,sizeof(cdvdman_settings));assert(sceCdRI(out,&status)==1&&status==0x25&&hardware_calls==1&&out[0]==0x10&&out[7]==0x17);
 assert(sceCdRI(out,NULL)==1&&hardware_calls==2);
 assert(oplParseILinkID("0123456789ABCDEF",cdvdman_settings.common.ilink_id)==1);
 assert(sceCdRI(out,&status)==1&&status==0&&hardware_calls==2&&!memcmp(out,wanted,8));
 assert(sceCdRI(out,NULL)==1&&hardware_calls==2);
 u64 guid;u32 model;assert(sceCdReadGUID(&guid)==1&&sceCdReadModelID(&model)==1);
 u32 word;memcpy(&word,wanted,4);assert((u32)guid==(wanted[0]|0x08004600)&&model==(word>>8));
 /* A subsequent game without an override MUST return to the real console. */
 assert(!oplParseILinkID(NULL,cdvdman_settings.common.ilink_id));
 assert(sceCdRI(out,&status)==1&&hardware_calls==3&&status==0x25);
 assert(offsetof(struct cdvdman_settings_common,ilink_id)==20&&sizeof(struct cdvdman_settings_common)==28);
 assert(offsetof(struct cdvdman_settings_hdd,lba_start)==28);
 assert(offsetof(struct cdvdman_settings_bdm,fragfile)==28);
 assert(offsetof(struct cdvdman_settings_mmce,port)==28);
 assert(offsetof(struct cdvdman_settings_udpfs,iso_handle)==28);
 struct cdvdman_settings_common defaults=CDVDMAN_SETTINGS_DEFAULT_COMMON;
 assert(!memcmp(defaults.ilink_id,(u8[8]){0},8));
 puts("PASS: console ID parser, byte order, UI normalization/validation, native-only controls, hardware fallback, status, GUID/model, next game and backend layout");
}
'''
with tempfile.TemporaryDirectory(prefix='console-ilink-id-') as folder:
    p = Path(folder)
    (p / 'tamtypes.h').write_text('#pragma once\n#include <stdint.h>\ntypedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;\n')
    (p / 'usbhdfsd-common.h').write_text('typedef struct { u64 sector; u32 count; } __attribute__((packed)) bd_fragment_t;\n')
    (p / 'test.c').write_text(code)
    subprocess.run(['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I', str(p), '-I', str(root / 'include'), '-I', str(root / 'modules/iopcore/common'),
                    str(p / 'test.c'), '-o', str(p / 'test')], check=True)
    subprocess.run([str(p / 'test')], check=True)
