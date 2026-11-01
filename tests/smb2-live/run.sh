#!/bin/sh
# Live SMB2 check: runs the loader's two SMB2 clients on the host against a real Samba server.
#
#   ingame.c  drives modules/iopcore/cdvdman/smb2.c (smb2_cdvdman, the in-game reader) the way
#             device-smb.c and smb_mcemu do: negotiate, NTLMv2 logon, tree connect, a whole 5 MB
#             image read back and compared byte for byte, end-of-file short counts, VMC page
#             writes and read-back, a 100 KB write across the 64 KB chunk, error paths.
#   browse.c  drives modules/network/smb2man/smb2man.c (the menu's browse driver) over libsmb2,
#             vendored at modules/network/smb2man/libsmb2: LOGON/OPENSHARE/GETSHARELIST devctls,
#             directory listing, stat, read/write/seek, create/truncate/exclusive opens, mkdir,
#             rename, remove, reconnect, and handles left open across LOGOFF.
#
# Both are built with AddressSanitizer and UBSan. The server is started on a private port with
# NTLMv2 only, run once with signing mandatory and once with signing off, and once capped at
# SMB 2.0.2. Guest and anonymous logons are checked against a guest-ok share.
#
# Needs: a C compiler, Samba (smbd, smbpasswd, smbclient) and the PS2SDK's ps2smb.h (found through
# PS2BUILD_HOME, default ~/.local/share/ps2build). Run as root (smbd wants to own its state) from
# anywhere: sh tests/smb2-live/run.sh
# This is a host test, not a console test: it does not exercise SMSTCPIP, the IOP or real hardware.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
work=$(mktemp -d)
port=${SMB2_LIVE_PORT:-4450}
sdk=${PS2BUILD_HOME:-$HOME/.local/share/ps2build}
ps2smb=$(find "$sdk/packages" -name ps2smb.h -path '*common/include*' 2>/dev/null | head -n 1)
[ -n "$ps2smb" ] || { echo "ps2smb.h not found under $sdk/packages"; exit 2; }
command -v smbd >/dev/null || { echo "smbd not installed (apt-get install samba smbclient)"; exit 2; }

cleanup() {
    [ -f "$work/run/smbd.pid" ] && kill "$(cat "$work/run/smbd.pid")" 2>/dev/null || true
    rm -rf "$work"
}
trap cleanup EXIT INT TERM

# ---- the share ----------------------------------------------------------------------------------
mkdir -p "$work/share/DVD" "$work/share/VMC" "$work/run/ncalrpc" "$work/inc"
python3 - "$work/share" <<'EOF'
import sys
root = sys.argv[1]
open(root + '/DVD/TEST.iso', 'wb').write(bytes((i * 7 + 3) & 0xff for i in range(5 * 1024 * 1024 + 1234)))
open(root + '/VMC/card.bin', 'wb').write(bytes(1024 * 1024 * 2))
EOF

conf="$work/smb.conf"
write_conf() { # $1 signing, $2 extra global line
    cat >"$conf" <<EOF
[global]
   server role = standalone server
   map to guest = bad user
   smb ports = $port
   server min protocol = SMB2_02
   server signing = $1
   ntlm auth = ntlmv2-only
   $2
   ncalrpc dir = $work/run/ncalrpc
   pid directory = $work/run
   lock directory = $work/run
   state directory = $work/run
   cache directory = $work/run
   private dir = $work/run
   log file = $work/run/log.%m
   disable netbios = yes
   load printers = no
[PS2SMB]
   path = $work/share
   read only = no
   force user = root
   guest ok = yes
EOF
}

start_smbd() {
    [ -f "$work/run/smbd.pid" ] && kill "$(cat "$work/run/smbd.pid")" 2>/dev/null || true
    sleep 1
    smbd -s "$conf" -D
    i=0
    until smbclient -s "$conf" -p "$port" //127.0.0.1/PS2SMB -U ps2%secret -c ls >/dev/null 2>&1; do
        i=$((i + 1))
        [ $i -lt 50 ] || { echo "smbd did not come up"; cat "$work/run/log.smbd" 2>/dev/null | tail -20; exit 1; }
        sleep 0.2
    done
}

