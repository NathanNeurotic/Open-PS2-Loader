#include <assert.h>
#include <stdio.h>
#include <string.h>

/* the code points of s, into cps; their count */
static int cps(const char *s, uint32_t *out, int max)
{
    int n = 0;
    while (*s && n < max) {
        int b = txtNext(s, &out[n]);
        assert(b > 0);
        s += b;
        n++;
    }
    return n;
}

static void expect(const char *in, int reorder, const uint32_t *want, int wantCount)
{
    static char out[512];
    uint32_t got[64];
    const char *r = txtShape(in, out, sizeof(out), reorder);
    int n, i;
    assert(r == out);
    n = cps(r, got, 64);
    if (n != wantCount) {
        fprintf(stderr, "count %d != %d for '%s'\n", n, wantCount, in);
        assert(0);
    }
    for (i = 0; i < n; i++) {
        if (got[i] != want[i]) {
            fprintf(stderr, "'%s' reorder %d: at %d U+%04X, want U+%04X\n", in, reorder, i, (unsigned)got[i], (unsigned)want[i]);
            assert(0);
        }
    }
}

#define EXPECT(in, reorder, ...)                                    \
    do {                                                            \
        static const uint32_t w[] = {__VA_ARGS__};                  \
        expect(in, reorder, w, (int)(sizeof(w) / sizeof(w[0])));    \
    } while (0)

