/*
  Copyright 2009, Ifcaro & volca
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.
*/

#include "include/opl.h"
#include "include/menusys.h"
#include "include/iosupport.h"
#include "include/favsupport.h"
#include "include/bdmsupport.h"
#include "include/vcdsupport.h" // vcdViewActive -- VCD view renders with the apps element family
#include "include/renderman.h"
#include "include/fntsys.h"
#include "include/lang.h"
#include "include/themes.h"
#include "include/pad.h"
#include "include/gui.h"
#include "include/guigame.h"
#include "include/system.h"
#include "include/ioman.h"
#include "include/sound.h"
#include "include/texcache.h"
#include <assert.h>

enum MENU_IDs {
    MENU_SETTINGS = 0,
    MENU_DEVICE_SETTINGS,
    MENU_GFX_SETTINGS,
    MENU_AUDIO_SETTINGS,
    MENU_CONTROLLER_SETTINGS,
    MENU_OSD_LANGUAGE_SETTINGS,
    MENU_PARENTAL_LOCK,
    MENU_NET_CONFIG,
    MENU_NET_UPDATE,
    MENU_START_NBD,
    MENU_ABOUT,
    MENU_SAVE_CHANGES,
    MENU_EXIT,
    MENU_POWER_OFF,
    MENU_LAUNCH_PS2_DISC
};

enum GAME_MENU_IDs {
    GAME_COMPAT_SETTINGS = 0,
    GAME_CHEAT_SETTINGS,
    GAME_GSM_SETTINGS,
    GAME_VMC_SETTINGS,
#ifdef PADEMU
    GAME_PADEMU_SETTINGS,
    GAME_PADMACRO_SETTINGS,
#endif
    GAME_OSD_LANGUAGE_SETTINGS,
    GAME_SAVE_CHANGES,
    GAME_TEST_CHANGES,
    GAME_REMOVE_CHANGES,
    GAME_RENAME_GAME,
    GAME_DELETE_GAME,
};

// global menu variables
static menu_list_t *menu;
static menu_list_t *selected_item;

static int actionStatus;
static int itemConfigId;
static config_set_t *itemConfig;

static u8 parentalLockCheckEnabled = 1;

// "main menu submenu"
static submenu_list_t *mainMenu;
// active item in the main menu
static submenu_list_t *mainMenuCurrent;

// "game settings submenu"
static submenu_list_t *gameMenu;
// active item in game settings
static submenu_list_t *gameMenuCurrent;

static submenu_list_t *appMenu;
static submenu_list_t *appMenuCurrent;

static s32 menuSemaId = -1;
static s32 menuListSemaId = -1;
static ee_sema_t menuSema;

#define MENU_MMCE_CONFIG_IDLE_FRAMES 20
#define MENU_APP_CONFIG_IDLE_FRAMES  1

static void menuInvalidateArtSelection(void)
{
    cacheAdvanceGeneration();
}

static int menuCanRequestItemConfig(item_list_t *list)
{
    if (list != NULL && list->mode == APP_MODE)
        return guiInactiveFrames >= MENU_APP_CONFIG_IDLE_FRAMES;

    if (cacheHasPendingInteractiveArt())
        return 0;

    if (list != NULL && list->mode == MMCE_MODE)
        return guiInactiveFrames >= MENU_MMCE_CONFIG_IDLE_FRAMES;

    return 1;
}

static void menuAdvanceArtSelectionOnMove(void)
{
    item_list_t *support = selected_item != NULL ? (item_list_t *)selected_item->item->userdata : NULL;

    /* Keep APP prefetch, but drop stale interactive work from prior selections. */
    if (support != NULL && support->mode == APP_MODE)
        cacheAdvanceGenerationPreservePrefetch();
    else
        cacheAdvanceGeneration();
}

static void menuRenameGame(submenu_list_t **submenu)
{
    if (!selected_item->item->current) {
        return;
    }

    if (!gEnableWrite)
        return;

    item_list_t *support = selected_item->item->userdata;

    // Favourites: rename is blocked from the FAV tab and on any favourited source item.
    if (support && support->mode == FAV_MODE) {
        char text[128];
        snprintf(text, sizeof(text), _l(_STR_FAV_MSG), _l(_STR_RENAME));
        guiMsgBox(text, 0, NULL);
        return;
    }
    if (selected_item->item->current->item.favourited) {
        char text[128];
        snprintf(text, sizeof(text), _l(_STR_FAV_PERSISTENCE_MSG), _l(_STR_RENAME));
        guiMsgBox(text, 0, NULL);
        return;
    }

    if (support) {
        if (support->itemRename) {
            if (menuCheckParentalLock() == 0) {
                sfxPlay(SFX_MESSAGE);
                int nameLength = support->itemGetNameLength(support, selected_item->item->current->item.id);
                char newName[nameLength];
                strncpy(newName, selected_item->item->current->item.text, nameLength);
                if (guiShowKeyboard(newName, nameLength)) {
                    guiSwitchScreen(GUI_SCREEN_MAIN);
                    submenuDestroy(submenu);

                    // Only rename the file if the name changed; trying to rename a file with a file name that hasn't changed can cause the file
                    // to be deleted on certain file systems.
                    if (strcmp(newName, selected_item->item->current->item.text) != 0) {
                        support->itemRename(support, selected_item->item->current->item.id, newName);
                        ioPutRequest(IO_MENU_UPDATE_DEFFERED, &support->mode);
                    }
                }
            }
        }
    } else
        guiMsgBox("NULL Support object. Please report", 0, NULL);
}

static void menuDeleteGame(submenu_list_t **submenu)
{
    if (!selected_item->item->current)
        return;

    if (!gEnableWrite)
        return;

    item_list_t *support = selected_item->item->userdata;

    // Favourites: delete is blocked from the FAV tab and on any favourited source item.
    if (support && support->mode == FAV_MODE) {
        char text[128];
        snprintf(text, sizeof(text), _l(_STR_FAV_MSG), _l(_STR_DELETE));
        guiMsgBox(text, 0, NULL);
        return;
    }
    if (selected_item->item->current->item.favourited) {
        char text[128];
        snprintf(text, sizeof(text), _l(_STR_FAV_PERSISTENCE_MSG), _l(_STR_DELETE));
        guiMsgBox(text, 0, NULL);
        return;
    }

    if (support) {
        if (support->itemDelete) {
            if (menuCheckParentalLock() == 0) {
                if (guiMsgBox(_l(_STR_DELETE_WARNING), 1, NULL)) {
                    guiSwitchScreen(GUI_SCREEN_MAIN);
                    submenuDestroy(submenu);
                    support->itemDelete(support, selected_item->item->current->item.id);
                    ioPutRequest(IO_MENU_UPDATE_DEFFERED, &support->mode);
                }
            }
        }
    } else
        guiMsgBox("NULL Support object. Please report", 0, NULL);
}

