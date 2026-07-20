#!/bin/bash
set -euo pipefail

git fetch origin 9980952721677f296db651269fc352c9a9f7fb3c
git reset --hard FETCH_HEAD
git clean -fdx

python3 - <<'PY'
from pathlib import Path
path = Path('src/opl.c')
text = path.read_text()
replacements = [
('''    gBDMStartMode = START_MODE_MANUAL;
    gHDDStartMode = START_MODE_DISABLED; // RiptOPL: APA/PFS HDD OFF by default (was Manual); user opts in
    gETHStartMode = START_MODE_DISABLED; // RiptOPL: network/SMB OFF by default (was Manual); user opts in
    gAPPStartMode = START_MODE_MANUAL;
    gMMCEStartMode = START_MODE_MANUAL;
    gFAVStartMode = START_MODE_MANUAL;
''', '''    // Device Settings defaults: use Manual wherever the row supports it. This exposes each page
    // without auto-starting its hardware stack; binary transport toggles below default Off.
    gBDMStartMode = START_MODE_MANUAL;
    gHDDStartMode = START_MODE_MANUAL;
    gETHStartMode = START_MODE_MANUAL;
    gAPPStartMode = START_MODE_MANUAL;
    gMMCEStartMode = START_MODE_MANUAL;
    gFAVStartMode = START_MODE_MANUAL;
'''),
('''    gEnableUSB = 1;
    gEnableILK = 0;
    gEnableMX4SIO = 0;
    gEnableBdmHDD = 0;                 // exFAT BDM HDD OFF by default (the other "HDD type"; APA/PFS is gHDDStartMode above)
''', '''    // These Device Settings entries are binary (no Manual state), so default all of them Off.
    gEnableUSB = 0;
    gEnableILK = 0;
    gEnableMX4SIO = 0;
    gEnableBdmHDD = 0;
'''),
('''    // Unified network selector defaults to OFF (was UDPFS, Nathan 2026-07-16). The reason is the NIC
    // latch: every network stack loads its IOP chain ONCE per boot and never unloads (re-binding the
    // UDPRDMA socket bricks UDPFS; smap registers a single SMAP_driver), so whichever protocol is
    // active FIRST owns the adapter until a restart -- the settings page even tells you so
    // (NETBOOT_RESTART). With UDPFS pre-selected, a user who wanted UDPBD or SMB had to change the
    // setting and REBOOT before their choice could load. Defaulting to Off means nothing claims the
    // NIC at boot, so the first protocol the user picks in Device Settings comes up live -- the apply
    // path re-derives the gEnableUDPBD/gNetBootProtocol shadows and forces a device refresh already.
    // Existing installs are unaffected: a saved net protocol in settings_riptopl.cfg overrides this.
    gNetworkProtocol = NET_PROTO_OFF;
    gNetStartMode = START_MODE_DISABLED; // Off in the 3-row Network setting; migration reconciles old configs
''', '''    // Network has a Manual start state, so fresh installs expose the SMB page without claiming the NIC
    // during boot. Protocol and start mode must be coherent: NET_PROTO_OFF would force the Manual row
    // back to Off during config reconciliation. Existing saved settings still override these defaults.
    gNetworkProtocol = NET_PROTO_SMB;
    gNetStartMode = START_MODE_MANUAL;
'''),
('''            // Since a NETWORK protocol became the shipped DEFAULT (UDPFS, 2026-07-13), the legacy branch
            // must key off the FILE's enable_udpbd, not the defaulted global -- a legacy config must only
            // ever derive from what IT expressed, never inherit a defaulted enable flag.
''', '''            // Fresh installs now default to SMB/Manual. The legacy branch must still key off the FILE's
            // enable_udpbd value, not the defaulted global: an older config must derive only from what it
            // expressed and must never inherit a newly shipped transport choice accidentally.
'''),
('''                // else: the file never expressed ANY network choice -> the shipped default stands (UDPFS)
''', '''                // else: the file never expressed ANY network choice -> the shipped SMB/Manual default stands
''')]
for old, new in replacements:
    if old not in text:
        raise SystemExit('Device-default anchor missing')
    text = text.replace(old, new, 1)
path.write_text(text)
PY

apk add --no-cache clang18-extra-tools
/usr/lib/llvm18/bin/clang-format -i src/opl.c

git add src/opl.c
export GIT_AUTHOR_NAME="ChatGPT"
export GIT_AUTHOR_EMAIL="noreply@openai.com"
export GIT_COMMITTER_NAME="ChatGPT"
export GIT_COMMITTER_EMAIL="noreply@openai.com"
parent=$(git rev-parse HEAD)
tree=$(git write-tree)
commit=$(printf '%s\n' "Default device entries to Manual or Off" | git commit-tree "$tree" -p "$parent")
git push --force origin "$commit":refs/heads/agent/unified-defaults-stage
