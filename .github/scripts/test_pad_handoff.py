#!/usr/bin/env python3
"""Regression tests for the DualShock launch handoff (belomaxorka/YAOPL c56a91b6).

The menu leaves a DualShock in DualShock mode, locked, with pressure on, and the pad is not powered off
across the IOP reset into a game. Before the port is closed it is put back as it powers up: pressure
off, digital, unlocked. Every wait for padman is bounded. waitPadIdle() itself is compiled on the host
against a scripted pad, so its timing is checked, not just its text.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CPP = ROOT / 'src/core/pad.cpp'
PAD = CPP if CPP.exists() else ROOT / 'src/pad.c'
UNLOAD = 'PadManager::unloadOne' if CPP.exists() else 'unloadPad'


def strip_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'//[^\n]*', '', text)


def function(text, name):
    match = re.search(r'\n[^\n;{}]*\b' + re.escape(name) + r'\([^;{]*\)[^;{\n]*\n\{', text)
    assert match, name
    depth, i = 0, match.end() - 1
    while True:
        depth += {'{': 1, '}': -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return text[match.start():i]


def constant(text, name):
    match = re.search(r'\b' + name + r'\b\s*=?\s*\(?\s*(\d+)\s*(?:\*\s*(\d+))?', text)
    assert match, name
    return int(match.group(1)) * int(match.group(2) or 1)


HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#define PAD_STATE_DISCONN 0x00
#define PAD_STATE_FINDCTP1 0x02
#define PAD_STATE_STABLE 0x06
#define PAD_RSTAT_COMPLETE 0x00
#define PAD_RSTAT_BUSY 0x02
#define LOG(...) (timeouts++)
#define PAD_HANDOFF_SETTLE_US %(settle)d
#define PAD_HANDOFF_MAX_US %(max)d
#define PAD_HANDOFF_POLL_US %(poll)d
struct pad_data_t { int port, slot; };
static int now, timeouts, stableAt, idleAt, disconnAt = -1;
static int padGetState(int port, int slot) { return disconnAt >= 0 && now >= disconnAt ? PAD_STATE_DISCONN : now >= stableAt ? PAD_STATE_STABLE : PAD_STATE_FINDCTP1; }
static unsigned char padGetReqState(int port, int slot) { return now >= idleAt ? PAD_RSTAT_COMPLETE : PAD_RSTAT_BUSY; }
static void DelayThread(int us) { now += us; }
%(function)s
static int run(int settle, int stable, int idle, int disconn)
{
    struct pad_data_t pad = {0, 0};
    now = 0, timeouts = 0, stableAt = stable, idleAt = idle, disconnAt = disconn;
    return waitPadIdle(&pad, settle);
}
int main(void)
{
    assert(run(0, 0, 0, -1) == PAD_STATE_STABLE && now == 0);                        /* idle pad: no wait */
    assert(run(0, 0, 0, 0) == PAD_STATE_DISCONN && now == 0);                        /* empty port: no wait */
    assert(run(PAD_HANDOFF_SETTLE_US, 0, 0, -1) == PAD_STATE_STABLE && now == PAD_HANDOFF_SETTLE_US);
    assert(run(PAD_HANDOFF_SETTLE_US, 0, 200000, -1) == PAD_STATE_STABLE && now == 200000 && !timeouts);
    assert(run(0, 300000, 0, -1) == PAD_STATE_STABLE && now == 300000);              /* waits out FINDCTP */
    assert(run(0, 0, 1 << 30, -1) == PAD_STATE_STABLE && now == PAD_HANDOFF_MAX_US && timeouts == 1);
    assert(run(0, 1 << 30, 0, -1) == PAD_STATE_FINDCTP1 && now == PAD_HANDOFF_MAX_US && timeouts == 1);
    assert(run(PAD_HANDOFF_SETTLE_US, 0, 1 << 30, 100000) == PAD_STATE_DISCONN && now == 100000); /* unplugged */
    puts("ok");
    return 0;
}
'''


class HandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PAD.read_text()
        cls.text = strip_comments(cls.raw)

    def test_unload_puts_a_dualshock_back_in_its_power_up_mode(self):
        body = function(self.text, UNLOAD)
        steps = [
            'if (waitPadIdle(pad, 0) == PAD_STATE_STABLE && padInfoMode(pad->port, pad->slot, PAD_MODECUREXID, 0) != 0)',
            'padExitPressMode(pad->port, pad->slot);',
            'waitPadIdle(pad, PAD_HANDOFF_SETTLE_US);',
            'padSetMainMode(pad->port, pad->slot, PAD_MMODE_DIGITAL, PAD_MMODE_UNLOCK);',
            'waitPadIdle(pad, PAD_HANDOFF_SETTLE_US);',
            'padPortClose(pad->port, pad->slot);',
        ]
        at = 0
        for step in steps:
            at = body.index(step, at) + len(step)
        self.assertEqual(body.count('padPortClose'), 1)

    def test_rumble_flush_and_keep_iop_handoff_are_kept(self):
        unload = function(self.text, 'PadManager::unloadEx' if CPP.exists() else 'unloadPadsEx')
        flush = 'rumbleFlush();' if CPP.exists() else 'padRumbleFlush();'
        self.assertLess(unload.index(flush), unload.index('unloadOne(' if CPP.exists() else 'unloadPad('))
        self.assertIn('if (!keepIopRpc)\n        padEnd();', unload)

    def test_handoff_limits(self):
        self.assertEqual(constant(self.text, 'PAD_HANDOFF_SETTLE_US'), 50 * 1000)
        self.assertEqual(constant(self.text, 'PAD_HANDOFF_MAX_US'), 1000 * 1000)

    @unittest.skipUnless(shutil.which('cc'), 'no host C compiler')
    def test_wait_pad_idle_timing(self):
        source = HARNESS % {
            'settle': constant(self.text, 'PAD_HANDOFF_SETTLE_US'),
            'max': constant(self.text, 'PAD_HANDOFF_MAX_US'),
            'poll': constant(self.text, 'PAD_HANDOFF_POLL_US'),
            'function': function(self.text, 'waitPadIdle'),
        }
        with tempfile.TemporaryDirectory() as tmp:
            src, exe = Path(tmp) / 'wait.c', Path(tmp) / 'wait'
            src.write_text(source)
            subprocess.run(['cc', '-std=c99', '-Wall', '-Werror', '-o', str(exe), str(src)], check=True)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'ok')


if __name__ == '__main__':
    unittest.main()
