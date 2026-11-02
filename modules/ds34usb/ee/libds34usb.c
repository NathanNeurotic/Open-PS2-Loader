#include <kernel.h>
#include <sifrpc.h>
#include <string.h>
#include <time.h>

#define DS34USB_INIT         1
#define DS34USB_GET_STATUS   2
#define DS34USB_GET_BDADDR   3
#define DS34USB_SET_BDADDR   4
#define DS34USB_SET_RUMBLE   5
#define DS34USB_SET_LED      6
#define DS34USB_GET_DATA     7
#define DS34USB_RESET        8
#define DS34USB_GET_RAW      9  // RIPPS2 build 129: Set Up A USB Pad
#define DS34USB_SET_PROFILES 10 // RIPPS2 build 129: the .pad block

#define DS34USB_BIND_RPC_ID 0x18E3878E

static SifRpcClientData_t ds34usb;

static u8 rpcbuf[256] __attribute__((aligned(64))); // build 129: 4 + the .pad block (180), or 8 + a report (64)

static u8 ds34usb_inited = 0;

int ds34usb_init()
{
    // Bounded: a module that failed to link never registers its server, and an endless bind here
    // stops the boot before the first frame (a black screen). Without the server the pad driver
    // stays off and every other call here is a no-op.
    clock_t start = clock(); // elapsed, not a deadline: clock() can wrap

    ds34usb.server = NULL;

    do {
        if (clock() - start > 3 * CLOCKS_PER_SEC)
            return 0;
        if (SifBindRpc(&ds34usb, DS34USB_BIND_RPC_ID, 0) < 0)
            return 0;

        nopdelay();
    } while (!ds34usb.server);

    ds34usb_inited = 1;

    return 1;
}

int ds34usb_deinit()
{
    ds34usb_inited = 0;
    return 1;
}

int ds34usb_reinit_ports(u8 ports)
{
    if (!ds34usb_inited)
        return 0;

    rpcbuf[0] = ports;
    return (SifCallRpc(&ds34usb, DS34USB_INIT, 0, rpcbuf, 1, NULL, 0, NULL, NULL) == 0);
}

int ds34usb_get_status(int port)
{
    if (!ds34usb_inited)
        return 0;

    rpcbuf[0] = port;

    if (SifCallRpc(&ds34usb, DS34USB_GET_STATUS, 0, rpcbuf, 1, rpcbuf, 1, NULL, NULL) == 0)
        return rpcbuf[0];

    return 0;
}

int ds34usb_get_bdaddr(int port, u8 *bdaddr)
{
    int i, ret;

    if (!ds34usb_inited)
        return 0;

    rpcbuf[0] = port;

    ret = (SifCallRpc(&ds34usb, DS34USB_GET_BDADDR, 0, rpcbuf, 1, rpcbuf, 7, NULL, NULL) == 0);

    ret &= rpcbuf[0];

    for (i = 0; i < 6; i++)
        bdaddr[i] = rpcbuf[i + 1];

    return ret;
}

int ds34usb_set_bdaddr(int port, u8 *bdaddr)
{
    int i;

    if (!ds34usb_inited)
        return 0;

    rpcbuf[0] = port;

    for (i = 0; i < 6; i++)
        rpcbuf[i + 1] = bdaddr[i];

    return (SifCallRpc(&ds34usb, DS34USB_SET_BDADDR, 0, rpcbuf, 7, NULL, 0, NULL, NULL) == 0);
}

int ds34usb_set_rumble(int port, u8 lrum, u8 rrum)
{
    if (!ds34usb_inited)
        return 0;

    rpcbuf[0] = port;
    rpcbuf[1] = lrum;
    rpcbuf[2] = rrum;

    return (SifCallRpc(&ds34usb, DS34USB_SET_RUMBLE, 0, rpcbuf, 3, NULL, 0, NULL, NULL) == 0);
}

int ds34usb_set_led(int port, u8 led)
{
    if (!ds34usb_inited)
        return 0;

    rpcbuf[0] = port;
    rpcbuf[1] = led;

    return (SifCallRpc(&ds34usb, DS34USB_SET_LED, 0, rpcbuf, 2, NULL, 0, NULL, NULL) == 0);
}

int ds34usb_get_data(int port, u8 *data)
{
    int ret;

    if (!ds34usb_inited)
        return 0;

    rpcbuf[0] = port;

    ret = (SifCallRpc(&ds34usb, DS34USB_GET_DATA, 0, rpcbuf, 1, rpcbuf, 18, NULL, NULL) == 0);

    memcpy(data, rpcbuf, 18);

    return ret;
}

int ds34usb_reset()
{
    if (!ds34usb_inited)
        return 0;

    return (SifCallRpc(&ds34usb, DS34USB_RESET, 0, NULL, 0, NULL, 0, NULL, NULL) == 0);
}

// RIPPS2 build 129: the .pad block (PAD_BLOCK_SIZE bytes; NULL: none) for the menu, and Set Up A USB Pad's switch: while
// learn is 1 a HID pad with no profile is taken too, so its reports can be read
int ds34usb_set_profiles(const u8 *block, int size, int learn)
{
    if (!ds34usb_inited || size < 0 || size > (int)sizeof(rpcbuf) - 4)
        return 0;

    memset(rpcbuf, 0, 4 + size);
    rpcbuf[0] = learn;
    if (block != NULL)
        memcpy(rpcbuf + 4, block, size);

    return (SifCallRpc(&ds34usb, DS34USB_SET_PROFILES, 0, rpcbuf, 4 + size, NULL, 0, NULL, NULL) == 0);
}

// RIPPS2 build 129: a port's state and its last report as it came (out: 8 + 64 bytes, see the IRX's ds34usb_get_raw)
int ds34usb_get_raw(int port, u8 *out)
{
    int ret;

    if (!ds34usb_inited)
        return 0;

    rpcbuf[0] = port;
    ret = (SifCallRpc(&ds34usb, DS34USB_GET_RAW, 0, rpcbuf, 1, rpcbuf, 72, NULL, NULL) == 0);
    memcpy(out, rpcbuf, 72);

    return ret;
}
