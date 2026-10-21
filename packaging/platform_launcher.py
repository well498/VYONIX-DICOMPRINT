"""Entrada única do pacote da plataforma (PyInstaller onedir):

* ``VyonixPlatform.exe serve|worker|init|migrate|status``  → ``vyonix.cli``
* ``VyonixPlatform.exe service core|worker --data …``       → serviços do Windows
* ``vyonix-deploy.exe …``                                   → VYONIX DEPLOY
"""

import os
import sys


def main() -> int:
    exe = os.path.splitext(os.path.basename(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]))[0].lower()
    if exe == "vyonix-deploy" or (len(sys.argv) > 1 and sys.argv[1] == "deploy"):
        from vyonix_deploy.cli import main as deploy_main
        args = sys.argv[2:] if (len(sys.argv) > 1 and sys.argv[1] == "deploy") else sys.argv[1:]
        return deploy_main(args)
    if len(sys.argv) > 1 and sys.argv[1] == "service":
        from vyonix.winservice import main as svc_main
        return svc_main(sys.argv[2:])
    from vyonix.cli import main as cli_main
    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