int main(void)
{
    char out[64], tiny[4];
    char big[4200];
    int i;

    /* no right-to-left letters: drawn as they are */
    assert(txtShape("abc 123", out, sizeof(out), 1) == NULL);
    assert(txtShape("\xd9\xa1\xd9\xa2", out, sizeof(out), 1) == NULL); /* Arabic digits read as numbers */

    /* salam: seen initial, lam-alef ligature after a joining letter, meem alone after the alef */
    EXPECT("\xd8\xb3\xd9\x84\xd8\xa7\xd9\x85", 0, 0xFEB3, 0xFEFC, 0xFEE1);
    EXPECT("\xd8\xb3\xd9\x84\xd8\xa7\xd9\x85", 1, 0xFEE1, 0xFEFC, 0xFEB3);
    /* beh beh: initial then final; laid out right to left */
    EXPECT("\xd8\xa8\xd8\xa8", 0, 0xFE91, 0xFE90);
    EXPECT("\xd8\xa8\xd8\xa8", 1, 0xFE90, 0xFE91);
    /* beh beh beh: the middle one is medial */
    EXPECT("\xd8\xa8\xd8\xa8\xd8\xa8", 0, 0xFE91, 0xFE92, 0xFE90);
    /* lam-alef on its own */
    EXPECT("\xd9\x84\xd8\xa7", 0, 0xFEFB);
    /* ZWNJ stops the join and goes */
    EXPECT("\xd8\xa8\xe2\x80\x8c\xd8\xa8", 0, 0xFE8F, 0xFE8F);
    /* a bracket on the right-to-left side turns round, so it still reads as brackets */
    EXPECT("(\xd8\xa8)", 1, '(', 0xFE8F, ')');
    /* Latin words and numbers keep their order inside the line */
    EXPECT("\xd8\xa8 abc 12", 1, 'a', 'b', 'c', ' ', '1', '2', ' ', 0xFE8F);
    /* 50% stays together */
    EXPECT("\xd8\xa8 50%", 1, '5', '0', '%', ' ', 0xFE8F);
    /* each line on its own: a Latin line after it is left alone */
    EXPECT("\xd8\xa8\nab", 1, 0xFE8F, '\n', 'a', 'b');
    /* a vowel mark stays after its letter, where it is drawn back over it */
    EXPECT("\xd8\xa8\xd9\x8e\xd8\xa8", 1, 0xFE90, 0xFE91, 0x064E);

    /* too small for the result, or too long to lay out: drawn as it is */
    assert(txtShape("\xd8\xa8\xd8\xa8", tiny, sizeof(tiny), 1) == NULL);
    for (i = 0; i < 2100; i++) {
        big[2 * i] = (char)0xd8;
        big[2 * i + 1] = (char)0xa8;
    }
    big[4200 - 1] = '\0';
    big[4200 - 2] = 'a';
    assert(txtShape(big, out, sizeof(out), 1) == NULL);

    /* zero-width marks */
    assert(txtZeroWidth(0x200B) && txtZeroWidth(0x200F) && txtZeroWidth(0xFEFF) && !txtZeroWidth('a') && !txtZeroWidth(0x2010));
    assert(txtRtlChar(0x05D0) && txtRtlChar(0x0628) && !txtRtlChar(0x0661) && !txtRtlChar('a'));

    /* line breaks */
    {
        const char *jp = "\xe6\x97\xa5\xe6\x9c\xac\xe3\x80\x82"; /* nihon + ideographic full stop */
        assert(txtNoSpaceScript(jp, (int)strlen(jp)));
        assert(!txtNoSpaceScript("hello", 5));
        assert(txtBreakAt(jp, jp + 3));      /* between two ideographs */
        assert(!txtBreakAt(jp, jp + 6));     /* never before the full stop */
        assert(!txtBreakAt(jp, jp + 4));     /* never inside a character */
        assert(!txtBreakAt(jp, jp));         /* never at the start */
        assert(!txtBreakAt("abcd", "abcd" + 2));
    }
    {
        const char *q = "\xe3\x80\x8c\xe6\x97\xa5"; /* opening corner bracket, then an ideograph */
        assert(!txtBreakAt(q, q + 3));
    }
    {
        const char *th = "\xe0\xb8\x81\xe0\xb8\xb2\xe0\xb8\x82"; /* ko kai, sara aa, kho khai */
        assert(txtNoSpaceScript(th, (int)strlen(th)));
        assert(!txtBreakAt(th, th + 3)); /* sara aa belongs to the letter before */
        assert(txtBreakAt(th, th + 6));  /* between letters */
        const char *th2 = "\xe0\xb9\x80\xe0\xb8\x81"; /* sara e, written ahead of its letter */
        assert(!txtBreakAt(th2, th2 + 3));
    }

    /* txtPut never writes past the end */
    assert(txtPut(tiny, 0, sizeof(tiny), 0x65E5) == 3);
    assert(txtPut(tiny, 1, sizeof(tiny), 0x65E5) == -1);
    puts("textshape ok");
    return 0;
}
/* ---- wrap ---- */
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void wrapExpect(const char *in, int innerW, int outSize, const char *want, int wantLines)
{
    char out[256];
    int lines = fntWrapText(0, in, innerW, out, outSize);
    if (strcmp(out, want) != 0 || lines != wantLines) {
        fprintf(stderr, "wrap '%s' at %d: got '%s' (%d lines), want '%s' (%d)\n", in, innerW, out, lines, want, wantLines);
        assert(0);
    }
}

int main(void)
{
    wrapExpect("hello world", 60, 256, "hello\nworld", 2);
    wrapExpect("hello   world", 200, 256, "hello world", 1);
    wrapExpect("a\nb", 200, 256, "a\nb", 2);
    wrapExpect("abcdefghij", 50, 256, "abcde\nfghij", 2);                             /* a word wider than the line */
    wrapExpect("\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\xe3\x81\xa7\xe3\x81\x99", 40, 256, /* nihongo desu: breaks between letters */
               "\xe6\x97\xa5\xe6\x9c\xac\n\xe8\xaa\x9e\xe3\x81\xa7\n\xe3\x81\x99", 3);
    wrapExpect("\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\xe3\x80\x82", 60, 256, /* never before the full stop: it stays on the line */
               "\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\xe3\x80\x82", 1);
    wrapExpect("OK \xe6\x97\xa5\xe6\x9c\xac", 1000, 256, "OK \xe6\x97\xa5\xe6\x9c\xac", 1); /* CJK goes on after a Latin word */
    wrapExpect("\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e", 1000, 6, "\xe6\x97\xa5", 1);          /* a full buffer never cuts a character */
    {
        char out[8];
        assert(fntWrapText(0, NULL, 10, out, sizeof(out)) == 0 && out[0] == '\0');
    }
    puts("wrap ok");
    return 0;
}
