/*
  padfile.c .pad, HID device profiles for PADEMU (RIPPS2 build 126): the reference reader and packer

  Copyright 2026, RIPPS2 contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  RIPPS2 defines the format (its pad-spec.md, format 1; docs/PAD-PROFILES.md here) and this is its reference code: the
  text read and checked, a profile packed into the block PADEMU gets, and the generic decoder that block drives. Plain C,
  no PS2 headers and no allocation, so a launcher, ee_core, an IRX or a PC tool builds it as it is (include/padfile.h). A
  file that is not right is refused with the line and the reason: it never reaches a game half read.

  From RIPPS2 v1.2.9-beta (build 129), https://github.com/akilluminati47/RIPPS2, by akilluminati47. Changed here only so
  it also builds as C++ and passes this repository's clang-format: two casts from void * and parentheses round three
  nested conditionals. Behaviour is RIPPS2's.
*/

#ifndef PADFILE_DECODE_ONLY
#include <string.h>
#include <stdio.h>
#endif

#include "include/padfile.h"

// RIPPS2 build 129: PADFILE_DECODE_ONLY builds the block's reader and the decoder alone (PADEMU on the IOP: no text, no
// libc, memcpy and memset given by the includer); the launcher and the PC tools build all of it
#ifndef PADFILE_DECODE_ONLY

static const char *const padButtonNames[PAD_B_COUNT] = {"select", "l3", "r3", "start", "up", "right", "down", "left",
                                                        "l2", "r2", "l1", "r1", "triangle", "circle", "cross", "square"};
static const char *const padAxisNames[PAD_AX_COUNT] = {"lx", "ly", "rx", "ry"};
static const char *const padDecoderNames[PAD_DEC_COUNT] = {"generic", "ds3", "ds4", "guitar_gh", "guitar_rb"};
static const char *const padSections[] = {"device", "buttons", "axes", "triggers", "mapping", "rumble"};

static int padLower(int c)
{
    return c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c;
}

static int padSame(const char *a, const char *b) // case-insensitive equality
{
    while (*a && padLower((unsigned char)*a) == padLower((unsigned char)*b)) {
        a++;
        b++;
    }
    return *a == '\0' && *b == '\0';
}

// a number: decimal or 0x hex; -1 when it is not one
static int padNumber(const char *s)
{
    int v = 0, base = 10, digits = 0;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        base = 16;
        s += 2;
    }
    for (; *s; s++, digits++) {
        int c = padLower((unsigned char)*s), d;
        if (c >= '0' && c <= '9')
            d = c - '0';
        else if (base == 16 && c >= 'a' && c <= 'f')
            d = c - 'a' + 10;
        else
            return -1;
        v = v * base + d;
        if (v > 0xFFFF)
            return -1;
    }
    return digits ? v : -1;
}

static int padFind(const char *const *names, int n, const char *key)
{
    int i;
    for (i = 0; i < n; i++)
        if (padSame(names[i], key))
            return i;
    return -1;
}

// The file a line at a time: key and value trimmed, comments and blank lines skipped, a [Section] checked. Calls
// line(ctx, n, key, value) for each key=value; stops at the first nonzero and returns it
typedef int (*pad_line_t)(void *ctx, int n, const char *key, const char *value, char *err, int errSize);

static int padLines(const char *text, int len, pad_line_t line, void *ctx, char *err, int errSize)
{
    char buf[160], *key, *value, *eq, *end;
    int pos = 0, n = 0, r;

    while (pos < len) {
        int start = pos, l;
        while (pos < len && text[pos] != '\n')
            pos++;
        l = pos - start;
        pos++; // past the '\n'
        n++;
        if (l >= (int)sizeof(buf)) {
            snprintf(err, errSize, "line %d: longer than %d characters", n, (int)sizeof(buf) - 1);
            return -1;
        }
        memcpy(buf, text + start, l);
        buf[l] = '\0';
        if ((end = strchr(buf, '#')) != NULL)
            *end = '\0';
        for (key = buf; *key == ' ' || *key == '\t'; key++)
            ;
        for (end = key + strlen(key); end > key && (end[-1] == ' ' || end[-1] == '\t' || end[-1] == '\r'); end--)
            ;
        *end = '\0';
        if (*key == '\0')
            continue;
        if (*key == '[') { // a section: one of the format's, else a newer one this reader skips
            if (end[-1] != ']') {
                snprintf(err, errSize, "line %d: a section ends with ]", n);
                return -1;
            }
            continue;
        }
        if ((eq = strchr(key, '=')) == NULL) {
            snprintf(err, errSize, "line %d: not key=value", n);
            return -1;
        }
        for (end = eq; end > key && (end[-1] == ' ' || end[-1] == '\t'); end--)
            ;
        *end = '\0';
        for (value = eq + 1; *value == ' ' || *value == '\t'; value++)
            ;
        if ((r = line(ctx, n, key, value, err, errSize)) != 0)
            return r;
    }
    (void)padSections;
    return 0;
}

