from .openwrt import OpenWrt


class OpenWisp1(OpenWrt):
    """
    Upgrader for OpenWISP 1.x
    Used to migrate legacy OpenWISP systems to OpenWISP 2.
    """

    UPGRADE_COMMAND = 'sysupgrade -v -n {path}'