static void _menuLoadConfig()
{
    int blockingLoad = 0;
    item_list_t *list = NULL;
    config_set_t *loadedConfig = NULL;
    int configId = -1;

    WaitSema(menuSemaId);
    blockingLoad = actionStatus != 0;
    if (!itemConfig && selected_item != NULL && selected_item->item->current != NULL && itemConfigId >= 0) {
        list = selected_item->item->userdata;
        configId = itemConfigId;
    }
    SignalSema(menuSemaId);

    if (blockingLoad)
        (void)cacheCancelPendingImageLoadsTimed(MENU_MIN_INACTIVE_FRAMES);

    if (list != NULL)
        loadedConfig = list->itemGetConfig(list, configId);

    WaitSema(menuSemaId);
    if (!itemConfig && loadedConfig != NULL && itemConfigId == configId)
        itemConfig = loadedConfig;
    else if (loadedConfig != NULL)
        configFree(loadedConfig);
    actionStatus = 0;
    SignalSema(menuSemaId);
}

static void _menuSaveConfig()
{
    int result;

    WaitSema(menuSemaId);
    result = configWrite(itemConfig);
    itemConfigId = -1; // to invalidate cache and force reload
    actionStatus = 0;
    SignalSema(menuSemaId);

    if (!result)
        setErrorMessage(_STR_ERROR_SAVING_SETTINGS);
}

static void _menuRequestConfig()
{
    int shouldQueueLoad = 0;

    WaitSema(menuSemaId);
    if (selected_item == NULL || selected_item->item == NULL || selected_item->item->current == NULL) {
        actionStatus = 0;
    } else if (itemConfigId != selected_item->item->current->item.id) {
        if (itemConfig) {
            configFree(itemConfig);
            itemConfig = NULL;
        }
        item_list_t *list = selected_item->item->userdata;
        int configIdleFrames = list->mode == APP_MODE ? MENU_APP_CONFIG_IDLE_FRAMES : list->delay;

        if (itemConfigId == -1 || guiInactiveFrames >= configIdleFrames) {
            itemConfigId = selected_item->item->current->item.id;
            shouldQueueLoad = 1;
        }
    } else if (itemConfig == NULL && actionStatus != 0) {
        shouldQueueLoad = 1;
    } else
        actionStatus = 0;

    SignalSema(menuSemaId);

    if (shouldQueueLoad && ioPutRequest(IO_CUSTOM_SIMPLEACTION, &_menuLoadConfig) != IO_OK) {
        WaitSema(menuSemaId);
        actionStatus = 0;
        SignalSema(menuSemaId);
    }
}

static config_set_t *menuLoadConfigDirectInternal(void)
{
    config_set_t *loadedConfig = NULL;
    config_set_t *result = NULL;
    item_list_t *list = NULL;
    int configId = -1;

    WaitSema(menuSemaId);
    if (selected_item != NULL && selected_item->item != NULL && selected_item->item->current != NULL) {
        list = selected_item->item->userdata;
        configId = selected_item->item->current->item.id;

        if (itemConfigId == configId && itemConfig != NULL) {
            result = itemConfig;
        } else {
            if (itemConfig != NULL) {
                configFree(itemConfig);
                itemConfig = NULL;
            }
            itemConfigId = configId;
        }
    } else {
        if (itemConfig != NULL) {
            configFree(itemConfig);
            itemConfig = NULL;
        }
        itemConfigId = -1;
    }
    SignalSema(menuSemaId);

    if (result != NULL || list == NULL || configId < 0)
        return result;

    if (list->mode == MMCE_MODE) {
        /* Signal the art loader to abort, but do not block waiting for it to
         * drain.  The MMCE config read that follows will simply be serialised
         * behind the current art chunk in the IOP queue (typically ≤ 20 ms).
         * A blocking wait here froze navigation for up to 60 ms on every
         * CROSS/CIRCLE press and – if the abort timed out – triggered a
         * TerminateThread that corrupted the fileXio RPC channel, causing art
         * to stop loading for the rest of the session. */
        cacheAbortMmceImageLoadsTimed(0);
    } else
        (void)cacheCancelPendingImageLoadsTimed(MENU_MIN_INACTIVE_FRAMES);
    loadedConfig = list->itemGetConfig(list, configId);

    WaitSema(menuSemaId);
    if (itemConfigId == configId && itemConfig == NULL)
        itemConfig = loadedConfig;
    else if (loadedConfig != NULL)
        configFree(loadedConfig);
    result = itemConfig;
    SignalSema(menuSemaId);

    return result;
}

config_set_t *menuLoadConfig()
{
    actionStatus = 1;
    itemConfigId = -1;
    guiHandleDeferedIO(&actionStatus, _l(_STR_LOADING_SETTINGS), IO_CUSTOM_SIMPLEACTION, &_menuRequestConfig);
    return itemConfig;
}

config_set_t *menuLoadConfigDirect(void)
{
    actionStatus = 0;
    return menuLoadConfigDirectInternal();
}

// we don't want a pop up when transitioning to or refreshing Game Menu gui.
config_set_t *gameMenuLoadConfig(struct UIItem *ui)
{
    actionStatus = 1;
    itemConfigId = -1;
    guiGameHandleDeferedIO(&actionStatus, ui, IO_CUSTOM_SIMPLEACTION, &_menuRequestConfig);
    return itemConfig;
}

void menuSaveConfig()
{
    actionStatus = 1;
    guiHandleDeferedIO(&actionStatus, _l(_STR_SAVING_SETTINGS), IO_CUSTOM_SIMPLEACTION, &_menuSaveConfig);
}

static void menuInitMainMenu(void)
{
    if (mainMenu)
        submenuDestroy(&mainMenu);

    // initialize the menu
    submenuAppendItem(&mainMenu, -1, NULL, MENU_LAUNCH_PS2_DISC, _STR_LAUNCH_PS2_DISC, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_SETTINGS, _STR_GENERAL_SETTINGS, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_DEVICE_SETTINGS, _STR_DEVICE_SETTINGS, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_GFX_SETTINGS, _STR_GFX_SETTINGS, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_AUDIO_SETTINGS, _STR_AUDIO_SETTINGS, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_CONTROLLER_SETTINGS, _STR_CONTROLLER_SETTINGS, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_OSD_LANGUAGE_SETTINGS, _STR_OSD_SETTINGS, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_PARENTAL_LOCK, _STR_PARENLOCKCONFIG, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_NET_CONFIG, _STR_NETCONFIG, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_NET_UPDATE, _STR_NET_UPDATE, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_START_NBD, _STR_STARTNBD, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_ABOUT, _STR_ABOUT, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_SAVE_CHANGES, _STR_SAVE_CHANGES, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_EXIT, _STR_EXIT, NULL);
    submenuAppendItem(&mainMenu, -1, NULL, MENU_POWER_OFF, _STR_POWEROFF, NULL);

    mainMenuCurrent = mainMenu;
}

