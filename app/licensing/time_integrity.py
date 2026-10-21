"""VYONIX Time Integrity — detecção de alterações do relógio do Windows usadas para prolongar licenças.

Linha do tempo **confiável** (``trusted``): só avança. Enquanto o VYONIX roda, ela avança pelo
relógio **monotônico** (``GetTickCount64``, que não muda quando a data é alterada); entre
execuções, pelo relógio do Windows — exceto quando há evidência de alteração:

* **mesma inicialização do Windows** (``BootId`` igual): a hora de inicialização calculada
  (relógio − tempo ligado) precisa permanecer a mesma; se mudou, o relógio foi alterado e a
  diferença é descontada;
* **durante a execução**: relógio do Windows × monotônico.

Regras:

* **Retrocesso** além da tolerância (26 h, que cobre fuso horário mal configurado e horário de
  verão) em relação ao horário confiável, ou para antes da emissão assinada da licença (48 h) →
  funções licenciadas suspensas até a correção do relógio ou revalidação administrativa.
* Retrocessos menores (NTP, pequenos acertos) não bloqueiam e **não devolvem tempo**: o horário
  efetivo usado para validade e DEMO é ``max(relógio, confiável)``.
* **Avanço** detectado com evidência não é incorporado ao horário confiável: ao corrigir o
  relógio, nada é bloqueado e nenhum tempo extra foi concedido.
* Todos os horários em UTC: fuso horário e horário de verão não alteram a contagem.

Fontes de horário confiável: o relógio monotônico e as datas **assinadas** pelo License Manager
(emissão da licença e revalidações). NTP não é usado (protocolo sem autenticação; o produto
funciona sem internet). Limites: um relógio adiantado em mais de 26 h **com o computador
reiniciado** nesse estado é indistinguível do tempo real passado — ao voltar a data, exige-se
revalidação administrativa; restaurar uma imagem completa do disco devolve o histórico anterior.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.licensing.vault import Vault
from app.utils.timeutil import from_iso, to_iso

log = logging.getLogger(__name__)

RECORD = "time"
ROLLBACK_TOLERANCE = timedelta(hours=26)
FLOOR_TOLERANCE = timedelta(hours=48)
JUMP_TOLERANCE = timedelta(minutes=10)
PERSIST_EVERY = timedelta(minutes=5)


# ---------------------------------------------------------------------------- relógios
@dataclass
class ClockReading:
    wall: datetime                 # UTC
    mono: float                    # segundos, monotônico (inclui suspensão)
    boot_id: str | None            # identificador da inicialização do Windows
    uptime: float | None           # segundos desde a inicialização


class SystemClock:
    def __init__(self) -> None:
        self._tick = None
        if sys.platform == "win32":
            k = ctypes.windll.kernel32
            k.GetTickCount64.restype = ctypes.c_ulonglong
            self._tick = k.GetTickCount64

    def _boot_id(self) -> str | None:
        if sys.platform == "win32":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                    r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
                                    r"\PrefetchParameters", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                    return str(winreg.QueryValueEx(key, "BootId")[0])
            except OSError:
                return None
        try:
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            return None

    def read(self) -> ClockReading:
        wall = datetime.now(timezone.utc)
        if self._tick is not None:
            t = self._tick() / 1000.0
            return ClockReading(wall, t, self._boot_id(), t)
        if hasattr(time, "CLOCK_BOOTTIME"):
            t = time.clock_gettime(time.CLOCK_BOOTTIME)
            return ClockReading(wall, t, self._boot_id(), t)
        return ClockReading(wall, time.monotonic(), None, None)


class SimulatedClock:
    """Relógio controlável para testes: data do Windows, tempo monotônico e reinicializações."""

    def __init__(self, start: datetime) -> None:
        self.wall = start.astimezone(timezone.utc)
        self.mono = 1000.0
        self.uptime = 1000.0
        self.boot = 1

    def advance(self, **kw) -> None:
        """Tempo real passando (relógio do Windows e monotônico juntos)."""
        d = timedelta(**kw).total_seconds()
        self.wall += timedelta(seconds=d)
        self.mono += d
        self.uptime += d

    def set_wall(self, dt: datetime) -> None:
        """Usuário altera a data/hora do Windows (o monotônico não muda)."""
        self.wall = dt.astimezone(timezone.utc)

    def shift_wall(self, **kw) -> None:
        self.wall += timedelta(**kw)

    def reboot(self, off: timedelta = timedelta(minutes=2)) -> None:
        """Desliga por ``off`` (a data do Windows segue) e inicia de novo."""
        self.wall += off
        self.boot += 1
        self.uptime = 30.0
        self.mono = 30.0

    def read(self) -> ClockReading:
        return ClockReading(self.wall, self.mono, f"boot-{self.boot}", self.uptime)


# ---------------------------------------------------------------------------- integridade
@dataclass
class TimeStatus:
    ok: bool
    wall: datetime
    trusted: datetime
    effective: datetime
    issue: str | None = None            # rollback | floor
    message: str = ""
    anomalies: list[str] = field(default_factory=list)


class TimeIntegrity:
    def __init__(self, vault: Vault, clock=None, *, log_event: Callable[..., None] | None = None,
                 process: str = "") -> None:
        self.vault = vault
        self.clock = clock or SystemClock()
        self.log_event = log_event or (lambda **kw: None)
        self.process = process
        self._lock = threading.Lock()
        self._last: tuple[datetime, float] | None = None   # (horário corrigido, monotônico) desta execução
        self._offset = 0.0                                   # salto já registrado nesta execução (s)
        self._persisted: datetime | None = None

    def _pick(self, recs: list[dict[str, Any]]) -> dict[str, Any]:
        return max(recs, key=lambda r: (r.get("trusted", ""), int(r.get("seq", 0))))

    def state(self) -> dict[str, Any] | None:
        return self.vault.best(RECORD, self._pick, repair=False)[0]

    def check(self, floor: datetime | None = None) -> TimeStatus:
        with self._lock:
            return self._check(floor)

    def _check(self, floor: datetime | None) -> TimeStatus:
        r = self.clock.read()
        rec, _rd = self.vault.best(RECORD, self._pick)
        rec = dict(rec or {})
        trusted = from_iso(rec["trusted"]) if rec.get("trusted") else None
        candidate = r.wall
        anomalies: list[str] = []

        def note(kind: str, delta: float, detail: str) -> None:
            anomalies.append(kind)
            self.log_event(kind=kind, wall=r.wall, trusted=trusted, delta_s=delta, boot_id=r.boot_id,
                           detail=detail)

        if self._last is not None:
            expected = self._last[0] + timedelta(seconds=r.mono - self._last[1])
            drift = (r.wall - expected).total_seconds()
            if abs(drift - self._offset) > JUMP_TOLERANCE.total_seconds():
                kind = "forward_jump" if drift > self._offset else "backward_jump"
                note(kind, drift, "relógio do Windows alterado durante a execução "
                                  f"({drift / 3600:+.2f} h em relação ao relógio monotônico)")
                self._offset = drift
            if abs(drift) > JUMP_TOLERANCE.total_seconds():
                candidate = expected
            else:
                self._offset = 0.0
        elif rec.get("boot_id") and r.boot_id and rec["boot_id"] == r.boot_id and r.uptime is not None \
                and rec.get("boot_epoch"):
            epoch_now = r.wall - timedelta(seconds=r.uptime)
            drift = (epoch_now - from_iso(rec["boot_epoch"])).total_seconds()
            if abs(drift) > JUMP_TOLERANCE.total_seconds():
                note("forward_jump_offline" if drift > 0 else "backward_jump_offline", drift,
                     "relógio alterado com o VYONIX fechado, na mesma inicialização do Windows "
                     f"({drift / 3600:+.2f} h)")
                candidate = r.wall - timedelta(seconds=drift)
                self._offset = drift
        elif rec.get("boot_id") != r.boot_id:
            self.log_event(kind="boot", wall=r.wall, trusted=trusted, delta_s=None, boot_id=r.boot_id,
                           detail="nova inicialização do Windows" if rec else "primeiro registro de horário")
        self._last = (candidate, r.mono)

        issue = None
        message = ""
        if trusted is not None and r.wall < trusted - ROLLBACK_TOLERANCE:
            issue = "rollback"
            message = (f"A data do Windows ({_local(r.wall)}) está anterior ao último horário confiável "
                       f"({_local(trusted)}). Corrija a data e a hora ou solicite revalidação administrativa.")
        elif floor is not None and r.wall < floor - FLOOR_TOLERANCE:
            issue = "floor"
            message = (f"A data do Windows ({_local(r.wall)}) está anterior à emissão da licença "
                       f"({_local(floor)}). Corrija a data e a hora do computador.")
        elif trusted is not None and r.wall < trusted - JUMP_TOLERANCE and "backward_jump" not in anomalies:
            anomalies.append("minor_correction")
        if issue and rec.get("issue") != issue:
            self.log_event(kind=issue, wall=r.wall, trusted=trusted,
                           delta_s=(r.wall - (trusted or floor)).total_seconds(), boot_id=r.boot_id, detail=message)
        elif not issue and rec.get("issue"):
            self.log_event(kind="corrected", wall=r.wall, trusted=trusted, delta_s=None, boot_id=r.boot_id,
                           detail="relógio corrigido; funções liberadas")

        new_trusted = max(trusted, candidate) if trusted else candidate
        effective = max(r.wall, new_trusted)
        changed = (trusted is None or new_trusted - trusted >= PERSIST_EVERY or anomalies
                   or rec.get("boot_id") != r.boot_id or rec.get("issue") != issue
                   or self._persisted is None)
        if changed:
            rec.update(trusted=to_iso(new_trusted), last_wall=to_iso(r.wall), boot_id=r.boot_id,
                       boot_epoch=to_iso(candidate - timedelta(seconds=r.uptime)) if r.uptime is not None else None,
                       issue=issue, first_seen=rec.get("first_seen") or to_iso(r.wall))
            if anomalies:
                rec["anomalies"] = int(rec.get("anomalies", 0)) + len(anomalies)
            self.vault.write(RECORD, rec)
            self._persisted = r.wall
        return TimeStatus(ok=issue is None, wall=r.wall, trusted=new_trusted, effective=effective, issue=issue,
                          message=message, anomalies=anomalies)

    def revalidate(self, trusted_time: datetime, actor: str) -> None:
        """Revalidação administrativa (documento assinado pelo License Manager)."""
        with self._lock:
            r = self.clock.read()
            rec = dict(self.state() or {})
            rec.update(trusted=to_iso(trusted_time), last_wall=to_iso(r.wall), boot_id=r.boot_id,
                       boot_epoch=to_iso(r.wall - timedelta(seconds=r.uptime)) if r.uptime is not None else None,
                       issue=None, revalidated_at=to_iso(r.wall), revalidated_by=actor)
            self.vault.write(RECORD, rec)
            self._last = (r.wall, r.mono)
            self._offset = 0.0
            self.log_event(kind="revalidated", wall=r.wall, trusted=trusted_time, delta_s=None, boot_id=r.boot_id,
                           detail=f"horário confiável redefinido por revalidação administrativa ({actor})")


def _local(dt: datetime) -> str:
    return dt.astimezone().strftime("%d/%m/%Y %H:%M")


def db_logger(db, process: str) -> Callable[..., None]:
    """Grava o histórico de integridade temporal no banco do VYONIX."""
    def write(*, kind, wall, trusted, delta_s, boot_id, detail) -> None:
        from app.utils.timeutil import utc_now_iso
        try:
            db.connection().execute(
                """INSERT INTO time_integrity_log(at, kind, wall, trusted, delta_s, boot_id, process, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (utc_now_iso(), kind, to_iso(wall), to_iso(trusted) if trusted else None, delta_s, boot_id,
                 process or str(os.getpid()), detail))
        except Exception as exc:  # noqa: BLE001
            log.warning("Histórico temporal não gravado: %s", exc)
    return write
