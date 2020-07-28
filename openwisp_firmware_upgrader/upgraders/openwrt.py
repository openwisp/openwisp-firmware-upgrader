import os
import socket
from hashlib import sha256
from time import sleep

from billiard import Process
from paramiko.ssh_exception import NoValidConnectionsError

from openwisp_controller.connection.connectors.openwrt.ssh import OpenWrt as BaseOpenWrt

from ..exceptions import (
    ReconnectionFailed,
    RecoverableFailure,
    UpgradeAborted,
    UpgradeNotNeeded,
)
from ..settings import OPENWRT_SETTINGS


class OpenWrt(BaseOpenWrt):
    CHECKSUM_FILE = '/etc/openwisp/firmware_checksum'
    REMOTE_UPLOAD_DIR = '/tmp'
    RECONNECT_DELAY = OPENWRT_SETTINGS.get('reconnect_delay', 120)
    RECONNECT_RETRY_DELAY = OPENWRT_SETTINGS.get('reconnect_retry_delay', 20)
    RECONNECT_MAX_RETRIES = OPENWRT_SETTINGS.get('reconnect_max_retries', 15)
    UPGRADE_TIMEOUT = OPENWRT_SETTINGS.get('upgrade_timeout', 90)
    UPGRADE_COMMAND = 'sysupgrade -v -c {path}'

    log_lines = None

    def __init__(self, upgrade_operation, connection):
        super(OpenWrt, self).__init__(
            params=connection.get_params(), addresses=connection.get_addresses()
        )
        connection.set_connector(self)
        self.upgrade_operation = upgrade_operation
        self.connection = connection

    def log(self, value, save=True):
        self.upgrade_operation.log_line(value, save=save)

    def upgrade(self, image):
        self._test_connection()
        checksum = self._test_checksum(image)
        remote_path = self.get_remote_path(image)
        self.upload(image.file, remote_path)
        self._test_image(remote_path)
        self._reflash(remote_path)
        self._write_checksum(checksum)

    def _test_connection(self):
        result = self.connection.connect()
        if not result:
            raise RecoverableFailure('Connection failed')
        self.log('Connection successful, starting upgrade...')

    def upload(self, *args, **kwargs):
        try:
            super().upload(*args, **kwargs)
        except Exception as e:
            raise RecoverableFailure(str(e))

    def get_remote_path(self, image):
        # discard directory info from image name
        filename = image.name.split('/')[-1]
        return os.path.join(self.REMOTE_UPLOAD_DIR, filename)

    def get_upgrade_command(self, path):
        return self.UPGRADE_COMMAND.format(path=path)

    def _test_checksum(self, image):
        """
        prevents the upgrade if an identical checksum signature file is found on
        the device, which indicates the upgrade has already been performed previously
        """
        # calculate firmware image checksum
        checksum = sha256(image.read()).hexdigest()
        image.seek(0)
        # test for presence of firmware checksum signature file
        output, exit_code = self.exec_command(
            f'test -f {self.CHECKSUM_FILE}', exit_codes=[0, 1]
        )
        if exit_code == 0:
            self.log('Image checksum file found', save=False)
            cat = f'cat {self.CHECKSUM_FILE}'
            output, code = self.exec_command(cat)
            if checksum == output:
                message = (
                    'Firmware already upgraded previously. '
                    'Identical checksum found in the filesystem, '
                    'upgrade not needed.'
                )
                self.log(message)
                self.disconnect()
                raise UpgradeNotNeeded(message)
            else:
                self.log(
                    'Checksum different, proceeding with '
                    'the upload of the new image...'
                )
        else:
            self.log(
                'Image checksum file not found, proceeding '
                'with the upload of the new image...'
            )
        return checksum

    def _test_image(self, path):
        try:
            self.exec_command(f'sysupgrade --test {path}')
        except Exception as e:
            self.log(str(e), save=False)
            self.disconnect()
            raise UpgradeAborted()
        self.log(
            'Sysupgrade test passed successfully, '
            'proceeding with the upgrade operation...'
        )

    def _reflash(self, path):
        """
        this will execute the upgrade operation in another process
        because the SSH connection may hang indefinitely while reflashing
        and would block the program; setting a timeout to `exec_command`
        doesn't seem to take effect on some OpenWRT versions
        so at least we can stop the process using
        `subprocess.join(timeout=self.UPGRADE_TIMEOUT)`
        """
        self.disconnect()
        command = self.get_upgrade_command(path)

        def upgrade(conn, path, timeout):
            conn.connect()
            conn.exec_command(command, timeout=timeout)
            conn.disconnect()

        subprocess = Process(target=upgrade, args=[self, path, self.UPGRADE_TIMEOUT])
        subprocess.start()
        self.log('Upgrade operation in progress...')
        subprocess.join(timeout=self.UPGRADE_TIMEOUT)
        self.log(
            f'SSH connection closed, will wait {self.RECONNECT_DELAY} seconds before '
            'attempting to reconnect...'
        )
        sleep(self.RECONNECT_DELAY)
        # kill the subprocess if it has hanged
        if subprocess.is_alive():
            subprocess.terminate()
            subprocess.join()

    def _refresh_addresses(self):
        """
        reloads the device info from the DB to
        handle cases in which the IP has changed
        """
        self.connection.device.refresh_from_db()
        self.addresses = self.connection.get_addresses()

    def _write_checksum(self, checksum):
        for attempt in range(1, self.RECONNECT_MAX_RETRIES + 1):
            self._refresh_addresses()
            addresses = ', '.join(self.addresses)
            self.log(
                f'Trying to reconnect to device at {addresses} (attempt n.{attempt})...',
                save=False,
            )
            try:
                self.connect()
            except (NoValidConnectionsError, socket.timeout):
                self.log(
                    'Device not reachable yet, '
                    f'retrying in {self.RECONNECT_RETRY_DELAY} seconds...'
                )
                sleep(self.RECONNECT_RETRY_DELAY)
                continue
            self.log('Connected! Writing checksum ' f'file to {self.CHECKSUM_FILE}')
            checksum_dir = os.path.dirname(self.CHECKSUM_FILE)
            self.exec_command(f'mkdir -p {checksum_dir}')
            self.exec_command(f'echo {checksum} > {self.CHECKSUM_FILE}')
            self.disconnect()
            self.log('Upgrade completed successfully.')
            return
        # if all previous attempts failed
        raise ReconnectionFailed(
            'Giving up, device not reachable anymore after upgrade'
        )