typedef struct
{
    pad_def_t *d;
    int format;
} pad_parse_t;

// "b3.1", "!b3.1", "a7", "none" into a button; 1 when it was one of those
static int padButtonValue(pad_def_t *d, int b, const char *v, int n, char *err, int errSize)
{
    int low = 0, byte, bit = 0;
    const char *dot;

    d->present &= ~(1u << b);
    d->activeLow &= ~(1u << b);
    d->fromAxis &= ~(1u << b);
    d->button[b] = PAD_REF_NONE;
    if (padSame(v, "none"))
        return 0;
    if (v[0] == '!') {
        low = 1;
        v++;
    }
    if ((v[0] == 'a' || v[0] == 'A') && !low) {
        if ((byte = padNumber(v + 1)) < 0 || byte > PAD_BYTE_MAX) {
            snprintf(err, errSize, "line %d: %s wants a<byte> with the byte 0-%d", n, padButtonNames[b], PAD_BYTE_MAX);
            return -1;
        }
        d->button[b] = (unsigned char)byte;
        d->fromAxis |= 1u << b;
        d->present |= 1u << b;
        return 0;
    }
    if ((v[0] != 'b' && v[0] != 'B') || (dot = strchr(v, '.')) == NULL || dot[1] < '0' || dot[1] > '7' || dot[2] != '\0') {
        snprintf(err, errSize, "line %d: %s wants b<byte>.<bit>, !b<byte>.<bit>, a<byte> or none", n, padButtonNames[b]);
        return -1;
    }
    {
        char num[8];
        int k = (int)(dot - v - 1);
        if (k <= 0 || k >= (int)sizeof(num)) {
            snprintf(err, errSize, "line %d: %s has no byte", n, padButtonNames[b]);
            return -1;
        }
        memcpy(num, v + 1, k);
        num[k] = '\0';
        byte = padNumber(num);
    }
    bit = dot[1] - '0';
    if (byte < 0 || byte > PAD_BYTE_MAX) {
        snprintf(err, errSize, "line %d: %s's byte must be 0-%d (after offset)", n, padButtonNames[b], PAD_BYTE_MAX);
        return -1;
    }
    d->button[b] = (unsigned char)(byte | bit << 5);
    d->present |= 1u << b;
    if (low)
        d->activeLow |= 1u << b;
    return 0;
}

