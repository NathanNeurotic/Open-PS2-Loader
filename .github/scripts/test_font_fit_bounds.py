"""Execute production word wrapping at exact allocations and guarded boundaries."""
from pathlib import Path
import subprocess
import tempfile
import sys

root=Path(__file__).resolve().parents[2]
path='src/gfx/fntsys.cpp' if (root/'src/gfx/fntsys.cpp').exists() else 'src/fntsys.c'
source=(subprocess.check_output(['git','show',sys.argv[1]+':'+path],cwd=root,text=True)
        if len(sys.argv)>1 else (root/path).read_text())
start=source.index('void fntFitString(');end=source.index('\n}\n',start)+3
code=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static const char *begin,*end;
static size_t rmScaleX(size_t width) {return width;}
static size_t fntCalcDimensions(int id,const char *p) {
 (void)id;
 if(p[0]==' ' && p[1]==0)return 1;
 assert((uintptr_t)p>=(uintptr_t)begin && (uintptr_t)p<=(uintptr_t)end);
 size_t count=0;
 for(;*p;p++) {
  assert(p<=end);
  if(((unsigned char)*p&0xc0)!=0x80)count++;
 }
 assert(p<=end);return count;
}
'''+source[start:end]+r'''
static void check(const char *input,size_t width,const char *want,int exact) {
 size_t n=strlen(input),capacity=n+1+(exact?0:65);
 char *buf=(char *)malloc(capacity);assert(buf);
 memcpy(buf,input,n+1);
 if(!exact) {memset(buf+n+1,'Z',64);buf[n+65]=0;}
 begin=buf;end=buf+n;
 fntFitString(0,buf,width);
 assert(buf[n]==0 && strlen(buf)==n);
 if(want)assert(!strcmp(buf,want));
 /* Wrapping changes separators only; UTF-8 bytes and original newlines stay intact. */
 for(size_t i=0;i<n;i++)assert(buf[i]==input[i] || (input[i]==' ' && buf[i]=='\n'));
 if(!exact)for(size_t i=n+1;i<n+65;i++)assert(buf[i]=='Z');
 free(buf);
}
int main(void) {
 for(int exact=0;exact<2;exact++) {
  check("fits",20,"fits",exact);check("LongFinalWord",1,"LongFinalWord",exact);
  check("",0,"",exact);check("x",0,"x",exact);check("a b",2,"a\nb",exact);
  check("a b c",3,"a b\nc",exact);check("a\nb",1,"a\nb",exact);
  check("a ",1,"a ",exact);check("a\n",0,"a\n",exact);
  check("\xe6\x97\xa5\xe6\x9c\xac \xe8\xaa\x9e",2,"\xe6\x97\xa5\xe6\x9c\xac\n\xe8\xaa\x9e",exact);
  for(int n=0;n<=255;n++) {
   char cfg[256];memset(cfg,'A',n);cfg[n]=0;
   for(int width=0;width<20;width++)check(cfg,width,cfg,exact);
  }
 }
 puts("PASS: exact/guarded strings, final long words, 255-byte CFG values, whitespace, narrow widths and UTF-8");
}
'''
with tempfile.TemporaryDirectory(prefix='font-fit-') as folder:
 p=Path(folder)
 for compiler,ext,standard in [('gcc','c','c99'),('g++','cpp','c++17')]:
  src=p/('test.'+ext);src.write_text(code)
  binary=p/('test-'+ext)
  subprocess.run([compiler,'-std='+standard,'-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(src),'-o',str(binary)],check=True)
  subprocess.run([str(binary)],check=True,timeout=15)
# The existing immutable-config fix must remain in place; this port does not
# replace it. Check the production caller still wraps its own allocated copy.
theme=(root/('src/gfx/themeelems.cpp' if 'cpp' in path else 'src/themes.c')).read_text()
assert 'fntFitString(elem->font, wrapped, elem->width)' in theme
assert 'memcpy(wrapped, mutableText->currentValue, len)' in theme
print('PASS: attribute text retains the existing private-copy wrapping path')
