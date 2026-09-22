"""Background music must never hold audsrv across an open-ended wait.

audsrv_wait_audio() parks audsrv's only IOP RPC thread -- and the EE library's call mutex -- until
the IOP play thread frees ring space, which it does only while SPU2 keeps completing block
transfers. The BGM playback thread lives in that wait, so whenever the stream stalled, every other
audsrv call waited with it for good: the menu thread's per-press sound effect froze the GUI with the
rumble motor left running, and bgmMute() hung the way into a launch. The playback thread polls
audsrv_available() instead, sleeping between polls; this pins that shape.
"""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[2]
failures = []

for path in sorted((root / 'src').rglob('*.c')):
    source = path.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n')
    for number, line in enumerate(source.split('\n'), 1):
        code = line.split('//')[0]
        if re.search(r'\baudsrv_wait_audio\s*\(', code):
            failures.append('%s:%d calls audsrv_wait_audio(); poll audsrv_available() instead'
                            % (path.relative_to(root).as_posix(), number))

sound = (root / 'src/sound.c').read_text(encoding='utf-8').replace('\r\n', '\n')

wait = re.search(r'^static int bgmWaitForRoom\(void\)\n\{.*?^\}', sound, re.M | re.S)
if wait is None:
    failures.append('src/sound.c: bgmWaitForRoom() not found')
elif not all(token in wait.group(0) for token in ('audsrv_available()', 'DelayThread(', 'terminateFlag')):
    failures.append('bgmWaitForRoom: must poll audsrv_available(), sleep between polls and honour terminateFlag')

thread = re.search(r'^static void bgmThread\(void \*arg\)\n\{.*?^\}', sound, re.M | re.S)
if thread is None or 'bgmWaitForRoom()' not in thread.group(0):
    failures.append('bgmThread: must wait for audsrv room through bgmWaitForRoom()')

if failures:
    print('Audio thread checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('audio threads: no open-ended audsrv wait')
