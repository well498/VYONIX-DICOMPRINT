"""Motor DICOM do VYONIX PACS como processo supervisionado (Orthanc oficial, sem modificações).

O ``Orthanc.exe`` não implementa o protocolo de serviço do Windows; por isso o serviço
``VyonixPacsEngine`` é o próprio ``VyonixPlatform.exe service pacs-engine``, que inicia o Orthanc como
processo filho com a configuração gerada pelo VYONIX DEPLOY e:

* encerra com ``POST /tools/shutdown`` (parada limpa do índice SQLite do Orthanc); só força o término
  se ele não sair no prazo;
* informa a queda do processo ao Windows (o serviço termina com erro e a recuperação automática o reinicia).

Arquivos (padrão do DEPLOY): binário ``<instalação>\\orthanc\\Orthanc.exe``; configuração
``<dados>\\pacs\\orthanc.json`` (com a senha do usuário REST, acessível só ao sistema, administradores e
ao serviço); armazenamento ``ProgramData\\VYONIX\\PACS``.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

log = logging.getLogger("vyonix.pacs.engine")
CONFIG_NAME = "orthanc.json"


def default_binary() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    return base / "orthanc" / ("Orthanc.exe" if sys.platform == "win32" else "Orthanc")


class EngineProcess:
    def __init__(self, binary: Path, config_file: Path, *, log_file: Path | None = None) -> None:
        self.binary, self.config_file, self.log_file = Path(binary), Path(config_file), log_file
        self.proc: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self._log_handle = None

    def _cfg(self) -> dict:
        return json.loads(self.config_file.read_text(encoding="utf-8"))

    def _client(self) -> httpx.Client:
        cfg = self._cfg()
        users = cfg.get("RegisteredUsers") or {}
        auth = next(iter(users.items())) if users else None
        return httpx.Client(base_url=f"http://127.0.0.1:{cfg.get('HttpPort', 8042)}", auth=auth, timeout=5)

    def start(self, wait_s: float = 60) -> None:
        if not self.binary.exists():
            raise FileNotFoundError(f"Motor DICOM não encontrado: {self.binary}")
        if not self.config_file.exists():
            raise FileNotFoundError(f"Configuração do motor não encontrada: {self.config_file}")
        if self._cfg().get("Plugins"):
            raise RuntimeError("A configuração do motor não pode carregar plugins (ADR-0012).")
        out = subprocess.DEVNULL
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = open(self.log_file, "ab")
            out = self._log_handle
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen([str(self.binary), str(self.config_file)], cwd=str(self.config_file.parent),
                                     stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=flags)
        self.thread = threading.Thread(target=self.proc.wait, name="vyonix-pacs-engine", daemon=True)
        self.thread.start()
        deadline = time.monotonic() + wait_s
        last = ""
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"O motor DICOM terminou ao iniciar (código {self.proc.returncode}).")
            try:
                with self._client() as c:
                    r = c.get("/system")
                if r.status_code == 200:
                    log.info("Motor DICOM em execução: Orthanc %s", r.json().get("Version"))
                    return
                last = f"HTTP {r.status_code}"
            except httpx.HTTPError as exc:
                last = str(exc)
            time.sleep(0.5)
        self.stop()
        raise RuntimeError(f"O motor DICOM não respondeu em {wait_s:.0f} s ({last}).")

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout: float = 30) -> int | None:
        if self.proc is None:
            return None
        if self.proc.poll() is None:
            try:
                with self._client() as c:
                    c.post("/tools/shutdown")
            except (httpx.HTTPError, OSError, ValueError):
                pass
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                log.warning("Motor DICOM não encerrou em %.0f s: término forçado.", timeout)
                self.proc.kill()
                self.proc.wait(10)
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None
        return self.proc.returncode
