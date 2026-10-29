"""Run the production history filename extraction with guarded output buffers.

The extracted name must fit what AddHistoryRecord() stores (sizeof(name) - 1 characters), or its
16-byte compare never matches the stored record and every launch takes a new history slot.
"""
from pathlib import Path
import subprocess
import tempfile
import sys

root=Path(__file__).resolve().parents[2]
path='src/core/OSDHistory.cpp' if (root/'src/core/OSDHistory.cpp').exists() else 'src/OSDHistory.c'
source=(subprocess.check_output(['git','show',sys.argv[1]+':'+path],cwd=root,text=True)
        if len(sys.argv)>1 else (root/path).read_text())
header=(root/'include/OSDHistory.h').read_text()
assert 'char name[16];' in header, 'HistoryEntry.name is no longer 16 bytes; update the 15-character clamp'
assert 'strncpy(NewEntry->name, name, sizeof(NewEntry->name) - 1);' in source, 'AddHistoryRecord store limit changed'
assert '!strncmp(HistoryEntries[i].name, name, sizeof(HistoryEntries[i].name))' in source, 'history compare changed'
start=source.index('static void GetBootFilename(')
end=source.index('\n}\n',start)+3
function=source[start:end]
code=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
'''+function+r'''
static void check(const char *path,const char *want) {
 struct {unsigned char before[16];char name[17];unsigned char after[4096];} out;
 memset(&out,0xa7,sizeof(out));GetBootFilename(path,out.name);
 assert(memchr(out.name,0,sizeof(out.name))!=NULL);
 assert(!strcmp(out.name,want));
 for(unsigned i=0;i<sizeof(out.before);i++)assert(out.before[i]==0xa7);
 for(unsigned i=0;i<sizeof(out.after);i++)assert(out.after[i]==0xa7);
}
int main(void) {
 check("cdrom0:\\DATA\\ABCDEFGHIJKLMNOPQRST.ELF;1","ABCDEFGHIJKLMNO");
 check("ABCDEFGHIJKLMNOPQRST.ELF","ABCDEFGHIJKLMNO");
 check("ABCDEFGHIJKLMNOP","ABCDEFGHIJKLMNO");
 check("ABCDEFGHIJKLMNO","ABCDEFGHIJKLMNO");
 check("cdrom0:/ABCDEFGHIJKLMNOP;1","ABCDEFGHIJKLMNO");
 check("cdrom0:/ABCDEFGHIJKLMNO;1","ABCDEFGHIJKLMNO");
 check("cdrom0:\\SLUS_123.45;1","SLUS_123.45");
 check("SLUS_123.45","SLUS_123.45");
 check("SLUS_123.45;1","SLUS_123.45;1"); /* retain bare-name behavior */
 check("cdrom0:/nested/GAME.ELF","GAME.ELF");
 check("cdrom0:/GAME.ELF;2","GAME.ELF;2");
 check("cdrom0:/","");check("cdrom0:;1","");check("","");
 for(int n=0;n<1024;n++) {
  char input[1100],want[17];memset(input,'A',n);input[n]=0;
  int keep=n<15?n:15;memset(want,'A',keep);want[keep]=0;check(input,want);
  snprintf(input,sizeof(input),"cdrom0:/%0*d;1",n?n:1,0);
  /* Decimal padding is independent of the production separator loop. */
  const char *leaf=strrchr(input,'/')+1;int count=strlen(leaf)-2;
  if(count>15)count=15;
  memcpy(want,leaf,count);want[count]=0;check(input,want);
 }
 puts("PASS: bounded history names, long alternate startup, exact fits, separators, versions and empty input");
}
'''
with tempfile.TemporaryDirectory(prefix='history-filename-') as folder:
 p=Path(folder);src=p/'test.c';src.write_text(code)
 subprocess.run(['gcc','-std=c99','-Wall','-Wextra','-Werror',str(src),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
