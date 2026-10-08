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
#define USBMASS_IOCTL_GET_FRAGLIST 2
#define LOG(...) ((void)0)
static char gVMCCreatePath[256];
static int openResult=4, result, suppliesLba, fragments, calls, closes;
static int open(const char *path, int flags) { (void)path; (void)flags; return openResult; }
static int close(int fd) { (void)fd; closes++; return 0; }
static int ps2sdk_get_iop_fd(int fd) { return fd+10; }
static int fileXioIoctl2(int fd, int cmd, void *arg, int arglen, void *out, int outlen) {
    (void)arg; (void)arglen;
    assert(fd == 14);
    if (cmd == USBMASS_IOCTL_GET_LBA) {
        assert(outlen == sizeof(u64));
        if (suppliesLba) *(u64 *)out = 0x123456789ULL;
        return result;
    }
    assert(cmd == USBMASS_IOCTL_GET_FRAGLIST && out == NULL && outlen == 0);
    calls++; return fragments;
}
@FUNCTION@
int main(void) {
    assert(sysVMCContiguity() == -1 && closes == 0);
    strcpy(gVMCCreatePath, "mmce0:/VMC/card.bin");
    // Actual mmceman contract: successful unsupported ioctl, output untouched; ioctl returns 0.
    result=0; suppliesLba=0; fragments=0;
    assert(sysVMCContiguity() == -1 && calls == 0 && closes == 1);
    suppliesLba=1; fragments=1;
    assert(sysVMCContiguity() == 1 && calls == 1 && closes == 2);
    fragments=2; assert(sysVMCContiguity() == 0 && calls == 2 && closes == 3);
    fragments=-5; assert(sysVMCContiguity() == -1 && calls == 3 && closes == 4);
    fragments=0; assert(sysVMCContiguity() == -1 && calls == 4 && closes == 5);
    result=-1; assert(sysVMCContiguity() == -1 && calls == 4 && closes == 6);
    openResult=-1; assert(sysVMCContiguity() == -1 && closes == 6);
    return 0;
}
'''.replace('@FUNCTION@', function)
with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    cfile, exe = temp / 'test.c', temp / 'test'
    cfile.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('VMC completion: unsupported MMCE ioctl stays unknown; positive fragment counts distinguish contiguous, fragmented and failed/empty queries')