void menuReinitMainMenu(void)
{
    menuInitMainMenu();
}

void menuInitGameMenu(void)
{
    if (gameMenu)
        submenuDestroy(&gameMenu);

    // initialize the menu
    submenuAppendItem(&gameMenu, -1, NULL, GAME_COMPAT_SETTINGS, _STR_COMPAT_SETTINGS, NULL);
    submenuAppendItem(&gameMenu, -1, NULL, GAME_CHEAT_SETTINGS, _STR_CHEAT_SETTINGS, NULL);
    submenuAppendItem(&gameMenu, -1, NULL, GAME_GSM_SETTINGS, _STR_GSCONFIG, NULL);
    submenuAppendItem(&gameMenu, -1, NULL, GAME_VMC_SETTINGS, _STR_VMC_SCREEN, NULL);
#ifdef PADEMU
    submenuAppendItem(&gameMenu, -1, NULL, GAME_PADEMU_SETTINGS, _STR_PADEMUCONFIG, NULL);
    submenuAppendItem(&gameMenu, -1, NULL, GAME_PADMACRO_SETTINGS, _STR_PADMACROCONFIG, NULL);
#endif
    submenuAppendItem(&gameMenu, -1, NULL, GAME_OSD_LANGUAGE_SETTINGS, _STR_OSD_SETTINGS, NULL);
    submenuAppendItem(&gameMenu, -1, NULL, GAME_SAVE_CHANGES, _STR_SAVE_CHANGES, NULL);
    submenuAppendItem(&gameMenu, -1, NULL, GAME_TEST_CHANGES, _STR_TEST, NULL);
    submenuAppendItem(&gameMenu, -1, NULL, GAME_REMOVE_CHANGES, _STR_REMOVE_ALL_SETTINGS, NULL);
    if (gEnableWrite) {
        submenuAppendItem(&gameMenu, -1, NULL, GAME_RENAME_GAME, _STR_RENAME, NULL);
        submenuAppendItem(&gameMenu, -1, NULL, GAME_DELETE_GAME, _STR_DELETE, NULL);
    }

    gameMenuCurrent = gameMenu;
}

void menuInitAppMenu(void)
{
    if (appMenu)
        submenuDestroy(&appMenu);

    // initialize the menu
    submenuAppendItem(&appMenu, -1, NULL, 0, _STR_RENAME, NULL);
    submenuAppendItem(&appMenu, -1, NULL, 1, _STR_DELETE, NULL);

    appMenuCurrent = appMenu;
}

// -------------------------------------------------------------------------------------------
// ---------------------------------------- Menu manipulation --------------------------------
// -------------------------------------------------------------------------------------------
void menuInit()
{
    menu = NULL;
    selected_item = NULL;
    itemConfigId = -1;
    itemConfig = NULL;
    mainMenu = NULL;
    mainMenuCurrent = NULL;
    gameMenu = NULL;
    gameMenuCurrent = NULL;
    appMenu = NULL;
    appMenuCurrent = NULL;
    menuInitMainMenu();

    // Create once; recreating on a second menuInit would leak the prior semaphore.
    if (menuSemaId < 0) {
        menuSema.init_count = 1;
        menuSema.max_count = 1;
        menuSema.option = 0;
        menuSemaId = CreateSema(&menuSema);
    }
    if (menuListSemaId < 0) {
        menuListSemaId = sbCreateSemaphore();
    }
}

void menuEnd()
{
    // destroy menu
    menu_list_t *cur = menu;

    while (cur) {
        menu_list_t *td = cur;
        cur = cur->next;

        if (td->item)
            submenuDestroy(&(td->item->submenu));

        menuRemoveHints(td->item);

        free(td);
    }

    submenuDestroy(&mainMenu);
    submenuDestroy(&gameMenu);
    submenuDestroy(&appMenu);

    if (itemConfig) {
        configFree(itemConfig);
        itemConfig = NULL;
    }

    DeleteSema(menuSemaId);
    menuSemaId = -1;
    DeleteSema(menuListSemaId);
    menuListSemaId = -1;
}

static menu_list_t *AllocMenuItem(menu_item_t *item)
{
    menu_list_t *it;

    it = malloc(sizeof(menu_list_t));

    it->prev = NULL;
    it->next = NULL;
    it->item = item;

    return it;
}

void menuAppendItem(menu_item_t *item)
{
    assert(item);

    WaitSema(menuListSemaId);

    if (menu == NULL) {
        menu = AllocMenuItem(item);
        selected_item = menu;
    } else {
        menu_list_t *cur = menu;

        // traverse till the end
        while (cur->next)
            cur = cur->next;

        // create new item
        menu_list_t *newitem = AllocMenuItem(item);

        // link
        cur->next = newitem;
        newitem->prev = cur;
    }

    SignalSema(menuListSemaId);
}

static void refreshMenuPosition(void)
{
    // Find the first menu in the list that is visible and set it as the active menu.
    if (menu == NULL)
        return;

    menu_list_t *cur = menu;
    while (cur->item->visible == 0 && cur->next)
        cur = cur->next;

    if (cur->item->visible == 0) {
        // No visible menu was found, just set the current menu to the first one in the list.
        selected_item = menu;
    } else {
        selected_item = cur;
    }

    menuInvalidateArtSelection();
}

void submenuRebuildCache(submenu_list_t *submenu)
{
    while (submenu) {
        if (submenu->item.cache_id)
            free(submenu->item.cache_id);
        if (submenu->item.cache_uid)
            free(submenu->item.cache_uid);

        int size = gTheme->gameCacheCount * sizeof(int);
        submenu->item.cache_id = malloc(size);
        memset(submenu->item.cache_id, -1, size);
        submenu->item.cache_uid = malloc(size);
        memset(submenu->item.cache_uid, -1, size);

        submenu = submenu->next;
    }
}

static submenu_list_t *submenuAllocItem(int icon_id, char *text, int id, int text_id, void *owner)
{
    submenu_list_t *it = (submenu_list_t *)malloc(sizeof(submenu_list_t));

    it->prev = NULL;
    it->next = NULL;
    it->item.icon_id = icon_id;
    it->item.text = text;
    it->item.text_id = text_id;
    it->item.id = id;
    it->item.cache_id = NULL;
    it->item.cache_uid = NULL;
    it->item.owner = owner;
    it->item.favourited = 0;
    submenuRebuildCache(it);

    return it;
}

submenu_list_t *submenuAppendItem(submenu_list_t **submenu, int icon_id, char *text, int id, int text_id, void *owner)
{
    if (*submenu == NULL) {
        *submenu = submenuAllocItem(icon_id, text, id, text_id, owner);
        return *submenu;
    }

    submenu_list_t *cur = *submenu;

    // traverse till the end
    while (cur->next)
        cur = cur->next;

    // create new item
    submenu_list_t *newitem = submenuAllocItem(icon_id, text, id, text_id, owner);

    // link
    cur->next = newitem;
    newitem->prev = cur;

    return newitem;
}

