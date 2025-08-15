#!/usr/bin/env python
#!/usr/bin/env python
import os
import sys

# Ensure the project root is on the Python path so Django can find openwisp_firmware_upgrader
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openwisp2.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
