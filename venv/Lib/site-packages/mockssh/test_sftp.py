import os
import stat

from pytest import fixture, raises


def files_equal(fname1, fname2):
    if os.stat(fname1).st_size == os.stat(fname2).st_size:
        with open(fname1, "rb") as f1, open(fname2, "rb") as f2:
            if f1.read() == f2.read():
                return True


def test_put(sftp_client, tmp_dir):
    target_fname = os.path.join(tmp_dir, "foo")
    sftp_client.put(__file__, target_fname, confirm=True)
    assert files_equal(target_fname, __file__)


def test_get(sftp_client, tmp_dir):
    target_fname = os.path.join(tmp_dir, "foo")
    sftp_client.get(__file__, target_fname)
    assert files_equal(target_fname, __file__)


def test_symlink(sftp_client, tmp_dir):
    foo = os.path.join(tmp_dir, "foo")
    bar = os.path.join(tmp_dir, "bar")

    open(foo, "w").write("foo")
    sftp_client.symlink(foo, bar)
    assert os.path.islink(bar)


def test_lstat(sftp_client, tmp_dir):
    foo = os.path.join(tmp_dir, "foo")
    bar = os.path.join(tmp_dir, "bar")

    open(foo, "w").write("foo")
    os.symlink(foo, bar)

    stat = sftp_client.stat(bar)
    lstat = sftp_client.lstat(bar)
    assert stat.st_size != lstat.st_size


def test_listdir(sftp_client, tmp_dir):
    open(os.path.join(tmp_dir, "foo"), "w").write("foo")
    open(os.path.join(tmp_dir, "bar"), "w").write("bar")

    dir_contents = sftp_client.listdir(tmp_dir)
    assert sorted(dir_contents) == ["bar", "foo"]

    with raises(IOError):
        sftp_client.listdir("/123_no_dir")


def test_remove(sftp_client, tmp_dir):
    test_file = os.path.join(tmp_dir, "x")
    open(test_file, "w").write("X")
    sftp_client.remove(test_file)
    assert not os.listdir(tmp_dir)


def test_unlink(sftp_client, tmp_dir):
    test_file = os.path.join(tmp_dir, "x")
    open(test_file, "w").write("X")
    sftp_client.unlink(test_file)
    assert not os.listdir(tmp_dir)


def test_mkdir(sftp_client, tmp_dir):
    target_dir = os.path.join(tmp_dir, "foo")
    sftp_client.mkdir(target_dir)
    assert os.path.exists(target_dir)
    assert os.path.isdir(target_dir)


def test_rmdir(sftp_client, tmp_dir):
    target_dir = os.path.join(tmp_dir, "foo")
    os.makedirs(target_dir)
    sftp_client.rmdir(target_dir)
    assert not os.path.exists(target_dir)
    assert not os.path.isdir(target_dir)


def test_chmod(sftp_client, tmp_dir):
    test_file = os.path.join(tmp_dir, "foo")
    open(test_file, "w").write("X")
    sftp_client.chmod(test_file, 0o600)
    st = os.stat(test_file)
    check_bits = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO
    assert st.st_mode & check_bits == 0o600


def test_chown(sftp_client, tmp_dir):
    test_file = os.path.join(tmp_dir, "foo")
    open(test_file, "w").write("X")
    # test process probably can't change file uids
    # so just test if no exception occurs
    sftp_client.chown(test_file, os.getuid(), os.getgid())


def test_handle_stat(sftp_client, tmp_dir):
    test_file = os.path.join(tmp_dir, "foo")
    open(test_file, "w").write("X")

    handle = sftp_client.open(test_file)
    # only test if no exception occurs
    handle.stat()


def test_rename(sftp_client, tmp_dir):
    test_file = os.path.join(tmp_dir, "foo")
    open(test_file, "w").write("X")
    renamed_test_file = os.path.join(tmp_dir, "bar")
    sftp_client.rename(test_file, renamed_test_file)
    assert os.path.exists(renamed_test_file)
    assert not os.path.exists(test_file)


@fixture(params=[("listdir_attr", "/"),
                 ("readlink", "/etc"),
                 ("truncate", "/etc/passwd", 0),
                 ("utime", "/", (0, 0))])
def unsupported_call(request):
    return request.param


def _test_sftp_unsupported_calls(server, unsupported_call):
    for uid in server.users:
        with server.client(uid) as c:
            meth, args = unsupported_call[0], unsupported_call[1:]
            sftp = c.open_sftp()
            with raises(IOError) as exc:
                getattr(sftp, meth)(*args)
            assert str(exc.value) == "Operation unsupported"
