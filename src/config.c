/*
  Copyright 2009, Ifcaro & volca
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.
*/

#include "include/opl.h"
#include "include/util.h"
#include "include/ioman.h"
#include "include/sound.h"
#include <string.h>

// FIXME: We should not need this function.
//        Use newlib's 'stat' to get GMT time.
#define NEWLIB_PORT_AWARE
#include <fileXio_rpc.h> // iox_stat_t, fileXioGetStat
int configGetStat(config_set_t *configSet, iox_stat_t *stat);

static u32 currentUID = 0;
static config_set_t configFiles[CONFIG_INDEX_COUNT];
static char legacyNetConfigPath[256] = "mc?:SYS-CONF/IPCONFIG.DAT";
static const char *configFilenames[CONFIG_INDEX_COUNT] = {
    CONFIG_OPL_FILENAME, // RiptOPL master settings (settings_riptopl.cfg; legacy conf_riptopl.cfg auto-migrated on read -- see configRead)
    "conf_last.cfg",
    "conf_apps.cfg",
    "conf_network.cfg",
    "conf_game.cfg",
};

static int strToColor(const char *string, unsigned char *color)
{
    int cnt = 0, n = 0;
    color[0] = 0;
    color[1] = 0;
    color[2] = 0;

    if (!string || !*string)
        return 0;
    if (string[0] != '#')
        return 0;

    string++;

    while (*string) {
        int fh = fromHex(*string);
        if (fh >= 0) {
            if (n >= 3)
                break; // never write past the caller's 3-byte color[] (RGB)
            color[n] = color[n] * 16 + fh;
        } else {
            break;
        }

        // Two characters per color
        if (cnt == 1) {
            cnt = 0;
            n++;
        } else {
            cnt++;
        }

        string++;
    }

    return 1;
}

/// true if given a whitespace character
int isWS(char c)
{
    return c == ' ' || c == '\t';
}

static int splitAssignment(char *line, char *key, size_t keymax, char *val, size_t valmax)
{
    // skip whitespace
    for (; isWS(*line); ++line)
        ;

    // find "=".
    // If found, the text before is key, after is val.
    // Otherwise malformed string is encountered

    char *eqpos = strchr(line, '=');

    if (eqpos) {
        // copy the key and value, reserving room for the NUL terminator so an
        // exactly-buffer-length key/val cannot be left unterminated (OOB read)
        size_t keylen = min(keymax - 1, (size_t)(eqpos - line));

        strncpy(key, line, keylen);
        key[keylen] = '\0';

        eqpos++;

        size_t vallen = min(valmax - 1, (size_t)(strlen(line) - (eqpos - line)));
        strncpy(val, eqpos, vallen);
        val[vallen] = '\0';
    }

    return (eqpos != NULL);
}

static int parsePrefix(char *line, char *prefix, size_t prefixSize)
{
    // find ":".
    // If found, the text before is the prefix.
    // Otherwise a malformed string is encountered.
    char *colpos = strchr(line, ':');

    if (colpos && colpos != line) {
        // copy the prefix, bounded to the destination buffer so a long
        // pre-colon segment in a user-editable config file cannot overflow it
        size_t n = (size_t)(colpos - line);
        if (prefixSize == 0)
            return 0;
        if (n >= prefixSize)
            n = prefixSize - 1;
        memcpy(prefix, line, n);
        prefix[n] = 0;

        return 1;
    } else {
        return 0;
    }
}

static int configKeyValidate(const char *key)
{
    if (strlen(key) == 0)
        return 0;

    return !strchr(key, '=');
}

static struct config_value_t *allocConfigItem(const char *key, const char *val)
{
    struct config_value_t *it = (struct config_value_t *)malloc(sizeof(struct config_value_t));
    if (it == NULL)
        return NULL;
    strncpy(it->key, key, sizeof(it->key));
    it->key[sizeof(it->key) - 1] = '\0';
    strncpy(it->val, val, sizeof(it->val));
    it->val[sizeof(it->val) - 1] = '\0';
    it->next = NULL;

    return it;
}

/// Low level key addition. Does not check for uniqueness.
static void addConfigValue(config_set_t *configSet, const char *key, const char *val)
{
    if (!configSet->tail) {
        configSet->head = allocConfigItem(key, val);
        configSet->tail = configSet->head;
    } else {
        struct config_value_t *it = allocConfigItem(key, val);
        if (it != NULL) {
            configSet->tail->next = it;
            configSet->tail = it;
        }
    }
}

