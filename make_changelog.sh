#!/bin/bash
set -euo pipefail

git fetch origin master
git reset --hard origin/master
git clean -fdx

python3 - <<'PY'
from pathlib import Path

opl = Path('src/opl.c')
text = opl.read_text()
repls = [
('''    // Bounded wait so BDM-on-HDD can be detected without long black-screen stalls.\n    if (hddLoadModules() >= 0 && bdmHDDIsPresent(500)) {\n''', '''    // Legacy config discovery is speculative: expected absence must not post the user-facing 401.\n    // Keep the scan for compatibility, but load the shared ATA stack silently here.\n    if (hddLoadModulesSilent() >= 0 && bdmHDDIsPresent(500)) {\n'''),
('''    if (hddLoadModules() < 0 || !hddLoadSupportModules())\n        return 0;\n''', '''    // Legacy config discovery is speculative: preserve HDD config lookup without reporting expected\n    // hardware absence as a startup error on HDD-less consoles.\n    if (hddLoadModulesSilent() < 0 || !hddLoadSupportModules())\n        return 0;\n'''),
('''    char pwd[8];\n    char redirectPath[64];\n    int value;\n    DIR *dir;\n\n    getcwd(pwd, sizeof(pwd));\n''', '''    char pwd[64] = "";\n    char redirectPath[64];\n    int value;\n    DIR *dir;\n\n    if (getcwd(pwd, sizeof(pwd)) == NULL)\n        pwd[0] = 0;\n''')]
for old, new in repls:
    if old not in text:
        raise SystemExit('opl.c anchor missing')
    text = text.replace(old, new, 1)
opl.write_text(text)

hdd = Path('src/hddsupport.c')
text = hdd.read_text()
text = text.replace('int hddLoadModules(void)\n{', 'static int hddLoadModulesInternal(int reportError)\n{', 1)
old = '''        LOG("HDD: No HardDisk Drive detected.\\n");\n        setErrorMessageWithCode(_STR_HDD_NOT_CONNECTED_ERROR, ERROR_HDD_IF_NOT_DETECTED);\n        return HDD_LOADMODULES_STATUS_ERROR;\n'''
new = '''        LOG("HDD: No HardDisk Drive detected.\\n");\n        if (reportError)\n            setErrorMessageWithCode(_STR_HDD_NOT_CONNECTED_ERROR, ERROR_HDD_IF_NOT_DETECTED);\n        return HDD_LOADMODULES_STATUS_ERROR;\n'''
if old not in text:
    raise SystemExit('hdd error anchor missing')
text = text.replace(old, new, 1)
old = '''    LOG("HDDSUPPORT LoadModules done\\n");\n    return HDD_LOADMODULES_STATUS_NOERROR;\n}\n\nint hddLoadSupportModules(void)\n'''
new = '''    LOG("HDDSUPPORT LoadModules done\\n");\n    return HDD_LOADMODULES_STATUS_NOERROR;\n}\n\nint hddLoadModules(void)\n{\n    return hddLoadModulesInternal(1);\n}\n\nint hddLoadModulesSilent(void)\n{\n    return hddLoadModulesInternal(0);\n}\n\nint hddLoadSupportModules(void)\n'''
if old not in text:
    raise SystemExit('hdd wrapper anchor missing')
hdd.write_text(text.replace(old, new, 1))

hdr = Path('include/hddsupport.h')
text = hdr.read_text()
old = 'int hddLoadModules(void);\nint hddLoadSupportModules(void);\n'
new = 'int hddLoadModules(void);\n// Speculative legacy-config probe: identical module load, but expected HDD absence remains log-only.\nint hddLoadModulesSilent(void);\nint hddLoadSupportModules(void);\n'
if old not in text:
    raise SystemExit('header anchor missing')
hdr.write_text(text.replace(old, new, 1))
PY

apk add --no-cache clang18-extra-tools
/usr/lib/llvm18/bin/clang-format --lines=1310:1380 -i src/opl.c
/usr/lib/llvm18/bin/clang-format --lines=210:310 -i src/hddsupport.c
/usr/lib/llvm18/bin/clang-format --lines=88:104 -i include/hddsupport.h

git add src/opl.c src/hddsupport.c include/hddsupport.h
export GIT_AUTHOR_NAME="ChatGPT"
export GIT_AUTHOR_EMAIL="noreply@openai.com"
export GIT_COMMITTER_NAME="ChatGPT"
export GIT_COMMITTER_EMAIL="noreply@openai.com"
tree=$(git write-tree)
commit=$(printf '%s\n' "Silence speculative HDD config probes" | git commit-tree "$tree" -p origin/master)
git push --force origin "$commit":refs/heads/agent/unified-mmce-vcd-hdd-bdma-fixes
