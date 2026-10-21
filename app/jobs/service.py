"""Fila persistente de trabalhos de impressão (§12).

* Cada trabalho tem uma **chave de idempotência** única: o mesmo pedido (ex.: a mesma série
  reenviada pelo equipamento) não gera uma segunda impressão; reimprimir é uma ação explícita
  que cria um novo trabalho ligado ao original.
* Toda mudança de estado é condicional (``UPDATE … WHERE state = ?``) e registrada em
  ``job_state_history`` na mesma transação — a interface e o processador nunca se atropelam.
* As configurações efetivas e a origem de cada uma ficam gravadas no trabalho.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from app.core.errors import InvalidStateTransition, ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.jobs.states import JobState, assert_transition
from app.printing import resolver
from app.printing.profiles import ProfileService
from app.utils.logging_setup import get_logger
from app.utils.timeutil import utc_now_iso

log = get_logger("jobs")

SOURCE_LABELS = {"dicom_print": "DICOM Print", "storage": "Recebimento (Storage)", "manual": "Manual",
                 "test_page": "Página de teste", "reprint": "Reimpressão"}
ACTIVE = ("received", "validating", "processing", "waiting_print", "held", "failed")


@dataclass
class Job:
    id: int
    uuid: str
    source_type: str
    state: JobState
    state_reason: str | None
    device_id: int | None
    device_name: str | None
    source_ae: str | None
    modality: str | None
    printer: str | None
    profile_id: int | None
    priority: int
    settings: dict[str, Any]
    origins: dict[str, str]
    page_count: int | None
    copies: int
    attempts: int
    max_attempts: int
    next_attempt_at: str | None
    spool_job_id: int | None
    spool_status: str | None
    document_name: str | None
    output_path: str | None
    parent_job_id: int | None
    created_at: str
    updated_at: str
    submitted_at: str | None
    completed_at: str | None
    items: int = 0

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source_type, self.source_type)

    @classmethod
    def from_row(cls, r) -> "Job":
        keys = r.keys()
        return cls(
            id=r["id"], uuid=r["uuid"], source_type=r["source_type"], state=JobState(r["state"]),
            state_reason=r["state_reason"], device_id=r["device_id"],
            device_name=r["device_name"] if "device_name" in keys else None, source_ae=r["source_ae"],
            modality=r["modality"], printer=r["printer_name"] if "printer_name" in keys else None,
            profile_id=r["profile_id"], priority=r["priority"], settings=json.loads(r["settings_json"] or "{}"),
            origins=json.loads(r["settings_origin_json"] or "{}"), page_count=r["page_count"], copies=r["copies"],
            attempts=r["attempts"], max_attempts=r["max_attempts"], next_attempt_at=r["next_attempt_at"],
            spool_job_id=r["spool_job_id"], spool_status=r["spool_status"], document_name=r["document_name"],
            output_path=r["output_path"], parent_job_id=r["parent_job_id"], created_at=r["created_at"],
            updated_at=r["updated_at"], submitted_at=r["submitted_at"], completed_at=r["completed_at"],
            items=r["item_count"] if "item_count" in keys else 0)


_SELECT = """SELECT j.*, d.name AS device_name, p.name AS printer_name,
                    (SELECT COUNT(*) FROM job_items i WHERE i.job_id = j.id) AS item_count
             FROM jobs j LEFT JOIN devices d ON d.id = j.device_id LEFT JOIN printers p ON p.id = j.printer_id"""


def group_key(items: Iterable[str], prefix: str) -> str:
    h = hashlib.sha256("\n".join(sorted(items)).encode("ascii", "replace")).hexdigest()
    return f"{prefix}:{h}"


class JobService:
    def __init__(self, db: Database, events: EventRepository, settings_get: Callable[[str], Any],
                 profiles: ProfileService, printer_id: Callable[[str], int | None], rules=None,
                 device_settings=None) -> None:
        self.rules = rules
        self.device_settings = device_settings
        self.db = db
        self.events = events
        self.get = settings_get
        self.profiles = profiles
        self.printer_id = printer_id
        self.wakeup = threading.Event()
        self._listeners: list[Callable[[int], None]] = []

    def subscribe(self, fn: Callable[[int], None]) -> None:
        self._listeners.append(fn)

    def _notify(self, job_id: int) -> None:
        self.wakeup.set()
        for fn in list(self._listeners):
            try:
                fn(job_id)
            except Exception:  # noqa: BLE001
                log.exception("Falha em ouvinte da fila")

    # ---------------------------------------------------------------- consulta
    def get_job(self, job_id: int) -> Job:
        r = self.db.connection().execute(_SELECT + " WHERE j.id = ?", (job_id,)).fetchone()
        if r is None:
            raise ValidationError(f"Trabalho {job_id} não encontrado.")
        return Job.from_row(r)

    def list(self, states: Iterable[str] | None = None, limit: int = 500, search: str = "") -> list[Job]:
        sql, params = _SELECT, []
        where = []
        if states:
            st = list(states)
            where.append(f"j.state IN ({','.join('?' * len(st))})")
            params += st
        if search:
            where.append("(j.source_ae LIKE ? OR d.name LIKE ? OR j.modality LIKE ? OR p.name LIKE ? OR CAST(j.id AS TEXT) = ?)")
            like = f"%{search}%"
            params += [like, like, like, like, search]
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY j.id DESC LIMIT ?"
        return [Job.from_row(r) for r in self.db.connection().execute(sql, (*params, limit))]

    def items(self, job_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.connection().execute(
            """SELECT ji.position, ji.frame_index, ji.instance_id, i.file_path, i.modality, i.number_of_frames,
                      i.received_at, i.sop_instance_uid
               FROM job_items ji LEFT JOIN instances i ON i.id = ji.instance_id
               WHERE ji.job_id = ? ORDER BY ji.position""", (job_id,))]

    def history(self, job_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.connection().execute(
            "SELECT * FROM job_state_history WHERE job_id = ? ORDER BY id", (job_id,))]

    def counts(self) -> dict[str, int]:
        return {r["state"]: r["n"] for r in self.db.connection().execute(
            "SELECT state, COUNT(*) AS n FROM jobs GROUP BY state")}

    # ---------------------------------------------------------------- criação
    def create(self, *, source_type: str, items: list[tuple[int, int]] | list[tuple[int, int, int]], idempotency_key: str | None = None,
               device_id: int | None = None, source_ae: str | None = None, modality: str | None = None,
               printer: str | None = None, overrides: dict[str, Any] | None = None,
               override_label: str = "Escolha manual", parent_job_id: int | None = None, priority: int = 0,
               actor: str = "system", hold: bool | None = None, resolved: resolver.Resolved | None = None,
               reason: str | None = None, rule_facts: dict[str, Any] | None = None,
               dicom: dict[str, Any] | None = None) -> tuple[int, bool]:
        """Cria o trabalho. Retorna (id, criado). Se a chave já existe, devolve o trabalho existente."""
        if source_type not in SOURCE_LABELS:
            raise ValidationError("Origem de trabalho inválida.")
        if not items and source_type != "test_page":
            raise ValidationError("O trabalho não tem imagens.")
        key = idempotency_key or f"{source_type}:{uuid.uuid4()}"
        conn = self.db.connection()
        existing = conn.execute("SELECT id FROM jobs WHERE idempotency_key = ?", (key,)).fetchone()
        if existing:
            return int(existing["id"]), False

        ev = None
        if resolved is None:
            ev = self.evaluate_rules(source_type=source_type, source_ae=source_ae, device_id=device_id,
                                     modality=modality, items=items, extra=rule_facts)
            resolved = self.resolve_for(device_id=device_id, modality=modality, printer=printer, overrides=overrides,
                                        override_label=override_label, rules=ev, dicom=dicom)
        if (hold is None and source_type in ("storage", "dicom_print")
                and resolved.values.get("auto_print") is False):
            hold = True
            reason = "; ".join(x for x in (reason, "Impressão manual: libere o trabalho para imprimir "
                                                   f"({resolved.origins.get('auto_print')})") if x)
        rule_id = ev.matched_ids[0] if ev is not None and ev.matched_ids else None
        if ev is not None and ev.hold and hold is None:
            hold = True
            reason = "; ".join(x for x in (reason, f"Retido pela regra \u201c{ev.hold}\u201d") if x)
        if ev is not None and ev.priority is not None:
            priority = ev.priority if priority == 0 else max(priority, ev.priority)
        values = resolved.values
        hold = bool(self.get("jobs.hold_new")) if hold is None else hold
        state = JobState.HELD if hold else JobState.RECEIVED
        now = utc_now_iso()
        pid = self.printer_id(values["printer"]) if values.get("printer") else None
        with self.db.transaction():
            cur = conn.execute(
                """INSERT INTO jobs(uuid, idempotency_key, source_type, parent_job_id, device_id, source_ae, modality,
                       printer_id, profile_id, rule_id, state, state_reason, settings_json, settings_origin_json, copies,
                       attempts, max_attempts, priority, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), key, source_type, parent_job_id, device_id, source_ae, modality, pid,
                 resolved.profile_id, rule_id, state.value, reason or ("Aguardando liberação manual" if hold else None),
                 json.dumps(values, ensure_ascii=False), json.dumps(resolved.origins, ensure_ascii=False),
                 int(values.get("copies") or 1), int(self.get("jobs.max_attempts")), priority, now, now))
            job_id = int(cur.lastrowid)
            conn.executemany("INSERT INTO job_items(job_id, instance_id, frame_index, position) VALUES (?, ?, ?, ?)",
                             [(job_id, it[0], it[1], it[2] if len(it) > 2 else pos) for pos, it in enumerate(items)])
            conn.execute("""INSERT INTO job_state_history(job_id, from_state, to_state, actor, reason, at)
                            VALUES (?, NULL, ?, ?, ?, ?)""", (job_id, state.value, actor, reason, now))
            self.events.add(level="INFO", category=Category.JOB, action="job.create",
                            message=f"Trabalho #{job_id} criado ({SOURCE_LABELS[source_type]}, "
                                    f"{len(items)} imagem(ns)" + (", retido" if hold else "") + ").",
                            device_id=device_id, job_id=job_id, actor=actor)
        self._notify(job_id)
        return job_id, True

    def resolve_for(self, *, device_id: int | None, modality: str | None, printer: str | None = None,
                    overrides: dict[str, Any] | None = None, override_label: str = "Escolha manual", rules=None,
                    dicom: dict[str, Any] | None = None) -> resolver.Resolved:
        """Resolve as configurações com toda a hierarquia (usada na criação, no reprocessamento e na
        pré-visualização)."""
        conn = self.db.connection()
        dev_profile = dev_printer = dev_name = None
        if device_id:
            d = conn.execute("""SELECT d.name, d.print_profile_id, p.name AS printer_name FROM devices d
                                LEFT JOIN printers p ON p.id = d.printer_id WHERE d.id = ?""", (device_id,)).fetchone()
            if d:
                dev_profile, dev_printer, dev_name = d["print_profile_id"], d["printer_name"], d["name"]
        dev_settings = self.device_settings.get(device_id) if (self.device_settings and device_id) else None
        res = resolver.resolve(self.get, self.profiles, device_id=device_id, device_profile_id=dev_profile,
                               modality=modality, printer=printer, overrides=overrides, override_label=override_label,
                               rules=rules, device_printer=dev_printer, device_settings=dev_settings,
                               dicom=dicom, device_name=dev_name)
        if rules is not None and rules.explanation:
            res.origins["_rules"] = "\n".join(rules.explanation)
        if dicom:
            res.origins["_dicom"] = json.dumps(dicom, ensure_ascii=False)
        return res

    def evaluate_rules(self, *, source_type: str, source_ae: str | None, device_id: int | None,
                       modality: str | None, items, extra: dict[str, Any] | None = None):
        """Avalia as regras ativas para os fatos deste trabalho (None se não houver motor)."""
        if self.rules is None:
            return None
        from types import SimpleNamespace
        from app.rules.engine import facts_for
        conn = self.db.connection()
        device = None
        if device_id:
            d = conn.execute("SELECT id, site, department FROM devices WHERE id = ?", (device_id,)).fetchone()
            device = SimpleNamespace(**dict(d)) if d else None
        first_file = None
        if items:
            r = conn.execute("SELECT file_path FROM instances WHERE id = ?", (items[0][0],)).fetchone()
            first_file = r["file_path"] if r else None
        facts = facts_for(source=source_type, calling_ae=source_ae, device=device, modality=modality,
                          image_count=len(items), first_file=first_file, extra=extra)
        return self.rules.evaluate(facts)

    # ---------------------------------------------------------------- transições
    def transition(self, job_id: int, to: JobState, *, actor: str, reason: str | None = None,
                   expect: JobState | None = None, **fields: Any) -> bool:
        """Transição condicional. Retorna False se o estado mudou nesse meio-tempo."""
        conn = self.db.connection()
        with self.db.transaction():
            row = conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise ValidationError(f"Trabalho {job_id} não encontrado.")
            current = JobState(row["state"])
            if expect is not None and current != expect:
                return False
            assert_transition(current, to)
            now = utc_now_iso()
            sets = {"state": to.value, "state_reason": reason, "updated_at": now, **fields}
            if to == JobState.COMPLETED:
                sets.setdefault("completed_at", now)
            cols = ", ".join(f"{k} = ?" for k in sets)
            cur = conn.execute(f"UPDATE jobs SET {cols} WHERE id = ? AND state = ?",
                               (*sets.values(), job_id, current.value))
            if cur.rowcount != 1:
                return False
            conn.execute("""INSERT INTO job_state_history(job_id, from_state, to_state, actor, reason, at)
                            VALUES (?, ?, ?, ?, ?, ?)""", (job_id, current.value, to.value, actor, reason, now))
        self._notify(job_id)
        return True

    def update_fields(self, job_id: int, **fields: Any) -> None:
        fields["updated_at"] = utc_now_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.connection().execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))

    # ---------------------------------------------------------------- ações do usuário
    def _act(self, job_id: int, to: JobState, actor: str, reason: str, action: str, message: str,
             level: str = "INFO", **fields: Any) -> None:
        job = self.get_job(job_id)
        try:
            assert_transition(job.state, to)
        except InvalidStateTransition as exc:
            raise ValidationError(f"Trabalho #{job_id}: {exc}") from exc
        if not self.transition(job_id, to, actor=actor, reason=reason, expect=job.state, **fields):
            raise ValidationError(f"Trabalho #{job_id} mudou de estado; atualize a lista e tente de novo.")
        self.events.add(level=level, category=Category.JOB, action=action, message=message,
                        device_id=job.device_id, job_id=job_id, actor=actor)

    def hold(self, job_id: int, *, actor: str) -> None:
        self._act(job_id, JobState.HELD, actor, "Retido pelo usuário", "job.hold", f"Trabalho #{job_id} retido.")

    def release(self, job_id: int, *, actor: str) -> None:
        self._act(job_id, JobState.VALIDATING, actor, "Liberado pelo usuário", "job.release",
                  f"Trabalho #{job_id} liberado.", next_attempt_at=None)

    def cancel(self, job_id: int, *, actor: str) -> None:
        self._act(job_id, JobState.CANCELLED, actor, "Cancelado pelo usuário", "job.cancel",
                  f"Trabalho #{job_id} cancelado.", level="WARNING", next_attempt_at=None)

    def retry(self, job_id: int, *, actor: str) -> None:
        """Tentar de novo com as mesmas configurações (zera o contador de tentativas)."""
        self._act(job_id, JobState.VALIDATING, actor, "Nova tentativa solicitada", "job.retry",
                  f"Trabalho #{job_id}: nova tentativa.", attempts=0, next_attempt_at=None)

    def reprocess(self, job_id: int, *, actor: str) -> None:
        """Tentar de novo resolvendo as configurações atuais (perfis e padrões)."""
        job = self.get_job(job_id)
        if job.state not in (JobState.FAILED, JobState.HELD):
            raise ValidationError("Só é possível reprocessar trabalhos com falha ou retidos.")
        items = [(it["instance_id"], it["frame_index"]) for it in self.items(job_id) if it["instance_id"]]
        ev = self.evaluate_rules(source_type=job.source_type, source_ae=job.source_ae, device_id=job.device_id,
                                 modality=job.modality, items=items)
        dicom = json.loads(job.origins["_dicom"]) if job.origins.get("_dicom") else None
        res = self.resolve_for(device_id=job.device_id, modality=job.modality, rules=ev, dicom=dicom)
        self._act(job_id, JobState.VALIDATING, actor, "Reprocessado com as configurações atuais", "job.reprocess",
                  f"Trabalho #{job_id} reprocessado com as configurações atuais.", attempts=0, next_attempt_at=None,
                  settings_json=json.dumps(res.values, ensure_ascii=False),
                  settings_origin_json=json.dumps(res.origins, ensure_ascii=False), profile_id=res.profile_id,
                  printer_id=self.printer_id(res.values["printer"]) if res.values.get("printer") else None,
                  copies=int(res.values.get("copies") or 1))

    def reprint(self, job_id: int, *, actor: str, printer: str | None = None, copies: int | None = None) -> int:
        """Novo trabalho com as mesmas imagens e configurações (opcionalmente outra impressora/cópias)."""
        job = self.get_job(job_id)
        items = [(it["instance_id"], it["frame_index"], it["position"]) for it in self.items(job_id)]
        if job.source_type != "test_page" and (not items or any(it[0] is None for it in items)):
            raise ValidationError("As imagens deste trabalho não estão mais disponíveis (retenção).")
        values, origins = dict(job.settings), dict(job.origins)
        if printer:
            values["printer"], origins["printer"] = printer, "Escolha manual (reimpressão)"
        if copies:
            if not 1 <= copies <= 99:
                raise ValidationError("Cópias devem estar entre 1 e 99.")
            values["copies"], origins["copies"] = copies, "Escolha manual (reimpressão)"
        new_id, _ = self.create(source_type="reprint" if job.source_type != "test_page" else "test_page",
                                items=items, device_id=job.device_id, source_ae=job.source_ae,
                                modality=job.modality, parent_job_id=job.id, priority=job.priority, actor=actor,
                                hold=False, resolved=resolver.Resolved(values, origins, job.profile_id),
                                reason=f"Reimpressão do trabalho #{job.id}")
        self.events.add(level="INFO", category=Category.JOB, action="job.reprint",
                        message=f"Trabalho #{job.id} reimpresso como #{new_id}.", device_id=job.device_id,
                        job_id=new_id, actor=actor)
        return new_id

    def test_page(self, *, printer: str, actor: str, overrides: dict[str, Any] | None = None,
                  device_id: int | None = None) -> int:
        """Página de teste (ou folha de calibração 3 × 3, com ``overrides['sheet']``). Com ``device_id``, usa as
        configurações daquele equipamento (calibração, cabeçalho/rodapé) — nunca as de outro."""
        ov = {"printer": printer, "layout": "1x1", **(overrides or {})}
        modality = None
        if device_id:
            r = self.db.connection().execute("SELECT modality FROM devices WHERE id = ?", (device_id,)).fetchone()
            modality = r["modality"] if r else None
        job_id, _ = self.create(source_type="test_page", items=[], printer=printer, overrides=ov, actor=actor,
                                hold=False, override_label="Página de teste", device_id=device_id, modality=modality)
        return job_id
