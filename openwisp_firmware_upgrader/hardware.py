"""
Mapping between hardware models and firwmare image
This if focused on OpenWrt only for now, but it should
be possible to add support for different embedded
systems in the future.
"""
from collections import OrderedDict
import json
from os import listdir

from . import settings as app_settings

if app_settings.CUSTOM_OPENWRT_IMAGES:
    OPENWRT_FIRMWARE_IMAGE_MAP = OrderedDict(app_settings.CUSTOM_OPENWRT_IMAGES)
else:  # pragma: no cover
    OPENWRT_FIRMWARE_IMAGE_MAP = OrderedDict()

#load devices from target

#get array composed of platforms and than iterate down
systems = listdir("targets")
for platform in systems:
    for subplatform in listdir("targets/"+platform):
        print("targets/"+platform+"/"+subplatform)
        try:
        #read each devices.json
            with open("targets/"+platform+"/"+subplatform+"/devices.json", "r", encoding="utf-8") as file:
                #json.load(file) is equivalent to json.loads(file.read()) 
                devobj = json.load(file)
                OPENWRT_FIRMWARE_IMAGE_MAP.update(devobj)
        except:
            print("failed to load "+"targets/"+platform+"/"+subplatform+"/devices.json")

# OpenWrt only for now, in the future we'll merge
# different dictionaries representing different firmwares
# eg: AirOS, Raspbian
FIRMWARE_IMAGE_MAP = OPENWRT_FIRMWARE_IMAGE_MAP

# Allows getting type from image board
REVERSE_FIRMWARE_IMAGE_MAP = {}
# Choices used in model
FIRMWARE_IMAGE_TYPE_CHOICES = []

for key, info in FIRMWARE_IMAGE_MAP.items():
    FIRMWARE_IMAGE_TYPE_CHOICES.append((key, info['label']))
    for board in info['boards']:
        REVERSE_FIRMWARE_IMAGE_MAP[board] = key