static int padDefLine(void *ctx, int n, const char *key, const char *v, char *err, int errSize)
{
    pad_parse_t *p = (pad_parse_t *)ctx;
    pad_def_t *d = p->d;
    int i, num;

    if ((i = padFind(padButtonNames, PAD_B_COUNT, key)) >= 0)
        return padButtonValue(d, i, v, n, err, errSize);
    if ((i = padFind(padAxisNames, PAD_AX_COUNT, key)) >= 0) {
        int inv = 0;
        char num2[8];
        size_t l = strlen(v);
        if (padSame(v, "none")) {
            d->axis[i] = PAD_REF_NONE;
            return 0;
        }
        if (l > 1 && v[l - 1] == '-')
            inv = 1, l--;
        if ((v[0] != 'a' && v[0] != 'A') || l < 2 || l - 1 >= sizeof(num2)) {
            snprintf(err, errSize, "line %d: %s wants a<byte> (a<byte>- inverts) or none", n, key);
            return -1;
        }
        memcpy(num2, v + 1, l - 1);
        num2[l - 1] = '\0';
        if ((num = padNumber(num2)) < 0 || num > 0x7E) {
            snprintf(err, errSize, "line %d: %s's byte must be 0-126", n, key);
            return -1;
        }
        d->axis[i] = (unsigned char)(num | (inv ? PAD_AXIS_INVERT : 0));
        return 0;
    }
    if (padSame(key, "format")) {
        if ((p->format = padNumber(v)) < 1) {
            snprintf(err, errSize, "line %d: format is a number", n);
            return -1;
        }
        if (p->format > PAD_FORMAT) {
            snprintf(err, errSize, "line %d: made for .pad format %d, this reads %d", n, p->format, PAD_FORMAT);
            return -1;
        }
        return 0;
    }
    if (padSame(key, "decoder")) {
        if ((i = padFind(padDecoderNames, PAD_DEC_COUNT, v)) < 0) {
            snprintf(err, errSize, "line %d: decoder is generic, ds3, ds4, guitar_gh or guitar_rb", n);
            return -1;
        }
        d->decoder = (unsigned char)i;
        return 0;
    }
    if (padSame(key, "dpad")) {
        if (padSame(v, "none") || padSame(v, "buttons")) {
            d->hat = PAD_REF_NONE;
            return 0;
        }
        if (padLower((unsigned char)v[0]) != 'h' || padLower((unsigned char)v[1]) != 'a' || padLower((unsigned char)v[2]) != 't' ||
            (num = padNumber(v + 3)) < 0 || num > 0x7E) {
            snprintf(err, errSize, "line %d: dpad wants hat<byte> (0-126), buttons or none", n);
            return -1;
        }
        d->hat = (unsigned char)num;
        return 0;
    }
    if (padSame(key, "report_id")) {
        if (padSame(v, "none")) {
            d->flags &= ~PAD_F_REPORT_ID;
            return 0;
        }
        if ((num = padNumber(v)) < 0 || num > 255) {
            snprintf(err, errSize, "line %d: report_id is none or a byte", n);
            return -1;
        }
        d->reportId = (unsigned char)num;
        d->flags |= PAD_F_REPORT_ID;
        return 0;
    }
    if (padSame(key, "offset") || padSame(key, "deadzone")) {
        int dz = padSame(key, "deadzone");
        if ((num = padNumber(v)) < 0 || num > (dz ? 127 : 255)) {
            snprintf(err, errSize, "line %d: %s is a number 0-%d", n, key, dz ? 127 : 255);
            return -1;
        }
        if (dz)
            d->deadzone = (unsigned char)num;
        else
            d->offset = (unsigned char)num;
        return 0;
    }
    if (padSame(key, "rumble") || padSame(key, "led") || padSame(key, "init")) {
        int k = padSame(key, "rumble") ? 0 : (padSame(key, "led") ? 1 : 2);
        unsigned char ds3 = k == 0 ? PAD_F_RUMBLE_DS3 : (k == 1 ? PAD_F_LED_DS3 : PAD_F_INIT_DS3);
        unsigned char ds4 = k == 0 ? PAD_F_RUMBLE_DS4 : (k == 1 ? PAD_F_LED_DS4 : 0);
        d->flags &= ~(ds3 | ds4);
        if (padSame(v, "ds3"))
            d->flags |= ds3;
        else if (padSame(v, "ds4") && ds4)
            d->flags |= ds4;
        else if (!padSame(v, "off")) {
            snprintf(err, errSize, "line %d: %s is %s", n, key, k == 2 ? "off or ds3" : "off, ds3 or ds4");
            return -1;
        }
        return 0;
    }
    return 0; // name= and keys of a newer format: not the block's
}

int padDefParse(const char *text, int len, unsigned vid, unsigned pid, pad_def_t *out, char *err, int errSize)
{
    pad_def_t d;
    pad_parse_t p;

    memset(&d, 0, sizeof(d));
    memset(d.axis, PAD_REF_NONE, sizeof(d.axis));
    memset(d.button, PAD_REF_NONE, sizeof(d.button));
    d.hat = PAD_REF_NONE;
    d.vid = (unsigned short)vid;
    d.pid = (unsigned short)pid;
    p.d = &d;
    p.format = PAD_FORMAT;
    if (err != NULL && errSize > 0)
        err[0] = '\0';
    if (padLines(text, len, padDefLine, &p, err, errSize) != 0)
        return -1;
    if (d.decoder == PAD_DEC_GENERIC && d.present == 0 && d.hat == PAD_REF_NONE) {
        snprintf(err, errSize, "no buttons: a generic profile maps at least one");
        return -1;
    }
    if (d.hat != PAD_REF_NONE && (d.present & (1u << PAD_B_UP | 1u << PAD_B_DOWN | 1u << PAD_B_LEFT | 1u << PAD_B_RIGHT))) {
        snprintf(err, errSize, "dpad=hat and up/down/left/right both given: one or the other");
        return -1;
    }
    *out = d;
    return 0;
}

