/*
 Copyright 2010, Volca
 Licenced under Academic Free License version 3.0
 Review OpenUsbLd README & LICENSE files for further details.
 */

#include "include/opl.h"
#include "include/gui.h"
#include "include/renderman.h"
#include "include/menusys.h"
#include "include/fntsys.h"
#include "include/ioman.h"
#include "include/lang.h"
#include "include/themes.h"
#include "include/pad.h"
#include "include/util.h"
#include "include/config.h"
#include "include/system.h"
#include "include/vcdsupport.h" // BDMA equip (vcdEquipBdma/vcdReadBdmaMode + VCD_BDMA_* enums)
#include "include/ethsupport.h"
#include "include/favsupport.h"
#include "include/compatupd.h"
#include "include/pggsm.h"
#include "include/cheatman.h"
#include "include/sound.h"
#include "include/guigame.h"
#include "include/texcache.h"

#include <limits.h>
#include <stdlib.h>
#include <libvux.h>

// Last Played Auto Start
#include <time.h>

static int gScheduledOps;
static int gCompletedOps;
static int gTerminate;
static int gInitComplete;

static gui_callback_t gFrameHook;

static s32 gSemaId;
static s32 gGUILockSemaId;
static ee_sema_t gQueueSema;

static int screenWidth;
static int screenHeight;

static int showPartPopup = 0;
static int showThmPopup;
static int showLngPopup;

static clock_t popupTimer;

// forward decl.
static void guiShow();

#ifdef __DEBUG

// debug version displays an FPS meter
static clock_t prevtime = 0;
static clock_t curtime = 0;
static float fps = 0.0f;

extern GSGLOBAL *gsGlobal;
#endif

// Global data
int guiInactiveFrames;
int guiFrameId;

struct gui_update_list_t
{
    struct gui_update_t *item;
    struct gui_update_list_t *next;
};

struct gui_update_list_t *gUpdateList;
struct gui_update_list_t *gUpdateEnd;

typedef struct
{
    void (*handleInput)(void);
    void (*renderScreen)(void);
    short inMenu;
} gui_screen_handler_t;

static gui_screen_handler_t screenHandlers[] = {{&menuHandleInputMain, &menuRenderMain, 0},
                                                {&menuHandleInputMenu, &menuRenderMenu, 1},
                                                {&menuHandleInputInfo, &menuRenderInfo, 1},
                                                {&menuHandleInputGameMenu, &menuRenderGameMenu, 1},
                                                {&menuHandleInputAppMenu, &menuRenderAppMenu, 1}};

// default screen handler (menu screen)
static gui_screen_handler_t *screenHandler = &screenHandlers[GUI_SCREEN_MENU];

// screen transition handling
static gui_screen_handler_t *screenHandlerTarget = NULL;
static int transIndex;

// Helper perlin noise data
#define PLASMA_H              32
#define PLASMA_W              32
#define PLASMA_ROWS_PER_FRAME 6
#define FADE_SIZE             256

static GSTEXTURE gBackgroundTex;
static int pperm[512];
static float fadetbl[FADE_SIZE + 1];

static VU_VECTOR pgrad3[12] = {{1, 1, 0, 1}, {-1, 1, 0, 1}, {1, -1, 0, 1}, {-1, -1, 0, 1}, {1, 0, 1, 1}, {-1, 0, 1, 1}, {1, 0, -1, 1}, {-1, 0, -1, 1}, {0, 1, 1, 1}, {0, -1, 1, 1}, {0, 1, -1, 1}, {0, -1, -1, 1}};

void guiReloadScreenExtents()
{
    rmGetScreenExtents(&screenWidth, &screenHeight);
}

void guiInit(void)
{
    guiFrameId = 0;
    guiInactiveFrames = 0;

    gFrameHook = NULL;
    gTerminate = 0;
    gInitComplete = 0;
    gScheduledOps = 0;
    gCompletedOps = 0;

    gUpdateList = NULL;
    gUpdateEnd = NULL;

    gQueueSema.init_count = 1;
    gQueueSema.max_count = 1;
    gQueueSema.option = 0;

    gSemaId = CreateSema(&gQueueSema);
    gGUILockSemaId = CreateSema(&gQueueSema);

    guiReloadScreenExtents();

    // background texture - for perlin
    gBackgroundTex.Width = PLASMA_W;
    gBackgroundTex.Height = PLASMA_H;
    gBackgroundTex.Mem = memalign(128, PLASMA_W * PLASMA_H * 4);
    gBackgroundTex.PSM = GS_PSM_CT32;
    gBackgroundTex.Filter = GS_FILTER_LINEAR;
    gBackgroundTex.Vram = 0;
    gBackgroundTex.VramClut = 0;
    gBackgroundTex.Clut = NULL;
    gBackgroundTex.ClutStorageMode = GS_CLUT_STORAGE_CSM1;

    // Precalculate the values for the perlin noise plasma
    int i;
    for (i = 0; i < 256; ++i) {
        pperm[i] = rand() % 256;
        pperm[i + 256] = pperm[i];
    }

    for (i = 0; i <= FADE_SIZE; ++i) {
        float t = (float)(i) / FADE_SIZE;

        fadetbl[i] = t * t * t * (t * (t * 6.0f - 15.0f) + 10.0f);
    }
}

void guiEnd()
{
    if (gBackgroundTex.Mem)
        free(gBackgroundTex.Mem);

    DeleteSema(gSemaId);
    DeleteSema(gGUILockSemaId);
}

void guiLock(void)
{
    WaitSema(gGUILockSemaId);
}

void guiUnlock(void)
{
    SignalSema(gGUILockSemaId);
}

void guiStartFrame(void)
{
    guiLock();
    rmStartFrame();
    guiFrameId++;
}

void guiEndFrame(void)
{
    rmEndFrame();
#ifdef __DEBUG
    // Measure time directly after vsync
    prevtime = curtime;
    curtime = clock();
#endif
    guiUnlock();
}

void guiShowAbout()
{
    char OPLVersion[40];
    char OPLBuildDetails[40];

    snprintf(OPLVersion, sizeof(OPLVersion), "Open PS2 Loader %s", OPL_VERSION);
    diaSetLabel(diaAbout, ABOUT_TITLE, OPLVersion);

    snprintf(OPLBuildDetails, sizeof(OPLBuildDetails), "GSM %s"
                                                       " - UDMA+"
#ifdef __RTL
                                                       " - RTL"
#endif
#ifdef IGS
                                                       " - IGS %s"
#endif
#ifdef PADEMU
                                                       " - PADEMU"
#endif
             // Version numbers
             ,
             GSM_VERSION
#ifdef IGS
             ,
             IGS_VERSION
#endif
    );
    diaSetLabel(diaAbout, ABOUT_BUILD_DETAILS, OPLBuildDetails);

    diaExecuteDialog(diaAbout, -1, 1, NULL);
}

void guiCheckNotifications(int checkTheme, int checkLang)
{
    if (gEnableNotifications) {
        if (checkTheme) {
            // Only disk themes have a path to announce; built-ins (<OPL>, <Coverflow>) return
            // NULL from thmGetFilePath -> no popup (and no NULL deref in guiShowNotifications).
            if (thmGetFilePath(thmGetGuiValue()) != NULL)
                showThmPopup = 1;
        }

        if (checkLang) {
            if (lngGetGuiValue() != 0)
                showLngPopup = 1;
        }
    }
}

static void guiResetNotifications(void)
{
    showThmPopup = 0;
    showLngPopup = 0;
    popupTimer = 0;
}

static void guiRenderNotifications(char *string, int y)
{
    int x;

    x = screenWidth - rmUnScaleX(fntCalcDimensions(gTheme->fonts[0], string)) - 10;

    rmDrawRect(x - 10, y, screenWidth - x, MENU_ITEM_HEIGHT + 10, gColDarker);
    fntRenderString(gTheme->fonts[0], x - 5, y + 5, ALIGN_NONE, 0, 0, string, gTheme->textColor);
}

static void guiShowNotifications(void)
{
    char notification[128];
    char *col_pos;
    int y = 10;
    int yadd = 35;

    if (showPartPopup || showThmPopup || showLngPopup || showCfgPopup) {
        if (!popupTimer) {
            popupTimer = clock() + 5000 * (CLOCKS_PER_SEC / 1000);
            sfxPlay(SFX_MESSAGE);
        }

        if (showPartPopup) {
            col_pos = strchr(gOPLPart, ':');
            col_pos++;

            snprintf(notification, sizeof(notification), _l(_STR_PARTITION_NOTIFICATION), col_pos);
            guiRenderNotifications(notification, y);
            y += yadd;
        }

        if (showCfgPopup) {
            snprintf(notification, sizeof(notification), _l(_STR_CFG_NOTIFICATION), configGetDir());
            if ((col_pos = strchr(notification, ':')) != NULL)
                *(col_pos + 1) = '\0';

            guiRenderNotifications(notification, y);
            y += yadd;
        }

        if (showThmPopup) {
            snprintf(notification, sizeof(notification), _l(_STR_THM_NOTIFICATION), thmGetFilePath(thmGetGuiValue()));
            if ((col_pos = strchr(notification, ':')) != NULL)
                *(col_pos + 1) = '\0';

            guiRenderNotifications(notification, y);
            y += yadd;
        }

        if (showLngPopup) {
            snprintf(notification, sizeof(notification), _l(_STR_LNG_NOTIFICATION), lngGetFilePath(lngGetGuiValue()));
            if ((col_pos = strchr(notification, ':')) != NULL)
                *(col_pos + 1) = '\0';

            guiRenderNotifications(notification, y);
        }

        if (clock() >= popupTimer) {
            guiResetNotifications();
            showPartPopup = 0;
            showCfgPopup = 0;
        }
    }
}

static int guiNetCompatUpdRefresh(int modified)
{
    int result;
    unsigned int done, total;

    if ((result = oplGetUpdateGameCompatStatus(&done, &total)) == OPL_COMPAT_UPDATE_STAT_WIP) {
        diaSetInt(diaNetCompatUpdate, NETUPD_PROGRESS, (done == 0 || total == 0) ? 0 : (int)((float)done / total * 100.0f));
    }

    return result;
}

static void guiShowNetCompatUpdateResult(int result)
{
    switch (result) {
        case OPL_COMPAT_UPDATE_STAT_DONE:
            // Completed with no errors.
            guiMsgBox(_l(_STR_NET_UPDATE_DONE), 0, NULL);
            break;
        case OPL_COMPAT_UPDATE_STAT_ERROR:
            // Completed with errors.
            guiMsgBox(_l(_STR_NET_UPDATE_FAILED), 0, NULL);
            break;
        case OPL_COMPAT_UPDATE_STAT_CONN_ERROR:
            // Completed with errors.
            guiMsgBox(_l(_STR_NET_UPDATE_CONN_FAILED), 0, NULL);
            break;
        case OPL_COMPAT_UPDATE_STAT_ABORTED:
            // User-aborted.
            guiMsgBox(_l(_STR_NET_UPDATE_CANCELLED), 0, NULL);
            break;
    }
}