# ---- build ----------------------------------------------------------------------------------------
cp "$ps2smb" "$work/inc/"
san="-fsanitize=address,undefined -fno-omit-frame-pointer -g -O1"
cc $san -Wall -Wno-unused-parameter -I"$here/inc-ingame" -I"$root/modules/iopcore/cdvdman" -I"$root/modules/iopcore/common" \
    "$here/ingame.c" "$root/modules/iopcore/cdvdman/smb2.c" "$root/modules/iopcore/cdvdman/smb2auth.c" -o "$work/ingame"

lib="$root/modules/network/smb2man/libsmb2"
# libsmb2 for the host, from the vendored sources, with the configuration its CMake build finds on Linux.
hostcfg="-DHAVE_ARPA_INET_H -DHAVE_FCNTL_H -DHAVE_INTTYPES_H -DHAVE_NETDB_H -DHAVE_NETINET_IN_H -DHAVE_NETINET_TCP_H \
 -DHAVE_POLL_H -DHAVE_SOCKADDR_STORAGE -DHAVE_LINGER -DHAVE_STDINT_H -DHAVE_STDIO_H -DHAVE_STDLIB_H -DHAVE_STRINGS_H \
 -DHAVE_STRING_H -DHAVE_SYS_IOCTL_H -DHAVE_SYS_POLL_H -DHAVE_SYS_SOCKET_H -DHAVE_SYS_STAT_H -DHAVE_SYS_TYPES_H \
 -DHAVE_SYS_UIO_H -DHAVE_TIME_H -DHAVE_SYS_TIME_H -DHAVE_UNISTD_H -DHAVE_ERRNO_H -DSTDC_HEADERS -DHAVE_GETRANDOM -DHAVE_SYS_RANDOM_H \
 -D_FILE_OFFSET_BITS=64 -D_U_=__attribute__((unused))"
mkdir -p "$work/lib"
for f in "$lib"/lib/*.c; do
    # shellcheck disable=SC2086
    cc $san -w $hostcfg -I"$lib/include" -I"$lib/include/smb2" -I"$lib/lib" -c "$f" -o "$work/lib/$(basename "$f" .c).o"
done
cc $san -Wall -Wno-unused-function -I"$here/inc-browse" -I"$work/inc" -I"$lib/include" -I"$lib/include/smb2" \
    -Dmalloc=iop_malloc -Dfree=iop_free -Dcalloc=iop_calloc -Drealloc=iop_realloc -D_start=smb2man_start \
    -c "$root/modules/network/smb2man/smb2man.c" -o "$work/smb2man.o"
cc $san -Wall -I"$here/inc-browse" -I"$work/inc" "$here/browse.c" "$work/smb2man.o" "$work"/lib/*.o -o "$work/browse"

id ps2 >/dev/null 2>&1 || useradd -M ps2
fails=0
run() { # $1 label, then the command
    label=$1
    shift
    if (cd "$work" && "$@") >"$work/out.txt" 2>&1; then
        echo "ok   $label"
    else
        echo "FAIL $label"
        tail -15 "$work/out.txt"
        fails=$((fails + 1))
    fi
}
ingame() { # $1 user, $2 password
    ./ingame 127.0.0.1 "$port" "$1" "$2" PS2SMB '\DVD\TEST.iso' '\VMC\card.bin' && cmp readback.bin share/DVD/TEST.iso
}
denied() { # the logon must fail cleanly, not hang or crash
    ./ingame 127.0.0.1 "$port" ps2 wrong PS2SMB '\DVD\TEST.iso' '\VMC\card.bin' | grep -q 'session setup -1000'
}
browse() {
    ./browse 127.0.0.1 "$port" ps2 secret PS2SMB '\DVD\TEST.iso' share/DVD/TEST.iso
}

for signing in mandatory disabled; do
    write_conf "$signing" ""
    printf 'secret\nsecret\n' | smbpasswd -c "$conf" -s -a ps2 >/dev/null
    start_smbd
    run "in-game reader, signing $signing, NTLMv2 user" ingame ps2 secret
    run "in-game reader, signing $signing, guest" ingame nobody x
    run "in-game reader, signing $signing, anonymous" ingame '' ''
    run "in-game reader, signing $signing, wrong password refused" denied
    run "browse driver, signing $signing" browse
done
write_conf mandatory "server max protocol = SMB2_02"
start_smbd
run "in-game reader, SMB 2.0.2 only, signing mandatory" ingame ps2 secret
run "browse driver, SMB 2.0.2 only" browse

[ $fails -eq 0 ] && echo "smb2-live: all passed" || echo "smb2-live: $fails failed"
exit $fails