// Linear search by id + text. Favourites uses this to locate the source-list item so the
// favourited flag (star) stays in sync on both the FAV copy and the source copy. Both text
// args are NULL-guarded before strcmp.
submenu_list_t *submenuFindItemByIdAndText(submenu_list_t *submenu, int id, const char *text)
{
    submenu_list_t *cur = submenu;
    while (cur) {
        if (cur->item.id == id && text && cur->item.text && !strcmp(cur->item.text, text))
            return cur;
        cur = cur->next;
    }
    return NULL;
}

static void submenuDestroyItem(submenu_list_t *submenu)
{
    free(submenu->item.cache_id);
    free(submenu->item.cache_uid);

    free(submenu);
}

void submenuRemoveItem(submenu_list_t **submenu, int id)
{
    submenu_list_t *cur = *submenu;
    submenu_list_t *prev = NULL;

    while (cur) {
        if (cur->item.id == id) {
            submenu_list_t *next = cur->next;

            if (prev)
                prev->next = cur->next;

            if (*submenu == cur)
                *submenu = next;

            submenuDestroyItem(cur);

            cur = next;
        } else {
            prev = cur;
            cur = cur->next;
        }
    }
}

void submenuDestroy(submenu_list_t **submenu)
{
    // destroy sub menu
    submenu_list_t *cur = *submenu;

    while (cur) {
        submenu_list_t *td = cur;
        cur = cur->next;

        submenuDestroyItem(td);
    }

    *submenu = NULL;
}

void menuAddHint(menu_item_t *menu, int text_id, int icon_id)
{
    // allocate a new hint item
    menu_hint_item_t *hint = malloc(sizeof(menu_hint_item_t));

    hint->text_id = text_id;
    hint->icon_id = icon_id;
    hint->next = NULL;

    if (menu->hints) {
        menu_hint_item_t *top = menu->hints;

        // rewind to end
        for (; top->next; top = top->next)
            ;

        top->next = hint;
    } else {
        menu->hints = hint;
    }
}

void menuRemoveHints(menu_item_t *menu)
{
    while (menu->hints) {
        menu_hint_item_t *hint = menu->hints;
        menu->hints = hint->next;
        free(hint);
    }
}

char *menuItemGetText(menu_item_t *it)
{
    if (it->text_id >= 0)
        return _l(it->text_id);
    else
        return it->text;
}

char *submenuItemGetText(submenu_item_t *it)
{
    if (it->text_id >= 0)
        return _l(it->text_id);
    else
        return it->text;
}

static void swap(submenu_list_t *a, submenu_list_t *b)
{
    submenu_list_t *pa, *nb;
    pa = a->prev;
    nb = b->next;

    a->next = nb;
    b->prev = pa;
    b->next = a;
    a->prev = b;

    if (pa)
        pa->next = b;

    if (nb)
        nb->prev = a;
}

// Sorts the given submenu by comparing the on-screen titles
void submenuSort(submenu_list_t **submenu)
{
    // a simple bubblesort
    // *submenu = mergeSort(*submenu);
    submenu_list_t *head;
    int sorted = 0;

    if ((submenu == NULL) || (*submenu == NULL) || ((*submenu)->next == NULL))
        return;

    head = *submenu;

    while (!sorted) {
        sorted = 1;

        submenu_list_t *tip = head;

        while (tip->next) {
            submenu_list_t *nxt = tip->next;

            char *txt1 = submenuItemGetText(&tip->item);
            char *txt2 = submenuItemGetText(&nxt->item);

            int cmp = strcasecmp(txt1, txt2);

            if (cmp > 0) {
                swap(tip, nxt);

                if (tip == head)
                    head = nxt;

                sorted = 0;
            } else {
                tip = tip->next;
            }
        }
    }

    *submenu = head;
}

static void menuNextH()
{
    struct menu_list *next = selected_item->next;
    while (next != NULL && next->item->visible == 0)
        next = next->next;

    // If we found a valid menu transition to it.
    if (next != NULL) {
        selected_item = next;
        itemConfigId = -1;
        menuInvalidateArtSelection();
        sfxPlay(SFX_CURSOR);
    }
}

static void menuPrevH()
{
    struct menu_list *prev = selected_item->prev;
    while (prev != NULL && prev->item->visible == 0)
        prev = prev->prev;

    if (prev != NULL) {
        selected_item = prev;
        itemConfigId = -1;
        menuInvalidateArtSelection();
        sfxPlay(SFX_CURSOR);
    }
}

static void menuFirstPage()
{
    submenu_list_t *cur = selected_item->item->current;
    if (cur && cur != selected_item->item->submenu) {
        if (cur->prev) {
            sfxPlay(SFX_CURSOR);
        }

        selected_item->item->current = selected_item->item->submenu;
        selected_item->item->pagestart = selected_item->item->current;
        menuInvalidateArtSelection();
    }
}

static void menuLastPage()
{
    submenu_list_t *cur = selected_item->item->current;
    if (cur && cur->next) {
        if (cur->next) {
            sfxPlay(SFX_CURSOR);
        }
        while (cur->next)
            cur = cur->next; // go to end

        selected_item->item->current = cur;

        int itms = ((items_list_t *)gTheme->itemsList->extended)->displayedItems;
        while (--itms && cur->prev) // and move back to have a full page
            cur = cur->prev;

        selected_item->item->pagestart = cur;
        menuInvalidateArtSelection();
    }
}

static void menuNextV()
{
    submenu_list_t *cur = selected_item->item->current;

    if (cur && cur->next) {
        selected_item->item->current = cur->next;
        sfxPlay(SFX_CURSOR);
        menuAdvanceArtSelectionOnMove();
        // coverflow slide animation; the wrap branch below stays instant
        if (gTheme->coverflow)
            thmTriggerCoverflowAnim(1);

        // if the current item is beyond the page start, move the page start one page down
        cur = selected_item->item->pagestart;
        int itms = ((items_list_t *)gTheme->itemsList->extended)->displayedItems + 1;
        while (--itms && cur)
            if (selected_item->item->current == cur)
                return;
            else
                cur = cur->next;

        selected_item->item->pagestart = selected_item->item->current;
    } else { // wrap to start
        menuFirstPage();
    }
}

static void menuPrevV()
{
    submenu_list_t *cur = selected_item->item->current;

    if (cur && cur->prev) {
        selected_item->item->current = cur->prev;
        sfxPlay(SFX_CURSOR);

        // if the current item is on the page start, move the page start one page up
        if (selected_item->item->pagestart == cur) {
            int itms = ((items_list_t *)gTheme->itemsList->extended)->displayedItems + 1; // +1 because the selection will move as well
            while (--itms && selected_item->item->pagestart->prev)
                selected_item->item->pagestart = selected_item->item->pagestart->prev;
        }

        menuAdvanceArtSelectionOnMove();
        // coverflow slide animation; the wrap branch below stays instant
        if (gTheme->coverflow)
            thmTriggerCoverflowAnim(-1);
    } else { // wrap to end
        menuLastPage();
    }
}