static struct config_value_t *getConfigItemForName(config_set_t *configSet, const char *name)
{
    struct config_value_t *val = configSet->head;

    while (val) {
        if (strncmp(val->key, name, sizeof(val->key)) == 0)
            break;

        val = val->next;
    }

    return val;
}

static char cfgDevice[8];

char *configGetDir(void)
{
    if (!strncmp(cfgDevice, "mc", 2)) {
        cfgDevice[2] = getmcID();
    }

    char *path = cfgDevice;
    return path;
}

void configPrepareNotifications(char *prefix)
{
    char *colpos;

    snprintf(cfgDevice, sizeof(cfgDevice), "%s", prefix); // prefix is caller/config data, never a format string

    if ((colpos = strchr(cfgDevice, ':')) != NULL)
        *(colpos + 1) = '\0';
}

void configInit(char *prefix)
{
    char path[256];
    int i;

    if (prefix)
        snprintf(legacyNetConfigPath, sizeof(legacyNetConfigPath), "%s/IPCONFIG.DAT", prefix);
    else
        prefix = gBaseMCDir;

    for (i = 0; i < CONFIG_INDEX_COUNT; i++) {
        snprintf(path, sizeof(path), "%s/%s", prefix, configFilenames[i]);
        configAlloc(1 << i, &configFiles[i], path);
    }

    configPrepareNotifications(prefix);
}

void configSetMove(char *prefix)
{
    char path[256];
    int i;

    if (prefix)
        snprintf(legacyNetConfigPath, sizeof(legacyNetConfigPath), "%s/IPCONFIG.DAT", prefix);
    else
        prefix = gBaseMCDir;

    for (i = 0; i < CONFIG_INDEX_COUNT; i++) {
        snprintf(path, sizeof(path), "%s/%s", prefix, configFilenames[i]);
        configMove(&configFiles[i], path);
    }

    configPrepareNotifications(prefix);
}

void configEnd()
{
    int index = 0;
    while (index < CONFIG_INDEX_COUNT) {
        config_set_t *configSet = &configFiles[index];

        configClear(configSet);
        free(configSet->filename);
        configSet->filename = NULL;
        index++;
    }
}

config_set_t *configAlloc(int type, config_set_t *configSet, char *fileName)
{
    int weAllocated = 0;
    if (!configSet) {
        configSet = (config_set_t *)malloc(sizeof(config_set_t));
        if (!configSet) // OOM: can't proceed without the struct
            return NULL;
        weAllocated = 1;
    }

    configSet->uid = ++currentUID;
    configSet->type = type;
    configSet->head = NULL;
    configSet->tail = NULL;
    if (fileName) {
        int length = strlen(fileName) + 1;
        configSet->filename = (char *)malloc(length * sizeof(char));
        if (!configSet->filename) { // OOM: clean up and bail
            if (weAllocated)
                free(configSet);
            return NULL;
        }
        memcpy(configSet->filename, fileName, length);
    } else
        configSet->filename = NULL;
    configSet->modified = 0;
    return configSet;
}

void configMove(config_set_t *configSet, const char *fileName)
{
    int length = strlen(fileName) + 1;
    // Use a temporary so a failed realloc doesn't clobber (and leak) the old pointer
    char *tmp = realloc(configSet->filename, length);
    if (!tmp)
        return;
    configSet->filename = tmp;
    memcpy(configSet->filename, fileName, length);
}

void configFree(config_set_t *configSet)
{
    configClear(configSet);
    free(configSet->filename);
    free(configSet);
}

// Deep-copy src into a fresh standalone (heap) config set. The clone is NOT registered in
// configFiles[] (configAlloc with a NULL set just mallocs one) and gets its own uid, so it is
// invisible to configGetByType and can be launched from + configFree()d without disturbing the
// live config. Faithfully copies every entry, including the runtime '#'-prefixed keys (Format/
// Startup/Size) the launch path needs. Returns NULL on OOM.
config_set_t *configClone(config_set_t *src)
{
    if (src == NULL)
        return NULL;

    config_set_t *dst = configAlloc(src->type, NULL, src->filename);
    if (dst == NULL)
        return NULL;

    struct config_value_t *it;
    for (it = src->head; it != NULL; it = it->next)
        addConfigValue(dst, it->key, it->val);

    dst->modified = 0;
    return dst;
}

