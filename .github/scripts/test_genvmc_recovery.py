"""Exercise genvmc's real cluster writer after failed and short writes."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "modules/vmc/genvmc/genvmc.c").read_text(encoding="utf-8")
start = source.index("static int mc_writecluster(")
function = source[start:source.index("\n}\n", start) + 3]
program = r'''
#include <assert.h>
typedef struct { int cluster_size; } MCDevInfo;
static MCDevInfo devinfo = {1024};
static int genvmc_abort_sema = 1, genvmc_abort, tokens = 1, writeResult, writes;
static int WaitSema(int id) { assert(id == 1 && tokens == 1); tokens--; return 0; }
static int SignalSema(int id) { assert(id == 1 && tokens == 0); tokens++; return 0; }
static int lseek(int fd, int offset, int whence) { (void)fd; (void)whence; return offset; }
static int write(int fd, void *buf, int count) { (void)fd; (void)buf; (void)count; writes++; return writeResult; }
#define SEEK_SET 0
@FUNCTION@
int main(void) {
    char buffer[2048];
    writeResult = -5;
    assert(mc_writecluster(3, 0, buffer, 2) == -1 && tokens == 1);
    writeResult = 512;
    assert(mc_writecluster(3, 0, buffer, 2) == -1 && tokens == 1);
    writeResult = 2048;
    assert(mc_writecluster(3, 0, buffer, 2) == 0 && tokens == 1);
    genvmc_abort = 1;
    assert(mc_writecluster(3, 0, buffer, 2) == -2 && tokens == 1 && writes == 3);
    genvmc_abort = 0;
    assert(mc_writecluster(3, 0, buffer, 2) == 0 && tokens == 1);
    return 0;
}
'''.replace("@FUNCTION@", function)
with tempfile.TemporaryDirectory() as directory:
    cfile, exe = Path(directory) / "test.c", Path(directory) / "test"
    cfile.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", str(cfile), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("genvmc: failed write, short write, retry and abort release the semaphore")
