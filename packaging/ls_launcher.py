"""Script de entrada usado pelo PyInstaller para gerar o ``VYONIX_License_Server.exe``."""

import sys

from license_server.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
