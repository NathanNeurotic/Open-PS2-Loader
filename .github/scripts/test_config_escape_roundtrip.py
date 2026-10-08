"""Production config writer/reader must preserve quoted paths across repeated saves."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/config.c').read_text(encoding='utf-8')
def function(signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]
program = '\n#include <stdio.h>\n#include <assert.h>\n#include <string.h>\n#include <ctype.h>\n#define CONFIG_KEY_NAME_LEN 32\n#define CONFIG_KEY_VALUE_LEN 256\ntypedef struct {char text[1200];} file_buffer_t;\ntypedef struct {char value[256];} config_set_t;\nstatic int isWS(char c) {return c==\' \'||c==\'\\t\'||c==\'\\r\'||c==\'\\n\';}\nstatic const char *cfgWoplToOurs(const char *k) {(void)k;return "$AltStartup";}\nstatic int configSetStr(config_set_t *c,const char *k,const char *v) {(void)k;snprintf(c->value,sizeof(c->value),"%s",v);return 1;}\nstatic void writeFileBuffer(file_buffer_t *b,const char *v,int n) {memcpy(b->text,v,n);b->text[n]=0;}\n@FUNCTIONS@\n\nstatic void roundtrip(const char *value) {\n config_set_t c;file_buffer_t b;char group[32]={0};\n snprintf(c.value,sizeof(c.value),"%s",value);\n for(int i=0;i<6;i++) {cfgWriteLibconfigLine(&b,"","alt_startup",c.value);cfgReadLibconfigLine(b.text,group,sizeof(group),&c);assert(strcmp(c.value,value)==0);}\n}\nint main(void) {\n roundtrip("MGS\\\\NET\\\\MGS3_N.ELF");roundtrip("A \\"quoted\\" title");roundtrip("path\\\\unknown\\\\q.ELF");\n char maximum[256];memset(maximum,\'\\\\\',255);maximum[255]=0;roundtrip(maximum);\n memset(maximum,\'"\',255);roundtrip(maximum);\n config_set_t c={"unchanged"};char group[32]={0};char plain[]="alt_startup = unquoted/path.ELF;";\n cfgReadLibconfigLine(plain,group,sizeof(group),&c);assert(strcmp(c.value,"unquoted/path.ELF")==0);\n char old[]="alt_startup = \\"MGS\\\\NET\\\\MGS3_N.ELF\\";";\n cfgReadLibconfigLine(old,group,sizeof(group),&c);assert(strcmp(c.value,"MGS\\\\NET\\\\MGS3_N.ELF")==0);\n return 0;\n}\n'
program = program.replace('@FUNCTIONS@', '\n'.join(function(s) for s in (
    'static int cfgValueIsBareScalar(', 'static void cfgWriteLibconfigLine(', 'static void cfgReadLibconfigLine(')))
with tempfile.TemporaryDirectory() as directory:
    cfile, exe = Path(directory) / 'roundtrip.c', Path(directory) / 'roundtrip'
    cfile.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', str(cfile), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('config round trip: paths, quotes, unknown escapes and maximum escaped values survive repeated saves')
