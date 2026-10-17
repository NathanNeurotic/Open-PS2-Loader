static void putc_b(char **p, char *end, char c)
{
    if (*p < end) *(*p)++ = c;
}
static void number(char **p, char *end, unsigned long n, unsigned int base,
                   unsigned int width, int zero, int negative, int upper)
{
    char digits[32];
    const char *hex = upper ? "0123456789ABCDEF" : "0123456789abcdef";
    unsigned int len = 0, total;
    do { digits[len++] = hex[n % base]; n /= base; } while (n && len < 32);
    total = len + (negative ? 1 : 0);
    if (negative && zero) putc_b(p, end, '-');
    while (width > total) { putc_b(p, end, zero ? '0' : ' '); --width; }
    if (negative && !zero) putc_b(p, end, '-');
    while (len) putc_b(p, end, digits[--len]);
}
static unsigned int format_line(char *out, unsigned int size,
                                const char *fmt, va_list ap)
{
    char *p = out, *end = out + size - 1;
    while (*fmt && p < end) {
        unsigned int width = 0;
        int zero = 0, islong = 0;
        char kind;
        if (*fmt != '%') { putc_b(&p, end, *fmt++); continue; }
        ++fmt;
        if (*fmt == '%') { putc_b(&p, end, *fmt++); continue; }
        if (*fmt == '0') { zero = 1; ++fmt; }
        while (*fmt >= '0' && *fmt <= '9') {
            width = width * 10 + (*fmt++ - '0');
            if (width > 32) width = 32;
        }
        if (*fmt == 'l') { islong = 1; ++fmt; }
        kind = *fmt;
        if (!kind) break;
        ++fmt;
        if (kind == 's') {
            const char *s = va_arg(ap, const char *);
            if (!s) s = "(null)";
            while (*s && p < end) putc_b(&p, end, *s++);
        } else if (kind == 'c') {
            putc_b(&p, end, (char)va_arg(ap, int));
        } else if (kind == 'd' || kind == 'i') {
            long n = islong ? va_arg(ap, long) : va_arg(ap, int);
            unsigned long mag = n < 0 ? 0UL - (unsigned long)n : (unsigned long)n;
            number(&p, end, mag, 10, width, zero, n < 0, 0);
        } else if (kind == 'u' || kind == 'x' || kind == 'X') {
            unsigned long n = islong ? va_arg(ap, unsigned long) : va_arg(ap, unsigned int);
            number(&p, end, n, kind == 'u' ? 10 : 16, width, zero, 0, kind == 'X');
        } else {
            putc_b(&p, end, '%'); putc_b(&p, end, kind);
        }
    }
    *p = 0;
    return (unsigned int)(p - out);
}
