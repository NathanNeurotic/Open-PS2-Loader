# Sourced by run.sh, after its other cases: games launched with the longest file names the menu
# lists and the lengths around the old 160-byte limit, and an image that is not there.
#
# longname.c compiles modules/iopcore/cdvdman/device-smb.c whole, with the real cdvd_config.h and the
# in-game reader of either module: smb2.c (smb2_cdvdman) or smb.c (smb_cdvdman, SMB1). It fills the
# settings block as the EE's launch does, for an image name of ISO_GAME_NAME_MAX bytes
# (include/supportbase.h), and of the lengths either side of each one the old 160-byte field cut,
# with the longest prefix the block holds and with none, then mounts and reads the image the way the
# in-game reader does: DeviceFSInit builds the path from the block and opens it, DeviceReadSectors
# reads sectors through it. A block too short for the name opens a file that does not exist, and the
# case fails. So does a read from a missing image that reports success. These cases need Samba and
# run only here, not in CI; launchname.c checks the same names without a server, in CI.
namemax=$(sed -n -E 's/^#define[[:space:]]+ISO_GAME_NAME_MAX[[:space:]]+([0-9]+).*/\1/p' "$root/include/supportbase.h")
[ -n "$namemax" ] || { echo "ISO_GAME_NAME_MAX not found in include/supportbase.h"; exit 2; }
ln_cc() { # $1 output, then the defines and sources that differ
    out=$1
    shift
    cc $san -Wall -Wno-unused-parameter -DSMB_DRIVER -DISO_GAME_NAME_MAX="$namemax" -I"$here/inc-device" -I"$here/inc-ingame" \
        -I"$root/modules/iopcore/cdvdman" -I"$root/modules/iopcore/common" "$here/longname.c" \
        "$root/modules/iopcore/cdvdman/device-smb.c" "$@" -o "$work/$out"
}
ln_cc longname "$root/modules/iopcore/cdvdman/smb2.c" "$root/modules/iopcore/cdvdman/smb2auth.c"
ln_cc longname1 -DLONGNAME_SMB1 "$root/modules/iopcore/cdvdman/smb.c"

longname() { # $1 format: old, plain, utf8, ul or missing; $2 prefix or none; $3 the name's length (optional)
    timeout 120 ./longname 127.0.0.1 "$port" ps2 secret PS2SMB share "$@"
}
longname1() { # SMB1 has no NTLMv2 here: an unknown user, logged on as the guest
    timeout 120 ./longname1 127.0.0.1 "$port" nobody x PS2SMB share "$@"
}
# The first lengths the old 160-byte field cut (old format from 144, plain from 156), and the lengths
# before them, with and without a prefix: $1 is the case's function, $2 its dialect.
boundaries() {
    for n in 143 144; do
        for pre in prefix none; do
            run "in-game launch ($2), old-format name of $n bytes, $pre" "$1" old "$pre" "$n"
        done
    done
    for n in 155 156; do
        for pre in prefix none; do
            run "in-game launch ($2), <name>.iso of $n bytes, $pre" "$1" plain "$pre" "$n"
        done
    done
}
write_conf mandatory ""
start_smbd
run "in-game launch (SMB2), longest old-format name (SLUS_209.46.<name>.iso), longest prefix" longname old prefix
run "in-game launch (SMB2), longest old-format name, no prefix" longname old none
run "in-game launch (SMB2), longest <name>.iso, no prefix" longname plain none
run "in-game launch (SMB2), longest <name>.iso, UTF-8 in the name, longest prefix" longname utf8 prefix
run "in-game launch (SMB2), USBExtreme game in two parts, longest prefix" longname ul prefix
run "in-game launch (SMB2), a missing image: the read fails" longname missing prefix 20
boundaries longname SMB2
# smb.c does not sign, and logs on with LM/NTLM responses.
write_conf disabled "server min protocol = NT1
   ntlm auth = yes"
start_smbd
run "in-game launch (SMB1), longest old-format name, longest prefix" longname1 old prefix
run "in-game launch (SMB1), longest old-format name, no prefix" longname1 old none
run "in-game launch (SMB1), longest <name>.iso, longest prefix" longname1 plain prefix
run "in-game launch (SMB1), USBExtreme game in two parts, longest prefix" longname1 ul prefix
run "in-game launch (SMB1), a missing image: the read fails, it does not return what its buffer held" longname1 missing prefix 20
boundaries longname1 SMB1
