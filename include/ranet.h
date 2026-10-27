/* RetroAchievements: talking to the PC client from the OPL menu. See src/ranet.c */
#ifndef __RANET_H__
#define __RANET_H__

/* Hashes are known; ask the PC for the watch list and store it next to
   the game. Returns 0 when the list was received, 1 when RetroAchievements
   does not know the image, -7 when the PC was still identifying it after
   the waiting rounds, -8 when the NIC is owned by a UDP transport and the
   ask was refused without touching the network, another negative value when
   the PC did not answer or the transfer broke. -9 means the selected
   Caduceus bridge answered but its RA session is offline.
   info (may be NULL) receives the game title, info2 (may be NULL) the
   achievement counts as the PC reported them, e.g. info "Need for Speed:
   Underground 2" and info2 "76 achievements: 3 unlocked, 10 unsupported".
   Older PC clients report only the total, so info2 is then just
   "76 achievements". */
int raAskPC(const char *hash, const char *serial, const char *savepath,
            char *info, int infosz, char *info2, int info2sz);

/* 1 when a UDP transport (UDPBD, or the UDPFS filesystem chain) owns the
   SMAP NIC. RA must not raise the SMB stack on top of it; the menu actions
   refuse with a notice instead. */
int raNetNicBusy(void);

/* raNetNicBusy, or the selected network protocol is a UDP transport that has
   not loaded yet. Menu-side RA actions use this: raising SMB first would claim
   the one NIC and leave UDPFS/UDPBD unable to load until the next boot. */
int raNetNicReserved(void);
/* Non-blocking TCP read that never loses bytes to ps2ips' tail truncation (#1062).
   chunk must be 64-byte aligned. Returns bytes read, 0 on close, -1 when nothing waits. */
int raNetTcpRecv(int sock, void *chunk, int want);
int raNetUdpfsNotLoaded(void); /* a UDPFS transport is selected but not loaded yet */

/* Xerabora-mode achievement browser. raNetXeraboraIdentify finds the
   xeRAbora PC (explicit RA companion IP, verified peer, or RAP1 broadcast;
   host in network byte order) and, when hash is not NULL, asks RAQ1 for the
   image's title and achievement count. 0 = known, 1 = unknown image, -8 =
   wrong mode or the NIC is reserved, other negatives = no answer.
   raNetHttpGet fetches host:port/path over HTTP/1.0 into buf and returns the
   body offset (status 200), with the body length in *length, or a negative
   value; a document larger than buf or cut off by the timeout is refused. */
int raNetXeraboraIdentify(const char *hash, const char *serial, unsigned int *host,
                          char *title, int titlesz, int *count);
int raNetHttpGet(unsigned int host, int port, const char *path, char *buf, int max, int *length);

/* Brings the menu network up for a telemetry launch (see ranet.c). */
void raLaunchNetworkUp(void);

/* Broadcasts a discovery request and reports the outcome as two lines
   of text for the notice popup. Returns 1 when a PC client answered. */
int raNetTestLink(char *line1, int sz1, char *line2, int sz2);

/* Verified for the current RA mode and SMB host. An unrelated UDP response
   never becomes the passive game's destination. */
unsigned int raNetPeerIP(void);
void raNetForgetPeer(void);
int raCaduceusPage(const char *request, unsigned int serial, char *out, int size);

#endif
