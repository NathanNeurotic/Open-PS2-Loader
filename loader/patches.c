/*
  Copyright 2009, Ifcaro, jimmikaelkael
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.  
*/

#include "loader.h"

#define MAX_PATCHES		63

typedef struct {
	u32 addr;
	u32 val;
	u32 check;
} game_patch_t;

typedef struct {
	char *game;
	int mode;
	game_patch_t patch;
} patchlist_t;

static patchlist_t patch_list[19] = {
	{ "SLES_524.58", USB_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Disgaea Hour of Darkness PAL - disable cdvd timeout stuff
	{ "SLES_524.58", ETH_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Disgaea Hour of Darkness PAL - reduce snd buffer allocated on IOP
	{ "SLUS_206.66", USB_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Disgaea Hour of Darkness NTSC U - disable cdvd timeout stuff
	{ "SLUS_206.66", ETH_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Disgaea Hour of Darkness NTSC U - reduce snd buffer allocated on IOP
	{ "SLPS_202.51", USB_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Makai Senki Disgaea NTSC J - disable cdvd timeout stuff
	{ "SLPS_202.51", ETH_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Makai Senki Disgaea NTSC J - reduce snd buffer allocated on IOP
	{ "SLPS_202.50", USB_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Makai Senki Disgaea (limited edition) NTSC J - disable cdvd timeout stuff
	{ "SLPS_202.50", ETH_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Makai Senki Disgaea (limited edition) NTSC J - reduce snd buffer allocated on IOP
	{ "SLPS_731.03", USB_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Makai Senki Disgaea (PlayStation2 the Best) NTSC J - disable cdvd timeout stuff
	{ "SLPS_731.03", ETH_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Makai Senki Disgaea (PlayStation2 the Best) NTSC J - reduce snd buffer allocated on IOP
	{ "SLES_529.51", USB_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Phantom Brave PAL - disable cdvd timeout stuff
	{ "SLUS_209.55", USB_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Phantom Brave NTSC U - disable cdvd timeout stuff
	{ "SLPS_203.45", USB_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Phantom Brave NTSC J - disable cdvd timeout stuff
	{ "SLPS_203.44", USB_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Phantom Brave (limited edition) NTSC J - disable cdvd timeout stuff
	{ "SLPS_731.08", USB_MODE, { 0xdeadbee0, 0x00000000, 0x00000000 }}, // Phantom Brave: 2-shuume Hajime Mashita (PlayStation 2 the Best) NTSC J - disable cdvd timeout stuff
	{ "SLUS_212.00", USB_MODE, { 0xdeadbee1, 0x00000000, 0x00000000 }}, // Armored Core Nine Breaker NTSC U - skip failing case on binding a RPC server
	{ "SLES_538.19", USB_MODE, { 0xdeadbee1, 0x00000000, 0x00000000 }}, // Armored Core Nine Breaker PAL - skip failing case on binding a RPC server
	{ "SLPS_254.08", USB_MODE, { 0xdeadbee1, 0x00000000, 0x00000000 }}, // Armored Core Nine Breaker NTSC J - skip failing case on binding a RPC server
	{ NULL, 0, { 0, 0, 0 }}												// terminater
};

static u32 NIScdtimeoutpattern[] = {
	0x3c010000,
	0x8c230000,
	0x24630001,
	0x3c010000,
	0xac230000,
	0x3c010000,
	0x8c230000,
	0x2861037b,
	0x14200000,
	0x00000000
};
static u32 NIScdtimeoutpattern_mask[] = {
	0xffff0000,
	0xffff0000,
	0xffffffff,
	0xffff0000,
	0xffff0000,
	0xffff0000,
	0xffff0000,
	0xffffffff,
	0xffff0000,
	0xffffffff
};

static u32 NISsndiopmemallocpattern[] = {
	0x8fa20030,
	0x2443003f,
	0x2402ffc0,
	0x00621024,
	0x3c010000,
	0xac220000,
	0x3c020000,
	0x34440000,
	0x0c000000,
	0x00000000
};
static u32 NISsndiopmemallocpattern_mask[] = {
	0xffffffff,
	0xffffffff,
	0xffffffff,
	0xffffffff,
	0xffff0000,
	0xffff0000,
	0xffff0000,
	0xffff0000,
	0xfc000000,
	0xffffffff
};

static u32 AC9Bpattern[] = {
	0x8e450000,
	0x0220202d,
	0x0c000000,
	0x0000302d,
	0x04410003,
	0x00000000,
	0x10000005,
	0x2402ffff,
	0x8e020000,
	0x1040fff6
};
static u32 AC9Bpattern_mask[] = {
	0xffffffff,
	0xffffffff,
	0xfc000000,
	0xffffffff,
	0xffffffff,
	0xffffffff,
	0xffffffff,
	0xffffffff,
	0xffffffff,
	0xffffffff
};

//-------------------------------------------------------------------------
static u8 *find_pattern_with_mask(u8 *buf, u32 bufsize, u8 *bytes, u8 *mask, u32 len)
{
	register u32 i, j;

	for (i = 0; i < bufsize - len; i++) {
		for (j = 0; j < len; j++) {
			if ((buf[i + j] & mask[j]) != bytes[j])
				break;
		}
		if (j == len)
			return &buf[i];
	}

	return NULL;
}

static void NIS_generic_patches(void)
{
	u8 *ptr;

	if (GameMode == USB_MODE) { // Nippon Ichi Sofwtare games generic patch to disable cdvd timeout
		ptr = find_pattern_with_mask((u8 *)0x100000, 0x01e00000, (u8 *)NIScdtimeoutpattern, (u8 *)NIScdtimeoutpattern_mask, 0x28);
		if (ptr) {
			u16 jmp = _lw((u32)ptr+32) & 0xffff;
			_sw(0x10000000|jmp, (u32)ptr+32);
		}
	}
	else if (GameMode == ETH_MODE) { // Nippon Ichi Sofwtare games generic patch to lower memory allocation for sounds
		ptr = find_pattern_with_mask((u8 *)0x100000, 0x01e00000, (u8 *)NISsndiopmemallocpattern, (u8 *)NISsndiopmemallocpattern_mask, 0x28);
		if (ptr) {
			u16 val = _lw((u32)ptr+24) & 0xffff;
			u16 val2 = _lw((u32)ptr+28) & 0xffff;			
			_sw(0x3c020000|(val-1), (u32)ptr+24);
			_sw(0x34440000|(val2+0x8000), (u32)ptr+28);
		}
	}
}

static void AC9B_generic_patches(void)
{
	u8 *ptr;

	if (GameMode == USB_MODE) { // Armored Core 9 Breaker generic USB patch
		ptr = find_pattern_with_mask((u8 *)0x100000, 0x01e00000, (u8 *)AC9Bpattern, (u8 *)AC9Bpattern_mask, 0x28);
		if (ptr)
			_sw(0, (u32)ptr+36);
	}
}

void apply_game_patches(void)
{
	patchlist_t *p = (patchlist_t *)&patch_list[0];

	// if there are patches matching game name/mode then fill the patch table
	while (p->game) {
		if ((!strcmp(GameID, p->game)) && (GameMode == p->mode)) {

			if (p->patch.addr == 0xdeadbee0)
				NIS_generic_patches(); 	// Nippon Ichi Software games generic patch
			else if (p->patch.addr == 0xdeadbee1)
				AC9B_generic_patches(); // Armored Core 9 Breaker USB generic patch

			// non-generic patches
			else if (_lw(p->patch.addr) == p->patch.check)
				_sw(p->patch.val, p->patch.addr);
		}
		p++;
	}
}