void guiShowNetCompatUpdate(void)
{
    int ret, UpdateAll;
    u8 done, started;
    void *UpdateFunction;

    diaSetVisible(diaNetCompatUpdate, NETUPD_BTN_START, 1);
    diaSetVisible(diaNetCompatUpdate, NETUPD_BTN_CANCEL, 0);
    diaSetVisible(diaNetCompatUpdate, NETUPD_PROGRESS_LBL, 0);
    diaSetVisible(diaNetCompatUpdate, NETUPD_PROGRESS_PERC_LBL, 0);
    diaSetVisible(diaNetCompatUpdate, NETUPD_PROGRESS, 0);
    diaSetInt(diaNetCompatUpdate, NETUPD_OPT_UPD_ALL, 0);
    diaSetEnabled(diaNetCompatUpdate, NETUPD_OPT_UPD_ALL, 1);

    done = 0;
    started = 0;
    UpdateFunction = NULL;
    while (!done) {
        ret = diaExecuteDialog(diaNetCompatUpdate, -1, 1, UpdateFunction);
        switch (ret) {
            case NETUPD_BTN_START:
                if (guiMsgBox(_l(_STR_CONFIRMATION_SETTINGS_UPDATE), 1, NULL)) {
                    guiRenderTextScreen(_l(_STR_PLEASE_WAIT));

                    if ((ret = ethLoadInitModules()) == 0) {
                        diaSetVisible(diaNetCompatUpdate, NETUPD_BTN_START, 0);
                        diaSetVisible(diaNetCompatUpdate, NETUPD_BTN_CANCEL, 1);
                        diaSetVisible(diaNetCompatUpdate, NETUPD_PROGRESS_LBL, 1);
                        diaSetVisible(diaNetCompatUpdate, NETUPD_PROGRESS_PERC_LBL, 1);
                        diaSetVisible(diaNetCompatUpdate, NETUPD_PROGRESS, 1);
                        diaSetEnabled(diaNetCompatUpdate, NETUPD_OPT_UPD_ALL, 0);

                        diaGetInt(diaNetCompatUpdate, NETUPD_OPT_UPD_ALL, &UpdateAll);
                        oplUpdateGameCompat(UpdateAll);
                        UpdateFunction = &guiNetCompatUpdRefresh;
                        started = 1;
                    } else {
                        ethDisplayErrorStatus();
                    }
                }
                break;
            case UIID_BTN_CANCEL: // If the user pressed the cancel button.
            case NETUPD_BTN_CANCEL:
                if (started) {
                    if (guiMsgBox(_l(_STR_CONFIRMATION_CANCEL_UPDATE), 1, NULL)) {
                        guiRenderTextScreen(_l(_STR_PLEASE_WAIT));
                        oplAbortUpdateGameCompat();
                        // The process truly ends when the UI callback gets the update from the worker thread that the process has ended.
                    }
                } else {
                    done = 1;
                    started = 0;
                }
                break;
            default:
                guiShowNetCompatUpdateResult(ret);
                done = 1;
                started = 0;
                UpdateFunction = NULL;
                break;
        }
    }
}

void guiShowNetCompatUpdateSingle(int id, item_list_t *support, config_set_t *configSet)
{
    int ConfigSource, result;

    ConfigSource = CONFIG_SOURCE_DEFAULT;
    configGetInt(configSet, CONFIG_ITEM_CONFIGSOURCE, &ConfigSource);

    if (guiMsgBox(_l(_STR_CONFIRMATION_SETTINGS_UPDATE), 1, NULL)) {
        guiRenderTextScreen(_l(_STR_PLEASE_WAIT));

        if ((ethLoadInitModules()) == 0) {
            if ((result = oplUpdateGameCompatSingle(id, support, configSet)) == OPL_COMPAT_UPDATE_STAT_DONE) {
                configSetInt(configSet, CONFIG_ITEM_CONFIGSOURCE, CONFIG_SOURCE_DLOAD);
            }
            guiShowNetCompatUpdateResult(result);
        } else {
            ethDisplayErrorStatus();
        }
    }
}

static int guiUpdater(int modified)
{
    int showAutoStartLast;

    if (modified) {
        diaGetInt(diaConfig, CFG_LASTPLAYED, &showAutoStartLast);
        diaSetVisible(diaConfig, CFG_LBL_AUTOSTARTLAST, showAutoStartLast);
        diaSetVisible(diaConfig, CFG_AUTOSTARTLAST, showAutoStartLast);
    }
    return 0;
}

int guiDeviceTypeToIoMode(int deviceType)
{
    // Translates an index into deviceNames into an IO mode index used internally.
    if (deviceType == 0)
        return BDM_MODE;
    else if (deviceType == 1)
        return ETH_MODE;
    else if (deviceType == 2)
        return HDD_MODE;
    else if (deviceType == 3)
        return APP_MODE;
    else
        return MMCE_MODE;
}

int guiIoModeToDeviceType(int ioMode)
{
    if (ioMode >= BDM_MODE && ioMode < ETH_MODE)
        return 0;
    if (ioMode == ETH_MODE)
        return 1;
    if (ioMode == HDD_MODE)
        return 2;
    if (ioMode == APP_MODE)
        return 3;
    if (ioMode == MMCE_MODE)
        return 4;

    return 0;
}

void guiShowConfig()
{
    diaSetInt(diaConfig, CFG_DEBUG, gEnableDebug);
    diaSetInt(diaConfig, CFG_PS2LOGO, gPS2Logo);
    diaSetString(diaConfig, CFG_EXITTO, gExitPath);
    diaSetString(diaConfig, CFG_NEUTRINO_ARGS, gNeutrinoArgs);
    diaSetString(diaConfig, CFG_POPSTARTER_PATH, gPopstarterPath);

    // BDMA (BDMAssault exFAT driver) equip. MODE reflects what's ACTUALLY on the card (read the
    // mc?:/POPSTARTER/ marker), so the menu is honest even if POPSLoader or a prior session set it.
    const char *bdmaSourceStrs[] = {_l(_STR_BDMA_SRC_USB), _l(_STR_BDMA_SRC_MX4SIO), _l(_STR_BDMA_SRC_MMCE), NULL};
    const char *bdmaModeStrs[] = {_l(_STR_BDMA_MODE_FAT32), _l(_STR_BDMA_MODE_USBEXFAT), _l(_STR_BDMA_MODE_MX4SIO), _l(_STR_BDMA_MODE_MMCE), NULL};
    gBdmaMode = vcdReadBdmaMode();
    diaSetEnum(diaConfig, CFG_BDMASOURCE, bdmaSourceStrs);
    diaSetEnum(diaConfig, CFG_BDMAMODE, bdmaModeStrs);
    diaSetInt(diaConfig, CFG_BDMASOURCE, gBdmaSource);
    diaSetInt(diaConfig, CFG_BDMAMODE, gBdmaMode);

    diaSetInt(diaConfig, CFG_ENWRITEOP, gEnableWrite);
    diaSetInt(diaConfig, CFG_LASTPLAYED, gRememberLastPlayed);
    diaSetInt(diaConfig, CFG_AUTOSTARTLAST, gAutoStartLastPlayed);
    diaSetVisible(diaConfig, CFG_AUTOSTARTLAST, gRememberLastPlayed);
    diaSetVisible(diaConfig, CFG_LBL_AUTOSTARTLAST, gRememberLastPlayed);

    int ret = diaExecuteDialog(diaConfig, -1, 1, &guiUpdater);
    if (ret) {
        diaGetInt(diaConfig, CFG_DEBUG, &gEnableDebug);
        diaGetInt(diaConfig, CFG_PS2LOGO, &gPS2Logo);
        diaGetString(diaConfig, CFG_EXITTO, gExitPath, sizeof(gExitPath));
        diaGetString(diaConfig, CFG_NEUTRINO_ARGS, gNeutrinoArgs, sizeof(gNeutrinoArgs));
        {
            // The dialog field is char[32]; only adopt the typed value if it actually changed, so
            // opening+saving General Settings never truncates a longer path stored via the cfg.
            char tmpPop[sizeof(gPopstarterPath)];
            diaGetString(diaConfig, CFG_POPSTARTER_PATH, tmpPop, sizeof(tmpPop));
            if (strncmp(tmpPop, gPopstarterPath, 31) != 0)
                snprintf(gPopstarterPath, sizeof(gPopstarterPath), "%s", tmpPop);
        }
        {
            // Equip BDMA modules only when SOURCE or MODE actually changed (the equip copies
            // files to the memory card). vcdEquipBdma is free-space-gated + truncation-safe, so a
            // failure never corrupts the card; report it and resync MODE to what's really equipped.
            int oldSrc = gBdmaSource, oldMode = gBdmaMode; // baselines (MODE = card's actual state)
            int newSrc = oldSrc, newMode = oldMode;
            diaGetInt(diaConfig, CFG_BDMASOURCE, &newSrc);
            diaGetInt(diaConfig, CFG_BDMAMODE, &newMode);
            if (newSrc != oldSrc || newMode != oldMode) {
                int er = vcdEquipBdma(newSrc, newMode);
                if (er == -4)
                    guiMsgBox(_l(_STR_BDMA_ERR_SRC), 0, NULL);
                else if (er == -2)
                    guiMsgBox(_l(_STR_BDMA_ERR_SPACE), 0, NULL);
                else if (er == -3)
                    guiMsgBox(_l(_STR_BDMA_ERR_IO), 0, NULL);
                gBdmaMode = vcdReadBdmaMode(); // MODE = what is now actually equipped
            }
            gBdmaSource = newSrc; // remember the source preference regardless of equip outcome
        }
        diaGetInt(diaConfig, CFG_ENWRITEOP, &gEnableWrite);
        diaGetInt(diaConfig, CFG_LASTPLAYED, &gRememberLastPlayed);
        diaGetInt(diaConfig, CFG_AUTOSTARTLAST, &gAutoStartLastPlayed);
        DisableCron = 1; // Disable Auto Start Last Played counter (we don't want to call it right after enable it on GUI)

        applyConfig(-1, -1, 0);
        menuReinitMainMenu();
    }
}

static int curTheme = -1;

static int guiUIUpdater(int modified)
{
    if (modified) {
        int temp, x, y;
        diaGetInt(diaUIConfig, UICFG_THEME, &temp);
        if (temp != curTheme) {
            curTheme = temp;
            if (temp == 0) {
                // Display the default theme's colours.
                diaSetItemType(diaUIConfig, UICFG_BGCOL, UI_COLOUR); // Must be correctly set before doing the diaS/GetColor !!
                diaSetItemType(diaUIConfig, UICFG_UICOL, UI_COLOUR);
                diaSetItemType(diaUIConfig, UICFG_TXTCOL, UI_COLOUR);
                diaSetItemType(diaUIConfig, UICFG_SELCOL, UI_COLOUR);
                diaSetColor(diaUIConfig, UICFG_BGCOL, gDefaultBgColor);
                diaSetColor(diaUIConfig, UICFG_UICOL, gDefaultUITextColor);
                diaSetColor(diaUIConfig, UICFG_TXTCOL, gDefaultTextColor);
                diaSetColor(diaUIConfig, UICFG_SELCOL, gDefaultSelTextColor);
            } else if (temp == thmGetGuiValue()) {
                // Display the current theme's colours.
                diaSetItemType(diaUIConfig, UICFG_BGCOL, UI_COLOUR);
                diaSetItemType(diaUIConfig, UICFG_UICOL, UI_COLOUR);
                diaSetItemType(diaUIConfig, UICFG_TXTCOL, UI_COLOUR);
                diaSetItemType(diaUIConfig, UICFG_SELCOL, UI_COLOUR);
                diaSetColor(diaUIConfig, UICFG_BGCOL, gTheme->bgColor);
                diaSetU64Color(diaUIConfig, UICFG_UICOL, gTheme->uiTextColor);
                diaSetU64Color(diaUIConfig, UICFG_TXTCOL, gTheme->textColor);
                diaSetU64Color(diaUIConfig, UICFG_SELCOL, gTheme->selTextColor);
            } else {
                // When another theme is highlighted in the list, its colours are not known. Don't show any colours.
                diaSetItemType(diaUIConfig, UICFG_BGCOL, UI_SPACER);
                diaSetItemType(diaUIConfig, UICFG_UICOL, UI_SPACER);
                diaSetItemType(diaUIConfig, UICFG_TXTCOL, UI_SPACER);
                diaSetItemType(diaUIConfig, UICFG_SELCOL, UI_SPACER);
            }

            // The user cannot adjust the current theme's colours.
            temp = !temp;
            diaSetEnabled(diaUIConfig, UICFG_BGCOL, temp);
            diaSetEnabled(diaUIConfig, UICFG_UICOL, temp);
            diaSetEnabled(diaUIConfig, UICFG_TXTCOL, temp);
            diaSetEnabled(diaUIConfig, UICFG_SELCOL, temp);
            diaSetEnabled(diaUIConfig, UICFG_RESETCOL, temp);
        }

        diaGetInt(diaUIConfig, UICFG_XOFF, &x);
        diaGetInt(diaUIConfig, UICFG_YOFF, &y);
        if ((x != gXOff) || (y != gYOff)) {
            gXOff = x;
            gYOff = y;
            rmSetDisplayOffset(x, y);
        }
        diaGetInt(diaUIConfig, UICFG_OVERSCAN, &temp);
        if (temp != gOverscan) {
            gOverscan = temp;
            rmSetOverscan(gOverscan);
            guiUpdateScreenScale();
        }
        diaGetInt(diaUIConfig, UICFG_WIDESCREEN, &temp);
        if (temp != gWideScreen) {
            gWideScreen = temp;
            rmSetAspectRatio((gWideScreen == 0) ? RM_ARATIO_4_3 : RM_ARATIO_16_9);
            guiUpdateScreenScale();
        }
    }

    return 0;
}

