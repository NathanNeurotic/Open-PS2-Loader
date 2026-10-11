"""Exercise the production UDPFS operation wrappers with two IOP callers modeled by threads."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "modules/network/udpfs_ioman/src/udpfs_ioman.c").read_text()

def function(signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]

wrappers = source[source.index("#define UDPFS_LOCKED"):source.index("#undef UDPFS_LOCKED")]
entries = re.findall(r"UDPFS_LOCKED\((int|s64), (\w+), (\([^\n]*?\)), (\([^\n]*?\))\)", wrappers)
assert len(entries) == 14
table = source[source.index("static iomanX_iop_device_ops_t udpfs_device_ops"):]
for _, name, _, _ in entries:
    assert name + "_locked" in table, name
watchdog = function("static int udpfs_watchdog(")
assert watchdog.index("WaitSema") < watchdog.index("udpfs_core_init") < watchdog.index("SignalSema")
deinit = function("static int udpfs_deinit_dev(")
assert deinit.index("WaitSema") < deinit.index("TerminateThread") < deinit.index("udpfs_core_exit") < deinit.index("DeleteSema")

prefix = r'''
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
typedef int64_t s64;
typedef struct { int unused; } iomanX_iop_file_t;
typedef struct { int unused; } iox_dirent_t;
typedef struct { int unused; } iox_stat_t;
#define M_DEBUG(...) ((void)0)
static int g_udpfs_sema = 1;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t state = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static int active, maximum, first_entered, release_first, second_attempted, fail_wait;
static s64 answer = 0x100000001LL;
static int WaitSema(int id) {
    (void)id;
    if (fail_wait) return -7;
    return pthread_mutex_lock(&mutex);
}
static int SignalSema(int id) { (void)id; return pthread_mutex_unlock(&mutex); }
static s64 operation(void) {
    pthread_mutex_lock(&state);
    active++;
    if (active > maximum) maximum = active;
    if (!first_entered) {
        first_entered = 1;
        pthread_cond_broadcast(&changed);
        while (!release_first) pthread_cond_wait(&changed, &state);
    }
    active--;
    pthread_mutex_unlock(&state);
    return answer;
}
'''
stubs = []
for result, name, params, _ in entries:
    if name in ("udpfs_lseek", "udpfs_dclose"):
        continue
    stubs.append(f"static {result} {name}{params} {{ return ({result})operation(); }}")
aliases = function("static int udpfs_lseek(") + "\n" + function("static int udpfs_dclose(")
main = r'''
static void *first(void *arg) {
    (void)arg;
    assert(udpfs_read_locked(NULL, NULL, 1) == 1);
    return NULL;
}
static void *second(void *arg) {
    (void)arg;
    assert(pthread_mutex_trylock(&mutex) != 0); /* first read owns the transport */
    pthread_mutex_lock(&state);
    second_attempted = 1;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&state);
    assert(udpfs_open_locked(NULL, "neutrino.elf", 1, 0) == 1);
    return NULL;
}
int main(void) {
    pthread_t a, b;
    pthread_create(&a, NULL, first, NULL);
    pthread_mutex_lock(&state);
    while (!first_entered) pthread_cond_wait(&changed, &state);
    pthread_mutex_unlock(&state);
    pthread_create(&b, NULL, second, NULL);
    pthread_mutex_lock(&state);
    while (!second_attempted) pthread_cond_wait(&changed, &state);
    release_first = 1;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&state);
    pthread_join(a, NULL);
    pthread_join(b, NULL);
    assert(maximum == 1);
    assert(udpfs_lseek64_locked(NULL, 0x100000001LL, 0) == 0x100000001LL);
    assert(udpfs_lseek_locked(NULL, 1, 0) == 1);
    assert(udpfs_dclose_locked(NULL) == 1);
    answer = -5;
    assert(udpfs_read_locked(NULL, NULL, 1) == -5);
    answer = 9;
    assert(udpfs_read_locked(NULL, NULL, 1) == 9); /* error released lock */
    fail_wait = 1;
    assert(udpfs_read_locked(NULL, NULL, 1) == -7);
    puts("PASS: UDPFS overlapping callers, nested aliases, 64-bit seek and error unlock");
    return 0;
}
'''
temp_root = ROOT / "build/test-tmp"
temp_root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
    path = Path(tmp)
    (path / "test.c").write_text("\n".join([prefix, *stubs, aliases, wrappers, main]))
    binary = path / "test.exe"
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Wno-unused-parameter",
                    "-Wno-unused-function", "-Werror", "-pthread", str(path / "test.c"),
                    "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)
