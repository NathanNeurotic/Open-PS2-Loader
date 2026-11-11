/*
 * Replacement for libsmb2/lib/errors.c on the IOP.
 *
 * Upstream's nterror_to_str() carries a ~30 KB table of NT_STATUS names that
 * smb2man only ever prints into smb2_set_error() messages. On the IOP that
 * table decides whether smb2man.irx fits into the memory left after the
 * network and BDM stacks are loaded, so it is replaced by a hex formatter.
 * nterror_to_errno() below is upstream's mapping, copied as is, clang-formatted (LGPL-2.1,
 * Copyright (C) 2016 by Ronnie Sahlberg <ronniesahlberg@gmail.com>).
 */

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <sysclib.h>

#include "compat.h"
#include "smb2.h"
#include "libsmb2.h"

const char *nterror_to_str(uint32_t status)
{
    static char buf[16];

    sprintf(buf, "0x%08x", (unsigned int)status);
    return buf;
}

int nterror_to_errno(uint32_t status)
{
    switch (status) {
        case SMB2_STATUS_SUCCESS:
        case SMB2_STATUS_END_OF_FILE:
            return 0;
        case SMB2_STATUS_PENDING:
            return EAGAIN;
        case SMB2_STATUS_SHUTDOWN:
            return -(int)SMB2_STATUS_SHUTDOWN;
        case SMB2_STATUS_NO_SUCH_FILE:
        case SMB2_STATUS_NO_SUCH_DEVICE:
        case SMB2_STATUS_BAD_NETWORK_NAME:
        case SMB2_STATUS_OBJECT_NAME_NOT_FOUND:
        case SMB2_STATUS_OBJECT_PATH_INVALID:
        case SMB2_STATUS_OBJECT_PATH_NOT_FOUND:
        case SMB2_STATUS_OBJECT_PATH_SYNTAX_BAD:
        case SMB2_STATUS_DFS_EXIT_PATH_FOUND:
        case SMB2_STATUS_DELETE_PENDING:
        case SMB2_STATUS_REDIRECTOR_NOT_STARTED:
        case SMB2_STATUS_NOT_FOUND:
            return ENOENT;
        case SMB2_STATUS_SMB_BAD_FID:
        case SMB2_STATUS_INVALID_HANDLE:
        case SMB2_STATUS_OBJECT_TYPE_MISMATCH:
        case SMB2_STATUS_PORT_DISCONNECTED:
        case SMB2_STATUS_INVALID_PORT_HANDLE:
        case SMB2_STATUS_HANDLE_NOT_CLOSABLE:
            return EBADF;
        case SMB2_STATUS_MORE_PROCESSING_REQUIRED:
            return EAGAIN;
        case SMB2_STATUS_ACCESS_DENIED:
        case SMB2_STATUS_NETWORK_ACCESS_DENIED:
        case SMB2_STATUS_ACCOUNT_RESTRICTION:
        case SMB2_STATUS_INVALID_LOGON_HOURS:
        case SMB2_STATUS_PASSWORD_EXPIRED:
        case SMB2_STATUS_ACCOUNT_DISABLED:
            return EACCES;
        case SMB2_STATUS_INVALID_LOCK_SEQUENCE:
        case SMB2_STATUS_INVALID_VIEW_SIZE:
        case SMB2_STATUS_ALREADY_COMMITTED:
        case SMB2_STATUS_PORT_CONNECTION_REFUSED:
        case SMB2_STATUS_THREAD_IS_TERMINATING:
        case SMB2_STATUS_PRIVILEGE_NOT_HELD:
        case SMB2_STATUS_FILE_IS_A_DIRECTORY:
        case SMB2_STATUS_FILE_RENAMED:
        case SMB2_STATUS_PROCESS_IS_TERMINATING:
        case SMB2_STATUS_CANNOT_DELETE:
        case SMB2_STATUS_FILE_DELETED:
            return EPERM;
        case SMB2_STATUS_DIRECTORY_NOT_EMPTY:
            return ENOTEMPTY;
        case SMB2_STATUS_NO_MORE_FILES:
            return ENODATA;
        case SMB2_STATUS_LOGON_FAILURE:
            return ECONNREFUSED;
        case SMB2_STATUS_NOT_A_DIRECTORY:
            return ENOTDIR;
        case SMB2_STATUS_NOT_IMPLEMENTED:
        case SMB2_STATUS_INVALID_DEVICE_REQUEST:
        case SMB2_STATUS_ILLEGAL_FUNCTION:
        case SMB2_STATUS_INVALID_PARAMETER:
        case SMB2_STATUS_NOT_SUPPORTED:
        case SMB2_STATUS_NOT_A_REPARSE_POINT:
        case SMB2_STATUS_IO_REPARSE_TAG_INVALID:
        case SMB2_STATUS_IO_REPARSE_TAG_MISMATCH:
        case SMB2_STATUS_IO_REPARSE_DATA_INVALID:
            return EINVAL;
        case SMB2_STATUS_IO_REPARSE_TAG_NOT_HANDLED:
        case SMB2_STATUS_REPARSE_POINT_NOT_RESOLVED:
            return ENOLINK;
        case SMB2_STATUS_DIRECTORY_IS_A_REPARSE_POINT:
            return EISDIR;
        case SMB2_STATUS_STOPPED_ON_SYMLINK:
            return ENOLINK;
        case SMB2_STATUS_TOO_MANY_OPENED_FILES:
            return EMFILE;
        case SMB2_STATUS_SECTION_TOO_BIG:
        case SMB2_STATUS_TOO_MANY_PAGING_FILES:
        case SMB2_STATUS_INSUFF_SERVER_RESOURCES:
            return ENOMEM;
        case SMB2_STATUS_NOT_SAME_DEVICE:
            return EXDEV;
        case SMB2_STATUS_SHARING_VIOLATION:
            return ETXTBSY;
        case SMB2_STATUS_FILE_LOCK_CONFLICT:
        case SMB2_STATUS_LOCK_NOT_GRANTED:
            return EDEADLK;
        case SMB2_STATUS_OBJECT_NAME_COLLISION:
            return EEXIST;
        case SMB2_STATUS_PIPE_DISCONNECTED:
            return EPIPE;
        case SMB2_STATUS_MEDIA_WRITE_PROTECTED:
            return EROFS;
        case SMB2_STATUS_NO_MEDIA_IN_DEVICE:
            return ENODEV;
        case SMB2_STATUS_DATA_ERROR:
        case SMB2_STATUS_CRC_ERROR:
        case SMB2_STATUS_DEVICE_DATA_ERROR:
        case SMB2_STATUS_IO_DEVICE_ERROR:
            return EIO;
        case SMB2_STATUS_DISK_FULL:
            return ENOSPC;
        case SMB2_STATUS_CANCELLED:
        case SMB2_STATUS_FILE_CLOSED:
        case SMB2_STATUS_VOLUME_DISMOUNTED:
        case SMB2_STATUS_CONNECTION_DISCONNECTED:
        case SMB2_STATUS_CONNECTION_RESET:
        case SMB2_STATUS_CONNECTION_INVALID:
        case SMB2_STATUS_CONNECTION_ABORTED:
        case SMB2_STATUS_NETWORK_NAME_DELETED:
        case SMB2_STATUS_INVALID_NETWORK_RESPONSE:
            /* 
                ** We return this errno with the intention that caller can
                ** retry when any of these are received.
                */
            return ENETRESET;
        case SMB2_STATUS_PATH_NOT_COVERED:
            /* 
                ** We do not have an errno which can be an equivalent of this
                ** NT_STATUS code. To handle this, return a code which will not
                ** be used as we are operating over a network.
                */
            return ENOEXEC;
        case SMB2_STATUS_IO_TIMEOUT:
            return ETIMEDOUT;
        case SMB2_STATUS_INSUFFICIENT_RESOURCES:
            return EBUSY;
        case SMB2_STATUS_INTERNAL_ERROR:
            /* Fall through. */
        default:
            return EIO;
    }
}
