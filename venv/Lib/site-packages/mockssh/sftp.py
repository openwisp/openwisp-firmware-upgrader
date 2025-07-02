import logging
import os

from errno import EACCES, EDQUOT, EPERM, EROFS, ENOENT, ENOTDIR

import paramiko


__all__ = [
    "SFTPServer",
]


class SFTPHandle(paramiko.SFTPHandle):

    log = logging.getLogger(__name__)

    def __init__(self, file_obj, flags=0):
        super(SFTPHandle, self).__init__(flags)
        self.file_obj = file_obj

    @property
    def readfile(self):
        return self.file_obj

    @property
    def writefile(self):
        return self.file_obj

    def stat(self):
        st = os.fstat(self.file_obj.fileno())
        return paramiko.SFTPAttributes.from_stat(st)


LOG = logging.getLogger(__name__)


def returns_sftp_error(func):

    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except OSError as err:
            LOG.debug("Error calling %s(%s, %s): %s",
                      func, args, kwargs, err, exc_info=True)
            errno = err.errno
            if errno in {EACCES, EDQUOT, EPERM, EROFS}:
                return paramiko.SFTP_PERMISSION_DENIED
            if errno in {ENOENT, ENOTDIR}:
                return paramiko.SFTP_NO_SUCH_FILE
            return paramiko.SFTP_FAILURE
        except Exception as err:
            LOG.debug("Error calling %s(%s, %s): %s",
                      func, args, kwargs, err, exc_info=True)
            return paramiko.SFTP_FAILURE

    return wrapped


class SFTPServerInterface(paramiko.SFTPServerInterface):

    log = logging.getLogger(__name__)

    def __init__(self, server, *largs, **kwargs):
        super(SFTPServerInterface, self).__init__(server, *largs, **kwargs)

    def session_started(self):
        pass

    def session_ended(self):
        pass

    @returns_sftp_error
    def open(self, path, flags, attr):
        fd = os.open(path, flags)
        self.log.debug("open(%s): fd: %d", path, fd)
        if flags & (os.O_WRONLY | os.O_RDWR):
            mode = "w"
        elif flags & (os.O_APPEND):
            mode = "a"
        else:
            mode = "r"
        mode += "b"
        self.log.debug("open(%s): Mode: %s", path, mode)
        return SFTPHandle(os.fdopen(fd, mode), flags)

    @returns_sftp_error
    def stat(self, path):
        st = os.stat(path)
        return paramiko.SFTPAttributes.from_stat(st, path)

    @returns_sftp_error
    def lstat(self, path):
        st = os.lstat(path)
        return paramiko.SFTPAttributes.from_stat(st, path)

    @returns_sftp_error
    def symlink(self, src, dest):
        try:
            os.symlink(src, dest)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

        return paramiko.SFTP_OK

    @returns_sftp_error
    def remove(self, path):
        try:
            os.remove(path)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

        return paramiko.SFTP_OK

    @returns_sftp_error
    def mkdir(self, path, attrs):
        mode = getattr(attrs, 'st_mode', 0o777)
        try:
            os.mkdir(path, mode)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

        return paramiko.SFTP_OK

    @returns_sftp_error
    def rmdir(self, path):
        try:
            os.rmdir(path)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

        return paramiko.SFTP_OK

    @returns_sftp_error
    def chattr(self, path, attrs):
        if attrs.st_mode is not None:
            try:
                os.chmod(path, attrs.st_mode)
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)

        if attrs.st_uid is not None:
            try:
                os.chown(path, attrs.st_uid, attrs.st_gid)
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)

        return paramiko.SFTP_OK

    @returns_sftp_error
    def rename(self, src, dst):
        try:
            os.rename(src, dst)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

        return paramiko.SFTP_OK

    @returns_sftp_error
    def list_folder(self, path):
        """Looks up folder contents of `path.`"""
        # Inspired by https://github.com/rspivak/sftpserver/blob/0.3/src/sftpserver/stub_sftp.py#L70
        try:
            folder_contents = []
            for f in os.listdir(path):
                attr = paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(path, f)))
                attr.filename = f
                folder_contents.append(attr)
            return folder_contents
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)


class SFTPServer(paramiko.SFTPServer):

    def __init__(self, channel, name, server, sftp_si=SFTPServerInterface,
                 *largs, **kwargs):
        kwargs["sftp_si"] = SFTPServerInterface
        super(SFTPServer, self).__init__(channel, name, server, *largs,
                                         **kwargs)
