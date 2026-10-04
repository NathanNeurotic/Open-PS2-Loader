"""Check that the console editor can round-trip long fields and refuses overflow."""

from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/supportbase.c").read_text(encoding="utf-8")


def function(name):
    match = re.search(r"^(?:static )?(?:int|void) " + name + r"\([^;{]*\)\s*\{", source, re.M)
    if not match:
        raise RuntimeError(f"missing {name}")
    return source[match.start() : source.index("\n}", match.start()) + 2]


declarations = "\n".join(
    function(name) for name in ("naAppend", "naAppendKV", "neutrinoArgsParse", "neutrinoArgsAssemble")
)
header = (root / "include/supportbase.h").read_text(encoding="utf-8")
struct = re.search(r"typedef struct\s*\{\s*int qb;.*?\} neutrino_args_t;", header, re.S)
if not struct:
    raise RuntimeError("missing neutrino_args_t")

harness = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
@STRUCT@
@FUNCTIONS@
int main(void)
{
    const char *input = "-cfg=mc0:/NEUTRINO/config/a-very-long-configuration-name.toml -bsdfs=bd --b level=2";
    neutrino_args_t args;
    char output[256];
    neutrinoArgsParse(input, &args);
    if (strcmp(args.cfg, "mc0:/NEUTRINO/config/a-very-long-configuration-name.toml")) return 1;
    args.qb = 1;
    if (!neutrinoArgsAssemble(&args, output, sizeof(output))) return 2;
    if (strcmp(output, "-qb -cfg=mc0:/NEUTRINO/config/a-very-long-configuration-name.toml -bsdfs=bd --b level=2")) return 3;
    memset(args.cfg, 'x', sizeof(args.cfg) - 1);
    args.cfg[sizeof(args.cfg) - 1] = '\0';
    if (neutrinoArgsAssemble(&args, output, sizeof(output))) return 4;
    memset(&args, 0, sizeof(args));
    memset(args.extra, 'x', 220);
    args.extra[220] = '\0';
    if (!neutrinoArgsAssemble(&args, output, sizeof(output)) || strlen(output) != 220) return 5;
    return 0;
}
"""

with tempfile.TemporaryDirectory() as tmp:
    program = Path(tmp) / "editor.c"
    binary = Path(tmp) / "editor"
    program.write_text(harness.replace("@STRUCT@", struct.group()).replace("@FUNCTIONS@", declarations), encoding="utf-8")
    subprocess.run(["gcc", "-std=gnu99", "-Wall", "-Werror", "-o", str(binary), str(program)], check=True)
    subprocess.run([str(binary)], check=True)

print("neutrino args editor: long value round-trip, flag order, and overflow rejection OK")