static void menuNextPage()
{
    submenu_list_t *cur = selected_item->item->pagestart;
    int displayed = ((items_list_t *)gTheme->itemsList->extended)->displayedItems;

    // Probe to the item one row past the bottom of the current page. If the end comes first, the
    // whole list already fits on screen -> R1 is a no-op (don't over-scroll a sub-page list, which
    // previously collapsed it to just the last item -- #48).
    submenu_list_t *probe = cur;
    int n = displayed;
    while (n-- && probe)
        probe = probe->next;

    if (cur && probe) {
        int itms = displayed + 1;
        sfxPlay(SFX_CURSOR);

        while (--itms && cur->next)
            cur = cur->next;

        selected_item->item->current = cur;
        selected_item->item->pagestart = selected_item->item->current;
        menuInvalidateArtSelection();
    }
}

static void menuPrevPage()
{
    submenu_list_t *cur = selected_item->item->pagestart;

    if (cur && cur->prev) {
        int itms = ((items_list_t *)gTheme->itemsList->extended)->displayedItems + 1;
        sfxPlay(SFX_CURSOR);

        while (--itms && cur->prev)
            cur = cur->prev;

        selected_item->item->current = cur;
        selected_item->item->pagestart = selected_item->item->current;
        menuInvalidateArtSelection();
    }
    // else: already on the first page -> no action. Page scroll CLAMPS at the
    // boundary (like R1/menuNextPage), it does not wrap. The old wrap called
    // menuLastPage(), which on a multi-page list flung L1 to the LAST page and on
    // a single-page list jumped the SELECTION to the last item -- both reported in
    // issue #48 (the prior #48 fix only clamped R1, leaving this L1 wrap behind).
}

void menuSetSelectedItem(menu_item_t *item)
{
    menu_list_t *itm = menu;

    while (itm) {
        if (itm->item == item) {
            selected_item = itm;
            menuInvalidateArtSelection();
            return;
        }

        itm = itm->next;
    }
}

void menuRenderMenu()
{
    if (guiDrawBGSettings() == 0)
        guiDrawBGPlasma();

    if (!mainMenu)
        return;

    // draw the animated menu
    if (!mainMenuCurrent)
        mainMenuCurrent = mainMenu;

    submenu_list_t *it = mainMenu;

    // calculate the number of items
    int count = 0;
    int sitem = 0;
    for (; it; count++, it = it->next) {
        if (it == mainMenuCurrent)
            sitem = count;
    }

    int spacing = 25;
    int y = (gTheme->usedHeight >> 1) - (spacing * (count >> 1));
    int cp = 0; // current position
    for (it = mainMenu; it; it = it->next, cp++) {
        // render, advance
        fntRenderString(gTheme->fonts[0], 320, y, ALIGN_CENTER, 0, 0, submenuItemGetText(&it->item), (cp == sitem) ? gTheme->selTextColor : gTheme->textColor);
        y += spacing;
        if (cp == (MENU_ABOUT - 1))
            y += spacing / 2;
    }

    // hints
    guiDrawSubMenuHints();
}

int menuSetParentalLockCheckState(int enabled)
{
    int wasEnabled;

    wasEnabled = parentalLockCheckEnabled;
    parentalLockCheckEnabled = enabled ? 1 : 0;

    return wasEnabled;
}

int menuCheckParentalLock(void)
{
    const char *parentalLockPassword;
    char password[CONFIG_KEY_VALUE_LEN];
    int result;

    result = 0; // Default to unlocked.
    if (parentalLockCheckEnabled) {
        config_set_t *configOPL = configGetByType(CONFIG_OPL);

        // Prompt for password, only if one was set.
        if (configGetStr(configOPL, CONFIG_OPL_PARENTAL_LOCK_PWD, &parentalLockPassword) && (parentalLockPassword[0] != '\0')) {
            password[0] = '\0';
            if (diaShowKeyb(password, CONFIG_KEY_VALUE_LEN, 1, _l(_STR_PARENLOCK_ENTER_PASSWORD_TITLE))) {
                if (strncmp(parentalLockPassword, password, CONFIG_KEY_VALUE_LEN) == 0) {
                    result = 0;
                    parentalLockCheckEnabled = 0; // Stop asking for the password.
                } else if (strncmp(OPL_PARENTAL_LOCK_MASTER_PASS, password, CONFIG_KEY_VALUE_LEN) == 0) {
                    guiMsgBox(_l(_STR_PARENLOCK_DISABLE_WARNING), 0, NULL);

                    configRemoveKey(configOPL, CONFIG_OPL_PARENTAL_LOCK_PWD);
                    saveConfig(CONFIG_OPL, 1);

                    result = 0;
                    parentalLockCheckEnabled = 0; // Stop asking for the password.
                } else {
                    guiMsgBox(_l(_STR_PARENLOCK_PASSWORD_INCORRECT), 0, NULL);
                    result = EACCES;
                }
            } else // User aborted.
                result = EACCES;
        }
    }

    return result;
}

