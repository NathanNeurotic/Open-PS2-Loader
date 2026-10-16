"""Execute the real masked-word scanner at empty, short and final windows."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
    source_path = Path(sys.argv[1])
    extra_args = sys.argv[2:]
else:
    source_path = ROOT / "ee_core/src/util.c"
    extra_args = sys.argv[1:]

source = source_path.read_text(encoding="utf-8")
start = source.index("u32 *find_pattern_with_mask(")
function = source[start:source.index("\n}", start) + 2]
program = r'''
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
typedef unsigned int u32;
''' + function + r'''
int main(int argc,char **argv) {
 (void)argv;
 u32 data[]={0x1234,0x55aa,0x6677};
 const u32 pair[]={0x55aa,0x6677}, mask[]={0xffffffff,0xffffffff};
 if (argc>1) {
  u32 *short_range=malloc(sizeof(u32));assert(short_range);*short_range=pair[0];
  assert(find_pattern_with_mask(short_range,4,pair,mask,sizeof(pair))==NULL);
  free(short_range);
 }
 /* Last window and exact-sized ranges are valid candidates. */
 assert(find_pattern_with_mask(data,sizeof(data),pair,mask,sizeof(pair))==data+1);
 assert(find_pattern_with_mask(data+1,sizeof(pair),pair,mask,sizeof(pair))==data+1);
 /* A logical range shorter than the pattern must not read its following word. */
 assert(find_pattern_with_mask(data+1,4,pair,mask,sizeof(pair))==NULL);
 assert(find_pattern_with_mask(NULL,0,pair,mask,sizeof(pair))==NULL);
 assert(find_pattern_with_mask(data,3,pair,mask,sizeof(pair))==NULL);
 assert(find_pattern_with_mask(data,sizeof(data),pair,mask,0)==NULL);
 assert(find_pattern_with_mask(data,sizeof(data),pair,mask,3)==NULL);
 const u32 absent[]={0x9999,0xaaaa};
 assert(find_pattern_with_mask(data,sizeof(data),absent,mask,sizeof(absent))==NULL);
 const u32 masked[]={0x5500,0x6600}, high[]={0xff00,0xff00};
 assert(find_pattern_with_mask(data,sizeof(data),masked,high,sizeof(masked))==data+1);
 puts("PASS: masked scan includes final/exact windows and rejects short/empty ranges without overread");
}
'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    c = path / "test.c"
    exe = path / ("test.exe" if os.name == "nt" else "test")
    c.write_text(program, encoding="utf-8")
    flags = ["-std=c99", "-Wall", "-Wextra", "-Werror"]
    if os.name != "nt":
        flags += ["-fsanitize=address,undefined", "-fno-pie", "-no-pie"]
    subprocess.run([os.environ.get("CC", "gcc"), *flags, str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe), *extra_args], check=True, timeout=10)