void guiShowUIConfig(void)
{
    int themeID = -1, langID = -1;
    curTheme = -1;
    showCfgPopup = 0;
    guiResetNotifications();

    // clang-format off
    const char *vmodeNames[] = {_l(_STR_AUTO)
        , "PAL 640x512i @50Hz 24bit"
        , "NTSC 640x448i @60Hz 24bit"
        , "EDTV 640x448p @60Hz 24bit"
        , "EDTV 640x512p @50Hz 24bit"
        , "VGA 640x480p @60Hz 24bit"
        , "PAL 704x576i @50Hz 24bit (HIRES)"
        , "NTSC 704x480i @60Hz 24bit (HIRES)"
        , "EDTV 704x480p @60Hz 24bit (HIRES)"
        , "EDTV 704x576p @50Hz 24bit (HIRES)"
        , "HDTV 1280x720p @60Hz 16bit (HIRES)"
        , "HDTV 1920x1080i @60Hz 16bit (HIRES)"
        , "PAL 640x256p @50Hz 24bit"
        , "NTSC 640x224p @60Hz 24bit"
        , NULL};
    // clang-format on
    int previousVMode;
    int previousTheme;

reselect_video_mode:
    previousVMode = gVMode;
    previousTheme = thmGetGuiValue();
    diaSetEnum(diaUIConfig, UICFG_THEME, (const char **)thmGetGuiList());
    diaSetEnum(diaUIConfig, UICFG_LANG, (const char **)lngGetGuiList());
    diaSetEnum(diaUIConfig, UICFG_VMODE, vmodeNames);
    diaSetInt(diaUIConfig, UICFG_THEME, thmGetGuiValue());
    diaSetInt(diaUIConfig, UICFG_LANG, lngGetGuiValue());
    diaSetInt(diaUIConfig, UICFG_AUTOSORT, gAutosort);
    diaSetInt(diaUIConfig, UICFG_AUTOREFRESH, gAutoRefresh);
    diaSetInt(diaUIConfig, UICFG_NOTIFICATIONS, gEnableNotifications);
    diaSetInt(diaUIConfig, UICFG_COVERART, gEnableArt);
    diaSetInt(diaUIConfig, UICFG_WIDESCREEN, gWideScreen);
    diaSetInt(diaUIConfig, UICFG_VMODE, gVMode);
    diaSetInt(diaUIConfig, UICFG_XOFF, gXOff);
    diaSetInt(diaUIConfig, UICFG_YOFF, gYOff);
    diaSetInt(diaUIConfig, UICFG_OVERSCAN, gOverscan);
    diaSetVisible(diaUIConfig, UICFG_COVERFLOW_BUTTON, gTheme->coverflow != NULL);
    guiUIUpdater(1);

    int ret = diaExecuteDialog(diaUIConfig, -1, 1, guiUIUpdater);
    if (ret) {
        diaGetInt(diaUIConfig, UICFG_LANG, &langID);
        diaGetInt(diaUIConfig, UICFG_THEME, &themeID);
        if (themeID == 0) {
            diaGetColor(diaUIConfig, UICFG_BGCOL, gDefaultBgColor);
            diaGetColor(diaUIConfig, UICFG_UICOL, gDefaultUITextColor);
            diaGetColor(diaUIConfig, UICFG_TXTCOL, gDefaultTextColor);
            diaGetColor(diaUIConfig, UICFG_SELCOL, gDefaultSelTextColor);
        }
        diaGetInt(diaUIConfig, UICFG_AUTOSORT, &gAutosort);
        diaGetInt(diaUIConfig, UICFG_AUTOREFRESH, &gAutoRefresh);
        diaGetInt(diaUIConfig, UICFG_NOTIFICATIONS, &gEnableNotifications);
        diaGetInt(diaUIConfig, UICFG_COVERART, &gEnableArt);
        diaGetInt(diaUIConfig, UICFG_WIDESCREEN, &gWideScreen);
        diaGetInt(diaUIConfig, UICFG_VMODE, &gVMode);
        diaGetInt(diaUIConfig, UICFG_XOFF, &gXOff);
        diaGetInt(diaUIConfig, UICFG_YOFF, &gYOff);
        diaGetInt(diaUIConfig, UICFG_OVERSCAN, &gOverscan);

        if (ret == UICFG_RESETCOL)
            setDefaultColors();

        if (previousTheme != themeID && isBgmPlaying())
            bgmStop();

        applyConfig(themeID, langID, 1);
        sfxInit(0);

        if (gEnableBGM && !isBgmPlaying())
            bgmStart();
    }

    if (ret == UICFG_COVERFLOW_BUTTON) {
        guiShowCoverflowConfig();
        goto reselect_video_mode;
    }

    if (previousVMode != gVMode) {
        if (guiConfirmVideoMode() == 0) {
            // Restore previous video mode, without changing the theme & language settings.
            gVMode = previousVMode;
            applyConfig(themeID, langID, 1);
            goto reselect_video_mode;
        }
    }
}

static int netConfigUpdater(int modified)
{
    int showAdvancedOptions, isNetBIOS, isDHCPEnabled, i;

    if (modified) {
        diaGetInt(diaNetConfig, NETCFG_SHOW_ADVANCED_OPTS, &showAdvancedOptions);

        diaGetInt(diaNetConfig, NETCFG_PS2_IP_ADDR_TYPE, &isDHCPEnabled);
        diaGetInt(diaNetConfig, NETCFG_SHARE_ADDR_TYPE, &isNetBIOS);
        diaSetVisible(diaNetConfig, NETCFG_SHARE_NB_ADDR, isNetBIOS);

        for (i = 0; i < 4; i++) {
            diaSetVisible(diaNetConfig, NETCFG_SHARE_IP_ADDR_0 + i, !isNetBIOS);

            diaSetEnabled(diaNetConfig, NETCFG_PS2_IP_ADDR_0 + i, !isDHCPEnabled);
            diaSetEnabled(diaNetConfig, NETCFG_PS2_NETMASK_0 + i, !isDHCPEnabled);
            diaSetEnabled(diaNetConfig, NETCFG_PS2_GATEWAY_0 + i, !isDHCPEnabled);
            diaSetEnabled(diaNetConfig, NETCFG_PS2_DNS_0 + i, !isDHCPEnabled);
        }

        for (i = 0; i < 3; i++)
            diaSetVisible(diaNetConfig, NETCFG_SHARE_IP_ADDR_DOT_0 + i, !isNetBIOS);

        diaSetEnabled(diaNetConfig, NETCFG_SHARE_PORT, showAdvancedOptions);
        diaSetEnabled(diaNetConfig, NETCFG_ETHOPMODE, showAdvancedOptions);
    }

    return 0;
}

void guiShowNetConfig(void)
{
    size_t i;
    const char *ethOpModes[] = {_l(_STR_AUTO), _l(_STR_ETH_100MFDX), _l(_STR_ETH_100MHDX), _l(_STR_ETH_10MFDX), _l(_STR_ETH_10MHDX), NULL};
    const char *addrConfModes[] = {_l(_STR_ADDR_TYPE_IP), _l(_STR_ADDR_TYPE_NETBIOS), NULL};
    const char *ipAddrConfModes[] = {_l(_STR_IP_ADDRESS_TYPE_STATIC), _l(_STR_IP_ADDRESS_TYPE_DHCP), NULL};
    diaSetEnum(diaNetConfig, NETCFG_PS2_IP_ADDR_TYPE, ipAddrConfModes);
    diaSetEnum(diaNetConfig, NETCFG_SHARE_ADDR_TYPE, addrConfModes);
    diaSetEnum(diaNetConfig, NETCFG_ETHOPMODE, ethOpModes);

    // upload current values
    diaSetInt(diaNetConfig, NETCFG_SHOW_ADVANCED_OPTS, 0);
    diaSetEnabled(diaNetConfig, NETCFG_ETHOPMODE, 0);
    diaSetEnabled(diaNetConfig, NETCFG_SHARE_PORT, 0);

    diaSetInt(diaNetConfig, NETCFG_PS2_IP_ADDR_TYPE, ps2_ip_use_dhcp);
    diaSetInt(diaNetConfig, NETCFG_SHARE_ADDR_TYPE, gPCShareAddressIsNetBIOS);
    diaSetVisible(diaNetConfig, NETCFG_SHARE_NB_ADDR, gPCShareAddressIsNetBIOS);
    diaSetInt(diaNetConfig, NETCFG_SHARE_NB_ADDR, gPCShareAddressIsNetBIOS);
    diaSetString(diaNetConfig, NETCFG_SHARE_NB_ADDR, gPCShareNBAddress);

    for (i = 0; i < 4; ++i) {
        diaSetEnabled(diaNetConfig, NETCFG_PS2_IP_ADDR_0 + i, !ps2_ip_use_dhcp);
        diaSetEnabled(diaNetConfig, NETCFG_PS2_NETMASK_0 + i, !ps2_ip_use_dhcp);
        diaSetEnabled(diaNetConfig, NETCFG_PS2_GATEWAY_0 + i, !ps2_ip_use_dhcp);
        diaSetEnabled(diaNetConfig, NETCFG_PS2_DNS_0 + i, !ps2_ip_use_dhcp);

        diaSetVisible(diaNetConfig, NETCFG_SHARE_IP_ADDR_0 + i, !gPCShareAddressIsNetBIOS);
        diaSetInt(diaNetConfig, NETCFG_PS2_IP_ADDR_0 + i, ps2_ip[i]);
        diaSetInt(diaNetConfig, NETCFG_PS2_NETMASK_0 + i, ps2_netmask[i]);
        diaSetInt(diaNetConfig, NETCFG_PS2_GATEWAY_0 + i, ps2_gateway[i]);
        diaSetInt(diaNetConfig, NETCFG_PS2_DNS_0 + i, ps2_dns[i]);
        diaSetInt(diaNetConfig, NETCFG_SHARE_IP_ADDR_0 + i, pc_ip[i]);
    }

    for (i = 0; i < 3; ++i)
        diaSetVisible(diaNetConfig, NETCFG_SHARE_IP_ADDR_DOT_0 + i, !gPCShareAddressIsNetBIOS);

    diaSetInt(diaNetConfig, NETCFG_SHARE_PORT, gPCPort);
    diaSetString(diaNetConfig, NETCFG_SHARE_NAME, gPCShareName);
    diaSetString(diaNetConfig, NETCFG_SHARE_USERNAME, gPCUserName);
    diaSetString(diaNetConfig, NETCFG_SHARE_PASSWORD, gPCPassword);
    diaSetInt(diaNetConfig, NETCFG_WRITE_POPSTARTER, gWritePopstarterNet);
    diaSetInt(diaNetConfig, NETCFG_ETHOPMODE, gETHOpMode);

    // Update the spacer item between the OK and reconnect buttons (See dialogs.c).
    if (gNetworkStartup == 0) {
        diaSetLabel(diaNetConfig, NETCFG_OK, _l(_STR_OK));
        diaSetVisible(diaNetConfig, NETCFG_RECONNECT, 1);
    } else if (gNetworkStartup >= ERROR_ETH_SMB_CONN) {
        diaSetLabel(diaNetConfig, NETCFG_OK, _l(_STR_RECONNECT));
        diaSetVisible(diaNetConfig, NETCFG_RECONNECT, 0);
    } else {
        diaSetLabel(diaNetConfig, NETCFG_OK, _l(_STR_OK));
        diaSetVisible(diaNetConfig, NETCFG_RECONNECT, 0);
    }

    int result = diaExecuteDialog(diaNetConfig, -1, 1, &netConfigUpdater);
    if (result) {
        // Store values
        diaGetInt(diaNetConfig, NETCFG_PS2_IP_ADDR_TYPE, &ps2_ip_use_dhcp);
        diaGetInt(diaNetConfig, NETCFG_SHARE_ADDR_TYPE, &gPCShareAddressIsNetBIOS);
        diaGetString(diaNetConfig, NETCFG_SHARE_NB_ADDR, gPCShareNBAddress, sizeof(gPCShareNBAddress));

        for (i = 0; i < 4; ++i) {
            diaGetInt(diaNetConfig, NETCFG_PS2_IP_ADDR_0 + i, &ps2_ip[i]);
            diaGetInt(diaNetConfig, NETCFG_PS2_NETMASK_0 + i, &ps2_netmask[i]);
            diaGetInt(diaNetConfig, NETCFG_PS2_GATEWAY_0 + i, &ps2_gateway[i]);
            diaGetInt(diaNetConfig, NETCFG_PS2_DNS_0 + i, &ps2_dns[i]);
            diaGetInt(diaNetConfig, NETCFG_SHARE_IP_ADDR_0 + i, &pc_ip[i]);
        }
        diaGetInt(diaNetConfig, NETCFG_ETHOPMODE, &gETHOpMode);

        diaGetInt(diaNetConfig, NETCFG_SHARE_PORT, &gPCPort);
        diaGetString(diaNetConfig, NETCFG_SHARE_NAME, gPCShareName, sizeof(gPCShareName));
        diaGetString(diaNetConfig, NETCFG_SHARE_USERNAME, gPCUserName, sizeof(gPCUserName));
        diaGetString(diaNetConfig, NETCFG_SHARE_PASSWORD, gPCPassword, sizeof(gPCPassword));
        diaGetInt(diaNetConfig, NETCFG_WRITE_POPSTARTER, &gWritePopstarterNet);

        // POPSTARTER needs the same IP/share data we just collected, so when the user opts in we
        // mirror it into POPSTARTER's own config files (mc?:/POPSTARTER/IPCONFIG.DAT + SMBCONFIG.DAT)
        // instead of asking twice. Opt-in (default off) so non-POPSTARTER users never touch the card;
        // the write is free-space-gated + truncation-safe, so a failure can't corrupt the card.
        if (gWritePopstarterNet) {
            char ipcfg[64], smbcfg[96];
            snprintf(ipcfg, sizeof(ipcfg), "%d.%d.%d.%d %d.%d.%d.%d %d.%d.%d.%d",
                     ps2_ip[0], ps2_ip[1], ps2_ip[2], ps2_ip[3],
                     ps2_netmask[0], ps2_netmask[1], ps2_netmask[2], ps2_netmask[3],
                     ps2_gateway[0], ps2_gateway[1], ps2_gateway[2], ps2_gateway[3]);
            snprintf(smbcfg, sizeof(smbcfg), "%d.%d.%d.%d:%d %s",
                     pc_ip[0], pc_ip[1], pc_ip[2], pc_ip[3], gPCPort, gPCShareName);
            if (vcdWritePopstarterNet(ipcfg, smbcfg) != 0)
                guiMsgBox(_l(_STR_POPSTARTER_NET_ERR), 0, NULL);
        }

        if (result == NETCFG_RECONNECT && gNetworkStartup < ERROR_ETH_SMB_CONN)
            gNetworkStartup = ERROR_ETH_SMB_LOGON;

        applyConfig(-1, -1, 0);
    }
}

