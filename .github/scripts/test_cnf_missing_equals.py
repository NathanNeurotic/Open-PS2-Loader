"""Execute the complete production SYSTEM.CNF file parser with real host files."""
from pathlib import Path
import subprocess
import tempfile
import sys

root=Path(__file__).resolve().parents[2]
source=(subprocess.check_output(['git','show',sys.argv[1]+':src/ps2cnf.c'],cwd=root,text=True)
        if len(sys.argv)>1 else (root/'src/ps2cnf.c').read_text())
source=source.replace('#include "ioman.h"','#define LOG(...) ((void)0)')
harness=r'''
#include <assert.h>
int main(int argc,char **argv) {
 char out[CNF_PATH_LEN_MAX];assert(argc==3);
 memset(out,0xa7,sizeof(out));
 int result=ps2cnfGetBootFile(argv[1],out);
 if(!strcmp(argv[2],"invalid")) {
  assert(result!=0);
  for(unsigned i=0;i<sizeof(out);i++)assert((unsigned char)out[i]==0xa7);
 } else {
  assert(!result && !strcmp(out,argv[2]));
 }
 return 0;
}
'''
cases=[
 ('BOOT2 cdrom0:\\SLUS_200.62;1\r\n','invalid'),
 ('BOOT2 missing_equals\n','invalid'),('BOOT2','invalid'),('BOOT2   ','invalid'),
 ('BOOT2 =','invalid'),('BOOT2 = \r\n','invalid'),('','invalid'),
 ('BO','invalid'),('VER = 1.00\n','invalid'),
 ('BOOT2 = cdrom0:\\SLUS_200.62;1\r\n','cdrom0:\\SLUS_200.62;1'),
 ('  BOOT2=cdrom0:\\SCES_123.45;1\n','cdrom0:\\SCES_123.45;1'),
 ('VER = 1.00\nVMODE = PAL\nBOOT2 = cdrom0:\\GAME.ELF;1\n','cdrom0:\\GAME.ELF;1'),
]
with tempfile.TemporaryDirectory(prefix='cnf-equals-') as folder:
 path=Path(folder);src=path/'test.c';src.write_text(source+harness)
 subprocess.run(['gcc','-std=c99','-Wall','-Wextra','-Werror','-Wno-sign-compare','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(root/'include'),str(src),'-o',str(path/'test')],check=True)
 for i,(cnf,want) in enumerate(cases):
  fixture=path/(str(i)+'.cnf');fixture.write_text(cnf)
  subprocess.run([str(path/'test'),str(fixture),want],check=True,timeout=5)
print('PASS: missing equals/EOF leave output untouched; valid BOOT2, CRLF and preceding fields still parse')
