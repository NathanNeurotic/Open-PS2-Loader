# test_ripps2_pad129.py .pad phase 2 (RIPPS2 build 129), run against this tree, and this port's own rules for it
#
# Copyright 2026, RIPPS2 contributors
# Licenced under Academic Free License version 3.0
# Review OpenUsbLd README & LICENSE files for further details.
#
# From RIPPS2 build 126-129 by akilluminati47 (https://github.com/akilluminati47/RIPPS2).
"""RIPPS2 build 129: .pad phase 2, run against this tree, and this port's own rules for it.

RIPPS2's test_ripps2_pad129.py, with this tree's names: src/padprofiles.c and padProfilesBlock, padProfilesPrepare,
padProfilesMenuLoad, padProfilesMenuTick and padProfilesMenuLearn for RIPPS2's src/ripps2pads.c and its ripps2Pads*
functions, and PAD_SETUP_BUTTON and the PAD_SETUP and HINT_PAD_SETUP labels for RIPPS2's RIPPS2_PAD_SETUP ones. The
format, and what this build does with it: docs/PAD-PROFILES.md.

RIPPS2's checks: PADEMU reads the block the launcher packs (padprofile.c, the reference decoder built decode-only),
ee_core hands it over after PADEMU's eight bytes with flag 1 << 19, the menu's USB pad driver reads the same block and
lets Set Up A USB Pad see a HID pad's reports, and the setup screen finds a button, a hat, a trigger and a stick from
what moved. On the PC: the wiring, padApplyMap, padfile.c built decode-only, and the setup screen's finder run on a
made-up pad. Changed from RIPPS2's test: a launch reads PADS in sbPrepare (src/supportbase.c), where RIPPS2 calls
ripps2PadsPrepare(gameIdStartup) in opl.c, so either file may hold the call; readPads may call padProfilesMenuTick under
#ifdef PADEMU; PAD_SETUP_SWING is read from gui.c rather than written here; the tree is this checkout unless RIPTOPL_DIR
names another.

This port's rules (each failure starts "this port:"):
1. PadEmuArgs is the last member of EECoreConfig_t, in no #if: the launcher and ee_core read the struct alike.
2. With PadEmuArgs NULL, ee_core clears bit 19 and hands PADEMU its eight bytes, as before profiles.
3. padprofile.c undefines memcpy and memset before it defines its own and builds padfile.c.
4. Neither PADEMU's usb_probe and usb_connect nor the menu driver's take a Sony vendor ID (054C, 12BA) for a profile.
5. Set Up A USB Pad puts an older file aside with fmRename, never rename(), and creates the new one with mode 0666.
6. padProfilesDir, compiled on the PC: PADS beside the settings; none for an empty home, mc? (no card found) or raw APA
   (hdd...), and none cut short.
7. Only the USB PADEMU links padprofile.o, and pademu.c reads the block in its USB build only.
8. PADEMU decodes a profiled pad's report with the length the transfer brought, not 64.
9. After a wait that ran out, the menu's driver drops the signal of a transfer that completed late before it reads it.
10. Both IOP Makefiles rebuild padprofile.o when src/padfile.c or include/padfile.h changes, and the top-level Makefile
    enters both sub-makes to let them.
11. PADEMU's game map moves a button's pressure byte with its press (a game in mode 0x79 reads both), compiled on the PC.
12. The menu's driver registers again for a profiled pad that was plugged in before its profile came, when a slot it
    reads is free (usbd-ra's own register and unregister, compiled on the PC), and imports sceUsbdUnregisterLdd for it.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(os.environ.get('RIPTOPL_DIR') or Path(__file__).resolve().parents[2])
fail = []


def text(rel):
    p = root / rel
    if not p.exists():
        fail.append(rel + ' missing')
        return ''
    return p.read_text(encoding='utf-8', errors='replace')


top_mk = text('Makefile')
pademu_mk = text('modules/pademu/Makefile')
pademu = text('modules/pademu/pademu.c')
pademu_usb = text('modules/pademu/ds34usb.c')
prof = text('modules/pademu/padprofile.c')
menu_mk = text('modules/ds34usb/iop/Makefile')
menu = text('modules/ds34usb/iop/ds34usb.c')
menu_ee = text('modules/ds34usb/ee/libds34usb.c')
iopmgr = text('ee_core/src/iopmgr.c')
coreconfig = text('ee_core/include/coreconfig.h')
system = text('src/system.c')
opl = text('src/opl.c')
supportbase = text('src/supportbase.c')
pads = text('src/padprofiles.c')
pad = text('src/pad.c')
gui = text('src/gui.c')
dialogs = text('src/dialogs.c')
base = text('lng_tmpl/_base.yml')
usbd_driver = text('modules/usb/usbd-ra/src/driver.c')


def blank(src):
    """C text with its comments and string and character literals blanked, same length and lines, for matching code."""
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith('//', i):
            j = src.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))
        elif src.startswith('/*', i):
            j = src.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r'[^\n]', ' ', src[i:j]))
        elif src[i] in '"\'':
            q, j = src[i], i + 1
            while j < n and src[j] != q and src[j] != '\n':
                j += 2 if src[j] == '\\' else 1
            j = min(j + 1, n)
            out.append(q + ' ' * (j - i - 2) + q if j - i >= 2 else src[i:j])
        else:
            j = i + 1
            out.append(src[i])
        i = j
    return ''.join(out)


def close(code, at):
    """code[at] is an opening brace or parenthesis: the index just past its match, or -1."""
    pair = {'{': '}', '(': ')'}[code[at]]
    depth = 0
    for i in range(at, len(code)):
        if code[i] == code[at]:
            depth += 1
        elif code[i] == pair:
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def functions(code, name_re):
    """(name, start, end) of each function defined in blanked code whose name matches name_re."""
    found = []
    for m in re.finditer(r'^[A-Za-z_][\w \t*]*?\b(' + name_re + r')\s*\([^;{)]*\)\s*\{', code, re.M):
        end = close(code, m.end() - 1)
        if end > 0:
            found.append((m.group(1), m.start(), end))
    return found


def body(code, name):
    f = functions(code, re.escape(name))
    return code[f[0][1]:f[0][2]] if f else ''


def call_args(code, at):
    """The arguments of the call whose '(' is at code[at], split at its top-level commas."""
    end = close(code, at)
    if end < 0:
        return []
    args, depth, cur = [], 0, ''
    for c in code[at + 1:end - 1]:
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        if c == ',' and depth == 0:
            args.append(cur.strip())
            cur = ''
        else:
            cur += c
    args.append(cur.strip())
    return args


def make_lines(mk):
    """Makefile lines with continuations joined and comments dropped."""
    return [line.split('#', 1)[0].rstrip() for line in re.sub(r'\\\n', ' ', mk).split('\n')]


# RIPPS2's checks, with this tree's names
code_pad = blank(pad)
prepare = re.compile(r'\bpadProfilesPrepare\s*\(')
checks = [
    ('padprofile.o' in pademu_mk, 'pademu Makefile: padprofile.o'),
    ('PADEMU_PROFILES_FLAG' in pademu and 'padProfilesLoad' in pademu, 'pademu.c: the block read after the settings'),
    ('GENERIC' in pademu_usb and 'padProfileDecode' in pademu_usb and 'padGameMapApply' in pademu_usb,
     'PADEMU ds34usb.c: a profiled pad decoded, the game map applied'),
    ('PADFILE_DECODE_ONLY' in prof and 'PADPROFILE_NO_IMPORTS' in prof, 'padprofile.c: decode-only, shared with the menu driver'),
    ('padprofile.o' in menu_mk, 'menu ds34usb Makefile: padprofile.o'),
    ('DS34USB_GET_RAW' in menu and 'DS34USB_SET_PROFILES' in menu and 'pads_learn' in menu, 'menu ds34usb.c: raw reports, profiles, learn'),
    ('rpcbuf[256]' in menu_ee and 'ds34usb_get_raw' in menu_ee and 'ds34usb_set_profiles' in menu_ee, 'libds34usb: the new calls'),
    ('PadEmuArgs' in coreconfig, 'coreconfig.h: PadEmuArgs'),
    ('(1 << 19)' in iopmgr and '8 + 180' in iopmgr, 'iopmgr.c: PADEMU gets the block and the flag'),
    ('PadEmuArgs' in system and 'padProfilesBlock' in system, 'system.c: the block placed for ee_core'),
    ((prepare.search(blank(supportbase)) or prepare.search(blank(opl))) and 'padProfilesMenuLoad()' in opl,
     'opl.c/supportbase.c: launch and boot read PADS'),
    ('padProfilesMenuTick' in pads and 'padProfilesMenuLearn' in pads, 'padprofiles.c: the menu copy'),
    ('padProfilesMenuTick();' in body(code_pad, 'readPads'), 'pad.c: readPads hands profiles to the driver'),
    ('guiSetUpUsbPad' in gui and re.search(r'\bPAD_SETUP_BUTTON\b', dialogs), 'gui.c/dialogs.c: Set Up A USB Pad'),
    (re.search(r'^\s*(?:-\s*)?label:\s*PAD_SETUP\s*$', base, re.M) and
     re.search(r'^\s*(?:-\s*)?label:\s*HINT_PAD_SETUP\s*$', base, re.M), '_base.yml: the button and its hint'),
]
for ok, what in checks:
    if not ok:
        fail.append(what)


def grab(src, start, what, end_marker='\n}\n'):
    i = src.find(start)
    j = src.find(end_marker, i) if i >= 0 else -1
    if j < 0:
        fail.append('gui.c: ' + what + ' not found')
        return ''
    return src[i:j + len(end_marker)]


swing = re.search(r'^\s*#\s*define\s+PAD_SETUP_SWING\s+(0x[0-9A-Fa-f]+|\d+)\b', gui, re.M)
if not swing:
    fail.append('gui.c: #define PAD_SETUP_SWING not found')
parts = [
    grab(gui, 'typedef struct\n{\n    int port, len, seq;', 'pad_setup_raw_t', '} pad_setup_raw_t;\n'),
    grab(gui, 'static int padSetupBits(', 'padSetupBits'),
    grab(gui, 'static int padSetupFind(', 'padSetupFind'),
    grab(gui, 'static int padSetupAtRest(', 'padSetupAtRest'),
]
finder = '\n'.join(parts) if swing and all(parts) else ''

PROG = r'''
#include <stdio.h>
#include <string.h>
#include "include/padfile.h"
#define PAD_SETUP_SWING ''' + (swing.group(1) if swing else '0x50') + '\n' + finder + r'''
int main(void)
{
    /* a made-up pad: byte 0 face buttons, byte 1 the rest (bit 3 set at rest: pressed is 0), byte 2 a hat (8 = centre),
       bytes 3-6 sticks round 0x80, byte 7 an analog L2, byte 8 a counter */
    unsigned char rest[16] = {0x00, 0x08, 0x08, 0x80, 0x7F, 0x80, 0x81, 0x00, 0x00};
    unsigned char noise[16] = {0, 0, 0, 3, 2, 3, 2, 0, 0xFF};
    unsigned char usedBits[16] = {0}, usedAxis[16] = {0};
    pad_setup_raw_t p;
    unsigned short buttons;
    unsigned char axes[4];
    int at = -1, bit = -1, low = -1;
    unsigned char map[PAD_B_COUNT];
    pad_def_t d;
    char err[96];
    const char *made = "[Device]\nformat=1\ndecoder=generic\n[Buttons]\ncross=b0.1\nselect=!b1.3\nl2=a7\nup=none\n[Axes]\n"
                       "dpad=hat2\nlx=a3\nly=a4-\ndeadzone=12\n";

    memset(&p, 0, sizeof(p));
    p.len = 9;
    memcpy(p.r, rest, 16);
    if (padSetupFind(rest, noise, &p, 0, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 0) return 1; /* nothing moved */
    p.r[0] = 0x02;
    if (padSetupFind(rest, noise, &p, 0, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 1 || at != 0 || bit != 1 || low) return 2;
    if (padSetupAtRest(rest, noise, usedAxis, &p)) return 3;
    usedBits[0] |= 2;
    if (padSetupFind(rest, noise, &p, 0, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 0) return 4; /* a used bit is not found again */
    memcpy(p.r, rest, 16);
    p.r[1] = 0x00;
    if (padSetupFind(rest, noise, &p, 0, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 1 || at != 1 || bit != 3 || !low) return 5;
    memcpy(p.r, rest, 16);
    p.r[2] = 0x00; /* Up on the hat: one bit drops, but on a d-pad step it is the hat */
    if (padSetupFind(rest, noise, &p, 0, 1, 0, usedBits, usedAxis, &at, &bit, &low) != 2 || at != 2) return 6;
    memcpy(p.r, rest, 16);
    p.r[7] = 0xFF; /* L2, an analog trigger */
    if (padSetupFind(rest, noise, &p, 0, 0, 1, usedBits, usedAxis, &at, &bit, &low) != 3 || at != 7) return 7;
    p.r[7] = 0x01; /* its first step down is one bit: not yet anything on a trigger step */
    if (padSetupFind(rest, noise, &p, 0, 0, 1, usedBits, usedAxis, &at, &bit, &low) == 3) return 8;
    memcpy(p.r, rest, 16);
    p.r[3] = 0xFF; /* the left stick to the right */
    if (padSetupFind(rest, noise, &p, 1, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 3 || at != 3 || low) return 9;
    p.r[3] = 0x80;
    p.r[4] = 0x00; /* "down" ran the other way: inverted */
    if (padSetupFind(rest, noise, &p, 1, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 3 || at != 4 || !low) return 10;
    memcpy(p.r, rest, 16);
    p.r[8] = 0x55; /* the counter moved: not a press, and still at rest */
    if (padSetupFind(rest, noise, &p, 0, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 0 || !padSetupAtRest(rest, noise, usedAxis, &p)) return 11;
    usedAxis[3] = 1;
    p.r[3] = 0x90; /* an axis a little off rest is at rest */
    if (!padSetupAtRest(rest, noise, usedAxis, &p)) return 12;
    /* what the screen writes, read back and run */
    if (padDefParse(made, strlen(made), 0x1234, 0x5678, &d, err, sizeof(err))) { printf("%s\n", err); return 13; }
    memcpy(p.r, rest, 16);
    p.r[0] = 0x02; p.r[1] = 0x00; p.r[2] = 0x06; p.r[7] = 0xC0; p.r[4] = 0x00;
    padTranslate(&d, p.r, p.len, &buttons, axes);
    if (buttons != (unsigned short)~(1u << PAD_B_CROSS | 1u << PAD_B_SELECT | 1u << PAD_B_L2 | 1u << PAD_B_LEFT) || axes[PAD_AX_LY] != 255)
        { printf("buttons %04x ly %d\n", buttons, axes[PAD_AX_LY]); return 14; }
    /* the game map: CROSS to CIRCLE, SELECT to nothing, the rest as they were */
    memset(map, PAD_REMAP_SAME, sizeof(map));
    if (!padMapIsSame(map)) return 15;
    map[PAD_B_CROSS] = PAD_B_CIRCLE;
    map[PAD_B_SELECT] = 0xFE;
    if (padMapIsSame(map)) return 16;
    buttons = padApplyMap((unsigned short)~(1u << PAD_B_CROSS | 1u << PAD_B_SELECT | 1u << PAD_B_START), map);
    if (buttons != (unsigned short)~(1u << PAD_B_CIRCLE | 1u << PAD_B_START)) { printf("map %04x\n", buttons); return 17; }
    printf("pad129 ok\n");
    return 0;
}
'''


# This port's rules
def port(what):
    fail.append('this port: ' + what)


def check_last_member():
    code = blank(coreconfig)
    m = re.search(r'\bstruct\s+EECoreConfig_t\s*\{', code)
    end = close(code, m.end() - 1) if m else -1
    if end < 0:
        return port('coreconfig.h: struct EECoreConfig_t not found')
    depth, last = 0, None
    for line in code[m.end():end - 1].split('\n'):
        s = line.strip()
        d = re.match(r'#\s*(if|ifdef|ifndef|elif|else|endif)\b', s)
        if d:
            depth += {'if': 1, 'ifdef': 1, 'ifndef': 1, 'endif': -1}.get(d.group(1), 0)
        elif s:
            last = (s, depth)
    if last is None or not re.fullmatch(r'char\s*\*\s*PadEmuArgs\s*;', last[0]):
        port('coreconfig.h: PadEmuArgs is not the last member of EECoreConfig_t (the last is %r)' % (last and last[0]))
    elif last[1]:
        port('coreconfig.h: PadEmuArgs, the last member of EECoreConfig_t, is inside an #if')


def check_bit19_clear():
    code = blank(iopmgr)
    m = re.search(r'\bif\s*\(\s*config->PadEmuArgs\s*(?:!=\s*NULL\s*)?\)\s*\{', code)
    if not m:
        return port('iopmgr.c: no if (config->PadEmuArgs != NULL) in New_Reset_Iop')
    then_end = close(code, m.end() - 1)
    e = re.match(r'\s*else\s*\{', code[then_end:]) if then_end > 0 else None
    if not e:
        return port('iopmgr.c: nothing loads PADEMU when PadEmuArgs is NULL')
    at = then_end + e.end() - 1
    other, before = code[at:close(code, at)], code[max(0, m.start() - 600):m.start()]
    clear = re.compile(r'&\s*~\s*(?:\(\s*1[uU]?\s*<<\s*19\s*\)|0x0*80000\b|\(?\s*PADEMU_PROFILES_FLAG\b)')
    if not (clear.search(other) or clear.search(before)):
        port('iopmgr.c: bit 19 (a block follows) is not cleared when PadEmuArgs is NULL')
    load = re.search(r'LoadOPLModule\s*\(\s*OPL_MODULE_ID_PADEMU\s*,\s*0\s*,\s*([^,]+?)\s*,', other)
    size = load.group(1) if load else ''
    by = re.fullmatch(r'sizeof\s*\(?\s*(\w+)\s*\)?', size)
    if not (size == '8' or (by and re.search(r'\b' + by.group(1) + r'\s*\[\s*8\s*\]', other + before))):
        port('iopmgr.c: PADEMU does not get exactly its 8 bytes when PadEmuArgs is NULL (%s)' % (size or 'no load'))


def check_undef():
    code = blank(prof)
    inc = re.search(r'^\s*#\s*include\s+"[^"]*src/padfile\.c"', prof, re.M)
    for name in ('memcpy', 'memset'):
        u = re.search(r'^\s*#\s*undef\s+' + name + r'\b', code, re.M)
        d = re.search(r'^\s*#\s*define\s+' + name + r'\b', code, re.M)
        if not u:
            port('padprofile.c: no #undef %s before its own %s' % (name, name))
        elif (d and u.start() > d.start()) or (inc and u.start() > inc.start()):
            port('padprofile.c: #undef %s comes after its #define or the padfile.c include' % name)


def check_sony(src, label):
    code = blank(src)
    for fn in ('usb_probe', 'usb_connect'):
        b = body(code, fn)
        call = re.search(r'\bpadProfileFind\s*\(', b)
        if not b or not call:
            port('%s: %s does not look for a profile' % (label, fn))
            continue
        head = b[:call.start()]
        if not (re.search(r'\bidVendor\s*!=\s*SONY_VID\b', head) and re.search(r'\bidVendor\s*!=\s*DS34_VID\b', head)):
            port('%s: %s looks for a profile before it rules out the Sony vendor IDs (SONY_VID, DS34_VID)' % (label, fn))


def check_setup_files():
    code = blank(gui)
    fns = functions(code, r'guiSetUpUsbPad|padSetup\w+')
    if not any(name == 'guiSetUpUsbPad' for name, _, _ in fns):
        return port('gui.c: guiSetUpUsbPad not found')
    src = ''.join(code[s:e] for _, s, e in fns)
    if not re.search(r'\bfmRename\s*\(', src):
        port('gui.c: Set Up A USB Pad does not put an older profile aside with fmRename')
    if re.search(r'(?<![\w.>])rename\s*\(', src):
        port('gui.c: Set Up A USB Pad calls rename(); fmRename works on every device')
    creating = [a for m in re.finditer(r'(?<![\w.>])open\s*\(', src) for a in [call_args(src, m.end() - 1)] if 'O_CREAT' in ' '.join(a)]
    if not creating:
        port('gui.c: Set Up A USB Pad creates no file with open(..., O_CREAT, 0666)')
    for a in creating:
        if len(a) < 3 or a[2] not in ('0666', '0x1B6', '0x1b6', '438'):
            port('gui.c: open(%s) creates a profile without mode 0666' % ', '.join(a))


def check_usb_only():
    stack, linked = [], 0
    for line in make_lines(pademu_mk):
        s = line.strip()
        if re.match(r'(ifeq|ifneq|ifdef|ifndef)\b', s):
            stack.append(re.sub(r'\s+', '', s))
        elif s.startswith('else') and stack:
            stack[-1] += ':else'
        elif s.startswith('endif') and stack:
            stack.pop()
        elif re.match(r'IOP_OBJS\s*[+:?]?=', s) and re.search(r'\bpadprofile\.o\b', s):
            linked += 1
            if stack != ['ifeq($(USE_USB),1)']:
                port('modules/pademu/Makefile: padprofile.o is linked outside the USB build (%s)' % (' / '.join(stack) or 'always'))
    if not linked:
        port('modules/pademu/Makefile: padprofile.o is never linked')
    stack = []  # per open #if: True in the USB build only, 'not' for #ifndef USB (its #else is), else False
    for line in blank(pademu).split('\n'):
        d = re.match(r'\s*#\s*(ifdef|ifndef|if|elif|else|endif)\b(.*)', line)
        if d:
            kind, cond = d.group(1), d.group(2).strip()
            if kind == 'ifdef':
                stack.append(cond == 'USB')
            elif kind == 'if':
                stack.append(bool(re.fullmatch(r'defined\s*\(?\s*USB\s*\)?', cond)))
            elif kind == 'ifndef':
                stack.append('not' if cond == 'USB' else False)
            elif kind == 'else' and stack:
                stack[-1] = stack[-1] == 'not'
            elif kind == 'elif' and stack:
                stack[-1] = False
            elif kind == 'endif' and stack:
                stack.pop()
        elif re.search(r'\bpadProfilesLoad\s*\(', line) and True not in stack:
            port('pademu.c: padProfilesLoad is called outside #ifdef USB')


def check_report_length():
    code = blank(pademu_usb)
    calls = [call_args(code, m.end() - 1) for m in re.finditer(r'\bpadProfileDecode\s*\(', code)]
    if not calls:
        return port('PADEMU ds34usb.c: no padProfileDecode call')
    for a in calls:
        if len(a) < 3 or re.fullmatch(r'MAX_BUFFER_SIZE|\d+|0x[0-9A-Fa-f]+', a[2]):
            port('PADEMU ds34usb.c: padProfileDecode gets %s as the report length, not the transfer\'s' % (a[2] if len(a) > 2 else '?'))
    if not re.search(r'[^=!<>]=[^;=]*\bbytes\b', body(code, 'usb_data_cb')):
        port('PADEMU ds34usb.c: usb_data_cb does not keep the report\'s length (bytes)')


def check_late_signal():
    b = body(blank(menu), 'ds34usb_get_data')
    sema = r'\s*\(\s*ds34pad\s*\[\s*port\s*\]\s*\.\s*data_sema\s*\)'
    wait = re.search(r'\bTransferWait' + sema, b)
    after = b[wait.end():] if wait else ''
    drop, read = re.search(r'\bPollSema' + sema, after), re.search(r'\bgenericReport\s*\(', after)
    if not (wait and drop and (not read or drop.start() < read.start())):
        port('menu ds34usb.c: after TransferWait on data_sema, a late completion\'s signal is not dropped (PollSema) before the report is read')


def check_prerequisites():
    for rel, mk, need in (('modules/pademu/Makefile', pademu_mk, ('src/padfile.c', 'include/padfile.h')),
                          ('modules/ds34usb/iop/Makefile', menu_mk, ('pademu/padprofile.c', 'src/padfile.c', 'include/padfile.h'))):
        deps = [d for line in make_lines(mk) for m in [re.match(r'\s*(\S*padprofile\.o)\s*:(?!=)(.*)', line)] if m for d in m.group(2).split()]
        for n in need:
            if not any(d == n or d.endswith('/' + n) for d in deps):
                port('%s: padprofile.o is not rebuilt when %s changes' % (rel, n))
    # the top level enters both sub-makes: a directory's timestamp does not show an edit to src/padfile.c
    lines = make_lines(top_mk)
    phony = {t for line in lines for m in [re.match(r'\s*\.PHONY\s*:(.*)', line)] if m for t in m.group(1).split()}
    for irx in ('modules/pademu/usb_pademu.irx', 'modules/ds34usb/iop/ds34usb.irx'):
        deps = [d for line in lines for m in [re.match(re.escape(irx) + r'\s*:(?!=)(.*)', line)] if m for d in m.group(1).split()]
        if not any(d in phony for d in deps) and not {'src/padfile.c', 'include/padfile.h'} <= set(deps):
            port('Makefile: %s does not enter its sub-make when src/padfile.c or include/padfile.h changes' % irx)


DIR_PROG = r'''
#include <stdio.h>
#include <string.h>
static const char *home = "";
const char *configGetHomePath(void) { return home; }
char *configGetDir(void) { static char s[] = "configGetDir:"; return s; } /* not the settings' home: PADS goes beside it */
@@FUNCTION@@
int main(void)
{
    static const char *homes[] = {HOMES};
    char out[256], small[8];
    unsigned i;
    for (i = 0; i < sizeof(homes) / sizeof(homes[0]); i++) {
        int r;
        home = homes[i];
        memset(out, 'x', sizeof(out) - 1);
        out[sizeof(out) - 1] = '\0';
        r = padProfilesDir(out, sizeof(out));
        printf("%d\t%s\n", r, r == 0 ? out : "");
    }
    home = "mass0:/RIPTOPL";
    printf("%d\n", padProfilesDir(small, sizeof(small)));
    return 0;
}
'''
# The settings' home, and the PADS folders padProfilesDir may give for it (None: it must refuse, with -1)
HOMES = [('mc0:OPL', ('mc0:OPL/PADS',)), ('mass0:/OPL', ('mass0:/OPL/PADS',)), ('mass0:/OPL/', ('mass0:/OPL/PADS',)),
         ('pfs0:OPL', ('pfs0:OPL/PADS',)), ('pfs0:', ('pfs0:PADS', 'pfs0:/PADS')), ('', None), ('mc?:OPL', None),
         ('hdd0:', None), ('hdd0:+OPL', None), ('hdd1:__common', None)]


def check_dir(cc, td):
    m = functions(blank(pads), 'padProfilesDir')
    if not m:
        return port('padprofiles.c: padProfilesDir not found')
    prog = DIR_PROG.replace('HOMES', ', '.join('"%s"' % h for h, _ in HOMES)).replace('@@FUNCTION@@', pads[m[0][1]:m[0][2]])
    (td / 'dir.c').write_text(prog, encoding='utf-8')
    r = subprocess.run([cc, '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(td / 'dir.c'), '-o', str(td / 'dir.exe')],
                       capture_output=True, text=True)
    if r.returncode:
        return port('padProfilesDir must build on the PC with only configGetHomePath: ' + r.stderr[-600:])
    r = subprocess.run([str(td / 'dir.exe')], capture_output=True, text=True)
    rows = r.stdout.split('\n')
    if r.returncode or len(rows) < len(HOMES) + 1:
        return port('padProfilesDir run failed: ' + r.stdout[-300:] + r.stderr[-300:])
    for (home, want), row in zip(HOMES, rows):
        got, _, path = row.partition('\t')
        if want is None and got != '-1':
            port('padProfilesDir("%s") gives %s %r, not -1 (no PADS there)' % (home, got, path))
        elif want is not None and (got != '0' or path not in want):
            port('padProfilesDir("%s") gives %s %r, not 0 and %s' % (home, got, path, ' or '.join(want)))
    if rows[len(HOMES)] != '-1':
        port('padProfilesDir into 8 bytes gives %s, not -1: a PADS path cut short' % rows[len(HOMES)])


MAP_PROG = r'''
#include <stdio.h>
#include <string.h>
#define mips_memcpy memcpy
#define mips_memset memset
#define PADPROFILE_NO_IMPORTS
#include "modules/pademu/padprofile.c"
#define B(x) (1u << PAD_B_##x)
static int show(int code, const struct ds2report *r)
{
    printf("buttons %04x; pressure Cross %d Circle %d Triangle %d Square %d L1 %d R1 %d Up %d\n", r->nButtonState, r->PressureCross,
           r->PressureCircle, r->PressureTriangle, r->PressureSquare, r->PressureL1, r->PressureR1, r->PressureUp);
    return code;
}
int main(void)
{
    unsigned char report[8] = {0x0F};
    struct ds2report r;
    pad_def_t *d = &padProfiles[0];

    /* a profiled pad, no pressure of its own: byte 0 bit 0 Cross, bit 1 Start, bit 2 Square, bit 3 L1, all four held */
    memset(d, 0, sizeof(*d));
    d->vid = 0x0079;
    d->pid = 0x0006;
    d->hat = PAD_REF_NONE;
    memset(d->axis, PAD_REF_NONE, sizeof(d->axis));
    d->button[PAD_B_CROSS] = 0 | 0 << 5;
    d->button[PAD_B_START] = 0 | 1 << 5;
    d->button[PAD_B_SQUARE] = 0 | 2 << 5;
    d->button[PAD_B_L1] = 0 | 3 << 5;
    d->present = B(CROSS) | B(START) | B(SQUARE) | B(L1);
    padProfileCount = 1;
    /* the game's map: Cross to Circle, Start to Triangle, Square to nothing, L1 to Select */
    memset(padGameMap, PAD_REMAP_SAME, sizeof(padGameMap));
    padGameMap[PAD_B_CROSS] = PAD_B_CIRCLE;
    padGameMap[PAD_B_START] = PAD_B_TRIANGLE;
    padGameMap[PAD_B_SQUARE] = 0xFE;
    padGameMap[PAD_B_L1] = PAD_B_SELECT;
    padGameMapOn = !padMapIsSame(padGameMap);
    padProfileDecode(0, report, (int)sizeof(report), &r);
    padGameMapApply(&r);
    if (r.nButtonState != (unsigned short)~(B(CIRCLE) | B(TRIANGLE) | B(SELECT))) return show(1, &r);
    if (r.PressureCircle != 0xFF || r.PressureCross) return show(2, &r); /* the pressure went with the press */
    if (r.PressureTriangle != 0xFF) return show(3, &r);                   /* Start has none: 255 while held */
    if (r.PressureSquare || r.PressureL1) return show(4, &r);             /* to nothing, or to Select: none left */
    /* a DS3's own pressure: kept where the map leaves a button (a light touch too), the higher where two meet */
    memset(&r, 0, sizeof(r));
    r.nButtonState = (unsigned short)~(B(CROSS) | B(CIRCLE) | B(R1));
    r.PressureCross = 0x30;
    r.PressureCircle = 0x90;
    r.PressureR1 = 0x40;
    r.PressureUp = 0x07;
    padGameMapApply(&r);
    if (r.nButtonState != (unsigned short)~(B(CIRCLE) | B(R1)) || r.PressureCircle != 0x90 || r.PressureCross ||
        r.PressureR1 != 0x40 || r.PressureUp != 0x07)
        return show(5, &r);
    /* Cross and Circle swapped */
    padGameMap[PAD_B_CIRCLE] = PAD_B_CROSS;
    memset(&r, 0, sizeof(r));
    r.nButtonState = (unsigned short)~B(CROSS);
    r.PressureCross = 0x30;
    padGameMapApply(&r);
    if (r.nButtonState != (unsigned short)~B(CIRCLE) || r.PressureCircle != 0x30 || r.PressureCross) return show(6, &r);
    /* no map: nothing moves */
    padGameMapOn = 0;
    memset(&r, 0, sizeof(r));
    r.nButtonState = (unsigned short)~B(CROSS);
    r.PressureCross = 0x30;
    padGameMapApply(&r);
    if (r.nButtonState != (unsigned short)~B(CROSS) || r.PressureCross != 0x30 || r.PressureCircle) return show(7, &r);
    printf("map ok\n");
    return 0;
}
'''


def check_map_pressure(cc, td):
    (td / 'map.c').write_text(MAP_PROG, encoding='utf-8')
    r = subprocess.run([cc, '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-I', str(root), '-I', str(root / 'include'),
                        str(td / 'map.c'), '-o', str(td / 'map.exe')], capture_output=True, text=True)
    if r.returncode:
        return port('modules/pademu/padprofile.c must build on the PC (PADPROFILE_NO_IMPORTS): ' + r.stderr[-800:])
    r = subprocess.run([str(td / 'map.exe')], capture_output=True, text=True)
    if r.returncode:
        port('PADEMU\'s game map, check %d: a pressure byte did not go with its press: %s' % (r.returncode, r.stdout.strip()))


REPROBE_PROG = r'''
#include <stdio.h>
#include <string.h>
#include "include/padfile.h"
typedef unsigned char u8;
typedef unsigned int u32;
#define USE_GP_REGISTER 0
#define USB_RC_OK 0
#define USB_RC_BADDRIVER 0x103
#define USB_RC_BUSY 0x104
#define DEVICE_READY 5
#define DPRINTF(...) do { } while (0)
#define dbg_printf(...) do { } while (0)
/* the layout of ps2sdk's usbd.h, and the members of usbd-ra's Device that driver.c uses */
typedef struct _UsbDriver
{
    struct _UsbDriver *next, *prev;
    char *name;
    int (*probe)(int devID);
    int (*connect)(int devID);
    int (*disconnect)(int devID);
    u32 reserved1, reserved2, reserved3, reserved4, reserved5;
    void *gp;
} sceUsbdLddOps;
typedef sceUsbdLddOps UsbDriver;
typedef struct _endpoint
{
    struct _endpoint *next;
} Endpoint;
typedef struct _device
{
    u32 id;
    struct _device *next;
    Endpoint *endpointListStart;
    sceUsbdLddOps *devDriver;
    u8 deviceStatus;
    u8 functionAddress;
    struct _device *childListStart;
    void *privDataField;
    unsigned vid, pid; /* this test's: what the device descriptor says */
} Device;
static struct
{
    Device *deviceTreeRoot;
} memPool;
static int usbdLock(void) { return 0; }
static int usbdUnlock(void) { return 0; }
static void removeEndpointFromDevice(Device *dev, Endpoint *ep) { (void)dev; (void)ep; }
static int callUsbDriverFunc(int (*func)(int devId), int devId, void *gp) /* driver.c's, without the GP switch */
{
    int res = 0;
    (void)gp;
    if (func) {
        usbdUnlock();
        res = func(devId);
        usbdLock();
    }
    return res;
}
@@USBD@@
/* the menu driver's side: its slots, its profiles, and probe and connect as ds34usb.c decides them */
#define MAX_PADS 2
static struct
{
    int devId, enabled;
    unsigned vid, pid;
} ds34pad[MAX_PADS];
pad_def_t padProfiles[PAD_DEFS_MAX];
int padProfileCount;
static Device hDev[3]; /* the root hub, then two devices */
static char hLog[256];
static void hNote(const char *s) { strncat(hLog, s, sizeof(hLog) - strlen(hLog) - 1); }
static int usb_probe(int devId)
{
    int i;
    if (hDev[devId].vid == 0x054C && hDev[devId].pid == 0x0268)
        return 1; /* a DualShock 3 */
    for (i = 0; i < padProfileCount; i++)
        if (padProfiles[i].vid == hDev[devId].vid && padProfiles[i].pid == hDev[devId].pid)
            return 1;
    return 0;
}
static int usb_connect(int devId)
{
    int pad;
    for (pad = 0; pad < MAX_PADS; pad++)
        if (ds34pad[pad].devId == -1 && ds34pad[pad].enabled)
            break;
    if (pad >= MAX_PADS)
        return 1;
    ds34pad[pad].devId = devId;
    ds34pad[pad].vid = hDev[devId].vid;
    ds34pad[pad].pid = hDev[devId].pid;
    return 0;
}
static int usb_disconnect(int devId) { (void)devId; hNote("D "); return 0; }
static void usb_release(int pad)
{
    char s[8];
    snprintf(s, sizeof(s), "R%d ", pad);
    hNote(s);
    ds34pad[pad].devId = -1;
}
static int hNone(int devId) { (void)devId; return 0; }
static UsbDriver usb_driver = {NULL, NULL, "ds34usb", usb_probe, usb_connect, usb_disconnect, 0, 0, 0, 0, 0, NULL};
static UsbDriver hHub = {NULL, NULL, "hub", hNone, NULL, NULL, 0, 0, 0, 0, 0, NULL};
static UsbDriver hMass = {NULL, NULL, "usbmass", hNone, NULL, NULL, 0, 0, 0, 0, 0, NULL};
static int UsbRegisterDriver(UsbDriver *d) { hNote("G "); return doRegisterDriver(d, NULL); }
static int UsbUnregisterDriver(UsbDriver *d) { hNote("U "); return doUnregisterDriver(d); }
@@REPROBE@@
/* Boot: the hub driver, the menu's driver with the profiles it has at its start, a storage driver after it; then the
   profiles arrive (SET_PROFILES) and usb_reprobe runs */
static void boot(unsigned vid1, unsigned pid1, unsigned vid2, unsigned pid2, int enabled, int profilesAtStart)
{
    int i;
    memset(hDev, 0, sizeof(hDev));
    hDev[1].id = 1;
    hDev[1].vid = vid1;
    hDev[1].pid = pid1;
    hDev[2].id = 2;
    hDev[2].vid = vid2;
    hDev[2].pid = pid2;
    hDev[1].deviceStatus = hDev[2].deviceStatus = DEVICE_READY;
    hDev[0].childListStart = &hDev[1];
    hDev[1].next = vid2 ? &hDev[2] : NULL;
    memPool.deviceTreeRoot = &hDev[0];
    drvListStart = drvListEnd = drvAutoLoader = NULL;
    usb_driver.next = usb_driver.prev = hHub.next = hHub.prev = hMass.next = hMass.prev = NULL;
    for (i = 0; i < MAX_PADS; i++) {
        ds34pad[i].devId = -1;
        ds34pad[i].enabled = (enabled >> i) & 1;
    }
    memset(padProfiles, 0, sizeof(padProfiles));
    padProfiles[0].vid = 0x0079;
    padProfiles[0].pid = 0x0006;
    padProfileCount = profilesAtStart;
    doRegisterDriver(&hHub, NULL);
    doRegisterDriver(&usb_driver, NULL);
    doRegisterDriver(&hMass, NULL);
    padProfileCount = 1;
    hLog[0] = '\0';
}
static int holds(unsigned vid, unsigned pid)
{
    int pad;
    for (pad = 0; pad < MAX_PADS; pad++)
        if (ds34pad[pad].devId != -1 && ds34pad[pad].vid == vid && ds34pad[pad].pid == pid)
            return 1;
    return 0;
}
int main(void)
{
    /* 1: the profiled pad plugged in before the profiles came, the menu's one port free */
    boot(0x0079, 0x0006, 0, 0, 1, 0);
    if (hDev[1].devDriver != NULL || holds(0x0079, 0x0006)) return 1; /* turned down at the driver's start */
    usb_reprobe();
    if (strcmp(hLog, "U G ") || hDev[1].devDriver != &usb_driver || !holds(0x0079, 0x0006)) { printf("1: %s\n", hLog); return 2; }
    if (drvListStart != &hHub || hHub.next != &hMass || hMass.next != &usb_driver || drvListEnd != &usb_driver) return 3;
    /* 2: the menu's one port held by a DualShock 3: nothing moves */
    boot(0x054C, 0x0268, 0x0079, 0x0006, 1, 0);
    usb_reprobe();
    if (hLog[0] || !holds(0x054C, 0x0268) || hDev[2].devDriver != NULL) { printf("2: %s\n", hLog); return 4; }
    /* 3: both ports read, a DualShock 3 in one: it is let go before the driver goes, and both are taken again */
    boot(0x054C, 0x0268, 0x0079, 0x0006, 3, 0);
    usb_reprobe();
    if (strcmp(hLog, "R0 U G ") || !holds(0x054C, 0x0268) || !holds(0x0079, 0x0006) || hDev[1].devDriver != &usb_driver ||
        hDev[2].devDriver != &usb_driver) { printf("3: %s\n", hLog); return 5; }
    /* 4: the pad taken at the start already (its profile was there): nothing moves */
    boot(0x0079, 0x0006, 0, 0, 3, 1);
    usb_reprobe();
    if (hLog[0] || !holds(0x0079, 0x0006)) { printf("4: %s\n", hLog); return 6; }
    /* 5: no profile: nothing moves */
    boot(0x0079, 0x0006, 0, 0, 1, 0);
    padProfileCount = 0;
    usb_reprobe();
    if (hLog[0] || hDev[1].devDriver != NULL) { printf("5: %s\n", hLog); return 7; }
    printf("reprobe ok\n");
    return 0;
}
'''


def check_reprobe(cc, td):
    usbd = blank(usbd_driver)
    names = ('probeDeviceTree', 'doRegisterDriver', 'disconnectDriver', 'doUnregisterDriver')
    found = {n: usbd_driver[s:e] for n, s, e in functions(usbd, '|'.join(names))}
    reprobe = functions(blank(menu), 'usb_reprobe')
    if len(found) != len(names) or not reprobe:
        return port('menu ds34usb.c: usb_reprobe, or usbd-ra driver.c\'s %s, not found' % ', '.join(n for n in names if n not in found))
    usbd_src = 'static sceUsbdLddOps *drvListStart, *drvListEnd, *drvAutoLoader;\n' + '\n'.join(found[n] for n in names)
    prog = REPROBE_PROG.replace('@@USBD@@', usbd_src).replace('@@REPROBE@@', menu[reprobe[0][1]:reprobe[0][2]])
    (td / 'reprobe.c').write_text(prog, encoding='utf-8')
    r = subprocess.run([cc, '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-I', str(root), str(td / 'reprobe.c'),
                        '-o', str(td / 'reprobe.exe')], capture_output=True, text=True)
    if r.returncode:
        return port('usb_reprobe with usbd-ra\'s driver list must build on the PC: ' + r.stderr[-800:])
    r = subprocess.run([str(td / 'reprobe.exe')], capture_output=True, text=True)
    if r.returncode:
        port('menu ds34usb.c: a profiled pad plugged in before its profile came, check %d: %s' % (r.returncode, r.stdout.strip()))
    if not re.search(r'^\s*I_sceUsbdUnregisterLdd\s*$', text('modules/ds34usb/iop/imports.lst'), re.M):
        port('modules/ds34usb/iop/imports.lst: no I_sceUsbdUnregisterLdd for usb_reprobe')
    if not re.search(r'\bif\s*\(\s*!\s*pads_learn\s*\)\s*usb_reprobe\s*\(\s*\)\s*;', body(blank(menu), 'ds34usb_set_profiles')):
        port('menu ds34usb.c: ds34usb_set_profiles does not call usb_reprobe once the setup screen is closed')


check_last_member()
check_bit19_clear()
check_undef()
check_sony(pademu_usb, 'PADEMU ds34usb.c')
check_sony(menu, 'menu ds34usb.c')
check_setup_files()
check_usb_only()
check_report_length()
check_late_signal()
check_prerequisites()

cc = shutil.which('gcc') or shutil.which('cc')
if cc is None:
    print('\n'.join(fail) or 'build129 pad: no host C compiler, programs skipped')
    sys.exit(1 if fail else 0)

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    src = root / 'src/padfile.c'
    (td / 'only.c').write_text('#include <string.h>\n#define PADFILE_DECODE_ONLY\n#include "src/padfile.c"\nint main(void) { return 0; }\n',
                               encoding='utf-8')
    r = subprocess.run([cc, '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-I', str(root), str(td / 'only.c'), '-o', str(td / 'only.exe')],
                       capture_output=True, text=True)
    if r.returncode:
        fail.append('padfile.c must build decode-only (as PADEMU and the menu driver build it): ' + r.stderr[-600:])
    if finder:
        (td / 't.c').write_text(PROG, encoding='utf-8')
        r = subprocess.run([cc, '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-I', str(root), str(td / 't.c'), str(src),
                            '-o', str(td / 't.exe')], capture_output=True, text=True)
        if r.returncode:
            fail.append('the setup screen\'s finder must build on the PC: ' + r.stderr[-800:])
        else:
            r = subprocess.run([str(td / 't.exe')], capture_output=True, text=True)
            if r.returncode:
                fail.append('pad129 check %d failed: %s' % (r.returncode, r.stdout.strip()))
    if pads:
        check_dir(cc, td)
    if prof:
        check_map_pressure(cc, td)
    if menu and usbd_driver:
        check_reprobe(cc, td)

print('\n'.join(fail) or 'build129 pad: PADEMU, ee_core, the launcher and the menu driver wired; decode-only build; the setup '
      'screen finds a button, an active-low button, a hat, a trigger and a stick (inverted too), ignores a counter; the game map '
      'applies; this port: PadEmuArgs last, bit 19 clear with no block, memcpy and memset undefined, no Sony VID takes a '
      'profile, fmRename and mode 0666, PADS beside the settings and never on raw APA, the USB build only, the real report '
      'length, a late signal dropped, padprofile.o rebuilt, the game map moves pressure with the press, a pad plugged in '
      'before its profile is taken')
sys.exit(1 if fail else 0)