static int guiDeviceUpdater(int modified)
{
    if (modified) {
        int hddMode, bdmHdd;
        diaGetInt(diaDeviceConfig, CFG_HDDMODE, &hddMode);
        diaGetInt(diaDeviceConfig, CFG_ENABLEBDMHDD, &bdmHdd);
        // BDM HDD (GPT/MBR) and the APA HDD mode are mutually exclusive; keep the
        // two interlocked live now that both live on the same page.
        diaSetEnabled(diaDeviceConfig, CFG_HDDMODE, !bdmHdd);
        diaSetEnabled(diaDeviceConfig, CFG_ENABLEBDMHDD, hddMode == 0);
    }

    return 0;
}

void guiShowDeviceConfig(void)
{
    const char *deviceNames[] = {_l(_STR_BDM_GAMES), _l(_STR_NET_GAMES), _l(_STR_HDD_GAMES), _l(_STR_APPS), _l(_STR_MMCE), NULL};
    const char *deviceModes[] = {_l(_STR_OFF), _l(_STR_MANUAL), _l(_STR_AUTO), NULL};
    const char *deviceSlots[] = {"0", "1", _l(_STR_AUTO), NULL};
    const char *deviceAckWaitCycles[] = {"0", "1", "2", "3", "4", "5", NULL};
    const char *deviceOnOff[] = {"OFF", "ON", NULL};
    const char *deviceIGRSlots[] = {"NONE", "0", "1", "BOTH", NULL};

    // Devices & modes
    diaSetEnum(diaDeviceConfig, CFG_DEFDEVICE, deviceNames);
    diaSetEnum(diaDeviceConfig, CFG_BDMMODE, deviceModes);
    diaSetEnum(diaDeviceConfig, CFG_HDDMODE, deviceModes);
    diaSetEnum(diaDeviceConfig, CFG_ETHMODE, deviceModes);
    diaSetEnum(diaDeviceConfig, CFG_APPMODE, deviceModes);
    diaSetEnum(diaDeviceConfig, CFG_FAVMODE, deviceModes);

    int deviceModeIndex = guiIoModeToDeviceType(gDefaultDevice);
    diaSetInt(diaDeviceConfig, CFG_DEFDEVICE, deviceModeIndex);
    diaSetInt(diaDeviceConfig, CFG_BDMMODE, gBDMStartMode);
    diaSetInt(diaDeviceConfig, CFG_HDDMODE, gHDDStartMode);
    diaSetInt(diaDeviceConfig, CFG_ETHMODE, gETHStartMode);
    diaSetInt(diaDeviceConfig, CFG_APPMODE, gAPPStartMode);
    diaSetInt(diaDeviceConfig, CFG_FAVMODE, gFAVStartMode);

    // Block devices (inlined; interlocked with the APA HDD mode)
    diaSetInt(diaDeviceConfig, CFG_ENABLEUSB, gEnableUSB);
    diaSetInt(diaDeviceConfig, CFG_ENABLEILK, gEnableILK);
    diaSetInt(diaDeviceConfig, CFG_ENABLEMX4SIO, gEnableMX4SIO);
    diaSetInt(diaDeviceConfig, CFG_ENABLEBDMHDD, gEnableBdmHDD);
    diaSetEnabled(diaDeviceConfig, CFG_ENABLEBDMHDD, !gHDDStartMode);
    diaSetEnabled(diaDeviceConfig, CFG_HDDMODE, !gEnableBdmHDD);

    // Prefix paths
    diaSetString(diaDeviceConfig, CFG_BDMPREFIX, gBDMPrefix);
    diaSetString(diaDeviceConfig, CFG_ETHPREFIX, gETHPrefix);
    diaSetString(diaDeviceConfig, CFG_MMCEPREFIX, gMMCEPrefix);

    // Cache & storage
    diaSetInt(diaDeviceConfig, CFG_HDDSPINDOWN, gHDDSpindown);
    diaSetInt(diaDeviceConfig, CFG_HDDGAMELISTCACHE, gHDDGameListCache);
    diaSetInt(diaDeviceConfig, CFG_BDMCACHE, bdmCacheSize);
    diaSetInt(diaDeviceConfig, CFG_HDDCACHE, hddCacheSize);
    diaSetInt(diaDeviceConfig, CFG_SMBCACHE, smbCacheSize);

    // MMCE
    diaSetEnum(diaDeviceConfig, CFG_MMCEMODE, deviceModes);
    diaSetInt(diaDeviceConfig, CFG_MMCEMODE, gMMCEStartMode);
    diaSetEnum(diaDeviceConfig, CFG_MMCESLOT, deviceSlots);
    diaSetInt(diaDeviceConfig, CFG_MMCESLOT, gMMCESlot);
    diaSetEnum(diaDeviceConfig, CFG_MMCEIGRSLOT, deviceIGRSlots);
    diaSetInt(diaDeviceConfig, CFG_MMCEIGRSLOT, gMMCEIGRSlot);
    diaSetEnum(diaDeviceConfig, CFG_MMCE_WAIT_CYCLES, deviceAckWaitCycles);
    diaSetInt(diaDeviceConfig, CFG_MMCE_WAIT_CYCLES, gMMCEAckWaitCycles);
    diaSetEnum(diaDeviceConfig, CFG_MMCE_USE_ALARMS, deviceOnOff);
    diaSetInt(diaDeviceConfig, CFG_MMCE_USE_ALARMS, gMMCEUseAlarms);
    diaSetInt(diaDeviceConfig, CFG_MMCEGAMEID, gMMCEEnableGameID);
    diaSetInt(diaDeviceConfig, CFG_APPLYGAMEID, gApplyGameID);

    int ret = diaExecuteDialog(diaDeviceConfig, -1, 1, &guiDeviceUpdater);
    if (ret) {
        diaGetInt(diaDeviceConfig, CFG_DEFDEVICE, &deviceModeIndex);
        gDefaultDevice = guiDeviceTypeToIoMode(deviceModeIndex);
        diaGetInt(diaDeviceConfig, CFG_BDMMODE, &gBDMStartMode);
        diaGetInt(diaDeviceConfig, CFG_HDDMODE, &gHDDStartMode);
        diaGetInt(diaDeviceConfig, CFG_ETHMODE, &gETHStartMode);
        diaGetInt(diaDeviceConfig, CFG_APPMODE, &gAPPStartMode);
        diaGetInt(diaDeviceConfig, CFG_FAVMODE, &gFAVStartMode);

        diaGetInt(diaDeviceConfig, CFG_ENABLEUSB, &gEnableUSB);
        diaGetInt(diaDeviceConfig, CFG_ENABLEILK, &gEnableILK);
        diaGetInt(diaDeviceConfig, CFG_ENABLEMX4SIO, &gEnableMX4SIO);
        diaGetInt(diaDeviceConfig, CFG_ENABLEBDMHDD, &gEnableBdmHDD);

        diaGetString(diaDeviceConfig, CFG_BDMPREFIX, gBDMPrefix, sizeof(gBDMPrefix));
        diaGetString(diaDeviceConfig, CFG_ETHPREFIX, gETHPrefix, sizeof(gETHPrefix));
        diaGetString(diaDeviceConfig, CFG_MMCEPREFIX, gMMCEPrefix, sizeof(gMMCEPrefix));

        diaGetInt(diaDeviceConfig, CFG_HDDSPINDOWN, &gHDDSpindown);
        diaGetInt(diaDeviceConfig, CFG_HDDGAMELISTCACHE, &gHDDGameListCache);
        diaGetInt(diaDeviceConfig, CFG_BDMCACHE, &bdmCacheSize);
        diaGetInt(diaDeviceConfig, CFG_HDDCACHE, &hddCacheSize);
        diaGetInt(diaDeviceConfig, CFG_SMBCACHE, &smbCacheSize);

        diaGetInt(diaDeviceConfig, CFG_MMCEMODE, &gMMCEStartMode);
        diaGetInt(diaDeviceConfig, CFG_MMCESLOT, &gMMCESlot);
        diaGetInt(diaDeviceConfig, CFG_MMCEIGRSLOT, &gMMCEIGRSlot);
        diaGetInt(diaDeviceConfig, CFG_MMCEGAMEID, &gMMCEEnableGameID);
        diaGetInt(diaDeviceConfig, CFG_APPLYGAMEID, &gApplyGameID);
        diaGetInt(diaDeviceConfig, CFG_MMCE_WAIT_CYCLES, &gMMCEAckWaitCycles);
        diaGetInt(diaDeviceConfig, CFG_MMCE_USE_ALARMS, &gMMCEUseAlarms);

        applyConfig(-1, -1, 0);
        menuReinitMainMenu();
    }
}

void guiShowParentalLockConfig(void)
{
    int result;
    char password[CONFIG_KEY_VALUE_LEN];
    config_set_t *configOPL = configGetByType(CONFIG_OPL);

    // Set current values
    configGetStrCopy(configOPL, CONFIG_OPL_PARENTAL_LOCK_PWD, password, CONFIG_KEY_VALUE_LEN); // This will return the current password, or a blank string if it is not set.
    diaSetString(diaParentalLockConfig, CFG_PARENLOCK_PASSWORD, password);

    result = diaExecuteDialog(diaParentalLockConfig, -1, 1, NULL);
    if (result) {
        diaGetString(diaParentalLockConfig, CFG_PARENLOCK_PASSWORD, password, CONFIG_KEY_VALUE_LEN);

        if (strlen(password) > 0) {
            if (strncmp(OPL_PARENTAL_LOCK_MASTER_PASS, password, CONFIG_KEY_VALUE_LEN) != 0) {
                // Store password
                configSetStr(configOPL, CONFIG_OPL_PARENTAL_LOCK_PWD, password);
            } else {
                // Password not acceptable (i.e. master password entered).
                guiMsgBox(_l(_STR_PARENLOCK_INVALID_PASSWORD), 0, NULL);
            }
        } else {
            configRemoveKey(configOPL, CONFIG_OPL_PARENTAL_LOCK_PWD);

            guiMsgBox(_l(_STR_PARENLOCK_DISABLE_WARNING), 0, diaParentalLockConfig);
        }

        menuSetParentalLockCheckState(1);
    }
}

