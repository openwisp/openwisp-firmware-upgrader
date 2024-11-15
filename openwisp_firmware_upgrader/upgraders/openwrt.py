import os
import re
from hashlib import sha256
from time import sleep

import jsonschema
from billiard import Process, Queue
from django.utils.translation import gettext_lazy as _

from openwisp_controller.connection.exceptions import NoWorkingDeviceConnectionError

from ..exceptions import (
    FirmwareUpgradeOptionsException,
    ReconnectionFailed,
    RecoverableFailure,
    UpgradeAborted,
    UpgradeNotNeeded,
)
from ..settings import OPENWRT_SETTINGS


class OpenWrt(object):
    CHECKSUM_FILE = '/etc/openwisp/firmware_checksum'
    REMOTE_UPLOAD_DIR = '/tmp'
    RECONNECT_DELAY = OPENWRT_SETTINGS.get('reconnect_delay', 180)
    RECONNECT_RETRY_DELAY = OPENWRT_SETTINGS.get('reconnect_retry_delay', 20)
    RECONNECT_MAX_RETRIES = OPENWRT_SETTINGS.get('reconnect_max_retries', 35)
    UPGRADE_TIMEOUT = OPENWRT_SETTINGS.get('upgrade_timeout', 90)
    UPGRADE_COMMAND = '{sysupgrade} -v {flags} {path}'
    # path to sysupgrade command
    _SYSUPGRADE = '/sbin/sysupgrade'
    SCHEMA = {
        'type': 'object',
        'properties': {
            'c': {
                'type': 'boolean',
                'title': _('Attempt to preserve all changed files in /etc/ (-c)'),
                'format': 'checkbox',
                'default': True,
            },
            'o': {
                'type': 'boolean',
                'title': _(
                    'Attempt to preserve all changed files in /, except those from '
                    'packages but including changed confs. (-o)'
                ),
                'format': 'checkbox',
            },
            'n': {
                'type': 'boolean',
                'title': _('Do not save configuration over reflash (-n)'),
                'format': 'checkbox',
            },
            'u': {
                'type': 'boolean',
                'title': _(
                    'Skip from backup files that are equal to those in /rom (-u)'
                ),
                'format': 'checkbox',
            },
            'p': {
                'type': 'boolean',
                'title': _(
                    'Do not attempt to restore the partition table after flash. (-p)'
                ),
                'format': 'checkbox',
            },
            'k': {
                'type': 'boolean',
                'title': _(
                    'Include in backup a list of current installed packages at'
                    ' /etc/backup/installed_packages.txt (-k)'
                ),
                'format': 'checkbox',
            },
            'F': {
                'type': 'boolean',
                'title': _(
                    'Flash image even if image checks fail, this is dangerous! (-F)'
                ),
                'format': 'checkbox',
            },
        },
        'additionalProperties': False,
    }

    log_lines = None

    _false_positives = [
        'Command failed: ubus call system sysupgrade '
        '\{ "prefix": "\\\/tmp\\\/root", "path": "[^"]*", '
        '"backup": "\\\/tmp\\\/sysupgrade.tgz", '
        '"command": "\\\/lib\\\/upgrade\\\/do_stage2", '
        '"options": \{ "save_partitions": 1 \} \}',
        'Command failed: ubus call system sysupgrade '
        '\{ "prefix": "\\\/tmp\\\/root", "path": "[^"]*", '
        '"command": "\\\/lib\\\/upgrade\\\/do_stage2", '
        '"options": \{ "save_partitions": 1 \} \}',
    ]

    def __init__(self, upgrade_operation, connection):
        self.upgrade_operation = upgrade_operation
        self.connection = connection
        self._non_critical_services_stopped = False

    @classmethod
    def validate_upgrade_options(cls, upgrade_options):
        jsonschema.Draft4Validator(cls.SCHEMA).validate(upgrade_options)
        if upgrade_options.get('n', False):
            if upgrade_options.get('o', False):
                raise FirmwareUpgradeOptionsException(
                    {
                        'upgrade_options': _(
                            'The "-n" and "-o" options cannot be used together'
                        )
                    }
                )
            if upgrade_options.get('c', False):
                raise FirmwareUpgradeOptionsException(
                    {
                        'upgrade_options': _(
                            'The "-n" and "-c" options cannot be used together'
                        )
                    }
                )

    def log(self, value, save=True):
        self.upgrade_operation.log_line(value, save=save)

    def connect(self):
        """
        Wrapper method to call "connect" method of the connection object
        """
        return self.connection.connect()

    def disconnect(self):
        """
        Wrapper method to call "disconnect" method of the connection object
        """
        return self.connection.disconnect()

    def exec_command(self, *args, **kwargs):
        """
        Wrapper method to call "exec_command" method of the connection object
        """
        return self.connection.connector_instance.exec_command(*args, **kwargs)

    def upload(self, image_file, remote_path):
        """
        Wrapper method to call "upload" method of the connection object
        """
        self.check_memory(image_file)
        try:
            self.connection.connector_instance.upload(image_file, remote_path)
        except Exception as e:
            raise RecoverableFailure(str(e))

    def upgrade(self, image):
        self._test_connection()
        checksum = self._test_checksum(image)
        remote_path = self.get_remote_path(image)
        self.upload(image.file, remote_path)
        self._test_image(remote_path)
        self._reflash(remote_path)
        self._write_checksum(checksum)

    def _test_connection(self):
        result = self.connect()
        if not result:
            raise RecoverableFailure('Connection failed')
        self.log(_('Connection successful, starting upgrade...'))

    _non_critical_services = [
        'uhttpd',
        'dnsmasq',
        'openwisp_config',
        'openwisp-config',
        'openwisp-monitoring',
        'cron',
        'rpcd',
        'rssileds',
        'odhcpd',
        'log',
    ]

    def check_memory(self, image_file):
        """
        Tries to free up memory before upgrading
        """
        self._free_memory()
        # if there's enouogh available memory, proceed
        current_free_memory = self._get_free_memory()
        if image_file.size < current_free_memory:
            return
        file_size_mib = self._get_mib(image_file.size)
        free_memory_mib = self._get_mib(current_free_memory)
        # otherwise try to free up some more memory by stopping services
        self.log(
            _(
                'The image size ({file_size_mib} MiB) is greater '
                'than the available memory on the system ({free_memory_mib} MiB).\n'
                'For this reason the upgrade procedure will try to free up '
                'memory by stopping non critical services.\n'
                'WARNING: it is recommended to reboot the device is the upgrade '
                'fails unexpectedly because these services will not be restarted '
                'automatically.\n'
                'NOTE: The reboot can be avoided if the status of the upgrade becomes '
                '"aborted" because in this case the system will restart the '
                'services automatically.'.format(
                    file_size_mib=file_size_mib, free_memory_mib=free_memory_mib
                )
            )
        )
        self._stop_non_critical_services()
        self._free_memory()
        # check memory again
        # this time abort if there's still not enough free memory
        current_free_memory = self._get_free_memory()
        free_memory_mib = self._get_mib(current_free_memory)
        if image_file.size < current_free_memory:
            self.log(
                _(
                    'Enough available memory was freed up on the system '
                    '({0} MiB)!\n'
                    'Proceeding to upload of the image file...'.format(free_memory_mib)
                )
            )
        else:
            self.log(
                _(
                    'There is still not enough available memory on '
                    'the system ({0} MiB).\n'
                    'Starting non critical services again...'.format(free_memory_mib)
                )
            )
            self._start_non_critical_services()
            self.log(_('Non critical services started, aborting upgrade.'))
            raise UpgradeAborted()

    def _get_mib(self, value):
        """
        Converts bytes to megabytes
        """
        if value == 0:
            return value
        _MiB = 1048576
        return round(value / _MiB, 2)

    def _get_free_memory(self):
        """
        Tries to get the available memory
        If that fails it falls back to use MemFree (should happen only on older systems)
        """
        meminfo_grep = 'cat /proc/meminfo | grep'
        output, exit_code = self.exec_command(
            f'{meminfo_grep} MemAvailable', exit_codes=[0, 1]
        )
        if exit_code == 1:
            output, exit_code = self.exec_command(f'{meminfo_grep} MemFree')
        parts = output.split()
        return int(parts[1]) * 1024

    def _free_memory(self):
        """
        Attempts to free up some memory without stopping any service.
        """
        # remove OPKG index
        self.exec_command('rm -rf /tmp/opkg-lists/')
        # free internal cache
        self.exec_command('sync && echo 3 > /proc/sys/vm/drop_caches')

    def _stop_non_critical_services(self):
        """
        Stops non critical services in order to free up memory.
        """
        for service in self._non_critical_services:
            initd = f'/etc/init.d/{service}'
            self.exec_command(
                f'test -f {initd} && {initd} stop', raise_unexpected_exit=False
            )
        self.exec_command('test -f /sbin/wifi && /sbin/wifi down')
        self._non_critical_services_stopped = True

    def _start_non_critical_services(self):
        """
        Starts again non critical services.
        To be used if an upgrade operation is aborted.
        """
        for service in self._non_critical_services:
            initd = f'/etc/init.d/{service}'
            self.exec_command(
                f'test -f {initd} && {initd} start', raise_unexpected_exit=False
            )
        self.exec_command('test -f /sbin/wifi && /sbin/wifi up')
        self._non_critical_services_stopped = False

    def get_remote_path(self, image):
        # discard directory info from image name
        filename = image.name.split('/')[-1]
        return os.path.join(self.REMOTE_UPLOAD_DIR, filename)

    def get_upgrade_command(self, path):
        # Build flags for the command
        flags = []
        for key, value in self.upgrade_operation.upgrade_options.items():
            if value is True:
                flags.append(f'-{key}')
        # Enforce defaults
        for key, property in self.SCHEMA['properties'].items():
            if self.upgrade_operation.upgrade_options.get(
                key, None
            ) is None and property.get('default'):
                flags.append(f'-{key}')
        flags = ' '.join(flags)
        return self.UPGRADE_COMMAND.format(
            sysupgrade=self._SYSUPGRADE, flags=flags, path=path
        )

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
            self.log(_('Image checksum file found'), save=False)
            cat = f'cat {self.CHECKSUM_FILE}'
            output, code = self.exec_command(cat)
            if checksum == output.strip():
                message = _(
                    'Firmware already upgraded previously. '
                    'Identical checksum found in the filesystem, '
                    'upgrade not needed.'
                )
                self.log(message)
                self.disconnect()
                raise UpgradeNotNeeded(message)
            else:
                self.log(
                    _(
                        'Checksum different, proceeding with '
                        'the upload of the new image...'
                    )
                )
        else:
            self.log(
                _(
                    'Image checksum file not found, proceeding '
                    'with the upload of the new image...'
                )
            )
        return checksum

    def _test_image(self, path):
        try:
            self.exec_command(f'{self._SYSUPGRADE} --test {path}')
        except Exception as e:
            self.log(str(e), save=False)
            # if non critical services were stopped to free up memory, restart them
            if self._non_critical_services_stopped:
                self.log(_('Starting non critical services again...'))
                self._start_non_critical_services()
            self.disconnect()
            raise UpgradeAborted()
        self.log(
            _(
                'Sysupgrade test passed successfully, '
                'proceeding with the upgrade operation...'
            )
        )

    def _reflash(self, path):
        """
        this method will execute the reflashing operation in another process
        because the SSH connection may hang indefinitely while reflashing
        and would block the program; setting a timeout to `exec_command`
        doesn't seem to take effect on some OpenWrt versions
        so at least we can stop the process using
        `subprocess.join(timeout=self.UPGRADE_TIMEOUT)`
        """
        self.disconnect()
        self.log(_('Upgrade operation in progress...'))

        failure_queue = Queue()
        subprocess = Process(
            target=self._call_reflash_command,
            args=[self, path, self.UPGRADE_TIMEOUT, failure_queue],
        )
        subprocess.start()
        subprocess.join(timeout=self.UPGRADE_TIMEOUT)

        # if the child process catched an exception, raise it here in the
        # parent so it will be logged and will flag the upgrade as failed
        if not failure_queue.empty():
            raise failure_queue.get()
        failure_queue.close()

        self.upgrade_operation.refresh_from_db()
        self.log(
            _(
                'SSH connection closed, will wait {0} '
                'seconds before attempting to reconnect...'.format(self.RECONNECT_DELAY)
            )
        )
        sleep(self.RECONNECT_DELAY)
        # kill the subprocess if it has hanged
        if subprocess.is_alive():
            subprocess.terminate()
            subprocess.join()

    @classmethod
    def _call_reflash_command(cls, upgrader, path, timeout, failure_queue):
        try:
            upgrader.connect()
            command = upgrader.get_upgrade_command(path)
            # remove persistent checksum if present (introduced in openwisp-config 0.6.0)
            # otherwise the device will not download the configuration again after reflash
            upgrader.exec_command(
                'rm /etc/openwisp/checksum 2> /dev/null', exit_codes=[0, -1, 1]
            )
            output, exit_code = upgrader.exec_command(
                command, timeout=timeout, exit_codes=[0, -1]
            )
            upgrader.log(output)
        except Exception as e:
            # In some cases, for some unknown reason, the sysupgrade command
            # returns a non zero exit code, but it is carried out anyway.
            # This is a workaround to recognize this false positive and ignore it.
            error = str(e)
            for pattern in cls._false_positives:
                if re.search(pattern, error):
                    break
            else:
                failure_queue.put(e)
        upgrader.disconnect()

    def _refresh_addresses(self):
        """
        reloads the device info from the DB to
        handle cases in which the IP has changed
        """
        self.connection.device.refresh_from_db()
        self.connection = self.connection.get_working_connection(self.connection.device)
        self.addresses = self.connection.get_addresses()

    def _log_reconnecting_error(self, attempt):
        addresses = ', '.join(self.addresses)
        self.log(
            _(
                'Trying to reconnect to device at {addresses} (attempt n.{attempt})...'.format(
                    addresses=addresses, attempt=attempt
                )
            ),
            save=False,
        )

    def _write_checksum(self, checksum):
        for attempt in range(1, self.RECONNECT_MAX_RETRIES + 1):
            try:
                self._refresh_addresses()
            except NoWorkingDeviceConnectionError as error:
                if error.connection:
                    self.addresses = error.connection.get_addresses()
                self._log_reconnecting_error(attempt)
                if not str(error):
                    error = _('connection failed')
                self.log(
                    _(
                        'Device not reachable yet, ({0}).\n'
                        'retrying in {1} seconds...'.format(
                            error, self.RECONNECT_RETRY_DELAY
                        )
                    )
                )
                sleep(self.RECONNECT_RETRY_DELAY)
                continue
            self._log_reconnecting_error(attempt)
            self.log(_('Connected! Writing checksum ' f'file to {self.CHECKSUM_FILE}'))
            checksum_dir = os.path.dirname(self.CHECKSUM_FILE)
            self.exec_command(f'mkdir -p {checksum_dir}')
            self.exec_command(f'echo {checksum} > {self.CHECKSUM_FILE}')
            self.disconnect()
            self.log(_('Upgrade completed successfully.'))
            return
        # if all previous attempts failed
        raise ReconnectionFailed(
            'Giving up, device not reachable anymore after upgrade'
        )