config_set_t *configGetByType(int type)
{
    int index = 0;
    while (index < CONFIG_INDEX_COUNT) {
        config_set_t *configSet = &configFiles[index];

        if (configSet->type == type)
            return configSet;
        index++;
    }
    return NULL;
}

int configSetStr(config_set_t *configSet, const char *key, const char *value)
{
    if (!configKeyValidate(key))
        return 0;

    struct config_value_t *it = getConfigItemForName(configSet, key);

    if (it) {
        if (strncmp(it->val, value, sizeof(it->val)) != 0) {
            strncpy(it->val, value, sizeof(it->val));
            it->val[sizeof(it->val) - 1] = '\0';
            if (it->key[0] != '#')
                configSet->modified = 1;
        }
    } else {
        addConfigValue(configSet, key, value);
        if (key[0] != '#')
            configSet->modified = 1;
    }

    return 1;
}

// sets the value to point to the value str in the config. Do not overwrite - it will overwrite the string in config
int configGetStr(config_set_t *configSet, const char *key, const char **value)
{
    if (!configKeyValidate(key))
        return 0;

    struct config_value_t *it = getConfigItemForName(configSet, key);

    if (it) {
        *value = it->val;
        return 1;
    } else
        return 0;
}

int configGetStrCopy(config_set_t *configSet, const char *key, char *value, int length)
{
    const char *valref = NULL;
    if (configGetStr(configSet, key, &valref)) {
        strncpy(value, valref, length);
        value[length - 1] = '\0';
        return 1;
    } else {
        value[0] = '\0';
        return 0;
    }
}

int configSetInt(config_set_t *configSet, const char *key, const int value)
{
    char tmp[12];
    snprintf(tmp, sizeof(tmp), "%d", value);
    return configSetStr(configSet, key, tmp);
}

int configGetInt(config_set_t *configSet, const char *key, int *value)
{
    const char *valref = NULL;
    if (configGetStr(configSet, key, &valref)) {
        *value = atoi(valref);
        return 1;
    } else {
        return 0;
    }
}

int configSetColor(config_set_t *configSet, const char *key, unsigned char *color)
{
    char tmp[8];
    snprintf(tmp, sizeof(tmp), "#%02X%02X%02X", color[0], color[1], color[2]);
    return configSetStr(configSet, key, tmp);
}

int configGetColor(config_set_t *configSet, const char *key, unsigned char *color)
{
    const char *valref = NULL;
    if (configGetStr(configSet, key, &valref)) {
        strToColor(valref, color);
        return 1;
    } else {
        return 0;
    }
}

int configRemoveKey(config_set_t *configSet, const char *key)
{
    if (!configKeyValidate(key))
        return 0;

    struct config_value_t *val = configSet->head;
    struct config_value_t *prev = NULL;

    while (val) {
        if (strncmp(val->key, key, sizeof(val->key)) == 0) {
            if (key[0] != '#')
                configSet->modified = 1;

            if (val == configSet->tail)
                configSet->tail = prev;

            val = val->next;
            if (prev) {
                free(prev->next);
                prev->next = val;
            } else {
                free(configSet->head);
                configSet->head = val;
            }
        } else {
            prev = val;
            val = val->next;
        }
    }

    return 1;
}

void configMerge(config_set_t *dest, const config_set_t *source)
{
    struct config_value_t *val;

    for (val = source->head; val != NULL; val = val->next) {
        configSetStr(dest, val->key, val->val);
    }
}