static void guiSetAudioSettingsState(void)
{
    diaGetInt(diaAudioConfig, CFG_SFX, &gEnableSFX);
    diaGetInt(diaAudioConfig, CFG_BOOT_SND, &gEnableBootSND);
    diaGetInt(diaAudioConfig, CFG_BGM, &gEnableBGM);
    diaGetInt(diaAudioConfig, CFG_SFX_VOLUME, &gSFXVolume);
    diaGetInt(diaAudioConfig, CFG_BOOT_SND_VOLUME, &gBootSndVolume);
    diaGetInt(diaAudioConfig, CFG_BGM_VOLUME, &gBGMVolume);
    diaGetString(diaAudioConfig, CFG_DEFAULT_BGM_PATH, gDefaultBGMPath, sizeof(gDefaultBGMPath));
    audioSetVolume();

    if (gEnableBGM && !isBgmPlaying())
        bgmStart();
}

static int guiAudioUpdater(int modified)
{
    if (modified) {
        guiSetAudioSettingsState();
    }

    return 0;
}

void guiShowAudioConfig(void)
{
    diaSetInt(diaAudioConfig, CFG_SFX, gEnableSFX);
    diaSetInt(diaAudioConfig, CFG_BOOT_SND, gEnableBootSND);
    diaSetInt(diaAudioConfig, CFG_BGM, gEnableBGM);
    diaSetInt(diaAudioConfig, CFG_SFX_VOLUME, gSFXVolume);
    diaSetInt(diaAudioConfig, CFG_BOOT_SND_VOLUME, gBootSndVolume);
    diaSetInt(diaAudioConfig, CFG_BGM_VOLUME, gBGMVolume);
    diaSetString(diaAudioConfig, CFG_DEFAULT_BGM_PATH, gDefaultBGMPath);

    diaExecuteDialog(diaAudioConfig, -1, 1, guiAudioUpdater);
}

void guiShowCoverflowConfig(void)
{
    int value;
    int i;

    // Map index<->stored value: scale 0/15/30/45 is linear (idx*15); anim 0/100/200/400 is a lookup.
    static const int animValues[] = {0, 100, 200, 400};

    const char *coverCounts[] = {"3", "5", NULL};
    const char *centerScales[] = {_l(_STR_NONE), _l(_STR_SMALL), _l(_STR_MEDIUM), _l(_STR_LARGE), NULL};
    const char *animSpeeds[] = {_l(_STR_OFF), _l(_STR_FAST), _l(_STR_NORMAL), _l(_STR_SLOW), NULL};

    diaSetEnum(diaCoverflowConfig, COVERFLOW_CFG_COUNT, coverCounts);
    diaSetEnum(diaCoverflowConfig, COVERFLOW_CFG_SCALE, centerScales);
    diaSetEnum(diaCoverflowConfig, COVERFLOW_CFG_ANIM, animSpeeds);

    diaSetInt(diaCoverflowConfig, COVERFLOW_CFG_COUNT, (gCoverflowCount == 5) ? 1 : 0);

    int scaleIdx = gCoverflowCenterScale / 15;
    if (scaleIdx < 0)
        scaleIdx = 0;
    else if (scaleIdx > 3)
        scaleIdx = 3;
    diaSetInt(diaCoverflowConfig, COVERFLOW_CFG_SCALE, scaleIdx);

    // default to Normal (200ms) if the stored value isn't one of the table entries
    int animIdx = 2;
    for (i = 0; i < 4; i++)
        if (animValues[i] == gCoverflowAnimSpeed)
            animIdx = i;
    diaSetInt(diaCoverflowConfig, COVERFLOW_CFG_ANIM, animIdx);

    diaSetInt(diaCoverflowConfig, COVERFLOW_CFG_DIM, gCoverflowDimCovers ? 1 : 0);

    int result = diaExecuteDialog(diaCoverflowConfig, -1, 1, NULL);
    if (result) {
        if (diaGetInt(diaCoverflowConfig, COVERFLOW_CFG_COUNT, &value))
            gCoverflowCount = (value == 1) ? 5 : 3;
        if (diaGetInt(diaCoverflowConfig, COVERFLOW_CFG_SCALE, &value))
            gCoverflowCenterScale = ((value >= 0 && value <= 3) ? value : 0) * 15;
        if (diaGetInt(diaCoverflowConfig, COVERFLOW_CFG_ANIM, &value))
            gCoverflowAnimSpeed = animValues[(value >= 0 && value <= 3) ? value : 2];
        if (diaGetInt(diaCoverflowConfig, COVERFLOW_CFG_DIM, &value))
            gCoverflowDimCovers = value ? 1 : 0;
    }
}

void guiShowControllerConfig(void)
{
    int value;

    // configure the enumerations
    const char *scrollSpeeds[] = {_l(_STR_SLOW), _l(_STR_MEDIUM), _l(_STR_FAST), NULL};
    const char *selectButtons[] = {_l(_STR_CIRCLE), _l(_STR_CROSS), NULL};
    const char *sensitivity[] = {_l(_STR_LOW), _l(_STR_MEDIUM), _l(_STR_HIGH), NULL};

    diaSetEnum(diaControllerConfig, UICFG_SCROLL, scrollSpeeds);
    diaSetEnum(diaControllerConfig, CFG_SELECTBUTTON, selectButtons);
    diaSetEnum(diaControllerConfig, CFG_XSENSITIVITY, sensitivity);
    diaSetEnum(diaControllerConfig, CFG_YSENSITIVITY, sensitivity);

    diaSetInt(diaControllerConfig, UICFG_SCROLL, gScrollSpeed);
    diaSetInt(diaControllerConfig, CFG_SELECTBUTTON, gSelectButton == KEY_CIRCLE ? 0 : 1);
    diaSetInt(diaControllerConfig, CFG_XSENSITIVITY, gXSensitivity);
    diaSetInt(diaControllerConfig, CFG_YSENSITIVITY, gYSensitivity);

    int result = diaExecuteDialog(diaControllerConfig, -1, 1, NULL);
    if (result) {
        diaGetInt(diaControllerConfig, UICFG_SCROLL, &gScrollSpeed);
        diaGetInt(diaControllerConfig, CFG_XSENSITIVITY, &gXSensitivity);
        diaGetInt(diaControllerConfig, CFG_YSENSITIVITY, &gYSensitivity);

        if (diaGetInt(diaControllerConfig, CFG_SELECTBUTTON, &value))
            gSelectButton = value == 0 ? KEY_CIRCLE : KEY_CROSS;
        else
            gSelectButton = KEY_CIRCLE;
#ifdef PADEMU
        if (result == PADEMU_GLOBAL_BUTTON) {
            guiGameShowPadEmuConfig(1);
        } else if (result == PADMACRO_GLOBAL_BUTTON) {
            guiGameShowPadMacroConfig(1);
        }
#endif
        applyConfig(-1, -1, 1);
    }
}

int guiShowKeyboard(char *value, int maxLength)
{
    char tmp[maxLength];
    strncpy(tmp, value, maxLength);

    int result = diaShowKeyb(tmp, maxLength, 0, NULL);
    if (result) {
        strncpy(value, tmp, maxLength);
        value[maxLength - 1] = '\0';
    }

    return result;
}

int guiGetOpCompleted(int opid)
{
    return gCompletedOps > opid;
}

int guiDeferUpdate(struct gui_update_t *op)
{
    WaitSema(gSemaId);

    struct gui_update_list_t *up = (struct gui_update_list_t *)malloc(sizeof(struct gui_update_list_t));
    up->item = op;
    up->next = NULL;

    if (!gUpdateList) {
        gUpdateList = up;
        gUpdateEnd = gUpdateList;
    } else {
        gUpdateEnd->next = up;
        gUpdateEnd = up;
    }

    SignalSema(gSemaId);

    return gScheduledOps++;
}

static void guiHandleOp(struct gui_update_t *item)
{
    submenu_list_t *result = NULL;

    switch (item->type) {
        case GUI_INIT_DONE:
            gInitComplete = 1;
            break;

        case GUI_OP_ADD_MENU:
            menuAppendItem(item->menu.menu);
            break;

        case GUI_OP_APPEND_MENU:
            result = submenuAppendItem(item->menu.subMenu, item->submenu.icon_id, item->submenu.text, item->submenu.id, item->submenu.text_id, item->submenu.owner);
            // coverflow wrap tail: submenuAppendItem always returns the new tail
            item->menu.menu->last = result;
            if (!item->menu.menu->submenu) { // first subitem in list
                item->menu.menu->submenu = result;
                if (!item->submenu.selected) {
                    item->menu.menu->current = result;
                    item->menu.menu->pagestart = result;
                }
            }
            if (item->submenu.selected) { // remember last played game feature
                item->menu.menu->current = result;
                item->menu.menu->pagestart = result;
                item->menu.menu->remindLast = 1;

                // Last Played Auto Start
                if ((gAutoStartLastPlayed) && !(KeyPressedOnce))
                    DisableCron = 0; // Release Auto Start Last Played counter
            }

            break;

        case GUI_OP_SELECT_MENU:
            menuSetSelectedItem(item->menu.menu);
            screenHandler = &screenHandlers[GUI_SCREEN_MAIN];
            break;

        case GUI_OP_CLEAR_SUBMENU:
            submenuDestroy(item->menu.subMenu);
            item->menu.menu->submenu = NULL;
            item->menu.menu->current = NULL;
            item->menu.menu->pagestart = NULL;
            item->menu.menu->last = NULL; // coverflow wrap tail
            cacheAdvanceGeneration();
            break;

        case GUI_OP_SORT:
            submenuSort(item->menu.subMenu);
            item->menu.menu->submenu = *item->menu.subMenu;

            { // recompute the coverflow wrap tail after the sort reorders the list
                submenu_list_t *tail = item->menu.menu->submenu;
                while (tail && tail->next)
                    tail = tail->next;
                item->menu.menu->last = tail;
            }

            if (!item->menu.menu->remindLast)
                item->menu.menu->current = item->menu.menu->submenu;

            item->menu.menu->pagestart = item->menu.menu->current;
            cacheAdvanceGeneration();
            break;

        case GUI_OP_ADD_HINT:
            // append the hint list in the menu item
            menuAddHint(item->menu.menu, item->hint.text_id, item->hint.icon_id);
            break;

        default:
            LOG("GUI: ??? (%d)\n", item->type);
    }
}

static void guiHandleDeferredOps(void)
{

    WaitSema(gSemaId);
    while (gUpdateList) {

        guiHandleOp(gUpdateList->item);

        struct gui_update_list_t *td = gUpdateList;
        gUpdateList = gUpdateList->next;

        free(td);

        gCompletedOps++;
    }
    SignalSema(gSemaId);

    gUpdateEnd = NULL;
}

void guiExecDeferredOps(void)
{
    // Clears deferred operations list by executing them.
    guiHandleDeferredOps();
}

static void guiDrawBusy(int alpha)
{
    if (gTheme->loadingIcon) {
        GSTEXTURE *texture = thmGetTexture(LOAD0_ICON + (guiFrameId >> 1) % gTheme->loadingIconCount);
        if (texture && texture->Mem) {
            u64 mycolor = GS_SETREG_RGBA(0x80, 0x80, 0x80, alpha);
            rmDrawPixmap(texture, gTheme->loadingIcon->posX, gTheme->loadingIcon->posY, gTheme->loadingIcon->aligned, gTheme->loadingIcon->width, gTheme->loadingIcon->height, gTheme->loadingIcon->scaled, mycolor, 0);
        }
    }
}

static void guiRenderGreeting(int alpha)
{
    u64 mycolor = GS_SETREG_RGBA(0x1C, 0x1C, 0x1C, alpha);
    rmDrawRect(0, 0, screenWidth, screenHeight, mycolor);

    // If the theme/build ships animated boot-logo frames (logo0..logoN), cycle
    // them at the loading-icon cadence; otherwise use the single LOGO_PICTURE.
    int logoTex = LOGO_PICTURE;
    if (gTheme->logoFrameCount >= 1)
        logoTex = LOGO0_PICTURE + (guiFrameId >> 1) % gTheme->logoFrameCount;

    GSTEXTURE *logo = thmGetTexture(logoTex);
    if (logo) {
        mycolor = GS_SETREG_RGBA(0x80, 0x80, 0x80, alpha);
        rmDrawPixmap(logo, screenWidth >> 1, gTheme->usedHeight >> 1, ALIGN_CENTER, logo->Width, logo->Height, SCALING_RATIO, mycolor, 0);
    }
}

