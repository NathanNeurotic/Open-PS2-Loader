"""Exercise the production attribute renderer's optional Title fallback on the host."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/themes.c').read_text(encoding='utf-8')
start = source.index('static void drawAttributeText(')
end = source.index('\nstatic void initAttributeText(', start)
renderer = source[start:end]
program = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#define CONFIG_ITEM_NAME "#Name"
#define SIZING_WRAP 1
#define DISPLAY_NEVER 0
#define DISPLAY_ALWAYS 1
#define _STR_SIZE 0
struct menu_list { int unused; };
struct submenu_list { int unused; };
typedef struct { int uid; const char *title, *name, *genre; } config_set_t;
typedef struct {
    int currentConfigId, sizingMode, displayMode;
    char *value, *currentValue, *wrappedValue, *alias;
} mutable_text_t;
typedef struct theme_element { void *extended; int font, width; } theme_element;
typedef theme_element theme_element_t;
static char drawn[300];
static const char *_l(int id) { (void)id; return "Size"; }
static int configGetStr(config_set_t *c, const char *key, const char **out)
{
    const char *v = !strcmp(key, "Title") ? c->title :
                    !strcmp(key, "#Name") ? c->name : c->genre;
    if (!v) return 0;
    *out = v;
    return 1;
}
static void fntFitString(int font, char *value, int width)
{
    (void)font; (void)width;
    char *space = strchr(value, ' ');
    if (space) *space = '\n';
}
static void thmDrawElemText(theme_element_t *elem, int mode, const char *s, int flag)
{
    (void)elem; (void)mode; (void)flag;
    snprintf(drawn, sizeof(drawn), "%s", s);
}
@RENDERER@
int main(void)
{
    struct submenu_list item = {0};
    mutable_text_t text = {.value="Title", .alias="Title: ", .displayMode=DISPLAY_ALWAYS};
    theme_element_t elem = {.extended=&text, .width=200};
    config_set_t a = {1, NULL, "Library Name", NULL};
    drawAttributeText(NULL, &item, &a, &elem);
    assert(!strcmp(drawn, "Title: Library Name"));
    config_set_t b = {2, "Explicit Title", "Other Name", NULL};
    drawAttributeText(NULL, &item, &b, &elem);
    assert(!strcmp(drawn, "Title: Explicit Title"));
    config_set_t c = {3, "", "Empty Title Fallback", NULL};
    text.sizingMode = SIZING_WRAP;
    drawAttributeText(NULL, &item, &c, &elem);
    assert(!strcmp(drawn, "Title: Empty\nTitle Fallback"));
    assert(!strcmp(c.name, "Empty Title Fallback"));
    assert(!strcmp(c.title, ""));
    text.value = "Genre"; text.alias = "Genre: ";
    config_set_t d = {4, NULL, "Never Invent Genre", NULL};
    drawAttributeText(NULL, &item, &d, &elem);
    assert(!strcmp(drawn, "Genre: "));
    drawn[0] = 0;
    drawAttributeText(NULL, NULL, &d, &elem);
    assert(!drawn[0]);
    free(text.wrappedValue);
    puts("metadata: title fallback, explicit title, empty title, private wrapping, selection changes, missing genre and empty list pass");
    return 0;
}
'''.replace('@RENDERER@', renderer)
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    cfile = path / 'metadata.c'
    exe = path / ('metadata.exe' if sys.platform == 'win32' else 'metadata')
    cfile.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', str(cfile), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
