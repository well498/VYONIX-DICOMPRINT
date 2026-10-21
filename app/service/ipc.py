"""Canal de controle entre a interface e o serviço (Fase 7).

* Windows: *named pipe* local ``\\\\.\\pipe\\vyonix-dicomprint`` (não acessível pela rede).
* Outros sistemas (testes): socket Unix na pasta de dados.
* Autenticação: desafio HMAC do ``multiprocessing.connection`` com uma chave aleatória de 32 bytes
  criada pelo serviço em ``<ProgramData>\\VYONIX\\DICOM Print\\service\\ipc.key``.
* Somente comandos de controle (estado, iniciar/parar/reiniciar servidores, recarregar
  configurações, atualizar impressoras, acordar a fila). Dados (trabalhos, configurações,
  equipamentos) continuam no banco compartilhado, que o serviço observa.
* Mensagens são dicionários JSON — nunca objetos Python serializados (sem *pickle*).
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from app.utils.logging_setup import get_logger

log = get_logger("service.ipc")

PIPE_NAME = r"\\.\pipe\vyonix-dicomprint"
KEY_FILE = "ipc.key"
MAX_MESSAGE = 64 * 1024


def address_for(machine_root: Path) -> tuple[str, str]:
    if sys.platform == "win32":
        # Pasta de dados padrão: nome fixo. Pastas isoladas (--data-dir, testes): nome derivado do caminho,
        # para que duas instalações de teste não conversem entre si.
        default = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "VYONIX" / "DICOM Print"
        if Path(machine_root).resolve() == default.resolve():
            return PIPE_NAME, "AF_PIPE"
        import hashlib
        digest = hashlib.sha256(str(Path(machine_root).resolve()).lower().encode("utf-8")).hexdigest()[:12]
        return f"{PIPE_NAME}-{digest}", "AF_PIPE"
    return str(machine_root / "service" / "ipc.sock"), "AF_UNIX"


def key_path(machine_root: Path) -> Path:
    return machine_root / "service" / KEY_FILE


def ensure_key(machine_root: Path) -> bytes:
    p = key_path(machine_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(key)
    os.replace(tmp, p)
    return key


def read_key(machine_root: Path) -> bytes | None:
    try:
        data = key_path(machine_root).read_bytes()
        return data if len(data) == 32 else None
    except OSError:
        return None


class IpcServer:
    def __init__(self, machine_root: Path, handlers: dict[str, Callable[[dict], Any]]) -> None:
        self.machine_root = machine_root
        self.handlers = handlers
        self._listener = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        from multiprocessing.connection import Listener
        key = ensure_key(self.machine_root)
        address, family = address_for(self.machine_root)
        if family == "AF_UNIX":
            Path(address).unlink(missing_ok=True)
        self._listener = Listener(address, family=family, authkey=key)
        self._thread = threading.Thread(target=self._serve, name="vyonix-ipc", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._listener is not None:
            try:   # desbloqueia o accept() com uma conexão própria
                client = IpcClient(self.machine_root, timeout=1.0)
                client.call("ping")
            except Exception:  # noqa: BLE001
                pass
            try:
                self._listener.close()
            except Exception:  # noqa: BLE001
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn = self._listener.accept()
            except Exception as exc:  # noqa: BLE001 - autenticação falhou ou listener fechado
                if self._stop.is_set():
                    return
                log.warning("Conexão de controle recusada: %s", exc)
                continue
            threading.Thread(target=self._handle, args=(conn,), daemon=True, name="vyonix-ipc-conn").start()

    def _handle(self, conn) -> None:
        try:
            with conn:
                if not conn.poll(10):
                    return
                raw = conn.recv_bytes(MAX_MESSAGE)
                try:
                    msg = json.loads(raw.decode("utf-8"))
                    cmd = msg.get("cmd")
                    fn = self.handlers.get(cmd)
                    if fn is None:
                        reply = {"ok": False, "error": f"comando desconhecido: {cmd}"}
                    else:
                        reply = {"ok": True, "result": fn(msg.get("args") or {})}
                except Exception as exc:  # noqa: BLE001
                    log.exception("Falha ao executar comando de controle")
                    reply = {"ok": False, "error": str(exc)}
                conn.send_bytes(json.dumps(reply, ensure_ascii=False, default=str).encode("utf-8"))
        except Exception:  # noqa: BLE001
            log.debug("Conexão de controle encerrada", exc_info=True)


class ServiceUnavailable(Exception):
    pass


class IpcClient:
    def __init__(self, machine_root: Path, timeout: float = 5.0) -> None:
        self.machine_root = machine_root
        self.timeout = timeout

    def call(self, cmd: str, **args: Any) -> Any:
        from multiprocessing.connection import Client
        key = read_key(self.machine_root)
        if key is None:
            raise ServiceUnavailable("serviço não iniciado (sem chave de controle)")
        address, family = address_for(self.machine_root)
        if family == "AF_UNIX" and not Path(address).exists():
            raise ServiceUnavailable("serviço não iniciado")
        result: dict[str, Any] = {}

        def run() -> None:
            try:
                with Client(address, family=family, authkey=key) as conn:
                    conn.send_bytes(json.dumps({"cmd": cmd, "args": args}).encode("utf-8"))
                    if conn.poll(self.timeout):
                        result["reply"] = json.loads(conn.recv_bytes(MAX_MESSAGE).decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                result["error"] = exc
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(self.timeout + 1)
        if "reply" not in result:
            raise ServiceUnavailable(f"serviço não respondeu: {result.get('error') or 'tempo esgotado'}")
        reply = result["reply"]
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error") or "falha no serviço")
        return reply.get("result")

    def available(self) -> bool:
        try:
            return self.call("ping") == "pong"
        except Exception:  # noqa: BLE001
            return False
