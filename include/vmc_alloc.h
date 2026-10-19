/* Private, versioned RiptOPL BDM allocation contract. Shared by EE/IOP/driver.
 * Success is a positive magic value; an unsupported ioctl returning zero fails.
 */
#ifndef VMC_ALLOC_H
#define VMC_ALLOC_H
#define VMC_ALLOC_CAPS        0x564D4300
#define VMC_ALLOC_RESERVE     0x564D4301
#define VMC_ALLOC_VERIFY      0x564D4302
#define VMC_ALLOC_V1          0x564D0101
#define VMC_CREATE_CONTIGUOUS 1
typedef struct
{
    unsigned int version;
    unsigned int bytes;
} vmc_alloc_request_t;
#endif