void menuHandleInputMenu()
{
    if (!mainMenu)
        return;

    if (!mainMenuCurrent)
        mainMenuCurrent = mainMenu;

    if (getKey(KEY_UP)) {
        sfxPlay(SFX_CURSOR);
        if (mainMenuCurrent->prev)
            mainMenuCurrent = mainMenuCurrent->prev;
        else // rewind to the last item
            while (mainMenuCurrent->next)
                mainMenuCurrent = mainMenuCurrent->next;
    }

    if (getKey(KEY_DOWN)) {
        sfxPlay(SFX_CURSOR);
        if (mainMenuCurrent->next)
            mainMenuCurrent = mainMenuCurrent->next;
        else
            mainMenuCurrent = mainMenu;
    }

    if (getKeyOn(gSelectButton)) {
        // execute the item via looking at the id of it
        int id = mainMenuCurrent->item.id;

        sfxPlay(SFX_CONFIRM);

        if (id == MENU_LAUNCH_PS2_DISC) {
            if (sysLaunchDisc() < 0) // success never returns; <0 means no/!PS2 disc -> stay in OPL
                guiMsgBox(_l(_STR_DISC_LAUNCH_ERR), 0, NULL);
        } else if (id == MENU_SETTINGS) {
            if (menuCheckParentalLock() == 0)
                guiShowConfig();
        } else if (id == MENU_DEVICE_SETTINGS) {
            if (menuCheckParentalLock() == 0)
                guiShowDeviceConfig();
        } else if (id == MENU_GFX_SETTINGS) {
            if (menuCheckParentalLock() == 0)
                guiShowUIConfig();
        } else if (id == MENU_AUDIO_SETTINGS) {
            if (menuCheckParentalLock() == 0)
                guiShowAudioConfig();
        } else if (id == MENU_CONTROLLER_SETTINGS) {
            if (menuCheckParentalLock() == 0)
                guiShowControllerConfig();
        } else if (id == MENU_OSD_LANGUAGE_SETTINGS) {
            if (menuCheckParentalLock() == 0)
                guiGameShowOSDLanguageConfig(1);
        } else if (id == MENU_PARENTAL_LOCK) {
            if (menuCheckParentalLock() == 0)
                guiShowParentalLockConfig();
        } else if (id == MENU_NET_CONFIG) {
            if (menuCheckParentalLock() == 0)
                guiShowNetConfig();
        } else if (id == MENU_NET_UPDATE) {
            if (menuCheckParentalLock() == 0)
                guiShowNetCompatUpdate();
        } else if (id == MENU_START_NBD) {
            if (menuCheckParentalLock() == 0)
                handleLwnbdSrv();
        } else if (id == MENU_ABOUT) {
            guiShowAbout();
        } else if (id == MENU_SAVE_CHANGES) {
            if (menuCheckParentalLock() == 0) {
                guiGameSaveOSDLanguageGlobalConfig(configGetByType(CONFIG_GAME));
#ifdef PADEMU
                guiGameSavePadEmuGlobalConfig(configGetByType(CONFIG_GAME));
                guiGameSavePadMacroGlobalConfig(configGetByType(CONFIG_GAME));
#endif
                saveConfig(CONFIG_OPL | CONFIG_NETWORK | CONFIG_GAME, 1);
                menuSetParentalLockCheckState(1); // Re-enable parental lock check.
            }
        } else if (id == MENU_EXIT) {
            if (guiMsgBox(_l(_STR_CONFIRMATION_EXIT), 1, NULL))
                sysExecExit();
        } else if (id == MENU_POWER_OFF) {
            if (guiMsgBox(_l(_STR_CONFIRMATION_POFF), 1, NULL))
                sysPowerOff();
        }

        // so the exit press wont propagate twice
        readPads();
    }

    if (getKeyOn(KEY_START) || getKeyOn(gSelectButton == KEY_CIRCLE ? KEY_CROSS : KEY_CIRCLE)) {
        // Check if there is anything to show the user, at all.
        if (gAPPStartMode || gETHStartMode || gBDMStartMode || gHDDStartMode || gMMCEStartMode || gFAVStartMode) {
            guiSwitchScreen(GUI_SCREEN_MAIN);
            refreshMenuPosition();
        }
    }
}

static void menuRenderElements(theme_elems_t *elems, int allowItemConfig, config_set_t *renderConfig)
{
    // selected_item can't be NULL here as we only allow to switch to "Main" rendering when there is at least one device activated
    theme_element_t *elem = elems->first;
    item_list_t *list = selected_item != NULL && selected_item->item != NULL ? selected_item->item->userdata : NULL;

    if (allowItemConfig && elems->needsItemConfig && menuCanRequestItemConfig(list))
        _menuRequestConfig();

    WaitSema(menuSemaId);

    /* _menuRequestConfig() may have configFree()'d and NULLed itemConfig on the
     * frame the selection changed.  The caller captured renderConfig from
     * itemConfig BEFORE that call, so using it now would be a use-after-free.
     * Re-read the live pointer under the lock; the draw path tolerates NULL. */
    if (allowItemConfig)
        renderConfig = itemConfig;

    while (elem) {
        if (elem->drawElem)
            elem->drawElem(selected_item, selected_item->item->current, renderConfig, elem);

        elem = elem->next;
    }
    SignalSema(menuSemaId);
}

void menuRenderMain(void)
{
    item_list_t *list = selected_item->item->userdata;
    int allowItemConfig = !(list != NULL && list->mode == MMCE_MODE);
    config_set_t *renderConfig = allowItemConfig ? itemConfig : NULL;

    if (list->mode == FAV_MODE) {
        // Favourites render with the theme's favs family (favsMain*); falls back to the game
        // elements when the theme defines no favsMain override.
        menuRenderElements(&gTheme->favsMainElems, allowItemConfig, renderConfig);
        // Fall back to the games list (the slot every real theme populates -- the 1st/only ItemsList)
        // when the theme defines no favs/apps/vcd ItemsList, so gTheme->itemsList stays set: the
        // scroll/paging code (menuNextV/PrevV/Page) derefs gTheme->itemsList->extended without a NULL check.
        gTheme->itemsList = gTheme->favsItemsList ? gTheme->favsItemsList : gTheme->gamesItemsList;
    } else if (vcdViewActive(list->mode)) {
        // VCD/PS1 listings render with the vcd family (vcdMain*; each slot falls back at parse time to
        // appsMain* then main*). The VCD list uses its OWN items-list slot (vcdItemsList) so it keeps a
        // SEPARATE cover cache from the device's ISO list -- the view reuses the device's game list
        // (same item ids), so a shared cache thrashes on every L3 toggle. Falls back to the games list
        // when the theme defines no 4th ItemsList (never NULL).
        menuRenderElements(&gTheme->vcdMainElems, allowItemConfig, renderConfig);
        gTheme->itemsList = gTheme->vcdItemsList ? gTheme->vcdItemsList : gTheme->gamesItemsList;
    } else if (list->mode == APP_MODE) {
        menuRenderElements(&gTheme->appsMainElems, allowItemConfig, renderConfig);
        gTheme->itemsList = gTheme->appsItemsList ? gTheme->appsItemsList : gTheme->gamesItemsList;
    } else {
        menuRenderElements(&gTheme->mainElems, allowItemConfig, renderConfig);
        gTheme->itemsList = gTheme->gamesItemsList;
    }
}

// Coverflow rotates the nav axis on the MAIN screen only: Left/Right step through the
// carousel (a vertical list move) while Up/Down switch device menus. Non-coverflow themes
// behave exactly as before. The info screen is intentionally NOT rotated (menuHandleInputInfo).
static void menuNavigateLeft()
{
    if (gTheme->coverflow)
        menuPrevV();
    else
        menuPrevH();
}

static void menuNavigateRight()
{
    if (gTheme->coverflow)
        menuNextV();
    else
        menuNextH();
}

static void menuNavigateUp()
{
    if (gTheme->coverflow)
        menuPrevH();
    else
        menuPrevV();
}

static void menuNavigateDown()
{
    if (gTheme->coverflow)
        menuNextH();
    else
        menuNextV();
}

