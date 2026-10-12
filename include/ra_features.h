#ifndef RIPTOPL_RA_FEATURES_H
#define RIPTOPL_RA_FEATURES_H

/* One RA release supports both clients. Cards are compiled into RA builds,
   but require the explicit, default-Off Caduceus experimental cards setting.
   An idle GIF DMA channel does not prove ownership of the game's GS transfer
   state: cards may flicker or freeze games. This compile-time switch can still
   exclude the renderer path in developer builds; it is not the user setting. */
#ifndef RA_EXPERIMENTAL_CARD_DMA
#define RA_EXPERIMENTAL_CARD_DMA 1
#endif

#endif
