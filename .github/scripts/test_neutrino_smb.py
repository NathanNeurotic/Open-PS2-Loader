"""Neutrino over SMB (-bsd=smb, ps2max32/neutrino PR #236 by Ronnie Sahlberg).

Runs the actual sysNeutrinoSmbPreflight against a fake filesystem: it must refuse a Neutrino without the
SMB modules or bsd-smb.toml, write this game's network and login into every module arg of the stock file
(TOML-escaped), leave comments and other strings alone, refuse a file missing an arg that matters, and
not rewrite a file that already holds the values. Then checks the SMB launch leg's wiring.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "src/system.c").read_text(encoding="utf-8")
header = (ROOT / "include/system.h").read_text(encoding="utf-8")
failures = []


def function(signature, text=source):
    start = text.index(signature)
    return text[start:text.index("\n}", start) + 2]


def block(start_marker, end_marker, text):
    start = text.index(start_marker)
    return text[start:text.index(end_marker, start) + len(end_marker)]


functions = "\n".join([
    function("static const char *sysLastPathSeparator("),
    block("#define NEUTRINO_SMB_MOD_MINISTACK", "} neutrino_smb_key_t;", source),
    function("static int sysTomlEscape("),
    function("static int sysTomlRewriteSmbArgs("),
    function("int sysNeutrinoSmbPreflight("),
])
smb_header = block("#define NEUTRINO_SMB_USER_MAX", "} neutrino_smb_args_t;", header)

STOCK = r'''# Name of loaded config, to show to user
name = "SMB driver"

# Drivers this driver depends on (config file must exist)
depends = ["i_dev9_hidden"]

# Modules to load
[[module]]
file = "iomanX.irx"
env = ["LE"]
[[module]]
file = "fileXio.irx"
env = ["LE"]
[[module]]
file = "smap.irx"
env = ["LE", "EE"]
[[module]]
file = "ministack.irx"
args = ["ip=192.168.1.10"]
env = ["LE", "EE"]
[[module]]
file = "smb_ioman.irx"
args = ["ip=192.168.1.10", "mask=255.255.255.0", "gw=192.168.1.1", "srv=192.168.1.2", "user=guest", "pass=", "share=PS2SMB"]
env = ["LE"]
[[module]]
file = "smb_fhi.irx"
args = ["ip=192.168.1.10", "mask=255.255.255.0", "gw=192.168.1.1", "srv=192.168.1.2", "user=guest", "pass=", "share=PS2SMB"]
env = ["EE"]
'''

program = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdarg>
#include <map>
#include <string>
#define O_RDONLY 0x0001
#define O_WRONLY 0x0002
#define O_CREAT 0x0200
#define O_TRUNC 0x0400
#define LOG(...) ((void)0)
@HEADER@
static std::map<std::string, std::string> files;
static std::string current;
static int pos, writes, live;

static int fake_open(const char *path, int flags, ...) {
    assert(!live);
    if (!(flags & O_CREAT) && !files.count(path)) return -1;
    if (flags & O_TRUNC) files[path].clear();
    current = path; pos = 0; live = 1;
    if (flags & O_WRONLY) writes++;
    return 3;
}
static int fake_read(int fd, void *buffer, int size) {
    assert(fd == 3 && live);
    const std::string &b = files[current];
    int left = (int)b.size() - pos, count = left < size ? left : size;
    memcpy(buffer, b.data() + pos, count); pos += count; return count;
}
static int fake_write(int fd, const void *buffer, int size) {
    assert(fd == 3 && live);
    files[current].append((const char *)buffer, size); pos += size; return size;
}
static int fake_close(int fd) { assert(fd == 3 && live); live = 0; return 0; }
#define open fake_open
#define read fake_read
#define write fake_write
#define close fake_close
@FUNCTIONS@

static const char *ELF = "mass0:/neutrino/neutrino.elf";
static const char *TOML = "mass0:/neutrino/config/bsd-smb.toml";
static int fails;
static void check(bool ok, const char *what) { if (!ok) { printf("FAIL %s\n", what); fails++; } }

static neutrino_smb_args_t args(const char *user, const char *pass, const char *share) {
    neutrino_smb_args_t a = {{10, 0, 0, 7}, {255, 255, 0, 0}, {10, 0, 0, 1}, {10, 0, 0, 2}, "", "", ""};
    strcpy(a.user, user); strcpy(a.pass, pass); strcpy(a.share, share);
    return a;
}
static void install(const char *toml, bool modules) {
    files.clear();
    if (toml) files[TOML] = toml;
    if (modules) { files["mass0:/neutrino/modules/smb_ioman.irx"] = "x"; files["mass0:/neutrino/modules/smb_fhi.irx"] = "x"; }
}
static int count(const std::string &s, const char *needle) {
    int n = 0; for (size_t p = s.find(needle); p != std::string::npos; p = s.find(needle, p + 1)) n++; return n;
}

int main() {
    neutrino_smb_args_t a = args("ripto", "pa\"ss\\word", "GAMES");

    install(nullptr, true);
    check(sysNeutrinoSmbPreflight(ELF, &a) == -1, "no bsd-smb.toml: no SMB support");
    install(R"(@STOCK@)", false);
    check(sysNeutrinoSmbPreflight(ELF, &a) == -1, "no smb modules: no SMB support (a Neutrino from before #236)");
    check(files[TOML] == R"(@STOCK@)", "a refused launch leaves bsd-smb.toml as it was");

    install(R"(@STOCK@)", true);
    check(sysNeutrinoSmbPreflight(ELF, &a) == 0, "stock file takes this game's values");
    const std::string &t = files[TOML];
    check(count(t, "\"ip=10.0.0.7\"") == 3, "ip= in ministack, smb_ioman and smb_fhi");
    check(count(t, "\"mask=255.255.0.0\"") == 2 && count(t, "\"gw=10.0.0.1\"") == 2 && count(t, "\"srv=10.0.0.2\"") == 2, "mask, gw, srv");
    check(count(t, "\"user=ripto\"") == 2 && count(t, "\"share=GAMES\"") == 2, "user and share");
    check(count(t, "\"pass=pa\\\"ss\\\\word\"") == 2, "pass is TOML-escaped");
    check(t.find("192.168.1.") == std::string::npos && t.find("guest") == std::string::npos, "no stock value left");
    check(t.find("name = \"SMB driver\"") != std::string::npos && t.find("depends = [\"i_dev9_hidden\"]") != std::string::npos, "the rest untouched");
    writes = 0;
    check(sysNeutrinoSmbPreflight(ELF, &a) == 0 && writes == 0, "already in sync: not rewritten");
    neutrino_smb_args_t b = args("guest", "", "PS2SMB");
    check(sysNeutrinoSmbPreflight(ELF, &b) == 0 && files[TOML].find("\"pass=\"") != std::string::npos, "an empty password is written as empty");

    // A key inside a comment or inside another string is not an arg.
    std::string commented = std::string("# set \"ip=1.2.3.4\" here\nnote = \"say ip=1.2.3.4\"\n") + R"(@STOCK@)";
    install(commented.c_str(), true);
    check(sysNeutrinoSmbPreflight(ELF, &a) == 0, "commented file takes the values");
    check(files[TOML].find("# set \"ip=1.2.3.4\" here") != std::string::npos && files[TOML].find("\"say ip=1.2.3.4\"") != std::string::npos, "comment and other strings untouched");

    // A file without the args that matter is not written.
    std::string nopass = R"(@STOCK@)";
    for (size_t p; (p = nopass.find(", \"pass=\"")) != std::string::npos;) nopass.erase(p, 9);
    install(nopass.c_str(), true);
    check(sysNeutrinoSmbPreflight(ELF, &a) == -2, "no pass= args: refused");
    check(files[TOML] == nopass, "refused file untouched");
    // Each module must carry its own: a key moved into another module does not count, and is not written.
    std::string moved = R"(@STOCK@)";
    {
        size_t fhi = moved.find("file = \"smb_fhi.irx\"");
        size_t user = moved.find(", \"user=guest\"", fhi);
        moved.erase(user, 14);
        moved += "[[module]]\nfile = \"other.irx\"\nargs = [\"user=guest\"]\n";
    }
    install(moved.c_str(), true);
    check(sysNeutrinoSmbPreflight(ELF, &a) == -2, "user= only in another module, not smb_fhi: refused");
    check(files[TOML] == moved, "refused file untouched");
    std::string extra = std::string(R"(@STOCK@)") + "[[module]]\nfile = \"other.irx\"\nargs = [\"ip=1.2.3.4\", \"user=keep\"]\n";
    install(extra.c_str(), true);
    check(sysNeutrinoSmbPreflight(ELF, &a) == 0, "an extra module does not stop the hand-over");
    check(files[TOML].find("[\"ip=1.2.3.4\", \"user=keep\"]") != std::string::npos, "another module's args untouched");
    check(count(files[TOML], "\"ip=10.0.0.7\"") == 3, "ip= written in the three modules it belongs to");
    install("args = [\"ip=1\n", true);
    check(sysNeutrinoSmbPreflight(ELF, &a) == -2, "unterminated string: refused");

    neutrino_smb_args_t c = args("ripto", "tab\there", "GAMES");
    install(R"(@STOCK@)", true);
    check(sysNeutrinoSmbPreflight(ELF, &c) == -2, "a control character in the login: refused");
    check(sysNeutrinoSmbPreflight("neutrino.elf", &a) == -1, "flat path: no folder to look in");
    return fails ? 1 : 0;
}
'''

program = (program.replace("@HEADER@", smb_header).replace("@FUNCTIONS@", functions)
           .replace("@STOCK@", STOCK))
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "smb.cpp"
    exe = Path(tmp) / "smb"
    src.write_text(program, encoding="utf-8")
    build = subprocess.run(["g++", "-std=c++17", "-Wall", "-Werror", "-Wno-unused-function", str(src), "-o", str(exe)],
                           capture_output=True, text=True)
    if build.returncode:
        failures.append("harness does not build:\n" + build.stderr[-3000:])
    else:
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        if run.returncode:
            failures.append("preflight scenarios:\n" + run.stdout)

# Wiring of the SMB launch leg.
eth = (ROOT / "src/ethsupport.c").read_text(encoding="utf-8")
leg = function("static int ethTryNeutrino(", eth)
launch = function("static void ethLaunchGame(", eth)
if "if (ethTryNeutrino(itemList, game, configSet))\n        return;" not in launch:
    failures.append("ethLaunchGame must try the Neutrino leg before the OPL core")
if launch.index("ethTryNeutrino(") > launch.index("sbPrepare("):
    failures.append("the Neutrino leg must run before the OPL core prepares smb_cdvdman")
if "coreLoader == 1" not in function("static int ethSmbNeutrinoRequested(", eth):
    failures.append("only the game's own Neutrino key takes SMB to Neutrino; Default stays on the OPL core")
order = ["sbResolveNeutrinoPath(NULL)", "NEUTRINO_SMB_PORT", "sbBuildVmcNeutrinoArgs(", "sysNeutrinoSmbPreflight(",
         'sysNeutrinoPreflight("smb"', "sbPrepare(", "sbUnprepare(", "deinitEx(", 'sysLaunchNeutrino("smb"']
positions = [leg.find(m) for m in order]
if -1 in positions or positions != sorted(positions):
    failures.append("ethTryNeutrino: every fallback check comes before sbPrepare, and the hand-off last (%r)" % positions)
# Every fallback before sbPrepare returns 0 (the OPL core runs the game); nothing after it does.
before, after = leg[:leg.index("sbPrepare(")], leg[leg.index("sbPrepare("):]
if "return 1;" in before.split("ethSmbNeutrinoRequested")[1] or "return 0;" in after:
    failures.append("ethTryNeutrino: fallbacks return 0 before sbPrepare, back-outs return 1 after it")
if not re.search(r'snprintf\(partname, sizeof\(partname\), "smb:%s", sharePath\);', leg):
    failures.append('ethTryNeutrino: -dvd is "smb:<path on the share>"')

gui = (ROOT / "src/guigame.c").read_text(encoding="utf-8")
if re.search(r"coreNeverNeutrino = [^;]*ETH_MODE", gui):
    failures.append("guigame: the SMB Loader Core row must not be locked to the OPL core any more")
if "coreDefaultOpl = support != NULL && sourceMode == ETH_MODE;" not in gui:
    failures.append("guigame: SMB's Default row means the OPL core, for a Favourite of an SMB game too")
if not re.search(r"static int guiGameDialogCoreIsNeutrino\(int sourceMode,", gui) or "if (sourceMode == ETH_MODE)\n        return coreChoice == 1;" not in gui:
    failures.append("guigame: the title defaults follow the owning source's core (a Favourite of an SMB game)")

if failures:
    print("Neutrino SMB checks FAILED:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("neutrino smb: bsd-smb.toml preflight (support probe, rewrite, escaping, refusals) and launch-leg wiring OK")
