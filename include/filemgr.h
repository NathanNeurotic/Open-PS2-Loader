#ifndef __OPL_FILEMGR_H
#define __OPL_FILEMGR_H

// File Manager (main menu), after RIPPS2's Memory Files browser (akilluminati47/RIPPS2, ripps2files.c).
// This half is plain file I/O (opendir / stat / open / read / write / mkdir / rename / remove), with no GUI,
// so the host test runs it against a real folder. The dialog is in guifilemgr.c.

#define FM_NAME 128 // a name in a folder, with its NUL

typedef struct
{
    char name[FM_NAME];
    int isDir;
    unsigned long long size; // bytes; 0 for a folder
} fm_entry_t;

enum {
    FM_OK = 0,
    FM_ERR_EXISTS, // the target name is already there
    FM_ERR_INSIDE, // a folder copied or moved into itself
    FM_ERR_NAME,   // empty, ".", "..", or has a slash, backslash or colon
    FM_ERR_READ,   // a source could not be opened or read
    FM_ERR_WRITE,  // a target could not be made or written (full, read-only, pulled)
    FM_ERR_DELETE, // something could not be removed
    FM_ERR_DEEP,   // folders nested deeper than FM_DEPTH
    FM_ERR_MEMORY, // no buffer
};

#define FM_DEPTH 16 // folder levels a copy or delete goes down

// What the last operation failed with (FM_OK after a success)
int fmError(void);

// The separator a path on this device uses: '\\' for an SMB share, '/' for everything else
char fmSep(const char *path);

// dir + name, with one separator between ("mass0:/" + "A" -> "mass0:/A"); 0 if it does not fit
int fmJoin(char *out, int size, const char *dir, const char *name);

// The folder above path ("mass0:/A/B" -> "mass0:/A", "mass0:/A" -> "mass0:/"); 0 at a device root
int fmParent(char *out, int size, const char *path);

// The last name in a path
const char *fmBaseName(const char *path);

// 1 if name can be made in a folder (1 to FM_NAME - 1 bytes, not "." or "..", no '/', '\\' or ':')
int fmNameOk(const char *name);

// A folder's entries, folders first, each group by name (case ignored), "." and ".." left out.
// Returns how many (up to max), or -1 if the folder cannot be opened.
int fmList(const char *dir, fm_entry_t *out, int max);

// 1 if path names something that is there
int fmExists(const char *path);

// Bytes in a file, or in everything under a folder; *count gets the number of files (may be NULL)
unsigned long long fmTreeSize(const char *path, int isDir, int *count);

// Called while copying with the bytes done so far and the bytes in all; may be NULL
typedef void (*fm_progress_t)(const char *name, unsigned long long done, unsigned long long total);

// Copies src (a file, or a folder and everything in it) into the folder dstDir under the same name. Refuses a
// name already there (FM_ERR_EXISTS) and a folder into itself. A file that fails part way is removed, so a
// cut-short copy is never left looking whole. 1 on success.
int fmCopy(const char *src, int isDir, const char *dstDir, fm_progress_t progress);

// Moves src into dstDir: a rename on the same device, else a copy and, only once the whole copy is made, the
// source removed. 1 on success.
int fmMove(const char *src, int isDir, const char *dstDir, fm_progress_t progress);

// Removes a file, or a folder and everything in it. 1 on success.
int fmDelete(const char *path, int isDir);

// Renames path to newName in the same folder. 1 on success.
int fmRename(const char *path, const char *newName);

// Makes the folder dir/name. 1 on success.
int fmMakeDir(const char *dir, const char *name);

// "12 KB" / "3.4 MB" / "1.2 GB" from bytes
void fmSizeText(unsigned long long bytes, char *out, int size);

#endif
