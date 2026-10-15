#!/usr/bin/env python3
"""Page keys use the existing carousel animation without changing paging targets."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/menusys.c').read_text(encoding='utf-8')
functions = []
for name in ('menuFirstPage', 'menuLastPage', 'menuNextPage', 'menuPrevPage'):
    start = source.index('static void ' + name + '(')
    functions.append(source[start:source.index('\n}', start) + 2])
harness = r'''
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
typedef struct node {struct node *next, *prev;} submenu_list_t;
typedef struct {int displayedItems;} items_list_t;
static items_list_t list = {1};
static struct {void *extended;} element = {&list};
static struct {int coverflow; __typeof__(element) *itemsList;} theme = {1, &element};
static __typeof__(theme) *gTheme = &theme;
static struct {submenu_list_t *current, *pagestart, *submenu;} item;
static struct {__typeof__(item) *item;} selection = {&item};
static __typeof__(selection) *selected_item = &selection;
#define SFX_CURSOR 0
static void sfxPlay(int id) {(void)id;}
static int animations, direction;
static void thmTriggerCoverflowAnim(int dir) {animations++;direction=dir;}
@FUNCTIONS@
int main(void) {
    submenu_list_t nodes[3] = {{0}};
    for (int i=0;i<3;i++) {nodes[i].prev=i ? &nodes[i-1] : NULL;nodes[i].next=i<2 ? &nodes[i+1] : NULL;}
    item.submenu=item.current=item.pagestart=&nodes[0];
    menuNextPage();assert(item.current==&nodes[1] && animations==1 && direction==1);
    menuNextPage();assert(item.current==&nodes[2] && animations==2);
    menuNextPage();assert(item.current==&nodes[0] && animations==3 && direction==1);
    menuPrevPage();assert(item.current==&nodes[2] && animations==4 && direction==-1);
    menuPrevPage();assert(item.current==&nodes[1] && animations==5);
    theme.coverflow=0;menuPrevPage();assert(item.current==&nodes[0] && animations==5);
    /* A page containing the entire list must not collapse to its last row. */
    theme.coverflow=1;list.displayedItems=4;
    menuNextPage();assert(item.current==&nodes[0] && item.pagestart==&nodes[0] && animations==5);
    item.current=item.pagestart=NULL;
    menuNextPage();menuPrevPage();assert(animations==5);
    /* One-item libraries never animate an unchanged selection. */
    nodes[0].next=NULL;item.current=item.pagestart=&nodes[0];
    menuNextPage();menuPrevPage();assert(animations==5);
    puts("PASS: page-key animation, both wraps, flat themes, short/empty/single-item lists");
}
'''.replace('@FUNCTIONS@', '\n'.join(functions))
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    c, exe = path / 'pages.c', path / 'pages.exe'
    c.write_text(harness, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