// Draw one standalone boot-splash frame: the same greeting guiIntroLoop() shows,
// at full opacity. Used as the boot "loading" screen instead of
// guiRenderTextScreen(), whose guiShow() call would render the not-yet-ready main
// menu (empty lists, no device selected) as a garbled landing page before the
// intro splash. This keeps the OPL logo on screen across the config load so boot
// shows the splash, never a half-drawn menu.
void guiRenderGreetingScreen(void)
{
    guiStartFrame();
    guiRenderGreeting(0x80);
    guiEndFrame();
}

static float mix(float a, float b, float t)
{
    return a + (b - a) * t;
}

static float fade(float t)
{
    return fadetbl[(int)(t * FADE_SIZE)];
}

// The same as mix, but with 8 (2*4) values mixed at once
static void VU0MixVec(VU_VECTOR *a, VU_VECTOR *b, float mix, VU_VECTOR *res)
{
    asm volatile(
#if __GNUC__ > 3
        "lqc2           $vf1, (%[a])\n"        // load the first vector
        "lqc2           $vf2, (%[b])\n"        // load the second vector
        "qmtc2          %[mix], $vf3\n"        // move the mix value from reg to VU
        "vaddw.x        $vf5, $vf0, $vf0\n"    // vf5.x = 1
        "vsub.x         $vf4x, $vf5x, $vf3x\n" // subtract 1 - vf3,x, store the result in vf4.x
        "vmulax.xyzw    $ACC, $vf1, $vf3x\n"   // multiply vf1 by vf3.x, store the result in ACC
        "vmaddx.xyzw    $vf1, $vf2, $vf4x\n"   // multiply vf2 by vf4.x add ACC, store the result in vf1
        "sqc2           $vf1, (%[res])\n"      // transfer the result in acc to the ee
#else
        "lqc2           vf1, (%[a])\n"      // load the first vector
        "lqc2           vf2, (%[b])\n"      // load the second vector
        "qmtc2          %[mix], vf3\n"      // move the mix value from reg to VU
        "vaddw.x        vf5, vf00, vf00\n"  // vf5.x = 1
        "vsub.x         vf4x, vf5x, vf3x\n" // subtract 1 - vf3,x, store the result in vf4.x
        "vmulax.xyzw    ACC, vf1, vf3x\n"   // multiply vf1 by vf3.x, store the result in ACC
        "vmaddx.xyzw    vf1, vf2, vf4x\n"   // multiply vf2 by vf4.x add ACC, store the result in vf1
        "sqc2           vf1, (%[res])\n"    // transfer the result in acc to the ee
#endif
        : [res] "+r"(res), "=m"(*res)
        : [a] "r"(a), [b] "r"(b), [mix] "r"(mix), "m"(*a), "m"(*b));
}

static float guiCalcPerlin(float x, float y, float z)
{
    // Taken from: http://people.opera.com/patrickl/experiments/canvas/plasma/perlin-noise-classical.js
    // By Sean McCullough

    // Find unit grid cell containing point
    int X = floorf(x);
    int Y = floorf(y);
    int Z = floorf(z);

    // Get relative xyz coordinates of point within that cell
    x = x - X;
    y = y - Y;
    z = z - Z;

    // Wrap the integer cells at 255 (smaller integer period can be introduced here)
    X = X & 255;
    Y = Y & 255;
    Z = Z & 255;

    // Calculate a set of eight hashed gradient indices
    int gi000 = pperm[X + pperm[Y + pperm[Z]]] % 12;
    int gi001 = pperm[X + pperm[Y + pperm[Z + 1]]] % 12;
    int gi010 = pperm[X + pperm[Y + 1 + pperm[Z]]] % 12;
    int gi011 = pperm[X + pperm[Y + 1 + pperm[Z + 1]]] % 12;
    int gi100 = pperm[X + 1 + pperm[Y + pperm[Z]]] % 12;
    int gi101 = pperm[X + 1 + pperm[Y + pperm[Z + 1]]] % 12;
    int gi110 = pperm[X + 1 + pperm[Y + 1 + pperm[Z]]] % 12;
    int gi111 = pperm[X + 1 + pperm[Y + 1 + pperm[Z + 1]]] % 12;

    // The gradients of each corner are now:
    // g000 = grad3[gi000];
    // g001 = grad3[gi001];
    // g010 = grad3[gi010];
    // g011 = grad3[gi011];
    // g100 = grad3[gi100];
    // g101 = grad3[gi101];
    // g110 = grad3[gi110];
    // g111 = grad3[gi111];
    // Calculate noise contributions from each of the eight corners
    VU_VECTOR vec;
    vec.x = x;
    vec.y = y;
    vec.z = z;
    vec.w = 1;

    VU_VECTOR a, b;

    // float n000
    a.x = Vu0DotProduct(&pgrad3[gi000], &vec);

    vec.y -= 1;

    // float n010
    a.z = Vu0DotProduct(&pgrad3[gi010], &vec);

    vec.x -= 1;

    // float n110
    b.z = Vu0DotProduct(&pgrad3[gi110], &vec);

    vec.y += 1;

    // float n100
    b.x = Vu0DotProduct(&pgrad3[gi100], &vec);

    vec.z -= 1;

    // float n101
    b.y = Vu0DotProduct(&pgrad3[gi101], &vec);

    vec.y -= 1;

    // float n111
    b.w = Vu0DotProduct(&pgrad3[gi111], &vec);

    vec.x += 1;

    // float n011
    a.w = Vu0DotProduct(&pgrad3[gi011], &vec);

    vec.y += 1;

    // float n001
    a.y = Vu0DotProduct(&pgrad3[gi001], &vec);

    // Compute the fade curve value for each of x, y, z
    float u = fade(x);
    float v = fade(y);
    float w = fade(z);

    // TODO: Low priority... This could be done on VU0 (xyzw for the first 4 mixes)
    // The result in sw
    // Interpolate along x the contributions from each of the corners
    VU_VECTOR rv;
    VU0MixVec(&b, &a, u, &rv);

    // TODO: The VU0MixVec could as well mix the results (as follows) - might improve performance...
    // Interpolate the four results along y
    float nxy0 = mix(rv.x, rv.z, v);
    float nxy1 = mix(rv.y, rv.w, v);
    // Interpolate the two last results along z
    float nxyz = mix(nxy0, nxy1, w);

    return nxyz;
}

static float dir = 0.02;
static float perz = -100;
static int pery = 0;
static unsigned char curbgColor[3] = {0, 0, 0};

static int cdirection(unsigned char a, unsigned char b)
{
    if (a == b)
        return 0;
    else if (a > b)
        return -1;
    else
        return 1;
}

// Optional settings/menu background: if the active theme supplies a SETTINGS_BG texture
// (theme cfg use_settings_bg=1, or a future embedded default), draw it full-screen behind
// dialogs/menus and return 1; otherwise return 0 so callers fall back to guiDrawBGPlasma().
// Dormant by default -- the SETTINGS_BG slot is empty unless a theme provides the image.
int guiDrawBGSettings(void)
{
    GSTEXTURE *bg = thmGetTexture(SETTINGS_BG);
    if (bg) {
        rmDrawPixmap(bg, 0, 0, ALIGN_NONE, screenWidth, screenHeight, SCALING_NONE, gDefaultCol, 0);
        return 1;
    }
    return 0;
}

void guiDrawBGPlasma()
{
    int x, y;

    // transition the colors
    curbgColor[0] += cdirection(curbgColor[0], gTheme->bgColor[0]);
    curbgColor[1] += cdirection(curbgColor[1], gTheme->bgColor[1]);
    curbgColor[2] += cdirection(curbgColor[2], gTheme->bgColor[2]);

    // it's PLASMA_ROWS_PER_FRAME rows a frame to stop being a resource hog
    if (pery >= PLASMA_H) {
        pery = 0;
        perz += dir;

        if (perz > 100.0f || perz < -100.0f)
            dir = -dir;
    }

    u32 *buf = gBackgroundTex.Mem + PLASMA_W * pery;
    int ymax = pery + PLASMA_ROWS_PER_FRAME;

    if (ymax > PLASMA_H)
        ymax = PLASMA_H;

    for (y = pery; y < ymax; y++) {
        for (x = 0; x < PLASMA_W; x++) {
            u32 fper = guiCalcPerlin((float)(2 * x) / PLASMA_W, (float)(2 * y) / PLASMA_H, perz) * 0x80 + 0x80;

            *buf = GS_SETREG_RGBA(
                (u32)(fper * curbgColor[0]) >> 8,
                (u32)(fper * curbgColor[1]) >> 8,
                (u32)(fper * curbgColor[2]) >> 8,
                0x80);

            ++buf;
        }
    }

    pery = ymax;
    rmInvalidateTexture(&gBackgroundTex);
    rmDrawPixmap(&gBackgroundTex, 0, 0, ALIGN_NONE, screenWidth, screenHeight, SCALING_NONE, gDefaultCol, 0);
}

int guiDrawIconAndText(int iconId, int textId, int font, int x, int y, u64 color)
{
    GSTEXTURE *iconTex = thmGetTexture(iconId);
    int w = 0;
    int h = 20;

    if (iconTex) {
        w = (iconTex->Width * 20) / iconTex->Height;
    }

    if (iconTex && iconTex->Mem) {
        y += h >> 1;
        rmDrawPixmap(iconTex, x, y, ALIGN_VCENTER, w, h, SCALING_RATIO, gDefaultCol, 0);
        x += rmWideScale(w) + 2;
    } else {
        // HACK: font is aligned to VCENTER, the default height icon height is 20
        y += 10;
    }

    x = fntRenderString(font, x, y, ALIGN_VCENTER, 0, 0, _l(textId), color);

    return x;
}

int guiAlignMenuHints(menu_hint_item_t *hint, int font, int width)
{
    int x = screenWidth;
    int w;

    for (; hint; hint = hint->next) {
        GSTEXTURE *iconTex = thmGetTexture(hint->icon_id);
        w = (iconTex->Width * 20) / iconTex->Height;
        char *text = _l(hint->text_id);

        x -= rmWideScale(w) + 2;
        x -= rmUnScaleX(fntCalcDimensions(font, text));
        if (hint->next != NULL)
            x -= width;
    }

    // align center
    x /= 2;

    return x;
}

int guiAlignSubMenuHints(int hintCount, int *textID, int *iconID, int font, int width, int align)
{
    int x = screenWidth;
    int i, w;

    for (i = 0; i < hintCount; i++) {
        GSTEXTURE *iconTex = thmGetTexture(iconID[i]);
        w = (iconTex->Width * 20) / iconTex->Height;
        char *text = _l(textID[i]);

        x -= rmWideScale(w) + 2;
        x -= rmUnScaleX(fntCalcDimensions(font, text));
        if (i != (hintCount - 1))
            x -= width;
    }

    if (align == 1) // align center
        x /= 2;

    if (align == 2) // align right
        x -= 20;

    return x;
}

void guiDrawSubMenuHints(void)
{
    int subMenuHints[2] = {_STR_SELECT, _STR_GAMES_LIST};
    int subMenuIcons[2] = {CIRCLE_ICON, CROSS_ICON};

    int x = guiAlignSubMenuHints(2, subMenuHints, subMenuIcons, gTheme->fonts[0], 12, 2);
    int y = gTheme->usedHeight - 32;

    x = guiDrawIconAndText(gSelectButton == KEY_CIRCLE ? subMenuIcons[0] : subMenuIcons[1], subMenuHints[0], gTheme->fonts[0], x, y, gTheme->textColor);
    x += 12;
    guiDrawIconAndText(gSelectButton == KEY_CIRCLE ? subMenuIcons[1] : subMenuIcons[0], subMenuHints[1], gTheme->fonts[0], x, y, gTheme->textColor);
}

