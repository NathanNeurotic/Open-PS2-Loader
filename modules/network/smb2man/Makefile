# smb2man.irx: the SMB2 browse driver, loaded instead of smbman when Settings > Network >
# SMB Version is SMB2. smb2man.c (the ps2smb.h devctl front end OPL's network menu uses) over
# libsmb2, vendored unmodified from upstream c6e4997 (libsmb2/VENDORED.txt). The defines are the
# ones upstream's own PS2 IOP CMake build passes. LGPL-2.1, like libsmb2.
# Size matters here: smb2man loads last, after the network and BDM stacks, into what is left of
# IOP RAM. Too big, LoadModuleBuffer failed with -400 (no memory) and ethsupport.c fell back to
# SMB1. So the link drops unreferenced functions (--gc-sections with the per-section linkfile) and
# errors_mini.c replaces libsmb2's 30 KB NT_STATUS name table (libsmb2/lib/errors.c is not built).
# Loading needs the staged file AND the resident image at once, and BDM's 128 KiB block cache per
# physical device ate the room on a four-device console, so libbdm caps the cached devices at two
# (modules/bdm/libbdm/src/bd_cache.c). Twin of RiptOPL #305.
IOP_BIN  = smb2man.irx
IOP_OBJS = smb2man.o libsmb2/lib/aes.o libsmb2/lib/aes128ccm.o libsmb2/lib/aes_reference.o libsmb2/lib/alloc.o libsmb2/lib/asn1-ber.o libsmb2/lib/compat.o errors_mini.o libsmb2/lib/hmac-md5.o libsmb2/lib/hmac.o libsmb2/lib/init.o libsmb2/lib/libsmb2.o libsmb2/lib/md4c.o libsmb2/lib/md5.o libsmb2/lib/ntlmssp.o libsmb2/lib/pdu.o libsmb2/lib/quic.o libsmb2/lib/sha1.o libsmb2/lib/sha224-256.o libsmb2/lib/sha384-512.o libsmb2/lib/smb2-cmd-cancel.o libsmb2/lib/smb2-cmd-close.o libsmb2/lib/smb2-cmd-create.o libsmb2/lib/smb2-cmd-echo.o libsmb2/lib/smb2-cmd-error.o libsmb2/lib/smb2-cmd-flush.o libsmb2/lib/smb2-cmd-ioctl.o libsmb2/lib/smb2-cmd-lock.o libsmb2/lib/smb2-cmd-logoff.o libsmb2/lib/smb2-cmd-negotiate.o libsmb2/lib/smb2-cmd-notify-change.o libsmb2/lib/smb2-cmd-oplock-break.o libsmb2/lib/smb2-cmd-query-directory.o libsmb2/lib/smb2-cmd-query-info.o libsmb2/lib/smb2-cmd-read.o libsmb2/lib/smb2-cmd-session-setup.o libsmb2/lib/smb2-cmd-set-info.o libsmb2/lib/smb2-cmd-tree-connect.o libsmb2/lib/smb2-cmd-tree-disconnect.o libsmb2/lib/smb2-cmd-write.o libsmb2/lib/smb2-data-file-info.o libsmb2/lib/smb2-data-filesystem-info.o libsmb2/lib/smb2-data-reparse-point.o libsmb2/lib/smb2-data-security-descriptor.o libsmb2/lib/smb2-share-enum.o libsmb2/lib/smb2-signing.o libsmb2/lib/smb3-seal.o libsmb2/lib/smbdirect.o libsmb2/lib/socket.o libsmb2/lib/spnego-wrapper.o libsmb2/lib/sync.o libsmb2/lib/timestamps.o libsmb2/lib/unicode.o libsmb2/lib/usha.o  imports.o

IOP_CFLAGS += -DHAVE_CONFIG_H -DHAVE_SYS_FCNTL_H -DNEED_BE64TOH -DNEED_GETLOGIN_R -DNEED_GETPID \
	-DNEED_POLL -DNEED_RANDOM -DNEED_READV -DNEED_SRANDOM -DNEED_STRDUP -DNEED_WRITEV \
	-DPS2 -D__PS2__ -D_IOP -D__ps2sdk_iop__ \
	-Os -fno-builtin -msoft-float -mno-explicit-relocs -Wno-unused-function -Wno-unused-variable \
	-ffunction-sections -fdata-sections
IOP_INCS += -I. -Ilibsmb2/include -Ilibsmb2/include/smb2 -Ilibsmb2/lib -I$(PS2SDK)/common/include
IOP_LIBS += -lgcc
IOP_LDFLAGS += -Wl,--gc-sections -Wl,-u,_irx_id
IOP_LINKFILE = linkfile

include $(PS2SDK)/Defs.make
include ../../Rules.bin.make
include $(PS2SDK)/samples/Makefile.iopglobal
