"""UDPFS/UDP network-chain hardening (follow-ups to PR #921).

* DEV9: sysInitDev9() reports whether DEV9 loaded, and the three UDP NIC chains (UDPFS Files, and the
  UDPBD/UDPFS-IMG block chain on its on-demand and boot paths) never load SMAP without it.
* Build: the top-level Makefile always enters the UDPFS sub-makes, and each module rebuilds its
  objects when a header it can include changes, so incremental builds never embed a stale IRX.
* IP conflict: the ministack export, the udpfs_ioman devctl and the loader all use one query value,
  the scan only queues the notice, and the menu frame hook shows it on the GUI thread.
* RA release workflow previews run only for RA packaging changes.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def body(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}\n", start) + 3]


failures = []


def check(what, ok):
    if not ok:
        failures.append(what)


# --- DEV9 ---
system = read("src/system.c")
check("sysInitDev9 returns whether DEV9 loaded", "int sysInitDev9(void)" in system and
      "return dev9Loaded;" in body(system, "int sysInitDev9(void)"))
check("system.h declares the int result", "int sysInitDev9(void);" in read("include/system.h"))

udpfs = read("src/udpfssupport.c")
loader = body(udpfs, "static void udpfsLoadModules(void)")
check("UDPFS Files refuses without DEV9 before loading SMAP",
      loader.index("if (!sysInitDev9())") < loader.index("udpfs_smap_irx"))
check("UDPFS Files releases the DEV9 reference it took", "sysShutdownDev9();\n        return;" in loader)

bdm = read("src/bdmsupport.c")
for signature in ("int bdmEnsureNetworkSourceModules(int protocol, u32 timeoutMs)", "if (gEnableUDPBD && !udpbdNicClaimed"):
    start = bdm.index(signature)
    chain = bdm[start:bdm.index("udpbdNicClaimed)", bdm.index("smap_udpbd_irx", start))]
    check(f"block chain checks DEV9 first ({signature[:40]})",
          "int dev9Ready = sysInitDev9();" in chain and
          chain.index("if (!dev9Ready)") < chain.index("udpfs_smap_irx") < chain.index("smap_udpbd_irx"))

# --- Build dependencies ---
makefile = read("Makefile")
check("udpfs-submake is phony", re.search(r"^\.PHONY: udpfs-submake$", makefile, re.M) is not None)
for module in ("udpfs_smap", "udpfs_ministack", "udpfs_bd", "udpfs_ioman"):
    check(f"{module}.irx always enters its sub-make",
          f"modules/network/{module}/{module}.irx: udpfs-submake\n\t$(MAKE) -C modules/network/{module}\n" in makefile)
    module_make = read(f"modules/network/{module}/Makefile")
    check(f"{module} objects depend on headers",
          "$(addprefix $(IOP_OBJS_DIR),$(IOP_OBJS)): $(UDPFS_OBJ_DEPS)" in module_make and
          module_make.index("all:: $(IOP_BIN)") < module_make.index("UDPFS_OBJ_DEPS :="))

# --- IP conflict notice ---
value = "0x55460001"
ioman = read("modules/network/udpfs_ioman/src/udpfs_ioman.c")
check("udpfs_ioman answers the conflict devctl", f"#define UDPFS_DEVCTL_IP_CONFLICT {value}" in ioman and
      "arp_ip_conflict(" in body(ioman, "static int udpfs_devctl("))
check("loader uses the same devctl value", f"#define UDPFS_DEVCTL_IP_CONFLICT {value}" in udpfs)
check("ministack exports arp_ip_conflict in slot 7",
      "DECLARE_EXPORT(arp_ip_conflict)" in read("modules/network/udpfs_ministack/src/exports.tab") and
      "DECLARE_IMPORT(7, arp_ip_conflict)" in read("modules/network/udpfs_ministack/include/mstack.h"))
check("udpfs_ioman imports it", "I_arp_ip_conflict" in read("modules/network/udpfs_ioman/src/imports.lst"))
check("udpfs_bd does not need it", "I_arp_ip_conflict" not in read("modules/network/udpfs_bd/src/imports.lst"))
conflict = body(udpfs, "static void udpfsCheckIpConflict(void)")
check("the scan only queues the notice", "guiWarning" not in conflict and "udpfsIpConflictNotice = 1;" in conflict)
check("the notice is shown once", "udpfsIpConflictWarned = 1;" in conflict)
check("the GUI frame hook shows it", "udpfsShowPendingNotice();" in body(read("src/opl.c"), "static void menuUpdateHook()"))
base = read("lng_tmpl/_base.yml")
# Append-only language file: the label sits after every label that existed before it (positional
# .lng files), whatever is appended later.
check("the conflict label was appended after the existing labels",
      base.index("- label: RA_NEUTRINO_UNTRACKED") < base.index("- label: UDPFS_IP_CONFLICT"))

# --- RA release previews ---
ra = read(".github/workflows/ra-release.yml")
trigger = ra[ra.index("  pull_request:"):ra.index("\npermissions:")]
check("RA release previews are limited to packaging paths", "    paths:\n" in trigger and
      "- .github/scripts/package_ra_release.py" in trigger and "- third_party/orbit-neutrino/**" in trigger and
      "src/" not in trigger)
check("RA release still follows every Rolling run", "  workflow_run:\n" in ra[:ra.index("\npermissions:")])

if failures:
    raise SystemExit("FAIL:\n  " + "\n  ".join(failures))
print("PASS: DEV9-gated UDP chains, UDPFS sub-make dependencies, IP-conflict notice and RA preview paths")