static int endIntro = 0; // Break intro loop and start 'Last Played Auto Start' countdown
static void guiDrawOverlays()
{
    static int busyAlpha = 0x00; // Fully transparant

    // are there any pending operations?
    int pending = ioHasPendingRequests();

    // During the boot intro, when an animated boot logo is shown, suppress the
    // loading spinner -- the animated logo is the boot activity indicator there.
    // The spinner is used normally everywhere else (and on boot for themes/builds
    // without animated logo frames, so a slow boot still shows activity).
    int showBusy = endIntro || (gTheme->logoFrameCount < 1);
    if (showBusy) {
        if (!pending) {
            // Fade out
            if (busyAlpha > 0x00)
                busyAlpha -= 0x02;
        } else {
            // Fade in
            if (busyAlpha < 0x80)
                busyAlpha += 0x02;
        }

        if (busyAlpha > 0x00)
            guiDrawBusy(busyAlpha);
    }

#ifdef __DEBUG
    char text[20];
    int x = screenWidth - 120;
    int y = 15;
    int yadd = 15;

    snprintf(text, sizeof(text), "VRAM:");
    fntRenderString(gTheme->fonts[0], x, y, ALIGN_LEFT, 0, 0, text, GS_SETREG_RGBA(0x60, 0x60, 0x60, 0x80));
    y += yadd;

    snprintf(text, sizeof(text), "%dKiB FIXED", gsGlobal->CurrentPointer / 1024);
    fntRenderString(gTheme->fonts[0], x, y, ALIGN_LEFT, 0, 0, text, GS_SETREG_RGBA(0x60, 0x60, 0x60, 0x80));
    y += yadd;

    snprintf(text, sizeof(text), "%dKiB TEXMAN", ((4 * 1024 * 1024) - gsGlobal->CurrentPointer) / 1024);
    fntRenderString(gTheme->fonts[0], x, y, ALIGN_LEFT, 0, 0, text, GS_SETREG_RGBA(0x60, 0x60, 0x60, 0x80));
    y += yadd;
    y += yadd; // Empty line

    if (prevtime != 0) {
        clock_t diff = curtime - prevtime;
        if (diff == 0)
            diff = 1;

        // Raw FPS value with 2 decimal places
        float rawfps = ((100 * CLOCKS_PER_SEC) / diff) / 100.0f;

        if (fps == 0.0f)
            fps = rawfps;
        else
            fps = fps * 0.9f + rawfps / 10.0f; // Smooth FPS value

        snprintf(text, sizeof(text), "%.1f FPS", fps);
        fntRenderString(gTheme->fonts[0], x, y, ALIGN_LEFT, 0, 0, text, GS_SETREG_RGBA(0x60, 0x60, 0x60, 0x80));
        y += yadd;
    }
#endif

    // Last Played Auto Start
    if (!pending && DisableCron == 0 && endIntro) {
        if (CronStart == 0) {
            CronStart = clock() / CLOCKS_PER_SEC;
        } else {
            char strAutoStartInNSecs[21];
            clock_t CronCurrent;

            CronCurrent = clock() / CLOCKS_PER_SEC;
            RemainSecs = gAutoStartLastPlayed - (CronCurrent - CronStart);
            snprintf(strAutoStartInNSecs, sizeof(strAutoStartInNSecs), _l(_STR_AUTO_START_IN_N_SECS), RemainSecs);
            fntRenderString(gTheme->fonts[0], screenWidth / 2, screenHeight / 2, ALIGN_CENTER, 0, 0, strAutoStartInNSecs, GS_SETREG_RGBA(0x60, 0x60, 0x60, 0x80));
        }
    }

    // BLURT output
    // if (gEnableDebug)
    //     fntRenderString(gTheme->fonts[0], 0, screenHeight - 24, ALIGN_NONE, 0, 0, blurttext, GS_SETREG_RGBA(255, 255, 0, 128));
}

static void guiReadPads()
{
    if (readPads())
        guiInactiveFrames = 0;
    else {
        int wasActive = (guiInactiveFrames == 0);

        guiInactiveFrames++;
        if (wasActive)
            cacheWakeInteractiveArtOnInputIdle();
    }
}

// renders the screen and handles inputs. Also handles screen transitions between numerous
// screen handlers. Fade transition code written by Maximus32
static void guiShow()
{
    // is there a transmission effect going on or are
    // we in a normal rendering state?
    if (screenHandlerTarget) {
        u8 alpha;
        const u8 transition_frames = 26;
        if (transIndex < (transition_frames / 2)) {
            // Fade-out old screen
            // index: 0..7
            // alpha: 1..8 * transition_step
            screenHandler->renderScreen();
            alpha = fade((float)(transIndex + 1) / (transition_frames / 2)) * 0x80;
        } else {
            // Fade-in new screen
            // index: 8..15
            // alpha: 8..1 * transition_step
            screenHandlerTarget->renderScreen();
            alpha = fade((float)(transition_frames - transIndex) / (transition_frames / 2)) * 0x80;
        }

        // Overlay the actual "fade"
        rmDrawRect(0, 0, screenWidth, screenHeight, GS_SETREG_RGBA(0x00, 0x00, 0x00, alpha));

        // Advance the effect
        transIndex++;
        if (transIndex >= transition_frames) {
            screenHandler = screenHandlerTarget;
            screenHandlerTarget = NULL;
        }
    } else
        // render with the set screen handler
        screenHandler->renderScreen();
}

void guiIntroLoop(void)
{
    int greetingAlpha = 0x80;
    const int fadeFrameCount = 0x80 / 2;
    const int fadeDuration = (fadeFrameCount * 1000) / 55; // Average between 50 and 60 fps
    clock_t tFadeDelayEnd = 0;

    while (!endIntro) {
        guiStartFrame();

        if (greetingAlpha < 0x80)
            guiShow();

        if (greetingAlpha > 0)
            guiRenderGreeting(greetingAlpha);

        // Initialize boot sound
        if (gInitComplete && !tFadeDelayEnd && gEnableBootSND) {
            // Start playing sound
            sfxPlay(SFX_BOOT);
            // Calculate transition delay
            tFadeDelayEnd = clock() + (sfxGetSoundDuration(SFX_BOOT) - fadeDuration) * (CLOCKS_PER_SEC / 1000);
        }

        if (gInitComplete && clock() >= tFadeDelayEnd)
            greetingAlpha -= 2;

        if (greetingAlpha <= 0)
            endIntro = 1;

        guiDrawOverlays();

        guiHandleDeferredOps();

        guiEndFrame();

        if (!screenHandlerTarget && screenHandler)
            screenHandler->handleInput();

        cachePrimeReadyTexture();
    }
}

void guiMainLoop(void)
{
    guiResetNotifications();
    guiCheckNotifications(1, 1);

    if (gOPLPart[0] != '\0')
        showPartPopup = 1;

    if (gEnableBGM)
        bgmStart();

    while (!gTerminate) {
        guiStartFrame();

        // Read the pad states to prepare for input processing in the screen handler
        guiReadPads();

        // handle inputs and render screen
        guiShow();

        // Render overlaying gui thingies :)
        guiDrawOverlays();

        if (gEnableNotifications)
            guiShowNotifications();

        // handle deferred operations
        guiHandleDeferredOps();

        guiEndFrame();

        // if not transiting, handle input
        // done here so we can use renderman if needed
        if (!screenHandlerTarget && screenHandler)
            screenHandler->handleInput();

        cachePrimeReadyTexture();

        if (gFrameHook)
            gFrameHook();
    }
}

void guiSetFrameHook(gui_callback_t cback)
{
    gFrameHook = cback;
}

void guiSwitchScreen(int target)
{
    // Only initiate the transition once or else we could get stuck in an infinite loop.
    if (screenHandlerTarget != NULL) {
        return;
    }

    cacheAdvanceGeneration();
    sfxPlay(SFX_TRANSITION);
    transIndex = 0;
    screenHandlerTarget = &screenHandlers[target];
}

struct gui_update_t *guiOpCreate(gui_op_type_t type)
{
    struct gui_update_t *op = (struct gui_update_t *)malloc(sizeof(struct gui_update_t));
    memset(op, 0, sizeof(struct gui_update_t));
    op->type = type;
    return op;
}

void guiUpdateScrollSpeed(void)
{
    // sanitize the settings
    if ((gScrollSpeed < 0) || (gScrollSpeed > 2))
        gScrollSpeed = 1;

    // update the pad delays for KEY_UP and KEY_DOWN
    // default delay is 7
    // fast - 100 ms
    // medium - 300 ms
    // slow - 500 ms
    setButtonDelay(KEY_UP, 500 - gScrollSpeed * 200); // 0,1,2 -> 500, 300, 100
    setButtonDelay(KEY_DOWN, 500 - gScrollSpeed * 200);
}

void guiUpdateScreenScale(void)
{
    fntUpdateAspectRatio();
}

int guiMsgBox(const char *text, int addAccept, struct UIItem *ui)
{
    int terminate = 0;

    sfxPlay(SFX_MESSAGE);

    while (!terminate) {
        guiStartFrame();

        readPads();

        if (getKeyOn(gSelectButton == KEY_CIRCLE ? KEY_CROSS : KEY_CIRCLE))
            terminate = 1;
        else if (getKeyOn(gSelectButton))
            terminate = 2;

        if (ui)
            diaRenderUI(ui, screenHandler->inMenu, NULL, 0);
        else
            guiShow();

        rmDrawRect(0, 0, screenWidth, screenHeight, gColDarker);

        rmDrawLine(50, 75, screenWidth - 50, 75, gColWhite);
        rmDrawLine(50, 410, screenWidth - 50, 410, gColWhite);

        fntRenderString(gTheme->fonts[0], screenWidth >> 1, gTheme->usedHeight >> 1, ALIGN_CENTER, 0, 0, text, gTheme->textColor);
        guiDrawIconAndText(gSelectButton == KEY_CIRCLE ? CROSS_ICON : CIRCLE_ICON, _STR_BACK, gTheme->fonts[0], 500, 417, gTheme->selTextColor);
        if (addAccept)
            guiDrawIconAndText(gSelectButton == KEY_CIRCLE ? CIRCLE_ICON : CROSS_ICON, _STR_ACCEPT, gTheme->fonts[0], 70, 417, gTheme->selTextColor);

        guiEndFrame();
    }

    if (terminate == 1) {
        sfxPlay(SFX_CANCEL);
    }
    if (terminate == 2) {
        sfxPlay(SFX_CONFIRM);
    }

    return terminate - 1;
}

void guiHandleDeferedIO(int *ptr, const char *message, int type, void *data)
{
    // Free the shared IOP/fileXio channel before running the deferred IO. The
    // cover-art worker's queued and in-flight reads otherwise tie up that single
    // channel, so a config write (e.g. the last-played save on game launch) queues
    // behind them and the screen freezes on "Saving config..." after browsing the
    // list (issue #45 -- confirmed on hardware: disabling cover art avoids it).
    // Cancel queued cover loads, abort a slow in-flight MMCE read, and drain. The
    // drain returns as soon as the art queue is empty (cacheWaitForAllRequestsTimed
    // early-exits when nothing is queued/active), so this adds no delay in the
    // common case; the timeout only bounds a genuinely stuck read.
    int abortOk = cacheAbortMmceImageLoadsTimed(500);
    int cancelOk = cacheCancelPendingImageLoadsTimed(500);
    if (!abortOk || !cancelOk) {
        // A cover-art read did not drain within the timeout -- most likely a slow
        // (not dead) storage device. We still issue the deferred IO below: bailing
        // here would silently drop a valid config save on a merely-slow card, and
        // could not unwedge a genuinely stuck IOP RPC channel anyway. Logged so a
        // true hardware hang is diagnosable rather than a silent freeze on the
        // unbounded wait below (Codex audit, Medium 1).
        LOG("guiHandleDeferedIO: art drain timed out; deferred IO may stall on stuck storage\n");
    }

    if (ioPutRequest(type, data) != IO_OK) {
        *ptr = 0;
        return;
    }

    // Belt-and-suspenders: lower our (GUI thread) priority while busy-waiting so
    // any art work that slips in afterwards can still reach a yield point and
    // release the channel. Restored before returning; the handshake is unchanged.
    int savedPriority = cacheLowerCallerPriority();

    while (*ptr)
        guiRenderTextScreen(message);

    cacheRestoreCallerPriority(savedPriority);
}

void guiGameHandleDeferedIO(int *ptr, struct UIItem *ui, int type, void *data)
{
    if (ioPutRequest(type, data) != IO_OK) {
        *ptr = 0;
        return;
    }

    while (*ptr) {
        guiStartFrame();
        if (ui)
            diaRenderUI(ui, screenHandler->inMenu, NULL, 0);
        else
            guiShow();
        guiEndFrame();
    }
}

void guiRenderTextScreen(const char *message)
{
    guiStartFrame();

    guiShow();

    rmDrawRect(0, 0, screenWidth, screenHeight, gColDarker);

    fntRenderString(gTheme->fonts[0], screenWidth >> 1, gTheme->usedHeight >> 1, ALIGN_CENTER, 0, 0, message, gTheme->textColor);

    guiDrawOverlays();

    guiEndFrame();
}

// ---- Visual GameID barcode (Pixel FX / RetroGEM / PS2Digital HDMI auto-profile) ----
// Renders the CosmicScale "GameID" barcode just before a game is handed to its core, so an HDMI
// scaler can auto-load that game's per-title display profile. Encoding is the canonical CosmicScale
// scheme (start word 0xA5 / end word 0xD5 / length byte / additive 0x100-sum checksum), drawn with
// rmDrawRect exactly as CosmicScale's own OPL fork does. Gated behind gApplyGameID (default OFF) --
// the pattern is meaningless to non-GameID displays, and the actual HDMI latch is only verifiable on
// real GameID hardware (experimental until a tester confirms).