static int configReadLegacyIP(void)
{
    config_set_t *configSet;
    char temp[16];

    int fd = openFile(legacyNetConfigPath, O_RDONLY);
    if (fd >= 0) {
        char ipconfig[256];
        int size = getFileSize(fd);
        // Bound the read to the stack buffer: the file size is untrusted and a
        // file larger than ipconfig[] would otherwise smash the stack.
        if (size < 0)
            size = 0;
        if (size >= (int)sizeof(ipconfig))
            size = sizeof(ipconfig) - 1;
        int rd = read(fd, ipconfig, size);
        if (rd < 0)
            rd = 0;
        ipconfig[rd] = '\0';
        close(fd);

        int n = sscanf(ipconfig, "%d.%d.%d.%d %d.%d.%d.%d %d.%d.%d.%d", &ps2_ip[0], &ps2_ip[1], &ps2_ip[2], &ps2_ip[3],
                       &ps2_netmask[0], &ps2_netmask[1], &ps2_netmask[2], &ps2_netmask[3],
                       &ps2_gateway[0], &ps2_gateway[1], &ps2_gateway[2], &ps2_gateway[3]);
        if (n != 12)
            return 0;

        configSet = &configFiles[CONFIG_INDEX_NETWORK];

        snprintf(temp, sizeof(temp), "%d.%d.%d.%d", ps2_ip[0], ps2_ip[1], ps2_ip[2], ps2_ip[3]);
        configSetStr(configSet, CONFIG_NET_PS2_IP, temp);
        snprintf(temp, sizeof(temp), "%d.%d.%d.%d", ps2_netmask[0], ps2_netmask[1], ps2_netmask[2], ps2_netmask[3]);
        configSetStr(configSet, CONFIG_NET_PS2_NETM, temp);
        snprintf(temp, sizeof(temp), "%d.%d.%d.%d", ps2_gateway[0], ps2_gateway[1], ps2_gateway[2], ps2_gateway[3]);
        configSetStr(configSet, CONFIG_NET_PS2_GATEW, temp);
        // The legacy format has no setting for the DNS server, so duplicate the gateway address.
        configSetStr(configSet, CONFIG_NET_PS2_DNS, temp);

        return 1;
    }

    return 0;
}

// dst has to have 5 bytes space
void configGetDiscIDBinary(config_set_t *configSet, void *dst)
{
    memset(dst, 0, 5);

    const char *gid = NULL;
    if (configGetStr(configSet, CONFIG_ITEM_DNAS, &gid)) {
        // convert from hex to binary
        char *cdst = dst;
        int p = 0;
        while (*gid && p < 10) {
            int dv = -1;

            while (dv < 0 && *gid) // skip spaces, etc
                dv = fromHex(*(gid++));

            if (dv < 0)
                break;

            *cdst = *cdst * 16 + dv;
            if ((++p & 1) == 0)
                cdst++;
        }
    }
}

static int configReadFileBuffer(file_buffer_t *fileBuffer, config_set_t *configSet)
{
    char *line;
    unsigned int lineno = 0;

    char prefix[CONFIG_KEY_NAME_LEN];
    memset(prefix, 0, sizeof(prefix));

    while (readFileBuffer(fileBuffer, &line)) {
        lineno++;

        char key[CONFIG_KEY_NAME_LEN], val[CONFIG_KEY_VALUE_LEN];
        memset(key, 0, sizeof(key));
        memset(val, 0, sizeof(val));

        if (splitAssignment(line, key, sizeof(key), val, sizeof(val))) {
            /* if the line does not start with whitespace,
             * the prefix ends and we have to reset it
             */
            if (!isWS(line[0]))
                memset(prefix, 0, sizeof(prefix));

            // insert config value
            if (prefix[0]) {
                // we have a prefix
                char composedKey[2 * CONFIG_KEY_NAME_LEN];

                snprintf(composedKey, sizeof(composedKey), "%s_%s", prefix, key);
                configSetStr(configSet, composedKey, val);
            } else {
                configSetStr(configSet, key, val);
            }
        } else if (parsePrefix(line, prefix, sizeof(prefix))) {
            // prefix is set, that's about it
        } else {
            LOG("CONFIG Malformed file '%s' line %d: '%s'\n", configSet->filename, lineno, line);
        }
    }
    configSet->modified = 0;
    return 1;
}

int configReadBuffer(config_set_t *configSet, const void *buffer, int size)
{
    int ret;
    file_buffer_t *fileBuffer = openFileBufferBuffer(0, buffer, size);
    if (!fileBuffer) {
        configSet->modified = 0;
        return 0;
    }

    ret = configReadFileBuffer(fileBuffer, configSet);

    closeFileBuffer(fileBuffer);
    return ret;
}

// RiptOPL master config was renamed conf_riptopl.cfg -> settings_riptopl.cfg. Given the built
// "<dir>/settings_riptopl.cfg" path, produce its legacy "<dir>/conf_riptopl.cfg" sibling so an
// existing install's settings still load (read-fallback); the next save writes the new name.
static void configBuildLegacyOplPath(const char *path, char *out, int outSize)
{
    const char *slash = strrchr(path, '/');
    if (slash != NULL)
        snprintf(out, outSize, "%.*s%s", (int)(slash - path) + 1, path, CONFIG_OPL_FILENAME_LEGACY);
    else
        snprintf(out, outSize, "%s", CONFIG_OPL_FILENAME_LEGACY);
}

