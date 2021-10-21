import shlex
import subprocess

from django.utils.translation import gettext_lazy as _

from .openwrt import OpenWrt


class OpenWisp1(OpenWrt):
    """
    Upgrader for OpenWISP 1.x
    Used to migrate legacy OpenWISP 1.x systems
    (the previous generation of OpenWISP built in ruby on rails)
    to OpenWISP 2.
    """

    UPGRADE_COMMAND = '{sysupgrade} -c -n {path}'
    RECONNECT_DELAY = 60 * 6

    def _test_image(self, path):  # pragma: no cover
        # ensure sysupgrade --test is supported or skip
        help_text, code = self.exec_command(
            f'{self._SYSUPGRADE} --help', exit_codes=[1]
        )
        if 'Usage:' in help_text and '--test' not in help_text:
            self.log(
                _(
                    'This image does not support sysupgrade --test, skipping this step...'
                )
            )
        else:
            super()._test_image(path)

    def _reflash_legacy(self, path, timeout):  # pragma: no cover
        self.log(
            _(
                'The version used is OpenWRT Backfire, '
                'using legacy reflash instructions.'
            )
        )

        credentials = self.connection.credentials.params
        if 'key' not in credentials:
            raise ValueError('SSH Key not found in credentials')
        ssh_private_key = credentials['key'] + '\n'

        # create temporary file
        process = subprocess.Popen('mktemp', stdout=subprocess.PIPE)
        result = process.communicate(timeout=5)
        if process.returncode != 0:
            raise ValueError(f'mktemp exited with {process.returncode}')

        # write SSH key to the temporary file
        temp_file_path = result[0].decode().strip()
        with open(temp_file_path, 'w') as temp_file:
            temp_file.write(ssh_private_key)

        # get sysupgrade command text
        sysupgrade = self.get_upgrade_command(path)
        # remove -c because not supported on backfire
        sysupgrade = sysupgrade.replace('-c ', '')
        # $PATH is buggy on Backfire,
        # a shell command in a subprocess
        # that sets the right path fixes it
        # without this, the upgrade fails
        ip = self.addresses[0]
        path = '/bin:/sbin:/usr/bin:/usr/sbin'
        command = (
            'ssh -o StrictHostKeyChecking=no '
            '-o UserKnownHostsFile=/dev/null '
            '-o "IdentitiesOnly=yes" '
            f'-i {temp_file_path} '
            f'root@{ip} -T '
            f'"export PATH={path}; {sysupgrade}"'
        )
        args = shlex.split(command)
        process = subprocess.Popen(
            args=args, stderr=subprocess.PIPE, stdout=subprocess.PIPE
        )
        output_results = list(process.communicate(timeout=timeout))

        # delete tmp file
        subprocess.Popen(shlex.split(f'rm {temp_file_path}'))

        # if there's any error, raise an exception
        output_results.reverse()
        output = ''
        for output_result in output_results:
            output += output_result.decode()
        if process.returncode != 0:
            raise ValueError(output)
        # log output if there was no error
        self.log(output)

    @classmethod
    def _call_reflash_command(
        cls, upgrader, path, timeout, failure_queue
    ):  # pragma: no cover
        upgrader.connect()
        # ensure these files are preserved after the upgrade
        upgrader.exec_command('echo /etc/config/network >> /etc/sysupgrade.conf')
        upgrader.exec_command(
            'echo /etc/dropbear/dropbear_rsa_host_key >> /etc/sysupgrade.conf'
        )
        upgrader.log(
            _(
                'Written openwisp config file in /etc/config/openwisp.\n'
                'Added entries to /etc/sysupgrade.conf:\n'
                '- /etc/config/network\n'
                '- /etc/dropbear/dropbear_rsa_host_key\n'
            )
        )
        output, exit_code = upgrader.exec_command(
            'cat /etc/openwrt_release', raise_unexpected_exit=False
        )
        try:
            if output and 'backfire' in output:
                upgrader._reflash_legacy(path, timeout=timeout)
            else:
                command = upgrader.get_upgrade_command(path)
                output, exit_code = upgrader.exec_command(
                    command, timeout=timeout, exit_codes=[0, -1]
                )
                upgrader.log(output)
        except Exception as e:
            failure_queue.put(e)
        upgrader.disconnect()
