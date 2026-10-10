#ifndef RIPTOPL_RA_FEATURES_H
#define RIPTOPL_RA_FEATURES_H

/* One RA release supports both xeRAbora and Caduceus via runtime Settings.
   The framebuffer IMAGE renderer is *not* hardware safe: a free GIF DMA channel
   does not prove a game's outstanding GS IMAGE transfer has completed.
   Leave the experimental renderer excluded from production launch paths so
   Caduceus uses the same safe gold-pulse notification as xeRAbora.
   This flag is solely for controlled developer experiments, NOT a new release
   flavour or a user-visible opt-in. A runtime display setting can be added
   when a safe GS ownership/synchronization scheme is proven. */
#ifndef RA_EXPERIMENTAL_CARD_DMA
#define RA_EXPERIMENTAL_CARD_DMA 0
#endif

#endif
