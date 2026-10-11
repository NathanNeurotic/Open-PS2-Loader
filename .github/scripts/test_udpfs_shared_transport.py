"""Guard against accidental divergence of the two UDPFS transport implementations."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
root = ROOT / "modules" / "network"

for variant in ("udpfs_ioman", "udpfs_bd"):
    make = (root / variant / "Makefile").read_text()
    assert "IOP_SRC_DIR := src/" in make
    assert "udpfs_core.o" in make and "udprdma.o" in make
    for name in ("udpfs_core.c", "udprdma.c"):
        obj = name.removesuffix(".c") + ".o"
        assert f"$(IOP_OBJS_DIR){obj}: ../udpfs_shared/src/{name}" in make
    assert f"-DFEATURE_{variant.upper()}" in make
    for name in ("udpfs_core.c", "udprdma.c"):
        local = root / variant / "src" / name
        contents = local.read_text()
        expected = f'#include "../../udpfs_shared/src/{name}"'
        assert expected in contents, (variant, name)
        assert contents.count("#include ") == 1, (variant, name)
        target = (local.parent / "../../udpfs_shared/src" / name).resolve()
        assert target == (root / "udpfs_shared" / "src" / name).resolve()
        assert target.is_file()

    # Local headers are intentionally retained for variant-specific compilation.
    for header in ("udpfs_core.h", "udprdma.h", "udprdma_seq.h",
                   "udpfs_packet.h", "udprdma_packet.h"):
        this = (root / variant / "src" / header).read_bytes()
        other = (root / ("udpfs_bd" if variant == "udpfs_ioman" else "udpfs_ioman")
                 / "src" / header).read_bytes()
        assert this == other, (variant, header)

shared = root / "udpfs_shared" / "src"
core = (shared / "udpfs_core.c").read_text()
transport = (shared / "udprdma.c").read_text()
assert "int udprdma_send(" in transport
assert "int udprdma_send_ll(" in transport
assert transport.count("if (udprdma_ack_covers(") == 2
assert "udpfs_core_init(" in core
print("PASS: filesystem and block UDPFS builds use identical canonical transport sources")
