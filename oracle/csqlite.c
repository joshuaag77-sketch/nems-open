/* The C half of EIA's fsqlite (the Flibs SQLite interface), for Linux.
 *
 * NEMS ships fsqlite.f90 and this layer only as Windows objects (libfsqlite.a holds COFF
 * files), which Linux cannot link. This is a small re-implementation of the 19 entry points
 * fsqlite.f90 binds to, written from its interface blocks. Handles are SQLite pointers stored
 * in the Fortran INTEGER(2) arrays; Fortran strings are fixed length and blank padded; every
 * integer that is not VALUE comes by reference.
 *
 * Build: gcc -c -O2 -fPIC csqlite.c ; link with -lsqlite3 (apt install libsqlite3-dev).
 */
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <sqlite3.h>

static void put_handle(void *dst, void *p) { memcpy(dst, &p, sizeof p); }
static void *get_handle(const void *src) { void *p; memcpy(&p, src, sizeof p); return p; }

/* copy a C string into a Fortran string of len characters: truncate, pad with blanks */
static void to_fortran(char *dst, int len, const char *src)
{
    int n = src ? (int)strlen(src) : 0;
    if (n > len) n = len;
    if (n) memcpy(dst, src, n);
    if (len > n) memset(dst + n, ' ', len - n);
}

int sqlite3_open_c(char *fname, int *handle, int len_fname)
{
    sqlite3 *db = NULL;
    int rc = sqlite3_open(fname, &db);
    put_handle(handle, db);
    return rc;
}

int sqlite3_close_c(int *handle) { return sqlite3_close((sqlite3 *)get_handle(handle)); }

int sqlite3_do_c(int *handle, char *command, char *errmsg, int len_command, int len_errmsg)
{
    char *err = NULL;
    int rc = sqlite3_exec((sqlite3 *)get_handle(handle), command, NULL, NULL, &err);
    to_fortran(errmsg, len_errmsg, err);
    if (err) sqlite3_free(err);
    return rc;
}

void sqlite3_errmsg_c(int *handle, char *errmsg, int len_errmsg)
{
    to_fortran(errmsg, len_errmsg, sqlite3_errmsg((sqlite3 *)get_handle(handle)));
}

int sqlite3_prepare_c(int *db, char *command, int *stmt, int len_command)
{
    sqlite3_stmt *st = NULL;
    int rc = sqlite3_prepare((sqlite3 *)get_handle(db), command, -1, &st, NULL);
    put_handle(stmt, st);
    return rc;
}

void sqlite3_finalize_c(int *stmt) { sqlite3_finalize((sqlite3_stmt *)get_handle(stmt)); }
void sqlite3_reset_c(int *stmt) { sqlite3_reset((sqlite3_stmt *)get_handle(stmt)); }
void sqlite3_step_c(int *stmt, int *completion) { *completion = sqlite3_step((sqlite3_stmt *)get_handle(stmt)); }

int sqlite3_bind_int_c(int *stmt, int *colidx, int *value)
{
    return sqlite3_bind_int((sqlite3_stmt *)get_handle(stmt), *colidx, *value);
}

int sqlite3_bind_double_c(int *stmt, int *colidx, double *value)
{
    return sqlite3_bind_double((sqlite3_stmt *)get_handle(stmt), *colidx, *value);
}

int sqlite3_bind_null_c(int *stmt, int *colidx)
{
    return sqlite3_bind_null((sqlite3_stmt *)get_handle(stmt), *colidx);
}

int sqlite3_bind_text_c(int *stmt, int *colidx, char *value, int len_value)
{
    return sqlite3_bind_text((sqlite3_stmt *)get_handle(stmt), *colidx, value, len_value, SQLITE_TRANSIENT);
}

void sqlite3_column_count_c(int *stmt, int *count) { *count = sqlite3_column_count((sqlite3_stmt *)get_handle(stmt)); }

int sqlite3_column_int_c(int *stmt, int *colidx, int *value)
{
    *value = sqlite3_column_int((sqlite3_stmt *)get_handle(stmt), *colidx);
    return 0;
}

int sqlite3_column_double_c(int *stmt, int *colidx, double *value)
{
    *value = sqlite3_column_double((sqlite3_stmt *)get_handle(stmt), *colidx);
    return 0;
}

/* the Fortran side turns NUL padding into blanks (stringtof) */
int sqlite3_column_text_c(int *stmt, int *colidx, char *value, int len_value)
{
    const unsigned char *t = sqlite3_column_text((sqlite3_stmt *)get_handle(stmt), *colidx);
    memset(value, 0, len_value);
    if (t) strncpy(value, (const char *)t, len_value);
    return 0;
}

void sqlite3_column_name_type_c(int *stmt, int *colidx, char *name, char *type, int len_name, int len_type)
{
    sqlite3_stmt *st = (sqlite3_stmt *)get_handle(stmt);
    const char *n = sqlite3_column_name(st, *colidx);
    const char *t = sqlite3_column_decltype(st, *colidx);
    int i;
    memset(name, 0, len_name);
    memset(type, 0, len_type);
    if (n) strncpy(name, n, len_name);
    if (t) {
        strncpy(type, t, len_type);
        for (i = 0; i < len_type && type[i]; i++) type[i] = (char)toupper((unsigned char)type[i]);
    }
}

/* sqlite3_get_table in two steps: run the query and keep the table, then copy it out */
static char **table = NULL;

int sqlite3_get_table_1_c(int *handle, char *commandc, int *ncol, int *nrow, char *errmsg,
                          int len_commandc, int len_errmsg)
{
    char *err = NULL;
    int rc;
    if (table) { sqlite3_free_table(table); table = NULL; }
    rc = sqlite3_get_table((sqlite3 *)get_handle(handle), commandc, &table, nrow, ncol, &err);
    to_fortran(errmsg, len_errmsg, err);
    if (err) sqlite3_free(err);
    return rc;
}

void sqlite3_get_table_2_c(int *ncol, int *nrow, char *result, int len_result)
{
    int i, n = (*nrow + 1) * *ncol;     /* the header row plus the data rows */
    for (i = 0; i < n; i++)
        to_fortran(result + (size_t)i * len_result, len_result, table ? table[i] : NULL);
    if (table) { sqlite3_free_table(table); table = NULL; }
}
