from .openwrt import OpenWrt


class OpenWisp1(OpenWrt):
    """
    Upgrader for OpenWISP 1.x
    Used to migrate legacy OpenWISP systems to OpenWISP 2.
    """

    UPGRADE_COMMAND = '/sbin/sysupgrade -v -n {path}'

    def _test_image(self, path):  # pragma: no cover
        # ensure sysupgrade --test is supported or skip
        help_text, code = self.exec_command('sysupgrade --help', exit_codes=[1])
        if 'Usage:' in help_text and '--test' not in help_text:
            self.log(
                'This image does not support sysupgrade --test, skipping this step...'
            )
        else:
            super()._test_image(path)
