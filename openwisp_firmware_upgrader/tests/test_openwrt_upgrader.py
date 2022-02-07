import io
from contextlib import redirect_stderr, redirect_stdout
from time import sleep
from unittest.mock import patch

from billiard import Queue
from celery.exceptions import Retry
from django.test import TransactionTestCase
from django.utils import timezone
from paramiko.ssh_exception import NoValidConnectionsError, SSHException

from openwisp_controller.connection.connectors.exceptions import CommandFailedException
from openwisp_controller.connection.connectors.openwrt.ssh import (
    OpenWrt as OpenWrtSshConnector,
)
from openwisp_controller.connection.tests.utils import SshServer

from ..swapper import load_model
from ..tasks import upgrade_firmware
from ..upgraders.openwrt import OpenWrt
from .base import TestUpgraderMixin, spy_mock

DeviceFirmware = load_model('DeviceFirmware')

TEST_CHECKSUM = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


def mocked_exec_upgrade_not_needed(command, exit_codes=None):
    cases = {
        f'test -f {OpenWrt.CHECKSUM_FILE}': ['', 0],
        f'cat {OpenWrt.CHECKSUM_FILE}': [TEST_CHECKSUM, 0],
    }
    return cases[command]


def mocked_exec_upgrade_success(command, exit_codes=None, timeout=None):
    defaults = ['', 0]
    _sysupgrade = OpenWrt._SYSUPGRADE
    _checksum = OpenWrt.CHECKSUM_FILE
    cases = {
        'rm -rf /tmp/opkg-lists/': defaults,
        'sync && echo 3 > /proc/sys/vm/drop_caches': defaults,
        'cat /proc/meminfo | grep MemAvailable': ['MemAvailable:      66984 kB', 0],
        f'test -f {_checksum}': defaults,
        f'cat {_checksum}': defaults,
        'mkdir -p /etc/openwisp': defaults,
        f'echo {TEST_CHECKSUM} > {_checksum}': defaults,
        f'{_sysupgrade} --help': ['--test', 1],
        'rm /etc/openwisp/checksum 2> /dev/null': defaults,
        # used in memory check tests
        'test -f /sbin/wifi && /sbin/wifi down': defaults,
        'test -f /sbin/wifi && /sbin/wifi up': defaults,
    }
    if command.startswith(f'{_sysupgrade} --test /tmp/openwrt-'):
        return defaults
    if command.startswith(f'{_sysupgrade} -v -c /tmp/openwrt-'):
        return [
            (
                'Image metadata not found\n'
                'Reading partition table from bootdisk...\n'
                'Reading partition table from image...\n'
            ),
            -1,
        ]
    try:
        return cases[command]
    except KeyError:
        raise CommandFailedException()


def mocked_sysupgrade_failure(command, exit_codes=None, timeout=None):
    if command.startswith(f'{OpenWrt._SYSUPGRADE} -v -c '):
        raise CommandFailedException(
            "Invalid image type\nImage check 'platform_check_image' failed."
        )
    return mocked_exec_upgrade_success(command, exit_codes=None, timeout=None)


def mocked_sysupgrade_test_failure(command, exit_codes=None, timeout=None):
    if command.startswith(f'{OpenWrt._SYSUPGRADE} --test'):
        raise CommandFailedException('Invalid image type')
    return mocked_exec_upgrade_success(command, exit_codes=None, timeout=None)


def mocked_exec_upgrade_memory_success(
    command, exit_codes=None, timeout=None, raise_unexpected_exit=None
):
    global _mock_memory_success_called
    if command.startswith('test -f /etc/init.d/'):
        return ['', 0]
    elif (
        not _mock_memory_success_called
        and command == 'cat /proc/meminfo | grep MemAvailable'
    ):
        _mock_memory_success_called = True
        return ['MemAvailable:      0 kB', 0]
    return mocked_exec_upgrade_success(command, exit_codes=None, timeout=None)


def mocked_exec_upgrade_memory_success_legacy(
    command, exit_codes=None, timeout=None, raise_unexpected_exit=None
):
    global _mock_memory_success_called
    if command == 'cat /proc/meminfo | grep MemAvailable':
        return ['', 1]
    elif command == 'cat /proc/meminfo | grep MemFree':
        if not _mock_memory_success_called:
            _mock_memory_success_called = True
            return ['MemFree:      0 kB', 0]
        else:
            return ['MemFree:      66984 kB', 0]
    return mocked_exec_upgrade_memory_success(
        command, exit_codes, timeout, raise_unexpected_exit
    )


