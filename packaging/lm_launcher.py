"""Script de entrada usado pelo PyInstaller para gerar o ``VYONIX_License_Manager.exe``."""

import sys

from license_manager.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