void menuHandleInputMain()
{
    if (getKey(KEY_LEFT)) {
        menuNavigateLeft();
    } else if (getKey(KEY_RIGHT)) {
        menuNavigateRight();
    } else if (getKey(KEY_UP)) {
        menuNavigateUp();
    } else if (getKey(KEY_DOWN)) {
        menuNavigateDown();
    } else if (getKeyOn(KEY_CROSS)) {
        selected_item->item->execCross(selected_item->item);
    } else if (getKeyOn(KEY_TRIANGLE)) {
        selected_item->item->execTriangle(selected_item->item);
    } else if (getKeyOn(KEY_CIRCLE)) {
        selected_item->item->execCircle(selected_item->item);
    } else if (getKeyOn(KEY_SQUARE)) {
        selected_item->item->execSquare(selected_item->item);
    } else if (getKeyOn(KEY_START)) {
        // reinit main menu - show/hide items valid in the active context
        menuInitMainMenu();
        guiSwitchScreen(GUI_SCREEN_MENU);
    } else if (getKeyOn(KEY_SELECT)) {
        selected_item->item->refresh(selected_item->item);
    } else if (getKey(KEY_L1)) {
        menuPrevPage();
    } else if (getKey(KEY_R1)) {
        menuNextPage();
    } else if (getKeyOn(KEY_L2)) { // home
        menuFirstPage();
    } else if (getKeyOn(KEY_R2)) { // end
        menuLastPage();
    } else if (getKeyOn(KEY_R3)) { // toggle favourite
        if (selected_item->item->fav)
            selected_item->item->fav(selected_item->item);
    } else if (getKeyOn(KEY_L3)) { // toggle VCD view (disc list <-> POPS/*.VCD)
        if (selected_item->item->toggleView)
            selected_item->item->toggleView(selected_item->item);
    }

    // Last Played Auto Start
    if (RemainSecs < 0) {
        DisableCron = 1; // Disable Counter
        if (gSelectButton == KEY_CIRCLE)
            selected_item->item->execCircle(selected_item->item);
        else
            selected_item->item->execCross(selected_item->item);
    }
}

void menuRenderInfo(void)
{
    item_list_t *list = selected_item->item->userdata;

    if (list->mode == FAV_MODE) {
        menuRenderElements(&gTheme->favsInfoElems, 1, itemConfig);
        gTheme->itemsList = gTheme->favsItemsList ? gTheme->favsItemsList : gTheme->gamesItemsList;
    } else if (vcdViewActive(list->mode)) {
        // VCD info uses the vcd family (vcdInfo*, falling back to info* -- the GAME info layout, so VCDs
        // keep their rich game-style metadata page unless a theme overrides it). The list uses
        // vcdItemsList (its own cover cache); falls back to the games list when absent so itemsList is
        // never NULL.
        menuRenderElements(&gTheme->vcdInfoElems, 1, itemConfig);
        gTheme->itemsList = gTheme->vcdItemsList ? gTheme->vcdItemsList : gTheme->gamesItemsList;
    } else if (list->mode == APP_MODE) {
        menuRenderElements(&gTheme->appsInfoElems, 1, itemConfig);
        gTheme->itemsList = gTheme->appsItemsList ? gTheme->appsItemsList : gTheme->gamesItemsList;
    } else {
        menuRenderElements(&gTheme->infoElems, 1, itemConfig);
        gTheme->itemsList = gTheme->gamesItemsList;
    }
}

void menuHandleInputInfo()
{
    if (getKeyOn(KEY_CROSS)) {
        if (gSelectButton == KEY_CIRCLE)
            guiSwitchScreen(GUI_SCREEN_MAIN);
        else
            selected_item->item->execCross(selected_item->item);
    } else if (getKey(KEY_UP)) {
        menuPrevV();
    } else if (getKey(KEY_DOWN)) {
        menuNextV();
    } else if (getKeyOn(KEY_CIRCLE)) {
        if (gSelectButton == KEY_CROSS)
            guiSwitchScreen(GUI_SCREEN_MAIN);
        else
            selected_item->item->execCircle(selected_item->item);
    } else if (getKey(KEY_L1)) {
        menuPrevPage();
    } else if (getKey(KEY_R1)) {
        menuNextPage();
    } else if (getKeyOn(KEY_L2)) {
        menuFirstPage();
    } else if (getKeyOn(KEY_R2)) {
        menuLastPage();
    }
}

void menuRenderGameMenu()
{
    if (guiDrawBGSettings() == 0)
        guiDrawBGPlasma();

    if (!gameMenu)
        return;

    // If the device menu that has the selected game suddenly goes invisible (device was removed), switch
    // back to the game list menu.
    if (selected_item->item->visible == 0) {
        guiSwitchScreen(GUI_SCREEN_MAIN);
        return;
    }

    // If we enter the game settings menu and there's no selected item bail out. I'm not entirely sure how we get into
    // this state but it seems to happen on some consoles when transitioning from the game settings menu back to the game
    // list menu.
    if (selected_item->item->current == NULL)
        return;

    // draw the animated menu
    if (!gameMenuCurrent)
        gameMenuCurrent = gameMenu;

    submenu_list_t *it = gameMenu;

    // calculate the number of items
    int count = 0;
    int sitem = 0;
    for (; it; count++, it = it->next) {
        if (it == gameMenuCurrent)
            sitem = count;
    }

    int spacing = 25;
    int y = (gTheme->usedHeight >> 1) - (spacing * (count >> 1));
    int cp = 0; // current position

    // game title
    fntRenderString(gTheme->fonts[0], 320, 20, ALIGN_CENTER, 0, 0, selected_item->item->current->item.text, gTheme->selTextColor);

    // config source
    char *cfgSource = gameConfigSource();
    fntRenderString(gTheme->fonts[0], 320, 40, ALIGN_CENTER, 0, 0, cfgSource, gTheme->textColor);

    // settings list
    for (it = gameMenu; it; it = it->next, cp++) {
        // render, advance
        fntRenderString(gTheme->fonts[0], 320, y, ALIGN_CENTER, 0, 0, submenuItemGetText(&it->item), (cp == sitem) ? gTheme->selTextColor : gTheme->textColor);
        y += spacing;
        if (cp == (GAME_SAVE_CHANGES - 1) || cp == (GAME_REMOVE_CHANGES - 1))
            y += spacing / 2;
    }

    // hints
    guiDrawSubMenuHints();
}

// Core-aware game menu: the Neutrino core ignores OPL's GSM, Cheats, PADEMU and
// OSD-language settings (see docs/NEUTRINO.md), so opening those panels for a
// Neutrino game would only edit dead options. Returns 1 when the selected game's
// Loader Core is Neutrino. (VMC and Compatibility stay available -- both are
// honored under Neutrino.)
static int gameMenuCoreIsNeutrino(void)
{
    int coreLoader = 0;
    if (itemConfig != NULL)
        configGetInt(itemConfig, CONFIG_ITEM_CORE_LOADER, &coreLoader);
    // UDPBD games are Neutrino-only even while $CoreLoader is still its OPL default.
    if (!coreLoader && selected_item != NULL && selected_item->item != NULL)
        coreLoader = bdmSupportIsUDPBD(selected_item->item->userdata);
    return coreLoader;
}

