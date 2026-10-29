"""Execute the production synchronous READ_KEY gate in C and C++.

No PS2 drive is accessed. Hardware stop/sync and launch still need validation.
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
program = r'''
#include <assert.h>
#include <stdio.h>
#include "disc_key.h"
SifRpcClientData_t clientNCmd;
int nCmdSemaId=7;
static int held,owner,acquisitions,releases,rpcs,rpc_result;
int _CdCheckNCmd(int cmd) {
 assert(cmd==0x0b);
 if(held)return 0;
 held=1;owner=1;acquisitions++;return 1;
}
int SignalSema(int id) {
 assert(id==7 && held && owner==1);
 held=owner=0;releases++;return 0;
}
int sceSifCallRpc(SifRpcClientData_t *client,int cmd,int mode,void *send,int sn,
                  void *recv,int rn,void (*callback)(void *),void *arg) {
 assert(client==&clientNCmd && cmd==0x0b && !mode && sn==12 && rn==24 && !callback && !arg);
 assert(held && owner==1);
 assert(((uintptr_t)send%64)==0 && ((uintptr_t)recv%64)==0);
 u32 *request=(u32 *)send;
 assert(request[0]==0 && request[1]==0 && request[2]==0x4b);
 /* Another N-command cannot acquire while our synchronous RPC is in flight. */
 assert(!_CdCheckNCmd(0x0b) && held && owner==1);
 for(int i=0;i<24;i++)((u8 *)recv)[i]=(u8)i;
 rpcs++;return rpc_result;
}
static int old_read_key(void) {
 if(!_CdCheckNCmd(0x0b))return 0;
 return 1; /* SDK regression: synchronous success forgot SignalSema. */
}
int main(void) {
 unsigned char key[18];
 assert(old_read_key() && !old_read_key() && held);
 held=owner=acquisitions=0;
 for(int i=0;i<100;i++) {
  memset(key,0xa7,sizeof(key));
  rpc_result=i%2?0:-1;
  assert(sysReadDiscKey(0,0,0x4b,key+1)==(rpc_result>=0));
  assert(!held && acquisitions==releases && rpcs==i+1);
  assert(key[0]==0xa7 && key[17]==0xa7);
  for(int n=0;n<16;n++)assert(key[n+1]==(rpc_result>=0?n+4:0xa7));
 }
 /* A rejected acquisition (e.g. another asynchronous N-command) is untouched. */
 held=1;owner=2;int prior=releases;
 assert(!sysReadDiscKey(0,0,0x4b,key) && held && owner==2 && releases==prior);
 held=owner=0;
 assert(!sysReadDiscKey(0,0,0x4b,NULL) && !held && releases==prior);
 /* No dependence on whether sceCdReadKey in a linked SDK is already fixed:
  * production directly owns this RPC and never calls that SDK function. */
 puts("PASS: reproduced old leak; repeated success/failure, lock ownership and key buffer bounds");
}
'''
with tempfile.TemporaryDirectory(prefix='disc-key-') as folder:
    path=Path(folder)
    (path/'tamtypes.h').write_text('#pragma once\n#include <stdint.h>\ntypedef uint32_t u32;typedef uint8_t u8;\n')
    (path/'kernel.h').write_text('#pragma once\n#define UNCACHED_SEG(p) (p)\n#ifdef __cplusplus\nextern "C" {\n#endif\nint SignalSema(int);\n#ifdef __cplusplus\n}\n#endif\n')
    (path/'sifrpc.h').write_text('#pragma once\ntypedef struct {int unused;} SifRpcClientData_t;\n#ifdef __cplusplus\nextern "C" {\n#endif\nint sceSifCallRpc(SifRpcClientData_t*,int,int,void*,int,void*,int,void(*)(void*),void*);\n#ifdef __cplusplus\n}\n#endif\n')
    for compiler,ext,standard in [('gcc','c','c99'),('g++','cpp','c++17')]:
        src=path/('test.'+ext);src.write_text(program)
        binary=path/('test-'+ext)
        subprocess.run([compiler,'-std='+standard,'-Wall','-Wextra','-Werror','-I'+str(path),'-I'+str(root/'include'),str(src),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
paths=['src/platform/system.cpp','src/platform/sysdisc.cpp'] if (root/'src/platform/system.cpp').exists() else ['src/system.c']
assert sum(len(re.findall(r'^\s*if \(sysReadDiscKey\(', (root/p).read_text(), re.M)) for p in paths)==2
assert not any(re.search(r'^\s*if \(sceCdReadKey\(', (root/p).read_text(), re.M) for p in paths)
print('PASS: both production disc-key paths use the owned synchronous helper')
