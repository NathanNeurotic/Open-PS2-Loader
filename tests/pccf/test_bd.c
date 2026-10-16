#include <assert.h>
#include <stdio.h>
#define GAME_DRIVER
#define _start cf_module_start
#include "../../modules/pccf/main.c"
#undef _start
static int locks, calls, fail_at, present = 1, stopped;
static unsigned int counts[8], addresses[8];
int CreateSema(iop_sema_t *s)
{
    assert(s->initial == 1 && s->max == 1);
    return 3;
}
int DeleteSema(int s)
{
    (void)s;
    return 0;
}
int WaitSema(int s)
{
    assert(s == 3 && !locks);
    locks = 1;
    return 0;
}
int SignalSema(int s)
{
    assert(s == 3 && locks);
    locks = 0;
    return 0;
}
int DelayThread(unsigned int n)
{
    (void)n;
    return 0;
}
void bdm_connect_bd(struct block_device *b) { (void)b; }
int pccf_hw_start(pccf_ata_t *a)
{
    (void)a;
    return -1;
}
int pccf_hw_present(void) { return present; }
void pccf_hw_stop(void)
{
    assert(locks);
    ++stopped;
}
int pccf_ata_read(pccf_ata_t *a, unsigned int l, unsigned int n, unsigned char *b)
{
    unsigned int i;
    assert(locks && a->ready && n && n <= 64);
    counts[calls] = n;
    addresses[calls] = l;
    ++calls;
    if (calls == fail_at) {
        a->ready = 0;
        return -1;
    }
    for (i = 0; i < n * 512; ++i)
        b[i] = (l + i / 512) & 255;
    return 0;
}
int main(void)
{
    char *owned[] = {"pccf_game", "owned"};
    char *foreign[] = {"pccf_game", "foreign"};
    assert(pccf_owned_handoff(2, owned));
    assert(!pccf_owned_handoff(1, owned) && !pccf_owned_handoff(2, foreign));

    static unsigned char buf[130 * 512 + 2];
    unsigned int i;
    io_lock = 3;
    ata.ready = 1;
    ata.sectors = 10000;
    memset(buf, 0xa5, sizeof(buf));
    assert(cf_read(&device, 100, buf + 1, 130) == 130 && calls == 3 && !locks);
    assert(counts[0] == 64 && counts[1] == 64 && counts[2] == 2);
    assert(addresses[0] == 100 && addresses[1] == 164 && addresses[2] == 228);
    for (i = 0; i < 130 * 512; ++i)
        assert(buf[i + 1] == ((100 + i / 512) & 255));
    assert(buf[0] == 0xa5 && buf[sizeof(buf) - 1] == 0xa5);
    assert(cf_read(&device, ((u64)1 << 32) + 100, buf, 1) < 0 && calls == 3);
    assert(cf_read(&device, 9999, buf, 2) < 0 && cf_read(&device, 0, NULL, 1) < 0);
    assert(cf_read(&device, 0, buf, 0) < 0 && calls == 3);
    assert(cf_write(&device, 0, buf, 1) == -EROFS && calls == 3);
    calls = 0;
    fail_at = 2;
    assert(cf_read(&device, 100, buf, 130) < 0 && calls == 2 && !ata.ready && !locks);
    assert(cf_read(&device, 100, buf, 1) < 0 && calls == 2);
    ata.ready = 1;
    present = 0;
    assert(cf_read(&device, 100, buf, 1) < 0 && !ata.ready && calls == 2);
    assert(cf_stop(&device) == 0 && stopped == 1 && !locks);
    puts("PASS CF BDM: 64-sector splitting, order/unaligned buffer/guards, 64-bit bounds, read-only, removal, offline latch, serialized stop");
}
