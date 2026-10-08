"""Execute the real completion probe with MMCE and FATFS ioctl contracts."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/system.c').read_text(encoding='utf-8')
start = source.index('int sysVMCContiguity(void)')
end = source.index('\n}\n', start) + 3
function = source[start:end]
program = r'''
#include <assert.h>
#include <stddef.h>
#include <string.h>
typedef unsigned long long u64;
#define O_RDONLY 0
#define USBMASS_IOCTL_GET_LBA 1
#define USBMASS_IOCTL_CHECK_CHAIN 2
#define LOG(...) ((void)0)
static char gVMCCreatePath[256];
static int openResult=4, result, suppliesLba, chain, calls, closes;
static int open(const char *path, int flags) { (void)path; (void)flags; return openResult; }
static int close(int fd) { (void)fd; closes++; return 0; }
static int ps2sdk_get_iop_fd(int fd) { return fd+10; }
static int fileXioIoctl2(int fd, int cmd, void *arg, int arglen, void *out, int outlen) {
    (void)arg; (void)arglen;
    assert(fd == 14 && cmd == USBMASS_IOCTL_GET_LBA && outlen == sizeof(u64));
    if (suppliesLba) *(u64 *)out = 0x123456789ULL;
    return result;
}
static int fileXioIoctl(int fd, int cmd, const char *arg) {
    (void)arg; assert(fd == 14 && cmd == USBMASS_IOCTL_CHECK_CHAIN); calls++; return chain;
}
@FUNCTION@
int main(void) {
    assert(sysVMCContiguity() == -1 && closes == 0);
    strcpy(gVMCCreatePath, "mmce0:/VMC/card.bin");
    // Actual mmceman contract: successful unsupported ioctl, output untouched; ioctl returns 0.
    result=0; suppliesLba=0; chain=0;
    assert(sysVMCContiguity() == -1 && calls == 0 && closes == 1);
    suppliesLba=1; chain=1;
    assert(sysVMCContiguity() == 1 && calls == 1 && closes == 2);
    chain=0; assert(sysVMCContiguity() == 0 && calls == 2 && closes == 3);
    chain=-5; assert(sysVMCContiguity() == -1 && calls == 3 && closes == 4);
    result=-1; assert(sysVMCContiguity() == -1 && calls == 3 && closes == 5);
    openResult=-1; assert(sysVMCContiguity() == -1 && closes == 5);
    return 0;
}
'''.replace('@FUNCTION@', function)
with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    cfile, exe = temp / 'test.c', temp / 'test'
    cfile.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('VMC completion: unsupported MMCE ioctl stays unknown; real FATFS chain checks remain enforced')
