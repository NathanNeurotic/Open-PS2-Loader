// RiptOPLite's device mask (include/riptlite.h). A full build compiles this to three empty functions.
#include "include/opl.h"
#include "include/riptlite.h"
#include "include/iosupport.h"
#include "include/gui.h"        // gNetworkProtocol
#include "include/bdmsupport.h" // gNetBootProtocol, NET_BOOT_*
#include "include/config.h"

#include <string.h>

#ifdef RIPTOPLITE

// The keys whose value this build forces. The file keeps the full build's values for them: they are
// read here when the file is read and written back over whatever the lite build set before it is
// saved, so running a lite build never changes which sources the full one uses.
static const char *const kDeviceKeys[] = {
    CONFIG_OPL_DEFAULT_DEVICE,
    CONFIG_OPL_BDM_MODE,
    CONFIG_OPL_HDD_MODE,
    CONFIG_OPL_ETH_MODE,
    CONFIG_OPL_MMCE_MODE,
    CONFIG_OPL_ENABLE_USB,
    CONFIG_OPL_ENABLE_ILINK,
    CONFIG_OPL_ENABLE_MX4SIO,
    CONFIG_OPL_ENABLE_PCCF,
#if !LITE_HAS_DVR
    CONFIG_OPL_ENABLE_DVR, // the HDD build keeps the user's own choice
#endif
    CONFIG_OPL_ENABLE_BDMHDD,
    CONFIG_OPL_ENABLE_UDPBD,
    CONFIG_OPL_NETWORK_PROTOCOL,
    CONFIG_OPL_NET_START_MODE,
    CONFIG_OPL_NET_PROTOCOL_PICK,
    CONFIG_OPL_NET_BOOT_PROTOCOL,
};
#define kDeviceKeyCount (sizeof(kDeviceKeys) / sizeof(kDeviceKeys[0]))

// The file's text for each key; present[i] == 0 when the file did not have it.
static char gRemembered[kDeviceKeyCount][16];
static unsigned char gPresent[kDeviceKeyCount];

void liteApplyDeviceMask(void)
{
    gEnableUSB = LITE_HAS_USB;
    gEnableMX4SIO = LITE_HAS_MX4SIO;
    gEnableILK = LITE_HAS_ILINK;
    gEnableBdmHDD = LITE_HAS_BDMHDD;
    gEnablePCCF = 0;
#if !LITE_HAS_DVR
    gEnableDVR = 0;
#endif

    // The one source starts at boot: there is nothing else to choose between.
#if LITE_HAS_BDM
    gBDMStartMode = START_MODE_AUTO;
#else
    gBDMStartMode = START_MODE_DISABLED;
#endif
    gHDDStartMode = LITE_HAS_APA ? START_MODE_AUTO : START_MODE_DISABLED;
    gMMCEStartMode = LITE_HAS_MMCE_GAMES ? START_MODE_AUTO : START_MODE_DISABLED;

    // The network: this build's protocol, or none.
#if LITE_HAS_SMB
    gNetworkProtocol = NET_PROTO_SMB;
#elif LITE_HAS_UDPBD
    gNetworkProtocol = NET_PROTO_UDPBD;
#elif LITE_HAS_UDPFS
    gNetworkProtocol = gUdpfsAccessMode ? NET_PROTO_UDPFSBD : NET_PROTO_UDPFS;
#else
    gNetworkProtocol = NET_PROTO_OFF;
#endif
    if (gNetworkProtocol == NET_PROTO_OFF) {
        gNetStartMode = START_MODE_DISABLED;
        gNetProtocolPick = NET_PROTO_SMB; // the shipped default: never a protocol this build lacks
    } else {
        gNetStartMode = START_MODE_AUTO;
        gNetProtocolPick = gNetworkProtocol;
    }
    // The legacy shadows, derived as settingsio.cpp derives them.
    gEnableUDPBD = (gNetworkProtocol == NET_PROTO_UDPBD || gNetworkProtocol == NET_PROTO_UDPFSBD);
    gNetBootProtocol = (gNetworkProtocol == NET_PROTO_UDPFSBD) ? NET_BOOT_UDPFS : NET_BOOT_UDPBD;
    gETHStartMode = (gNetworkProtocol == NET_PROTO_SMB) ? gNetStartMode : START_MODE_DISABLED;

    // Open on this build's page. Apps and Favourites stay a valid choice. A network page is
    // reached through ETH_MODE whatever the protocol (opl.cpp deferredInit).
    if (gDefaultDevice != APP_MODE && gDefaultDevice != FAV_MODE) {
#if LITE_HAS_APA
        gDefaultDevice = HDD_MODE;
#elif LITE_HAS_MMCE_GAMES
        gDefaultDevice = MMCE_MODE;
#elif LITE_HAS_NET_SOURCE
        gDefaultDevice = ETH_MODE;
#else
        gDefaultDevice = BDM_MODE;
#endif
    }
}

void liteRememberDeviceKeys(config_set_t *configOPL)
{
    unsigned i;
    for (i = 0; i < kDeviceKeyCount; i++) {
        const char *value = NULL;
        gPresent[i] = configOPL != NULL && configGetStr(configOPL, kDeviceKeys[i], &value) && value != NULL &&
                      strlen(value) < sizeof(gRemembered[i]);
        if (gPresent[i])
            strcpy(gRemembered[i], value);
    }
}

void liteRestoreDeviceKeys(config_set_t *configOPL)
{
    if (configOPL == NULL)
        return;
    unsigned i;
    for (i = 0; i < kDeviceKeyCount; i++) {
        if (gPresent[i])
            configSetStr(configOPL, kDeviceKeys[i], gRemembered[i]);
        else
            configRemoveKey(configOPL, kDeviceKeys[i]);
    }
}

#else // full build

void liteApplyDeviceMask(void)
{
}

void liteRememberDeviceKeys(config_set_t *configOPL)
{
    (void)configOPL;
}

void liteRestoreDeviceKeys(config_set_t *configOPL)
{
    (void)configOPL;
}

#endif