int configRead(config_set_t *configSet)
{
    int ret;
    file_buffer_t *fileBuffer = openFileBuffer(configSet->filename, O_RDONLY, 0, 4096);
    if (fileBuffer == NULL && configSet->type == CONFIG_OPL && configSet->filename != NULL) {
        // Migration: existing installs have the legacy conf_riptopl.cfg, not settings_riptopl.cfg.
        // Read the legacy file from the same dir so settings aren't lost; the next save writes the
        // new name. configSet->filename stays the new name, so configWrite migrates transparently.
        char legacyPath[256];
        configBuildLegacyOplPath(configSet->filename, legacyPath, sizeof(legacyPath));
        fileBuffer = openFileBuffer(legacyPath, O_RDONLY, 0, 4096);
        if (fileBuffer != NULL)
            LOG("CONFIG migrating settings from legacy %s\n", legacyPath);
    }
    if (!fileBuffer) {
        LOG("CONFIG No file %s.\n", configSet->filename);
        configSet->modified = 0;
        return 0;
    }

    ret = configReadFileBuffer(fileBuffer, configSet);

    closeFileBuffer(fileBuffer);
    return ret;
}

int configWrite(config_set_t *configSet)
{
    if (configSet->modified) {
        file_buffer_t *fileBuffer = openFileBuffer(configSet->filename, O_WRONLY | O_CREAT | O_TRUNC, 0, 4096);
        if (fileBuffer) {
            char line[512];

            bgmMute();
            struct config_value_t *cur = configSet->head;
            while (cur) {
                if ((cur->key[0] != '\0') && (cur->key[0] != '#')) {
                    snprintf(line, sizeof(line), "%s=%s\r\n", cur->key, cur->val); // add windows CR+LF (0x0D 0x0A)
                    writeFileBuffer(fileBuffer, line, strlen(line));
                }

                // and advance
                cur = cur->next;
            }

            closeFileBuffer(fileBuffer);
            configSet->modified = 0;
            bgmUnMute();
            return 1;
        }
        return 0;
    }
    return 1;
}

int configGetStat(config_set_t *configSet, iox_stat_t *stat)
{
    return (fileXioGetStat(configSet->filename, stat) >= 0 ? 1 : 0);
}

void configClear(config_set_t *configSet)
{
    while (configSet->head) {
        struct config_value_t *cur = configSet->head;
        configSet->head = cur->next;

        free(cur);
    }

    configSet->head = NULL;
    configSet->tail = NULL;
    configSet->modified = 1;
}

int configReadMulti(int types)
{
    int result = 0, index;

    for (index = 0; index < CONFIG_INDEX_COUNT; index++) {
        config_set_t *configSet = &configFiles[index];

        if (configSet->type & types) {
            configClear(configSet);
            if (configRead(configSet))
                result |= configSet->type;
        }
    }

    // If the network configuration is to be loaded and one cannot be loaded, attempt to load from the legacy network config file.
    if ((types & CONFIG_NETWORK) && !(result & CONFIG_NETWORK))
        if (configReadLegacyIP())
            result |= CONFIG_NETWORK;

    return result;
}

int configWriteMulti(int types)
{
    int result = 0, index;

    for (index = 0; index < CONFIG_INDEX_COUNT; index++) {
        config_set_t *configSet = &configFiles[index];

        if (configSet->type & types)
            result += configWrite(configSet);
    }

    return result;
}

void configGetVMC(config_set_t *configSet, char *vmc, int length, int slot)
{
    char gkey[CONFIG_KEY_NAME_LEN];
    snprintf(gkey, sizeof(gkey), "%s_%d", CONFIG_ITEM_VMC, slot);
    configGetStrCopy(configSet, gkey, vmc, length);
}

void configSetVMC(config_set_t *configSet, const char *vmc, int slot)
{
    char gkey[CONFIG_KEY_NAME_LEN];
    if (vmc[0] == '\0') {
        configRemoveVMC(configSet, slot);
        return;
    }
    snprintf(gkey, sizeof(gkey), "%s_%d", CONFIG_ITEM_VMC, slot);
    configSetStr(configSet, gkey, vmc);
}

void configRemoveVMC(config_set_t *configSet, int slot)
{
    char gkey[CONFIG_KEY_NAME_LEN];
    snprintf(gkey, sizeof(gkey), "%s_%d", CONFIG_ITEM_VMC, slot);
    configRemoveKey(configSet, gkey);
}
