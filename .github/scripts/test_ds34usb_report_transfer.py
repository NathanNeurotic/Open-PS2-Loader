#!/usr/bin/env python3
"""Regression tests for the DS3/DS4 USB report transfer and the IOP alarm cancels.

ps2sdk's CancelAlarm() removes an alarm only when both the handler and its argument match the
SetAlarm() call, so a cancel with the wrong argument never cancels: the 200 ms timeout fires
later and signals the semaphore of whatever transfer runs next. The in-game driver also shared
one report buffer and one completion semaphore between both pads and the rumble/LED commands,
and started a new report transfer while a timed-out one was still queued on the same buffer
(belomaxorka/YAOPL 1ef5b49c, 4b1106e4, c4a82e95).
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PADEMU = ROOT / 'modules/pademu/ds34usb.c'
PADEMU_H = ROOT / 'modules/pademu/ds34usb.h'
MENU = ROOT / 'modules/ds34usb/iop/ds34usb.c'


def strip_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'//[^\n]*', '', text)


def function(text, name):
    match = re.search(r'\n[^\n;{}]*\b' + name + r'\([^;{]*\)[^;{\n]*\n\{', text)
    assert match, name
    depth, i = 0, match.end() - 1
    while True:
        depth += {'{': 1, '}': -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return text[match.start():i]


def calls(text, name):
    """The arguments of every call to name, whitespace and a leading & dropped."""
    found = []
    for match in re.finditer(r'\b' + name + r'\s*\(', text):
        depth, i, args, arg = 1, match.end(), [], ''
        while depth:
            c = text[i]
            depth += {'(': 1, ')': -1}.get(c, 0)
            if (c == ',' and depth == 1) or depth == 0:
                args.append(re.sub(r'\s+', '', arg).lstrip('&'))
                arg = ''
            else:
                arg += c
            i += 1
        found.append(args)
    return found


class AlarmCancelTests(unittest.TestCase):
    def test_every_cancel_matches_a_set_alarm_in_the_same_file(self):
        checked = 0
        for path in sorted((ROOT / 'modules').rglob('*.c')):
            if 'tests' in path.parts:
                continue
            text = strip_comments(path.read_text(errors='replace'))
            cancels = [(args[0], args[1]) for args in calls(text, 'CancelAlarm')]
            if not cancels:
                continue
            sets = {(args[1], args[2]) for name in ('SetAlarm', 'iSetAlarm') for args in calls(text, name)}
            for cancel in cancels:
                checked += 1
                self.assertIn(cancel, sets,
                              f'{path.relative_to(ROOT)}: CancelAlarm{cancel} matches no SetAlarm, so it never cancels')
        self.assertGreater(checked, 10)

    def test_ds34usb_transfer_waits_cancel_their_own_alarm(self):
        for path in (PADEMU, MENU):
            body = function(strip_comments(path.read_text()), 'TransferWait')
            self.assertIn('SetAlarm(&cmd_timeout, timeout, (void *)sema)', body, path)
            self.assertIn('CancelAlarm(timeout, (void *)sema)', body, path)


class ReportTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = strip_comments(PADEMU.read_text())
        cls.header = strip_comments(PADEMU_H.read_text())

    def test_each_pad_has_its_own_report_buffer_and_completion(self):
        self.assertRegex(self.text, r'static u8 data_buf\[MAX_PADS\]\[MAX_BUFFER_SIZE \+ 32\]')
        for field in ('int data_sema;', 'int data_result;', 'u8 data_pending;'):
            self.assertIn(field, self.header)
        self.assertNotIn('usb_resulCode', self.text)
        init = function(self.text, 'ds34usb_init')
        self.assertIn('ds34pad[pad].data_sema = CreateMutex(IOP_MUTEX_LOCKED);', init)
        self.assertIn('ds34pad[pad].data_sema < 0', init)

    def test_completion_is_recorded_per_pad(self):
        cb = function(self.text, 'usb_data_cb')
        self.assertIn('ds34pad[pad].data_result = resultCode;', cb)
        self.assertIn('ds34pad[pad].data_pending = 0;', cb)
        self.assertIn('SignalSema(ds34pad[pad].data_sema);', cb)
        self.assertNotIn('ds34pad[pad].sema', cb)

    def test_no_new_transfer_while_one_is_queued(self):
        body = function(self.text, 'ds34usb_get_data')
        self.assertNotIn('usb_buf', body)
        start = body.index('UsbInterruptTransfer(ds34pad[port].interruptEndp, data_buf[port]')
        guard = body.rindex('if (!ds34pad[port].data_pending)', 0, start)
        self.assertLess(body.index('ds34pad[port].data_pending = 1;', guard), start)
        self.assertIn('TransferWait(ds34pad[port].data_sema);', body)
        # A report is read only from a transfer that completed and succeeded.
        for read in re.finditer(r'readReport\(data_buf\[port\], port\);', body):
            condition = body[body.rindex('if (', 0, read.start()):read.start()]
            self.assertIn('data_result', condition)

    def test_ds3_enable_report_does_not_share_the_command_buffer(self):
        body = function(self.text, 'DS3USB_init')
        self.assertNotIn('usb_buf', body)
        self.assertIn('ds3_enable_report', body)
        self.assertRegex(self.text, r'static u8 ds3_enable_report\[\][^=]*= \{0x42, 0x0c, 0x00, 0x00\};')

    def test_release_forgets_the_queued_transfer(self):
        body = function(self.text, 'usb_release')
        self.assertIn('ds34pad[pad].data_pending = 0;', body)
        self.assertIn('PollSema(ds34pad[pad].data_sema);', body)


if __name__ == '__main__':
    unittest.main()
