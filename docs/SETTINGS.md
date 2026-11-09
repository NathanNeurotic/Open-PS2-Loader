# Where every setting lives

This page maps the **Settings** hub (Start in the main menu) page by page: each row as the screen
shows it, what it does, and the key it is saved under. Fresh defaults are in
[DEFAULTS.md](DEFAULTS.md). Per-game settings (a game's Triangle menu) are listed at the end.

Unless a row says otherwise, keys are in the master configuration `settings_riptopl.cfg`
(older builds wrote `conf_riptopl.cfg`; it is still read). Network keys marked *(net)* are in
`conf_network.cfg`. Every key is defined in `include/config.h` and loaded and saved in `src/opl.c`.

## How the hub works

* The hub lists nine pages and **Save Changes**, and shows the running version under its title.
  Up and Down pick a page; Cross (or Circle, if swapped) opens it; L1 and R1 move between pages
  while one is open.
* A page's changes take effect when you leave it with OK. They are written to the memory card or
  device only by **Save Changes**. Leaving the hub with unsaved changes asks whether to save, exit
  without saving, or keep editing. Exiting without saving keeps the changes active until the
  console is switched off; only a picked HDD home folder is dropped.
* Three things write to the memory card at once on **OK**, without Save Changes, and leaving the
  hub without saving does not undo them:
  * POPSTARTER Network Settings (POPSTARTER's own `IPCONFIG.DAT` and `SMBCONFIG.DAT`);
  * its POPS UDPFS Network Settings sub-page (`SYS-CONF/IPCONFIG.DAT` and `UDPFSCONFIG.DAT`);
  * on PS Emulation Settings, a changed BDMA Mode, or a changed BDMA Source while the mode is not
    FAT32, equips or removes the BDMA driver files on the card.
* Each setting has one row in one place. A button marked *Modify* opens a sub-page and returns to
  the page that opened it.
* Some rows exist only in some builds: RiptOPLite ([RIPTOPLITE.md](RIPTOPLITE.md)) carries one
  game source, the RetroAchievements rows need `RETROACHIEVEMENTS=1`, Controller Emulation and
  Macros need `PADEMU=1`, and the In-Game Menu row needs `IGR_MENU=1`.

## Game Sources

| Row | What it does | Key |
| --- | --- | --- |
| Default Menu | The page the menu opens on. | `default_device` |
| HDD (APA) Start Mode | When the internal HDD (APA/PFS) page starts: Off, Manual or Auto. | `hdd_mode` |
| MMCE Start Mode | When the MMCE (SD2PSX, MemCard PRO2) page starts. | `mmce_mode` |
| MMCE Settings *(Modify)* | MMCE slot, IGR slot, Send GameID on Launch, communication and path settings (below). | |
| BDM Devices Start Mode | When the block-device pages (the indented rows below) start. | `usb_mode` |
| &nbsp;&nbsp;Internal HDD (exFAT) | Lists games from an exFAT internal HDD. | `enable_bdm_hdd` |
| &nbsp;&nbsp;USB | Lists games from USB mass storage. | `enable_usb` |
| &nbsp;&nbsp;MX4SIO | Lists games from an MX4SIO SD adapter. | `enable_mx4sio` |
| &nbsp;&nbsp;PC CARD CF (experimental) | Lists games from a CompactFlash card in a PC Card adapter. | `enable_pccf` |
| &nbsp;&nbsp;DESR DVR ISOs (experimental) | Lists ISOs on a PSX DESR's DVR partition. | `enable_dvr` |
| &nbsp;&nbsp;iLink | Lists games from an i.LINK (FireWire) drive. | `enable_ilink` |
| Network Connectivity | When the network page starts: Off, Manual or Auto. | `net_start_mode` |
| &nbsp;&nbsp;Protocol | The same setting as Protocol on the Network page, shown here beside the start mode. | `network_protocol`, `net_protocol_pick` |
| Applications Page Start Mode | When the Applications page starts. | `app_mode` |
| Favorites Page Start Mode | When the Favorites page starts. | `fav_mode` |
| All Games List | One list of every game instead of a page per device. Same setting as Interface → Library. | `all_games` |
| Show Hidden Games | Lists games you hid. | `show_hidden` |

**MMCE Settings** sub-page: MMCE Slot (`mmce_slot`), IGR Bootcard Slot(s) (`mmceigr_slot`), Send
GameID on Launch (`mmce_gameid`), Wait cycles after /ACK low (`mmce_wait_cycles`), Use timeout
alarms (`mmce_use_alarms`), MMCE Prefix Path (`mmce_prefix`).

## General & System

| Row | What it does | Key |
| --- | --- | --- |
| Remember Last Played Game | Selects the last game you started when the menu opens. | `remember_last` |
| Auto Start | Seconds before the remembered game starts by itself (shown when the row above is on). | `autostart_last` |
| Browse Folders in Game List | Shows games in their folders instead of one flat list. | `folder_nav` |
| IGR Path | Where in-game reset exits to. | `exit_path` |
| Custom Settings Path | A folder to read and save settings in instead of the default. | `custom_settings_path` |
| Write Operations | Allows writes to game devices (rename, delete, VMC, art). | `enable_delete_rename` |
| Parental Lock Password | Password that locks protected games and settings. | `parental_lock_password` |
| Debug Colors | Debug colours and logging during launch. | `disable_debug` |
| BDM Prefix Path | A folder on BDM devices that holds the game folders. | `usb_prefix` |
| ETH Prefix Path | A folder on the SMB share that holds the game folders. | `eth_prefix` |
| HDD Spindown | Minutes before the internal HDD spins down (0 = never). | `hdd_spindown` |
| Cache Game List (HDD APA) | Keeps the APA game list between starts. | `hdd_game_list_cache` |
| BDM Cache | In-game read cache for BDM devices (sectors). | `bdm_cache` |
| HDD Cache | In-game read cache for the APA HDD. | `hdd_cache` |
| SMB Cache | In-game read cache for SMB. | `smb_cache` |

## Language

| Row | What it does | Key |
| --- | --- | --- |
| Language | The menu language. See [LANGUAGES.md](LANGUAGES.md). | `language_text` |
| OSD Defaults *(Modify)* | The language, aspect ratio and video mode games see from the console settings. | `$CustomLanguage*`, `$OSD*` (global game config) |

## Network

Rows under a protocol appear only while that protocol is selected. See [HTTP.md](HTTP.md) for
HTTP and [RETROACHIEVEMENTS.md](RETROACHIEVEMENTS.md) for the RA rows.

| Row | What it does | Key |
| --- | --- | --- |
| Protocol | SMB, UDPFS, UDPBD or HTTP. | `network_protocol`, `net_protocol_pick` |
| Access | UDPFS only: read-only or read/write. | `udpfs_access` |
| SMB Version | SMB only: SMBv1 or SMB2. | `smb_dialect` |
| Advanced Options | Unlocks Ethernet Link Mode and the SMB port. Not saved. | |
| Ethernet Link Mode | Auto or a fixed speed and duplex. | `eth_linkmode` *(net)* |
| IP Address Type | DHCP or static. | `ps2_ip_use_dhcp` *(net)* |
| IP Address, Mask, Gateway, DNS Server | The console's static address. | `ps2_ip_addr`, `ps2_netmask`, `ps2_gateway`, `ps2_dns` *(net)* |
| Address Type | SMB server: IP address or NetBIOS name. | `smb_share_use_nbns` *(net)* |
| Address | The server's IP address or NetBIOS name. | `smb_ip`, `smb_share_nb_addr` *(net)* |
| Port | SMB port (Advanced Options). | `smb_port` *(net)* |
| Share, User, Password | The share and its login. | `smb_share`, `smb_user`, `smb_pass` *(net)* |
| HTTP server, HTTP port, HTTP base path | HTTP only: the catalogue server. | `http_ip`, `http_port`, `http_base_path` *(net)* |
| Test HTTP server *(button)* | Fetches the catalogue once and reports the result. | |
| RA Mode, RA companion IP, RetroAchievements telemetry, RetroAchievements badges, RA mark in game list, Caduceus experimental cards | RetroAchievements builds only. | `ra_mode`, `ra_host_ip`, `ra_telemetry`, `ra_badges`, `ra_badge_suffix`, `ra_experimental_cards` |
| OK / Reconnect | OK applies; Reconnect restarts the network connection with the new values. | |

POPSTARTER's own network files are edited from **PS Emulation Settings → POPSTARTER Network
Settings**.

## Interface

| Row | What it does | Key |
| --- | --- | --- |
| PS2/PS1 Game Display | Both (L3 switches), Mixed, PS2 or PS1 on each device page. See [VCD.md](VCD.md). | `default_game_view` |
| Applications Display | How the Applications page lists apps. | `apps_display` |
| Show [PS1]/[PS2] Labels | Marks each row with its system. | `game_type_labels` |
| Show CFG Titles in Game Lists | Uses the title from a game's CFG file. | `cfg_titles_in_lists` |
| List Title and Description | Theme, On or Off. | `list_cfg_text` |
| PS1 Duplicates | A PS1 game found for both cores: Both, Ember or POPSTARTER. | `ps1_duplicates` |
| Video Mode | The menu's video mode (not the games'; that is GSM Defaults on Game Launching). | `vmode` |
| Theme | The menu theme. See [INTERFACE.md](INTERFACE.md). | `theme` |
| Theme View | Default (the theme's own), List, Coverflow (3), Coverflow (5), PSBBN Flow or Grid; holding L3 cycles it too. | `theme_view` |
| Library | Pages or All Games. Same setting as Game Sources → All Games List. | `all_games` |
| Alternate Background | The theme's `alt=` background. | `theme_alt_bg` |
| Boot Theme Wait | Seconds the start-up screen waits for a saved theme's drive. | `boot_theme_wait` |
| Font Size | Small, Default or Large. | `font_size` |
| Button Glyphs | The theme's glyphs or a built-in set. | `glyph_set` |
| Coverflow Settings *(Modify)* | Center Scale, Animation Speed, Dim Side Covers, Grid Layout. | `coverflow_scale`, `coverflow_anim`, `coverflow_dim`, `grid_layout` |
| Artwork Settings *(Modify)* | Cover Art, Disc Artwork, Logo Artwork, Background Art, 3D Save Icons, Cover Art .tar Archive, Art Delay. | `enable_coverart`, `enable_discart`, `enable_logoart`, `enable_bgart`, `enable_save_icons`, `enable_art_tar`, `art_delay` |
| Colors *(Modify)* | Text, selected, dialog, game title, background and plasma blend colours. | `text_color`, `sel_text_color`, `ui_text_color`, `title_color`, `bg_color`, `plasma_blend_color` |
| Notifications | Shows short notices (device found, saved). | `enable_notifications` |
| Sort Games | Off, A to Z or Last played. | `autosort` |
| Automatic Refresh | Re-reads game lists while the menu is open. | `autorefresh` |
| Widescreen | 16:9 menu. | `wide_screen` |
| H-POS, V-POS | Moves the picture (kept per video mode). | `xoff`, `yoff` |
| Overscan | Shrinks the picture to fit the TV. | `overscan` |
| Show GameID Barcode (Pixel FX) | Sends the game ID to Pixel FX scalers: All, POPSTARTER only, PS2 only or Off. | `apply_gameid` (PS2), `popstarter_retrogem_gameid` (PS1) |

## Game Launching

| Row | What it does | Key |
| --- | --- | --- |
| PS2 Logo | Shows the PS2 logo before a game. | `ps2logo` |
| App Handoff Path | Legacy (`massN:`) or typed (`usb0:`, `ata0:`) paths passed to apps. | `app_handoff_path` |
| Create VMC on First Launch | Creates a virtual memory card the first time a game starts. | `auto_create_vmc` |
| In-Game Menu (Beta) | The in-game reset menu (`IGR_MENU=1` builds). See [IGR.md](IGR.md). | `igr_menu` |
| Default Loader Core | OPL core or Neutrino for games with no choice of their own. | `default_core` |
| GSM Defaults (All Games) *(Modify)* | The video mode games launch in unless a game has its own. See [GSM.md](GSM.md). | `$EnableGSM`, `$GSMVMode`, `$GSMXOffset`, `$GSMYOffset`, `$GSMFIELDFix` (global game config) |
| Neutrino Path | Where `neutrino.elf` is. See [NEUTRINO.md](NEUTRINO.md). | `neutrino_path` |
| Neutrino Video | Default video mode for Neutrino games. | `neutrino_video_default` |
| Neutrino GSM Compatibility | Default GSM type for Neutrino games (when Neutrino Video is on). | `neutrino_gsm_comp_default` |
| Auto Boot ELF (-elf), Show Launch Arguments | Neutrino launch options. | `neutrino_elf_arg`, `neutrino_show_args` |
| Neutrino Advanced Arguments *(Modify)* | Extra Neutrino arguments for every game. | `neutrino_args` |

## PS Emulation Settings

| Row | What it does | Key |
| --- | --- | --- |
| POPSTARTER.ELF Path | A full path to POPSTARTER.ELF, or empty for the default places. | `popstarter_path` |
| PS1 RetroGEM Game ID | Sends the PS1 game ID to RetroGEM. Same value as the PS1 half of Show GameID Barcode on Interface. | `popstarter_retrogem_gameid` |
| Ember Display Mode, Ember Timing, Ember Dithering, Ember Shading, Ember Controller | Global Ember defaults. A game's own Ember settings can override Timing, Dithering, Shading and Controller; Display Mode is global only. | `ember_display_mode`, `ember_timing`, `ember_dither`, `ember_shading`, `ember_controller` |
| VCD BDMA Apply on Launch, BDMA Source, BDMA Mode, USB BDMA Driver | Which exFAT driver POPSTARTER gets. See [VCD.md](VCD.md) §5. | `bdma_apply_launch`, `bdma_source`, `vcd_usb_bdma` |
| VCD Games List Settings *(Modify)* | Hide the PS1 game ID, first disc only, list `PP.<ID>.POPS` HDD partitions. | `vcd_hide_gameid`, `vcd_first_disc_only`, `vcd_show_pp_pops` |
| POPSTARTER Network Settings *(Modify)* | POPSTARTER's own `IPCONFIG.DAT` and `SMBCONFIG.DAT` on the memory card. See [VCD.md](VCD.md) §6. | (POPSTARTER's files) |

## Controller Settings

| Row | What it does | Key |
| --- | --- | --- |
| Scrolling Speed | Menu scroll speed. | `scrolling` |
| Select Button | Swaps Cross and Circle. | `swap_select_btn` |
| Analog X-Axis Sensitivity, Analog Y-Axis Sensitivity | Analog stick speed in the menu. | `x_sensitivity`, `y_sensitivity` |
| Controller Vibration in Menus | Vibration in the menu. | `enable_rumble` |
| Controller Emulation, Controller Macros *(Modify)* | Global PADEMU and macro settings (`PADEMU=1` builds). See [PADEMU.md](PADEMU.md). | `$PadEmuSettings`, `$PadMacroSettings` (global game config) |

## Audio Settings

| Row | What it does | Key |
| --- | --- | --- |
| Sound Effects, Boot Sound, Background Music | Turns each on. | `enable_sfx`, `enable_boot_snd`, `enable_bgm` |
| Sound Effects Volume, Boot Sound Volume, Background Music Volume | 0 to 100. | `sfx_volume`, `boot_snd_volume`, `bgm_volume` |
| Default Theme Music | The music file to play. | `default_bgm_path` |

## Per-game settings

Opened from a game's Triangle menu, saved in the game's own CFG file. Most of them have a
**Settings Mode** row that picks between the game's own values and the global ones above.

* **Game settings**: loader core, DMA mode, DNAS ID, Console i.LINK ID ([CONSOLE-ILINK-ID.md](CONSOLE-ILINK-ID.md)),
  alternate start-up, parental lock, compatibility modes, Neutrino arguments and video.
* **GSM**, **Cheats**, **Controller Emulation**, **Controller Macros**, **OSD settings**,
  **Ember settings** and **VMC** each have their own page.

## Moved rows (for anyone used to an older build)

Each of these used to be reachable from two pages and is now on one:

| Row | Now only on |
| --- | --- |
| GSM Defaults (All Games) | Game Launching (was also on General & System and Interface) |
| VCD Games List Settings | PS Emulation Settings (was also on Interface) |
| POPSTARTER Network Settings | PS Emulation Settings (was also on Network) |
| Video Mode | Interface (a second copy in a separate display table is gone) |

No key changed: a configuration saved by an older build loads unchanged.
