#ifndef __TEXTSHAPE_H
#define __TEXTSHAPE_H

// Text the font drawer can lay out: Arabic and Persian joined and right to left, and where lines may break in CJK,
// Thai and Lao text (ported from akilluminati47/RIPPS2 build 104).

#include <stdint.h>

// The character at s: its code point in *cp and the bytes it takes (a broken one: its first byte, 1; the end: 0)
int txtNext(const char *s, uint32_t *cp);
// c written at out[at] as UTF-8: the new end, or -1 when it does not fit in size bytes with the terminator
int txtPut(char *out, int at, int size, uint32_t c);
// A zero-width mark some translations carry (ZWSP, ZWNJ, ZWJ, LRM, RLM, BOM): it draws nothing
int txtZeroWidth(uint32_t c);
// Does s (len bytes) hold CJK, Thai or Lao letters, which write no spaces between words?
int txtNoSpaceScript(const char *s, int len);
// Could a line break go before the character at s, start being where the word began? Only between CJK, Thai or Lao
// letters, never inside a character, before closing punctuation or a mark that belongs to the letter before it.
int txtBreakAt(const char *start, const char *s);
// A right-to-left letter (Hebrew, Arabic and their presentation forms; not the Arabic digits)?
int txtRtlChar(uint32_t c);
// Arabic and Persian: in with its Arabic letters joined (their presentation forms, lam-alef as one) and, with
// reorder, each line laid out right to left for drawing from the left (Latin words and numbers keep their order,
// brackets turn round), in out (size bytes). NULL when in has no right-to-left letters (draw it as it is) or the
// result does not fit. One caller at a time: the font system calls it under its lock.
const char *txtShape(const char *in, char *out, int size, int reorder);

#endif
