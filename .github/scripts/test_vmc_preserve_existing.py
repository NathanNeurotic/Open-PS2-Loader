"""Execute sysCheckVMC() with a fake existing card: resizing must not delete saves."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/system.c").read_text(encoding="utf-8")
start = source.index("int sysCheckVMCEx(")
brace = source.index("{", start)
depth = 0
end = brace
while end < len(source):
    depth += (source[end] == "{") - (source[end] == "}")
    end += 1
    if depth == 0:
        break
assert depth == 0
function = source[start:end] + "\n" + source[source.index("int sysCheckVMC("):].split("\n}\n", 1)[0] + "\n}\n"
ui = (root / "src/guigame.c").read_text(encoding="utf-8")
assert "createResult == SYS_VMC_REPLACE_REQUIRES_DELETE" in ui
assert "_STR_VMC_REPLACE_REQUIRES_DELETE" in ui

program = r'''
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <assert.h>
#include <errno.h>
#define O_RDONLY 1
#define SEEK_END 2
#define SEEK_SET 0
#define S_IRUSR 0
#define S_IWUSR 0
#define S_IXUSR 0
#define S_IRGRP 0
#define S_IWGRP 0
#define S_IXGRP 0
#define S_IROTH 0
#define S_IWOTH 0
#define S_IXOTH 0
#define SYS_VMC_REPLACE_REQUIRES_DELETE (-2)
#define SYS_VMC_CREATE_FAILED (-3)
#define LOG(...) ((void)0)
typedef struct {
    char magic[32];
    int mc_type, mc_flag, page_size, pages_per_block, pages_per_cluster, clusters_per_card;
} vmc_superblock_t;
typedef struct {
    char VMC_filename[1024];
    int VMC_size_mb, VMC_blocksize, VMC_thread_priority, VMC_flags, VMC_card_slot;
} createVMCparam_t;
static char gVMCCreatePath[256] = {0};
static int exists, length, opened, erased, jobs, returnsError;
static int openError, badHeader, shortHeader;
static int dirOpenError, dirReadError, dirPosition;
typedef struct {char name[256];} iox_dirent_t;
static int fileXioDopen(const char *folder) {
    assert(!strcmp(folder,"mass0:/VMC"));dirPosition=0;
    return dirOpenError ? -1 : 4;
}
static int fileXioDread(int fd, iox_dirent_t *entry) {
    (void)fd;
    if (dirReadError) return -1;
    if (dirPosition++==0) {strcpy(entry->name,"unrelated.bin");return 1;}
    if (exists && dirPosition==2) {strcpy(entry->name,"save_0.BIN");return 1;}
    return 0;
}
static int fileXioDclose(int fd) {(void)fd;return 0;}
static int fake_open(const char *path, int flags, ...) {
    (void)path; (void)flags; opened++;
    if (openError) {errno=openError;return -1;}
    if (exists) return 3;
    errno=ENOENT;return -1;
}
static int fake_lseek(int fd, int offset, int whence) {
    (void)fd; (void)offset; return whence == SEEK_END ? length : 0;
}
static int fake_read(int fd, void *buf, int count) {
    (void)fd; memset(buf, 0, count);
    if (!badHeader) {
        vmc_superblock_t *sb = buf;
        memcpy(sb->magic, "Sony PS2 Memory Card Format", 27);
        sb->mc_type=2; sb->page_size=512; sb->pages_per_cluster=2;
        sb->clusters_per_card=length/1024;
    }
    return shortHeader ? count-1 : count;
}
static int fake_close(int fd) { (void)fd; return 0; }
static int fake_unlink(const char *path) { (void)path; erased++; return 0; }
static int fake_devctl(const char *path, int command, void *args, int alen, void *buf, int blen) {
    (void)path; (void)command; (void)args; (void)alen; (void)buf; (void)blen;
    jobs++; return returnsError ? -1 : 0;
}
#define open fake_open
#define lseek fake_lseek
#define read fake_read
#define close fake_close
#define unlink fake_unlink
#define fileXioDevctl fake_devctl
@FUNCTION@
int main(void) {
    char name[] = "SAVE_0";
    exists = 1; length = 8 * 1048576;
    char prefix[243];
    memset(prefix, 'p', 241); prefix[241] = 0;
    assert(sysCheckVMC(prefix, "/", name, 0, NULL) == 8); // 255 characters fit
    int priorOpened = opened;
    prefix[241] = 'p'; prefix[242] = 0;
    strcpy(gVMCCreatePath, "stale");
    assert(sysCheckVMC(prefix, "/", name, 8, NULL) == SYS_VMC_CREATE_FAILED);
    assert(!gVMCCreatePath[0]);
    assert(sysCheckVMC(prefix, "/", name, 0, NULL) == SYS_VMC_CREATE_FAILED);
    assert(sysCheckVMC(prefix, "/", name, -1, NULL) == SYS_VMC_CREATE_FAILED);
    assert(opened == priorOpened && erased == 0 && jobs == 0);
    assert(sysCheckVMC("mass0:/", "/", name, 16, NULL) == SYS_VMC_REPLACE_REQUIRES_DELETE);
    assert(erased == 0 && jobs == 0);
    const int errors[] = {EACCES, EIO, ENOTDIR};
    for (unsigned i=0;i<sizeof(errors)/sizeof(errors[0]);i++) {
        openError=errors[i];
        assert(sysCheckVMC("mass0:/", "/", name, 8, NULL) == SYS_VMC_CREATE_FAILED);
        assert(erased==0 && jobs==0 && !gVMCCreatePath[0]);
    }
    openError=0;
    assert(sysCheckVMC("mass0:/", "/", name, 8, NULL) == 8 && jobs == 0);
    // A failed format can leave a full-size zero image, including after restart or failed cleanup.
    badHeader=1;
    assert(sysCheckVMC("mass0:/", "/", name, 0, NULL) == SYS_VMC_CREATE_FAILED);
    assert(sysCheckVMC("mass0:/", "/", name, 8, NULL) == SYS_VMC_REPLACE_REQUIRES_DELETE);
    assert(erased==0 && jobs==0);
    badHeader=0;shortHeader=1;
    assert(sysCheckVMC("mass0:/", "/", name, 0, NULL) == SYS_VMC_CREATE_FAILED);
    shortHeader=0;
    length = 123; // corrupted or unrecognized size is still someone's data
    assert(sysCheckVMC("mass0:/", "/", name, 8, NULL) == SYS_VMC_REPLACE_REQUIRES_DELETE);
    assert(erased == 0 && jobs == 0);
    exists = 0;
    dirOpenError=1;
    assert(sysCheckVMC("mass0:/", "/", name, 8, NULL) == SYS_VMC_CREATE_FAILED);
    dirOpenError=0;dirReadError=1;
    assert(sysCheckVMC("mass0:/", "/", name, 8, NULL) == SYS_VMC_CREATE_FAILED);
    assert(jobs==0 && erased==0);
    dirReadError=0;openError=4; // FatFs FR_NO_FILE, not POSIX ENOENT
    assert(sysCheckVMC("mass0:/", "/", name, 8, NULL) == -1 && jobs==1);
    openError=0;jobs=0;
    assert(sysCheckVMC("mass0:/", "/", name, 8, NULL) == -1 && jobs == 1);
    assert(erased == 0);
    returnsError=1;
    assert(sysCheckVMC("mass0:/", "/", name, 8, NULL) == SYS_VMC_CREATE_FAILED);
    assert(jobs==2 && erased==0 && !gVMCCreatePath[0]);
    returnsError=0;
    assert(sysCheckVMC("mass0:/", "/", name, -1, NULL) == -1 && erased == 1);
    puts("PASS: VMC size changes preserve the existing card; only explicit Delete removes");
    return 0;
}
'''.replace("@FUNCTION@", function)
with tempfile.TemporaryDirectory() as d:
    src = Path(d) / "test.c"
    out = Path(d) / "test"
    src.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Wno-unused-parameter", "-Werror",
                    str(src), "-o", str(out)], check=True)
    subprocess.run([str(out)], check=True, timeout=10)
