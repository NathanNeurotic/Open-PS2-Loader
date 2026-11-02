
enum eDS34USBStatus {
    DS34USB_STATE_DISCONNECTED = 0x00,
    DS34USB_STATE_AUTHORIZED = 0x01,
    DS34USB_STATE_CONFIGURED = 0x02,
    DS34USB_STATE_CONNECTED = 0x04,
    DS34USB_STATE_RUNNING = 0x08,
};

int ds34usb_init();
int ds34usb_deinit();
int ds34usb_reinit_ports(u8 ports);
int ds34usb_get_status(int port);
int ds34usb_get_bdaddr(int port, u8 *bdaddr);
int ds34usb_set_bdaddr(int port, u8 *bdaddr);
int ds34usb_set_rumble(int port, u8 lrum, u8 rrum);
int ds34usb_set_led(int port, u8 led);
int ds34usb_get_data(int port, u8 *data);
int ds34usb_reset();
int ds34usb_set_profiles(const u8 *block, int size, int learn); // RIPPS2 build 129: .pad
int ds34usb_get_raw(int port, u8 *out);                         // RIPPS2 build 129: DS34USB_RAW_SIZE bytes

// RIPPS2 build 129: ds34usb_get_raw's reply is 8 bytes of a port's state, then its last report (the IRX's
// MAX_BUFFER_SIZE, 64 bytes). Byte 1 is the port's type: DS34USB_TYPE_GENERIC (the IRX's GENERIC) for a HID pad that
// a .pad profile drives, or none yet. The IRX's iop/ds34usb.h holds both values; test_ripps2_pad129.py checks they match
#define DS34USB_RAW_SIZE     72
#define DS34USB_TYPE_GENERIC 4