void menuHandleInputGameMenu()
{
    if (!gameMenu)
        return;

    if (!gameMenuCurrent)
        gameMenuCurrent = gameMenu;

    if (getKey(KEY_UP)) {
        sfxPlay(SFX_CURSOR);
        if (gameMenuCurrent->prev)
            gameMenuCurrent = gameMenuCurrent->prev;
        else // rewind to the last item
            while (gameMenuCurrent->next)
                gameMenuCurrent = gameMenuCurrent->next;
    }

    if (getKey(KEY_DOWN)) {
        sfxPlay(SFX_CURSOR);
        if (gameMenuCurrent->next)
            gameMenuCurrent = gameMenuCurrent->next;
        else
            gameMenuCurrent = gameMenu;
    }

    if (getKeyOn(gSelectButton)) {
        // execute the item via looking at the id of it
        int menuID = gameMenuCurrent->item.id;

        sfxPlay(SFX_CONFIRM);

        if (menuID == GAME_COMPAT_SETTINGS) {
            guiGameShowCompatConfig(selected_item->item->current->item.id, selected_item->item->userdata, itemConfig);
        } else if (menuID == GAME_CHEAT_SETTINGS) {
            if (gameMenuCoreIsNeutrino())
                guiMsgBox(_l(_STR_NEUTRINO_SETTING_NA), 0, NULL);
            else
                guiGameShowCheatConfig();
        } else if (menuID == GAME_GSM_SETTINGS) {
            if (gameMenuCoreIsNeutrino())
                guiMsgBox(_l(_STR_NEUTRINO_SETTING_NA), 0, NULL);
            else
                guiGameShowGSConfig();
        } else if (menuID == GAME_VMC_SETTINGS) {
            guiGameShowVMCMenu(selected_item->item->current->item.id, selected_item->item->userdata);
#ifdef PADEMU
        } else if (menuID == GAME_PADEMU_SETTINGS) {
            if (gameMenuCoreIsNeutrino())
                guiMsgBox(_l(_STR_NEUTRINO_SETTING_NA), 0, NULL);
            else
                guiGameShowPadEmuConfig(0);
        } else if (menuID == GAME_PADMACRO_SETTINGS) {
            if (gameMenuCoreIsNeutrino())
                guiMsgBox(_l(_STR_NEUTRINO_SETTING_NA), 0, NULL);
            else
                guiGameShowPadMacroConfig(0);
#endif
        } else if (menuID == GAME_OSD_LANGUAGE_SETTINGS) {
            if (gameMenuCoreIsNeutrino())
                guiMsgBox(_l(_STR_NEUTRINO_SETTING_NA), 0, NULL);
            else
                guiGameShowOSDLanguageConfig(0);
        } else if (menuID == GAME_SAVE_CHANGES) {
            if (guiGameSaveConfig(itemConfig, selected_item->item->userdata))
                configSetInt(itemConfig, CONFIG_ITEM_CONFIGSOURCE, CONFIG_SOURCE_USER);
            menuSaveConfig();
            saveConfig(CONFIG_GAME, 0);
            guiMsgBox(_l(_STR_GAME_SETTINGS_SAVED), 0, NULL);
            guiGameLoadConfig(selected_item->item->userdata, gameMenuLoadConfig(NULL));
        } else if (menuID == GAME_TEST_CHANGES) {
            guiGameTestSettings(selected_item->item->current->item.id, selected_item->item->userdata, itemConfig);
        } else if (menuID == GAME_REMOVE_CHANGES) {
            if (guiGameShowRemoveSettings(itemConfig, configGetByType(CONFIG_GAME))) {
                guiGameLoadConfig(selected_item->item->userdata, gameMenuLoadConfig(NULL));
            }
        } else if (menuID == GAME_RENAME_GAME) {
            menuRenameGame(&gameMenu);
        } else if (menuID == GAME_DELETE_GAME) {
            menuDeleteGame(&gameMenu);
        }
        // so the exit press wont propagate twice
        readPads();
    }

    if (getKeyOn(KEY_START) || getKeyOn(gSelectButton == KEY_CIRCLE ? KEY_CROSS : KEY_CIRCLE)) {
        guiSwitchScreen(GUI_SCREEN_MAIN);
    }
}

void menuRenderAppMenu()
{
    if (guiDrawBGSettings() == 0)
        guiDrawBGPlasma();

    if (!appMenu)
        return;

    // draw the animated menu
    if (!appMenuCurrent)
        appMenuCurrent = appMenu;

    submenu_list_t *it = appMenu;

    // calculate the number of items
    int count = 0;
    int sitem = 0;
    for (; it; count++, it = it->next) {
        if (it == appMenuCurrent)
            sitem = count;
    }

    int spacing = 25;
    int y = (gTheme->usedHeight >> 1) - (spacing * (count >> 1));
    int cp = 0; // current position

    // app title
    fntRenderString(gTheme->fonts[0], 320, 20, ALIGN_CENTER, 0, 0, selected_item->item->current->item.text, gTheme->selTextColor);

    for (it = appMenu; it; it = it->next, cp++) {
        // render, advance
        fntRenderString(gTheme->fonts[0], 320, y, ALIGN_CENTER, 0, 0, submenuItemGetText(&it->item), (cp == sitem) ? gTheme->selTextColor : gTheme->textColor);
        y += spacing;
    }

    // hints
    guiDrawSubMenuHints();
}

void menuHandleInputAppMenu()
{
    if (!appMenu)
        return;

    if (!appMenuCurrent)
        appMenuCurrent = appMenu;

    if (getKey(KEY_UP)) {
        sfxPlay(SFX_CURSOR);
        if (appMenuCurrent->prev)
            appMenuCurrent = appMenuCurrent->prev;
        else // rewind to the last item
            while (appMenuCurrent->next)
                appMenuCurrent = appMenuCurrent->next;
    }

    if (getKey(KEY_DOWN)) {
        sfxPlay(SFX_CURSOR);
        if (appMenuCurrent->next)
            appMenuCurrent = appMenuCurrent->next;
        else
            appMenuCurrent = appMenu;
    }

    if (getKeyOn(gSelectButton)) {
        // execute the item via looking at the id of it
        int menuID = appMenuCurrent->item.id;

        sfxPlay(SFX_CONFIRM);

        if (menuID == 0) {
            menuRenameGame(&appMenu);
        } else if (menuID == 1) {
            menuDeleteGame(&appMenu);
        }
        // so the exit press wont propagate twice
        readPads();
    }

    if (getKeyOn(KEY_START) || getKeyOn(gSelectButton == KEY_CIRCLE ? KEY_CROSS : KEY_CIRCLE)) {
        guiSwitchScreen(GUI_SCREEN_MAIN);
    }
}