static int padMapLine(void *ctx, int n, const char *key, const char *v, char *err, int errSize)
{
    unsigned char *map = (unsigned char *)ctx;
    int from = padFind(padButtonNames, PAD_B_COUNT, key), to;

    if (padSame(key, "format")) {
        if (padNumber(v) < 1 || padNumber(v) > PAD_FORMAT) {
            snprintf(err, errSize, "line %d: made for .pad format %s, this reads %d", n, v, PAD_FORMAT);
            return -1;
        }
        return 0;
    }
    if (from < 0)
        return 0; // a newer key
    if (padSame(v, "none")) {
        map[from] = PAD_REF_NONE - 1; // 0xFE: the press reaches nothing
        return 0;
    }
    if ((to = padFind(padButtonNames, PAD_B_COUNT, v)) < 0) {
        snprintf(err, errSize, "line %d: %s maps to a button name or none", n, key);
        return -1;
    }
    map[from] = to == from ? PAD_REMAP_SAME : (unsigned char)to;
    return 0;
}

int padMapParse(const char *text, int len, unsigned char map[PAD_B_COUNT], char *err, int errSize)
{
    unsigned char m[PAD_B_COUNT];
    memset(m, PAD_REMAP_SAME, sizeof(m));
    if (err != NULL && errSize > 0)
        err[0] = '\0';
    if (padLines(text, len, padMapLine, m, err, errSize) != 0)
        return -1;
    memcpy(map, m, sizeof(m));
    return 0;
}

int padFileId(const char *name, unsigned *vid, unsigned *pid)
{
    unsigned v = 0, p = 0;
    int i;

    for (i = 0; i < 9; i++) {
        int c = padLower((unsigned char)name[i]), d;
        if (i == 4) {
            if (c != '_')
                return -1;
            continue;
        }
        if (c >= '0' && c <= '9')
            d = c - '0';
        else if (c >= 'a' && c <= 'f')
            d = c - 'a' + 10;
        else
            return -1;
        if (i < 4)
            v = v << 4 | d;
        else
            p = p << 4 | d;
    }
    if (!padSame(name + 9, ".pad"))
        return -1;
    *vid = v;
    *pid = p;
    return 0;
}

#endif // PADFILE_DECODE_ONLY: the text and the packer above

#ifndef PADFILE_DECODE_ONLY
static void padPut16(unsigned char *o, unsigned v)
{
    o[0] = (unsigned char)v;
    o[1] = (unsigned char)(v >> 8);
}

#endif

static unsigned padGet16(const unsigned char *o)
{
    return o[0] | o[1] << 8;
}

#ifndef PADFILE_DECODE_ONLY
int padBlockPack(const pad_def_t *defs, int count, const unsigned char *map, unsigned char out[PAD_BLOCK_SIZE])
{
    int i;
    unsigned char *o;

    memset(out, 0, PAD_BLOCK_SIZE);
    if (count < 0)
        count = 0;
    if (count > PAD_DEFS_MAX)
        count = PAD_DEFS_MAX;
    out[0] = 'P';
    out[1] = 'D';
    out[2] = PAD_FORMAT;
    out[3] = (unsigned char)count;
    for (i = 0; i < count; i++) {
        const pad_def_t *d = &defs[i];
        o = out + 4 + i * PAD_DEF_SIZE;
        padPut16(o, d->vid);
        padPut16(o + 2, d->pid);
        o[4] = d->decoder;
        o[5] = d->reportId;
        o[6] = d->offset;
        o[7] = d->flags;
        o[8] = d->deadzone;
        o[9] = d->hat;
        memcpy(o + 10, d->axis, PAD_AX_COUNT);
        memcpy(o + 14, d->button, PAD_B_COUNT);
        padPut16(o + 30, d->present);
        padPut16(o + 32, d->activeLow);
        padPut16(o + 34, d->fromAxis);
        memset(o + 36, 0, 4);
    }
    o = out + 4 + PAD_DEFS_MAX * PAD_DEF_SIZE;
    if (map != NULL)
        memcpy(o, map, PAD_B_COUNT);
    else
        memset(o, PAD_REMAP_SAME, PAD_B_COUNT);
    return PAD_BLOCK_SIZE;
}

#endif