def mocked_exec_upgrade_memory_failure(
    command, exit_codes=None, timeout=None, raise_unexpected_exit=None
):
    if command == 'cat /proc/meminfo | grep MemAvailable':
        return ['MemAvailable:      0 kB', 0]
    return mocked_exec_upgrade_memory_success(command, exit_codes=None, timeout=None)


def mocked_exec_upgrade_memory_aborted(
    command, exit_codes=None, timeout=None, raise_unexpected_exit=None
):
    if command.startswith(f'{OpenWrt._SYSUPGRADE} --test'):
        raise CommandFailedException('Invalid image type')
    return mocked_exec_upgrade_memory_success(command, exit_codes=None, timeout=None)


def connect_fail_on_write_checksum_pre_action(*args, **kwargs):
    if connect_fail_on_write_checksum.mock.call_count >= 2:
        raise NoValidConnectionsError(errors={'127.0.0.1': 'mocked error'})


_mock_memory_success_called = False
connect_fail_on_write_checksum = spy_mock(
    OpenWrt.connect, connect_fail_on_write_checksum_pre_action
)


class TestOpenwrtUpgrader(TestUpgraderMixin, TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock_ssh_server = SshServer(
            {'root': cls._TEST_RSA_PRIVATE_KEY_PATH}
        ).__enter__()
        cls.ssh_server.port = cls.mock_ssh_server.port

    @classmethod
    def tearDownClass(cls):
        cls.mock_ssh_server.__exit__()

    def _trigger_upgrade(self, upgrade=True, exception=None):
        ckey = self._create_credentials_with_key(port=self.ssh_server.port)
        device_conn = self._create_device_connection(credentials=ckey)
        build = self._create_build(organization=device_conn.device.organization)
        image = self._create_firmware_image(build=build)
        output = io.StringIO()
        task_signature = None
        try:
            with redirect_stdout(output):
                device_fw = self._create_device_firmware(
                    image=image,
                    device=device_conn.device,
                    device_connection=False,
                    upgrade=upgrade,
                )
        except Exception as e:
            if exception and isinstance(e, exception):
                device_fw = DeviceFirmware.objects.order_by('created').last()
                if hasattr(e, 'sig'):
                    task_signature = e.sig
            else:
                raise e
        else:
            if exception:
                self.fail(f'{exception.__name__} not raised')

        if not upgrade:
            return device_fw, device_conn, output

        device_conn.refresh_from_db()
        device_fw.refresh_from_db()
        self.assertEqual(device_fw.image.upgradeoperation_set.count(), 1)
        upgrade_op = device_fw.image.upgradeoperation_set.first()
        return device_fw, device_conn, upgrade_op, output, task_signature

    @patch('scp.SCPClient.putfo')
    @patch.object(
        OpenWrt,
        'exec_command',
        side_effect=mocked_sysupgrade_test_failure,
    )
    def test_image_test_failed(self, exec_command, putfo):
        device_fw, device_conn, upgrade_op, output, _ = self._trigger_upgrade()
        self.assertTrue(device_conn.is_working)
        self.assertEqual(exec_command.call_count, 6)
        putfo.assert_called_once()
        self.assertEqual(upgrade_op.status, 'aborted')
        self.assertIn('Invalid image type', upgrade_op.log)
        self.assertFalse(device_fw.installed)

    @patch.object(
        OpenWrt,
        'exec_command',
        side_effect=mocked_exec_upgrade_not_needed,
    )
    def test_upgrade_not_needed(self, mocked):
        device_fw, device_conn, upgrade_op, output, _ = self._trigger_upgrade()
        self.assertTrue(device_conn.is_working)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(upgrade_op.status, 'success')
        self.assertIn('upgrade not needed', upgrade_op.log)
        self.assertTrue(device_fw.installed)

    @patch('scp.SCPClient.putfo')
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch('billiard.Process.is_alive', return_value=True)
    @patch.object(OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_success)
    def test_upgrade_success(self, exec_command, is_alive, putfo):
        device_fw, device_conn, upgrade_op, output, _ = self._trigger_upgrade()
        self.assertTrue(device_conn.is_working)
        # should be called 6 times but 1 time is
        # executed in a subprocess and not caught by mock
        self.assertEqual(upgrade_op.status, 'success')
        self.assertEqual(exec_command.call_count, 8)
        self.assertEqual(putfo.call_count, 1)
        self.assertEqual(is_alive.call_count, 1)
        lines = [
            'Image checksum file found',
            'Checksum different, proceeding',
            'Upgrade operation in progress',
            'Trying to reconnect to device at 127.0.0.1 (attempt n.1)',
            'Connected! Writing checksum',
            'Upgrade completed successfully',
        ]
        for line in lines:
            self.assertIn(line, upgrade_op.log)
        self.assertTrue(device_fw.installed)

    @patch.object(OpenWrt, '_call_reflash_command')
    @patch('scp.SCPClient.putfo')
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch.object(OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_success)
    @patch.object(OpenWrt, 'connect', connect_fail_on_write_checksum)
    def test_cant_reconnect_on_write_checksum(self, exec_command, putfo, *args):
        start_time = timezone.now()
        with redirect_stderr(io.StringIO()):
            device_fw, device_conn, upgrade_op, output, _ = self._trigger_upgrade()
        self.assertEqual(exec_command.call_count, 6)
        self.assertEqual(putfo.call_count, 1)
        self.assertEqual(connect_fail_on_write_checksum.mock.call_count, 11)
        self.assertEqual(upgrade_op.status, 'failed')
        lines = [
            'Checksum different, proceeding',
            'Upgrade operation in progress',
            'Trying to reconnect to device at 127.0.0.1 (attempt n.1)',
            'Device not reachable yet',
            'Giving up, device not reachable',
        ]
        for line in lines:
            self.assertIn(line, upgrade_op.log)
        self.assertTrue(device_fw.installed)
        self.assertFalse(device_conn.is_working)
        self.assertIn('Giving up', device_conn.failure_reason)
        self.assertTrue(device_conn.last_attempt > start_time)

    @patch('scp.SCPClient.putfo')
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch.object(upgrade_firmware, 'max_retries', 1)
    @patch.object(OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_success)
    @patch.object(
        OpenWrtSshConnector,
        'connect',
        side_effect=SSHException('Connection failed'),
    )
    def test_connection_failure(self, connect, exec_command, putfo):
        (
            device_fw,
            device_conn,
            upgrade_op,
            output,
            task_signature,
        ) = self._trigger_upgrade(exception=Retry)
        # retry once for testing purposes
        task_signature.replace().delay()
        upgrade_op.refresh_from_db()
        self.assertFalse(device_conn.is_working)
        self.assertEqual(exec_command.call_count, 0)
        self.assertEqual(putfo.call_count, 0)
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(upgrade_op.status, 'failed')
        lines = [
            'Detected a recoverable failure: Connection failed.',
            'The upgrade operation will be retried soon.',
            'Max retries exceeded. Upgrade failed: Connection failed.',
        ]
        for line in lines:
            self.assertIn(line, upgrade_op.log)
        self.assertFalse(device_fw.installed)

    @patch.object(
        OpenWrtSshConnector,
        'upload',
        side_effect=SSHException('Invalid packet blocking'),
    )
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch.object(upgrade_firmware, 'max_retries', 1)
    @patch.object(OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_success)
    def test_upload_failure(self, exec_command, upload):
        (
            device_fw,
            device_conn,
            upgrade_op,
            output,
            task_signature,
        ) = self._trigger_upgrade(exception=Retry)
        task_signature.replace().delay()
        upgrade_op.refresh_from_db()
        self.assertTrue(device_conn.is_working)
        self.assertEqual(upload.call_count, 2)
        self.assertEqual(upgrade_op.status, 'failed')
        lines = [
            'Image checksum file found',
            'Checksum different, proceeding',
            'Detected a recoverable failure: Invalid packet blocking.',
            'The upgrade operation will be retried soon.',
            'Max retries exceeded. Upgrade failed: Invalid packet blocking.',
        ]
        for line in lines:
            self.assertIn(line, upgrade_op.log)
        self.assertFalse(device_fw.installed)

    @patch.object(OpenWrt, '_call_reflash_command')
    @patch('scp.SCPClient.putfo')
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch('billiard.Process.is_alive', return_value=True)
    @patch.object(OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_success)
    def test_device_ip_changed_after_reflash(self, exec_command, alive, putfo, *args):
        device_fw, device_conn, output = self._trigger_upgrade(upgrade=False)

        def connect_pre_action(upgrader):
            if connect_mocked.mock.call_count == 1:
                return
            # simulate case in which IP address of the device
            # has changed after a few attempts
            if connect_mocked.mock.call_count == 3:
                device_model = upgrader.connection.device.__class__
                # instantiate a new object to avoid influencing
                # the correct replication of the bug case
                device = device_model.objects.get(pk=upgrader.connection.device.pk)
                device.management_ip = '192.168.99.254'
                device.save()
            if connect_mocked.mock.call_count > 1:
                raise NoValidConnectionsError(errors={'127.0.0.1': 'mocked error'})

        connect_mocked = spy_mock(OpenWrt.connect, connect_pre_action)

        with patch.object(OpenWrt, 'connect', connect_mocked):
            with redirect_stderr(io.StringIO()):
                device_fw.save()

        self.assertEqual(device_fw.image.upgradeoperation_set.count(), 1)
        upgrade_op = device_fw.image.upgradeoperation_set.first()
        device_fw.refresh_from_db()

        self.assertEqual(exec_command.call_count, 6)
        self.assertEqual(putfo.call_count, 1)
        self.assertEqual(upgrade_op.status, 'failed')
        lines = [
            'Trying to reconnect to device at 127.0.0.1 (attempt n.1)',
            'Trying to reconnect to device at 127.0.0.1 (attempt n.2)',
            'Trying to reconnect to device at 192.168.99.254, 127.0.0.1 (attempt n.3)',
            'Giving up, device not reachable',
        ]
        for line in lines:
            self.assertIn(line, upgrade_op.log)

    @patch('scp.SCPClient.putfo')
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch('billiard.Process.is_alive', return_value=True)
    @patch.object(OpenWrt, 'exec_command', side_effect=mocked_sysupgrade_failure)
    def test_sysupgrade_failure(self, exec_command, is_alive, putfo):
        device_fw, device_conn, upgrade_op, output, _ = self._trigger_upgrade()
        self.assertTrue(device_conn.is_working)
        self.assertEqual(putfo.call_count, 1)
        self.assertEqual(is_alive.call_count, 0)
        self.assertEqual(upgrade_op.status, 'failed')
        lines = [
            'Image checksum file found',
            'Checksum different, proceeding',
            'Upgrade operation in progress',
            'Invalid image type',
            "Image check 'platform_check_image' failed.",
        ]
        for line in lines:
            self.assertIn(line, upgrade_op.log)
        self.assertFalse(device_fw.installed)

    def test_openwrt_settings(self):
        self.assertEqual(OpenWrt.RECONNECT_DELAY, 150)
        self.assertEqual(OpenWrt.RECONNECT_RETRY_DELAY, 30)
        self.assertEqual(OpenWrt.RECONNECT_MAX_RETRIES, 10)
        self.assertEqual(OpenWrt.UPGRADE_TIMEOUT, 80)

    @patch('scp.SCPClient.putfo')
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch('billiard.Process.is_alive', return_value=True)
    @patch.object(OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_success)
    def test_get_upgrade_command(self, exec_command, is_alive, putfo):
        device_fw, device_conn, upgrade_op, output, _ = self._trigger_upgrade()
        upgrader = OpenWrt(upgrade_op, device_conn)
        upgrade_command = upgrader.get_upgrade_command('/tmp/test.bin')
        self.assertEqual(upgrade_command, '/sbin/sysupgrade -v -c /tmp/test.bin')

    @patch('scp.SCPClient.putfo')
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch('billiard.Process.is_alive', return_value=True)
    def test_call_reflash_command(self, is_alive, putfo):
        with patch.object(
            OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_success
        ) as exec_command:
            device_fw, device_conn, upgrade_op, output, _ = self._trigger_upgrade()

        upgrader = OpenWrt(upgrade_op, device_conn)
        path = '/tmp/openwrt-image.bin'
        command = f'/sbin/sysupgrade -v -c {path}'

        with self.subTest('success'):
            with patch.object(
                OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_success
            ) as exec_command:
                failure_queue = Queue()
                OpenWrt._call_reflash_command(
                    upgrader, path, upgrader.UPGRADE_TIMEOUT, failure_queue
                )
                self.assertEqual(exec_command.call_count, 2)
                self.assertEqual(
                    exec_command.call_args_list[0][0],
                    ('rm /etc/openwisp/checksum 2> /dev/null',),
                )
                self.assertEqual(
                    exec_command.call_args_list[0][1], dict(exit_codes=[0, -1, 1])
                )
                self.assertEqual(exec_command.call_args_list[1][0], (command,))
                self.assertEqual(
                    exec_command.call_args_list[1][1],
                    dict(timeout=upgrader.UPGRADE_TIMEOUT, exit_codes=[0, -1]),
                )
                self.assertTrue(failure_queue.empty())
                failure_queue.close()

        with self.subTest('failure'):
            with patch.object(
                OpenWrt, 'exec_command', side_effect=mocked_sysupgrade_failure
            ) as exec_command:
                failure_queue = Queue()
                OpenWrt._call_reflash_command(
                    upgrader, path, upgrader.UPGRADE_TIMEOUT, failure_queue
                )
                self.assertEqual(exec_command.call_count, 2)
                sleep(0.05)
                self.assertFalse(failure_queue.empty())
                exception = failure_queue.get()
                failure_queue.close()
                self.assertIsInstance(exception, CommandFailedException)
                self.assertEqual(
                    str(exception),
                    "Invalid image type\nImage check 'platform_check_image' failed.",
                )

    @patch('scp.SCPClient.putfo')
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch('billiard.Process.is_alive', return_value=True)
    @patch.object(
        OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_memory_success
    )
    def test_upgrade_free_memory_success(self, exec_command, is_alive, putfo):
        global _mock_memory_success_called
        _mock_memory_success_called = False
        device_fw, device_conn, upgrade_op, output, _ = self._trigger_upgrade()
        self.assertTrue(device_conn.is_working)
        self.assertEqual(upgrade_op.status, 'success')
        self.assertEqual(exec_command.call_count, 20)
        self.assertEqual(
            exec_command.call_args_list[5][0][0],
            'test -f /etc/init.d/uhttpd && /etc/init.d/uhttpd stop',
        )
        self.assertEqual(
            exec_command.call_args_list[12][0][0],
            'test -f /etc/init.d/log && /etc/init.d/log stop',
        )
        self.assertEqual(
            exec_command.call_args_list[13][0][0],
            'test -f /sbin/wifi && /sbin/wifi down',
        )
        self.assertEqual(putfo.call_count, 1)
        self.assertEqual(is_alive.call_count, 1)
        lines = [
            'Image checksum file found',
            'Checksum different, proceeding',
            'The image size (0 MiB) is greater than the available memory on the system (0 MiB).',
            'For this reason the upgrade procedure will try to free up',
            'Enough available memory was freed up on the system (65.41 MiB)!',
            'Upgrade operation in progress',
            'Trying to reconnect to device at 127.0.0.1 (attempt n.1)',
            'Connected! Writing checksum',
            'Upgrade completed successfully',
        ]
        for line in lines:
            self.assertIn(line, upgrade_op.log)
        self.assertTrue(device_fw.installed)

    @patch('scp.SCPClient.putfo')
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch('billiard.Process.is_alive', return_value=True)
    @patch.object(
        OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_memory_success_legacy
    )
    def test_upgrade_free_memory_success_legacy(self, exec_command, is_alive, putfo):
        global _mock_memory_success_called
        _mock_memory_success_called = False
        device_fw, device_conn, upgrade_op, output, _ = self._trigger_upgrade()
        self.assertTrue(device_conn.is_working)
        self.assertEqual(upgrade_op.status, 'success')
        self.assertEqual(exec_command.call_count, 22)
        self.assertEqual(
            exec_command.call_args_list[4][0][0],
            'cat /proc/meminfo | grep MemAvailable',
        )
        self.assertEqual(
            exec_command.call_args_list[5][0][0], 'cat /proc/meminfo | grep MemFree'
        )
        self.assertEqual(putfo.call_count, 1)
        self.assertEqual(is_alive.call_count, 1)
        lines = [
            'Image checksum file found',
            'Checksum different, proceeding',
            'The image size (0 MiB) is greater than the available memory on the system (0 MiB).',
            'For this reason the upgrade procedure will try to free up',
            'Enough available memory was freed up on the system (65.41 MiB)!',
            'Upgrade operation in progress',
            'Trying to reconnect to device at 127.0.0.1 (attempt n.1)',
            'Connected! Writing checksum',
            'Upgrade completed successfully',
        ]
        for line in lines:
            self.assertIn(line, upgrade_op.log)
        self.assertTrue(device_fw.installed)

    @patch('scp.SCPClient.putfo')
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch('billiard.Process.is_alive', return_value=True)
    @patch.object(
        OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_memory_failure
    )
    def test_upgrade_free_memory_failure(self, exec_command, is_alive, putfo):
        device_fw, device_conn, upgrade_op, output, _ = self._trigger_upgrade()
        self.assertTrue(device_conn.is_working)
        self.assertEqual(upgrade_op.status, 'aborted')
        self.assertEqual(exec_command.call_count, 26)
        self.assertEqual(
            exec_command.call_args_list[17][0][0],
            'test -f /etc/init.d/uhttpd && /etc/init.d/uhttpd start',
        )
        self.assertEqual(
            exec_command.call_args_list[24][0][0],
            'test -f /etc/init.d/log && /etc/init.d/log start',
        )
        self.assertEqual(
            exec_command.call_args_list[25][0][0],
            'test -f /sbin/wifi && /sbin/wifi up',
        )
        self.assertEqual(putfo.call_count, 0)
        self.assertEqual(is_alive.call_count, 0)
        lines = [
            'Image checksum file found',
            'Checksum different, proceeding',
            'The image size (0 MiB) is greater than the available memory on the system (0 MiB).',
            'For this reason the upgrade procedure will try to free up',
            'There is still not enough available memory on the system (0 MiB)',
            'Starting non critical services again...',
            'Non critical services started, aborting upgrade',
        ]
        for line in lines:
            self.assertIn(line, upgrade_op.log)
        self.assertFalse(device_fw.installed)

    test_upgrade_free_memory_aborted = None

    @patch('scp.SCPClient.putfo')
    @patch.object(OpenWrt, 'RECONNECT_DELAY', 0)
    @patch.object(OpenWrt, 'RECONNECT_RETRY_DELAY', 0)
    @patch('billiard.Process.is_alive', return_value=True)
    @patch.object(
        OpenWrt, 'exec_command', side_effect=mocked_exec_upgrade_memory_aborted
    )
    def test_upgrade_free_memory_aborted(self, exec_command, is_alive, putfo):
        global _mock_memory_success_called
        _mock_memory_success_called = False
        device_fw, device_conn, upgrade_op, output, _ = self._trigger_upgrade()
        self.assertTrue(device_conn.is_working)
        self.assertEqual(upgrade_op.status, 'aborted')
        self.assertEqual(exec_command.call_count, 27)
        self.assertEqual(
            exec_command.call_args_list[18][0][0],
            'test -f /etc/init.d/uhttpd && /etc/init.d/uhttpd start',
        )
        self.assertEqual(
            exec_command.call_args_list[25][0][0],
            'test -f /etc/init.d/log && /etc/init.d/log start',
        )
        self.assertEqual(
            exec_command.call_args_list[26][0][0],
            'test -f /sbin/wifi && /sbin/wifi up',
        )
        self.assertEqual(putfo.call_count, 1)
        self.assertEqual(is_alive.call_count, 0)
        lines = [
            'Image checksum file found',
            'Checksum different, proceeding',
            'The image size (0 MiB) is greater than the available memory on the system (0 MiB).',
            'For this reason the upgrade procedure will try to free up',
            'Enough available memory was freed up on the system (65.41 MiB)!',
            'Invalid image type',
            'Starting non critical services again...',
        ]
        for line in lines:
            self.assertIn(line, upgrade_op.log)
        self.assertFalse(device_fw.installed)