#define GAMEID_HOLD_FRAMES 45 // ~0.75s @ 60fps -- enough stable frames for a scaler to sample

// Normalise a startup id into the serial the GameID device expects: drop a POPS "XX."/"SB." prefix and
// a trailing ".elf"/".ELF", cap at 11 chars (e.g. "SLUS_200.02"). Copied VERBATIM (no case fold) to
// stay byte-identical to CosmicScale's HW-validated guiSetGameId; retail serials are already uppercase.
static void gameIDCleanSerial(const char *startup, char *out, int outSize)
{
    int i = 0, len;
    const char *src = startup;

    out[0] = '\0';
    if (src == NULL)
        return;

    if (!strncmp(src, "XX.", 3) || !strncmp(src, "SB.", 3))
        src += 3;

    while (src[i] != '\0' && i < outSize - 1) {
        out[i] = src[i];
        i++;
    }
    out[i] = '\0';

    len = (int)strlen(out);
    if (len >= 4 && !strcasecmp(&out[len - 4], ".elf"))
        out[len - 4] = '\0';
    if (strlen(out) > 11)
        out[11] = '\0';
}

// Build the GameID packet from a cleaned serial; returns its length in bytes.
static int gameIDBuildPacket(u8 *data, const char *serial)
{
    int n = 0, i, sum = 0, crcpos;
    int gidlen = (int)strlen(serial);
    if (gidlen > 11)
        gidlen = 11;

    data[n++] = 0xA5;       // start / detect word
    data[n++] = 0x00;       // address offset
    crcpos = n++;           // checksum placeholder (data[2])
    data[n++] = (u8)gidlen; // payload length
    for (i = 0; i < gidlen; i++)
        data[n++] = (u8)serial[i];
    data[n++] = 0x00;
    data[n++] = 0xD5; // end word
    data[n++] = 0x00; // padding

    for (i = 3; i < n; i++) // additive 8-bit checksum over {length byte .. end}
        sum += data[i];
    data[crcpos] = (u8)(0x100 - (sum & 0xFF));
    return n;
}

// Draw the barcode once: per data bit (MSB-first) a magenta clock column + a cyan(1)/yellow(0) column.
static void gameIDDrawBars(const char *startup)
{
    u8 data[32];
    char serial[16];
    int data_len, i, ii, xstart, ystart;

    gameIDCleanSerial(startup, serial, sizeof(serial));
    if (serial[0] == '\0')
        return;

    data_len = gameIDBuildPacket(data, serial);
    xstart = (screenWidth / 2) - (data_len * 8); // centered horizontally
    ystart = screenHeight - ((screenHeight / 8) * 2 + 20);

    for (i = 0; i < data_len; i++) {
        for (ii = 7; ii >= 0; ii--) {
            int x = xstart + (i * 16 + (7 - ii) * 2);
            rmDrawRect(x, ystart, 1, 2, GS_SETREG_RGBA(0xFF, 0x00, 0xFF, 0x80)); // magenta clock col
            rmDrawRect(x + 1, ystart, 1, 2,
                       ((data[i] >> ii) & 1) ? GS_SETREG_RGBA(0x00, 0xFF, 0xFF, 0x80) // cyan = 1
                                               :
                                               GS_SETREG_RGBA(0xFF, 0xFF, 0x00, 0x80)); // yellow = 0
        }
    }
}

void guiShowGameID(const char *startup)
{
    int frame;

    if (!gApplyGameID || startup == NULL || startup[0] == '\0')
        return;

    // Hold the barcode on a clean black field for a few frames so an HDMI scaler can latch it.
    for (frame = 0; frame < GAMEID_HOLD_FRAMES; frame++) {
        guiStartFrame();
        rmDrawRect(0, 0, screenWidth, screenHeight, GS_SETREG_RGBA(0x00, 0x00, 0x00, 0x80));
        gameIDDrawBars(startup);
        guiEndFrame();
    }
}

void guiWarning(const char *text, int count)
{
    guiStartFrame();

    guiShow();

    rmDrawRect(0, 0, screenWidth, screenHeight, gColDarker);

    rmDrawLine(50, 75, screenWidth - 50, 75, gColWhite);
    rmDrawLine(50, 410, screenWidth - 50, 410, gColWhite);

    fntRenderString(gTheme->fonts[0], screenWidth >> 1, gTheme->usedHeight >> 1, ALIGN_CENTER, screenWidth, screenHeight, text, gTheme->textColor);

    guiEndFrame();

    delay(count);
}

int guiConfirmVideoMode(void)
{
    clock_t timeEnd;
    int terminate = 0;

    sfxPlay(SFX_MESSAGE);

    timeEnd = clock() + OPL_VMODE_CHANGE_CONFIRMATION_TIMEOUT_MS * (CLOCKS_PER_SEC / 1000);
    while (!terminate) {
        guiStartFrame();

        readPads();

        if (getKeyOn(gSelectButton == KEY_CIRCLE ? KEY_CROSS : KEY_CIRCLE))
            terminate = 1;
        else if (getKeyOn(gSelectButton))
            terminate = 2;

        // If the user fails to respond within the timeout period, deem it as a cancel operation.
        if (clock() > timeEnd)
            terminate = 1;

        guiShow();

        rmDrawRect(0, 0, screenWidth, screenHeight, gColDarker);

        rmDrawLine(50, 75, screenWidth - 50, 75, gColWhite);
        rmDrawLine(50, 410, screenWidth - 50, 410, gColWhite);

        fntRenderString(gTheme->fonts[0], screenWidth >> 1, gTheme->usedHeight >> 1, ALIGN_CENTER, 0, 0, _l(_STR_CFM_VMODE_CHG), gTheme->textColor);
        guiDrawIconAndText(gSelectButton == KEY_CIRCLE ? CROSS_ICON : CIRCLE_ICON, _STR_BACK, gTheme->fonts[0], 500, 417, gTheme->selTextColor);
        guiDrawIconAndText(gSelectButton == KEY_CIRCLE ? CIRCLE_ICON : CROSS_ICON, _STR_ACCEPT, gTheme->fonts[0], 70, 417, gTheme->selTextColor);

        guiEndFrame();
    }

    if (terminate == 1) {
        sfxPlay(SFX_CANCEL);
    }
    if (terminate == 2) {
        sfxPlay(SFX_CONFIRM);
    }

    return terminate - 1;
}

int guiGameShowRemoveSettings(config_set_t *configSet, config_set_t *configGame)
{
    int terminate = 0;
    char message[256];

    sfxPlay(SFX_MESSAGE);

    while (!terminate) {
        guiStartFrame();

        readPads();

        if (getKeyOn(gSelectButton == KEY_CIRCLE ? KEY_CROSS : KEY_CIRCLE))
            terminate = 1;
        else if (getKeyOn(gSelectButton))
            terminate = 2;
        else if (getKeyOn(KEY_SQUARE))
            terminate = 3;
        else if (getKeyOn(KEY_TRIANGLE))
            terminate = 4;

        guiShow();

        rmDrawRect(0, 0, screenWidth, screenHeight, gColDarker);

        rmDrawLine(50, 75, screenWidth - 50, 75, gColWhite);
        rmDrawLine(50, 410, screenWidth - 50, 410, gColWhite);

        fntRenderString(gTheme->fonts[0], screenWidth >> 1, gTheme->usedHeight >> 1, ALIGN_CENTER, 0, 0, _l(_STR_GAME_SETTINGS_PROMPT), gTheme->textColor);

        guiDrawIconAndText(gSelectButton == KEY_CIRCLE ? CROSS_ICON : CIRCLE_ICON, _STR_BACK, gTheme->fonts[0], 500, 417, gTheme->selTextColor);
        guiDrawIconAndText(SQUARE_ICON, _STR_GLOBAL_SETTINGS, gTheme->fonts[0], 213, 417, gTheme->selTextColor);
        guiDrawIconAndText(TRIANGLE_ICON, _STR_ALL_SETTINGS, gTheme->fonts[0], 356, 417, gTheme->selTextColor);
        guiDrawIconAndText(gSelectButton == KEY_CIRCLE ? CIRCLE_ICON : CROSS_ICON, _STR_PERGAME_SETTINGS, gTheme->fonts[0], 70, 417, gTheme->selTextColor);

        guiEndFrame();
    }

    if (terminate == 1) {
        sfxPlay(SFX_CANCEL);
        return 0;
    } else if (terminate == 2) {
        guiGameRemoveSettings(configSet);
        snprintf(message, sizeof(message), _l(_STR_GAME_SETTINGS_REMOVED), _l(_STR_PERGAME_SETTINGS));
    } else if (terminate == 3) {
        guiGameRemoveGlobalSettings(configGame);
        snprintf(message, sizeof(message), _l(_STR_GAME_SETTINGS_REMOVED), _l(_STR_GLOBAL_SETTINGS));
    } else if (terminate == 4) {
        guiGameRemoveSettings(configSet);
        guiGameRemoveGlobalSettings(configGame);
        snprintf(message, sizeof(message), _l(_STR_GAME_SETTINGS_REMOVED), _l(_STR_ALL_SETTINGS));
    }
    sfxPlay(SFX_CONFIRM);
    guiMsgBox(message, 0, NULL);

    return 1;
}

void guiManageCheats(void)
{
    int offset = 0;
    int terminate = 0;
    int cheatCount = 0;
    int selectedCheat = 0;
    int visibleCheats = 10; // Maximum number of cheats visible on screen

    while (cheatCount < MAX_CODES && strlen(gCheats[cheatCount].name) > 0)
        cheatCount++;

    sfxPlay(SFX_MESSAGE);

    while (!terminate) {
        guiStartFrame();
        readPads();

        if (getKeyOn(KEY_UP) && selectedCheat > 0) {
            selectedCheat -= 1;
            if (selectedCheat < offset)
                offset = selectedCheat;
        }

        if (getKeyOn(KEY_DOWN) && selectedCheat < cheatCount - 1) {
            selectedCheat += 1;
            if (selectedCheat >= offset + visibleCheats)
                offset = selectedCheat - visibleCheats + 1;
        }

        if (getKeyOn(gSelectButton)) {
            if (!(strncasecmp(gCheats[selectedCheat].name, "mastercode", 10) == 0 || strncasecmp(gCheats[selectedCheat].name, "master code", 11) == 0))
                gCheats[selectedCheat].enabled = !gCheats[selectedCheat].enabled;
        }

        if (getKeyOn(KEY_START))
            terminate = 1;

        guiShow();

        rmDrawRect(0, 0, screenWidth, screenHeight, gColDarker);
        rmDrawLine(50, 75, screenWidth - 50, 75, gColWhite);
        rmDrawLine(50, 410, screenWidth - 50, 410, gColWhite);

        fntRenderString(gTheme->fonts[0], screenWidth >> 1, 60, ALIGN_CENTER, 0, 0, _l(_STR_CHEAT_SELECTION), gTheme->textColor);

        int renderedCheats = 0;
        for (int i = offset; renderedCheats < visibleCheats && i < cheatCount; i++) {
            if (strlen(gCheats[i].name) == 0)
                continue;

            int enabled = gCheats[i].enabled;

            int boxX = 50;
            int boxY = 100 + (renderedCheats * 30);
            int boxWidth = rmWideScale(25);
            int boxHeight = 17;

            if (enabled) {
                rmDrawRect(boxX, boxY + 3, boxWidth, boxHeight, gTheme->textColor);
                rmDrawRect(boxX + 2, boxY + 5, boxWidth - 4, boxHeight - 4, gTheme->selTextColor);
            }

            u32 textColour = (i == selectedCheat) ? gTheme->selTextColor : gTheme->textColor;
            fntRenderString(gTheme->fonts[0], boxX + 35, boxY + 3, ALIGN_LEFT, 0, 0, gCheats[i].name, textColour);

            renderedCheats++;
        }

        guiDrawIconAndText(gSelectButton == KEY_CIRCLE ? CIRCLE_ICON : CROSS_ICON, _STR_SELECT, gTheme->fonts[0], 70, 417, gTheme->selTextColor);
        guiDrawIconAndText(START_ICON, _STR_RUN, gTheme->fonts[0], 500, 417, gTheme->selTextColor);

        guiEndFrame();
    }

    sfxPlay(SFX_CONFIRM);
}