int padBlockUnpack(const unsigned char *in, int size, pad_def_t defs[PAD_DEFS_MAX], int *count, unsigned char map[PAD_B_COUNT])
{
    int i;
    const unsigned char *o;

    if (size < PAD_BLOCK_SIZE || in[0] != 'P' || in[1] != 'D' || in[2] != PAD_FORMAT || in[3] > PAD_DEFS_MAX)
        return -1;
    *count = in[3];
    for (i = 0; i < *count; i++) {
        pad_def_t *d = &defs[i];
        o = in + 4 + i * PAD_DEF_SIZE;
        d->vid = (unsigned short)padGet16(o);
        d->pid = (unsigned short)padGet16(o + 2);
        d->decoder = o[4];
        d->reportId = o[5];
        d->offset = o[6];
        d->flags = o[7];
        d->deadzone = o[8];
        d->hat = o[9];
        memcpy(d->axis, o + 10, PAD_AX_COUNT);
        memcpy(d->button, o + 14, PAD_B_COUNT);
        d->present = (unsigned short)padGet16(o + 30);
        d->activeLow = (unsigned short)padGet16(o + 32);
        d->fromAxis = (unsigned short)padGet16(o + 34);
        memset(d->spare, 0, sizeof(d->spare));
    }
    memcpy(map, in + 4 + PAD_DEFS_MAX * PAD_DEF_SIZE, PAD_B_COUNT);
    return 0;
}

void padTranslate(const pad_def_t *def, const unsigned char *report, int len, unsigned short *buttons, unsigned char axes[4])
{
    static const unsigned char hatBits[8] = {1u << (PAD_B_UP - 4), 1u << (PAD_B_UP - 4) | 1u << (PAD_B_RIGHT - 4),
                                             1u << (PAD_B_RIGHT - 4), 1u << (PAD_B_RIGHT - 4) | 1u << (PAD_B_DOWN - 4),
                                             1u << (PAD_B_DOWN - 4), 1u << (PAD_B_DOWN - 4) | 1u << (PAD_B_LEFT - 4),
                                             1u << (PAD_B_LEFT - 4), 1u << (PAD_B_LEFT - 4) | 1u << (PAD_B_UP - 4)};
    unsigned pressed = 0;
    int base = def->offset, i;

    if ((def->flags & PAD_F_REPORT_ID) && len > 0 && report[0] == def->reportId)
        base++;
    for (i = 0; i < PAD_B_COUNT; i++) {
        int at, on;
        if (!(def->present & (1u << i)))
            continue;
        if (def->fromAxis & (1u << i)) {
            at = base + def->button[i];
            on = at < len && report[at] >= 0x80;
        } else {
            at = base + (def->button[i] & 0x1F);
            on = at < len && ((report[at] >> (def->button[i] >> 5)) & 1);
            if (def->activeLow & (1u << i))
                on = at < len && !on;
        }
        if (on)
            pressed |= 1u << i;
    }
    if (def->hat != PAD_REF_NONE && base + def->hat < len) {
        unsigned h = report[base + def->hat] & 0x0F;
        if (h < 8)
            pressed |= (unsigned)hatBits[h] << 4;
    }
    for (i = 0; i < PAD_AX_COUNT; i++) {
        unsigned char a = def->axis[i];
        int v = 128, at = base + (a & 0x7F);
        if (a != PAD_REF_NONE && at < len) {
            v = report[at];
            if (a & PAD_AXIS_INVERT)
                v = 255 - v;
            if (v - 128 <= def->deadzone && 128 - v <= def->deadzone)
                v = 128;
        }
        axes[i] = (unsigned char)v;
    }
    *buttons = (unsigned short)~pressed;
}

unsigned short padApplyMap(unsigned short buttons, const unsigned char map[PAD_B_COUNT])
{
    unsigned pressed = (unsigned short)~buttons, out = 0;
    int i;

    for (i = 0; i < PAD_B_COUNT; i++) {
        if (!(pressed & (1u << i)))
            continue;
        if (map[i] == PAD_REMAP_SAME)
            out |= 1u << i;
        else if (map[i] < PAD_B_COUNT)
            out |= 1u << map[i]; // 0xFE (none): the press reaches nothing
    }
    return (unsigned short)~out;
}

int padMapIsSame(const unsigned char map[PAD_B_COUNT])
{
    int i;
    for (i = 0; i < PAD_B_COUNT; i++)
        if (map[i] != PAD_REMAP_SAME)
            return 0;
    return 1;
}
