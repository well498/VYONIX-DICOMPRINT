"""Script de entrada usado pelo PyInstaller para gerar o ``VyonixService.exe`` (sem Qt)."""

import sys

from app.service.winservice import main

if __name__ == "__main__":
    sys.exit(main())
