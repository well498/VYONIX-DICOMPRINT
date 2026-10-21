"""Exames recebidos — base do VYONIX Reception (controle de impressão e de retirada).

Um exame é um estudo (Study Instance UID). Os dados de identificação (nome do paciente, ID,
Accession Number, número de atendimento) são gravados para a pesquisa da recepção, acessível só a
usuários autenticados, e apagados pela retenção junto com as imagens (LGPD).

Situação da impressão (derivada da fila; o envio ao spooler é distinto da confirmação):
Recebendo imagens → Aguardando conclusão → Disponível (sob demanda) / Pendente de impressão →
Preparando impressão → Aguardando impressora → Enviado ao spooler → Impressão confirmada, ou Falha /
Cancelado. A conclusão do recebimento é o período sem novas imagens da série
(``jobs.collect_seconds``); o fim de uma associação, isoladamente, não conclui o exame.

Situação da retirada (independente da impressão): Aguardando preparação, Em preparação, Pronto
para retirada, Entregue, Entrega pendente, Entrega cancelada. Imprimir não marca como entregue.
"""

from __future__ import annotations

import json
import math
import shutil
import threading
from datetime import timedelta
from typing import Any

from app.core.errors import ValidationError
from app.jobs.states import JobState
from app.utils.timeutil import from_iso, to_iso, utc_now, utc_now_iso

PRINT_STATES = {
    "receiving": "Recebendo imagens", "awaiting": "Aguardando conclusão", "available": "Disponível",
    "pending": "Pendente de impressão", "preparing": "Preparando impressão",
    "waiting_printer": "Aguardando impressora", "spooled": "Enviado ao spooler",
    "confirmed": "Impressão confirmada", "failed": "Falha", "cancelled": "Cancelado",
}
PICKUP_STATES = {
    "aguardando_preparacao": "Aguardando preparação", "em_preparacao": "Em preparação",
    "pronto": "Pronto para retirada", "entregue": "Entregue", "entrega_pendente": "Entrega pendente",
    "entrega_cancelada": "Entrega cancelada",
}
JOB_TO_PRINT = {
    "held": "available", "received": "pending", "validating": "pending", "processing": "preparing",
    "waiting_print": "waiting_printer", "spooled": "spooled", "completed": "confirmed", "failed": "failed",
    "cancelled": "cancelled",
}
# Ordem de exibição do estado agregado (o primeiro presente vence).
PRECEDENCE = ("receiving", "awaiting", "preparing", "waiting_printer", "pending", "failed", "spooled",
              "confirmed", "available", "cancelled")
ACTIVE_JOB = ("received", "validating", "processing", "waiting_print")


class DuplicatePrint(ValidationError):
    """O exame já foi impresso: a interface pede confirmação (e motivo)."""

    def __init__(self, message: str, last: dict[str, Any]) -> None:
        super().__init__(message)
        self.last = last


def _text(ds, keyword: str) -> str | None:
    try:
        v = ds.get(keyword)
    except Exception:  # noqa: BLE001
        return None
    if v is None:
        return None
    s = str(v).strip()
    return s.replace("^", " ").strip() if keyword == "PatientName" else (s or None)


class ExamService:
    def __init__(self, db, events, jobs, settings_get, printers=None) -> None:
        self.db = db
        self.events = events
        self.jobs = jobs
        self.setting = settings_get
        self.printers = printers
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ registro
    def on_stored(self, instance, ds, source: str) -> None:
        conn = self.db.connection()
        now = utc_now_iso()
        cur = conn.execute("UPDATE exams SET instances = instances + 1, last_received_at = ?, "
                           "modality = COALESCE(modality, ?) WHERE study_uid = ?",
                           (now, instance.modality or None, instance.study_uid))
        if cur.rowcount:
            return
        study_date = _text(ds, "StudyDate")
        conn.execute(
            """INSERT OR IGNORE INTO exams(study_uid, source, patient_name, patient_id, accession, admission_id,
                   study_date, study_desc, modality, device_id, calling_ae, called_ae, source_ip, instances,
                   first_received_at, last_received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
            (instance.study_uid, source, _text(ds, "PatientName"), _text(ds, "PatientID"),
             _text(ds, "AccessionNumber"), _text(ds, "AdmissionID"),
             f"{study_date[:4]}-{study_date[4:6]}-{study_date[6:8]}" if study_date and len(study_date) >= 8 else None,
             _text(ds, "StudyDescription"), instance.modality or None, instance.device_id, instance.peer.calling_ae,
             instance.peer.called_ae, instance.peer.address, now, now))

    def link_job(self, job_id: int, first_instance_id: int | None, actor: str | None) -> None:
        if not first_instance_id:
            return
        self.db.connection().execute(
            """UPDATE jobs SET exam_id = (SELECT e.id FROM exams e JOIN instances i ON i.study_uid = e.study_uid
                                          WHERE i.id = ?),
                               requested_by = COALESCE(requested_by, ?) WHERE id = ?""",
            (first_instance_id, actor if actor and actor.startswith("usuario:") else None, job_id))

    def _event(self, exam_id: int, actor: str, action: str, detail: dict | str | None = None,
               job_ids: list[int] | None = None) -> None:
        self.db.connection().execute(
            "INSERT INTO exam_events(exam_id, at, actor, action, detail, job_ids) VALUES (?,?,?,?,?,?)",
            (exam_id, utc_now_iso(), actor, action,
             json.dumps(detail, ensure_ascii=False) if isinstance(detail, dict) else detail,
             json.dumps(job_ids) if job_ids else None))

    # ------------------------------------------------------------------ situação
    def _pending(self) -> dict[str, str]:
        rows = self.db.connection().execute(
            """SELECT i.study_uid, MAX(a.received_at) AS last FROM autoprint_pending a
               JOIN instances i ON i.id = a.instance_id GROUP BY i.study_uid""").fetchall()
        return {r["study_uid"]: r["last"] for r in rows}

    def _jobs_by_exam(self, ids: list[int]) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {i: [] for i in ids}
        if not ids:
            return out
        q = ",".join("?" * len(ids))
        for r in self.db.connection().execute(
                f"""SELECT j.id, j.exam_id, j.state, j.state_reason, j.source_type, j.parent_job_id, j.copies,
                           j.page_count, j.created_at, j.updated_at, j.submitted_at, j.requested_by, j.device_id,
                           p.name AS printer, (SELECT COUNT(*) FROM job_items ji WHERE ji.job_id = j.id) AS items,
                           j.settings_json FROM jobs j LEFT JOIN printers p ON p.id = j.printer_id
                    WHERE j.exam_id IN ({q}) ORDER BY j.id""", ids):
            out[r["exam_id"]].append(dict(r))
        return out

    def print_state(self, exam: dict, jobs: list[dict], pending: dict[str, str]) -> str:
        states = set()
        last = pending.get(exam["study_uid"])
        if last:
            quiet = int(self.setting("jobs.collect_seconds"))
            age = (utc_now() - from_iso(last)).total_seconds()
            states.add("receiving" if age < min(5, quiet) else "awaiting")
        for j in jobs:
            states.add(JOB_TO_PRINT.get(j["state"], "pending"))
        if not states:
            return "available"
        return next(s for s in PRECEDENCE if s in states)

    # ------------------------------------------------------------------ pesquisa
    def search(self, *, q: str = "", modality: str | None = None, device_id: int | None = None,
               date_from: str | None = None, date_to: str | None = None, print_state: str | None = None,
               pickup_state: str | None = None, limit: int = 300) -> dict[str, Any]:
        sql = """SELECT e.*, d.name AS rule_name FROM exams e LEFT JOIN devices d ON d.id = e.device_id
                 WHERE e.purged_at IS NULL"""
        args: list = []
        if q:
            like = f"%{q.strip()}%"
            sql += (" AND (e.patient_name LIKE ? OR e.patient_id LIKE ? OR e.accession LIKE ? OR e.admission_id LIKE ?"
                    " OR e.study_desc LIKE ?)")
            args += [like] * 5
        if modality:
            sql += " AND e.modality = ?"
            args.append(modality)
        if device_id:
            sql += " AND e.device_id = ?"
            args.append(int(device_id))
        if date_from:
            sql += " AND e.first_received_at >= ?"
            args.append(to_iso(from_iso(date_from + "T00:00:00-03:00")) if len(date_from) == 10 else date_from)
        if date_to:
            sql += " AND e.first_received_at <= ?"
            args.append(to_iso(from_iso(date_to + "T23:59:59-03:00")) if len(date_to) == 10 else date_to)
        if pickup_state:
            sql += " AND e.pickup_state = ?"
            args.append(pickup_state)
        sql += " ORDER BY e.first_received_at DESC LIMIT ?"
        args.append(int(limit) * (4 if print_state else 1))
        rows = [dict(r) for r in self.db.connection().execute(sql, args)]
        jobs = self._jobs_by_exam([r["id"] for r in rows])
        pending = self._pending()
        out, counts = [], {}
        for r in rows:
            st = self.print_state(r, jobs[r["id"]], pending)
            if print_state and st != print_state:
                continue
            r["print_state"], r["print_state_label"] = st, PRINT_STATES[st]
            r["pickup_label"] = PICKUP_STATES[r["pickup_state"]]
            printed = [j for j in jobs[r["id"]] if j["state"] in ("spooled", "completed")]
            r["printed_count"] = len(printed)
            r["jobs"] = len(jobs[r["id"]])
            out.append(r)
            counts[r["modality"] or "—"] = counts.get(r["modality"] or "—", 0) + 1
            if len(out) >= limit:
                break
        return {"exams": out, "by_modality": counts, "total": len(out)}

    def get(self, exam_id: int) -> dict:
        r = self.db.connection().execute("""SELECT e.*, d.name AS rule_name FROM exams e
                                            LEFT JOIN devices d ON d.id = e.device_id WHERE e.id = ?""",
                                         (exam_id,)).fetchone()
        if r is None or r["purged_at"]:
            raise ValidationError("Exame não encontrado ou removido pela retenção.")
        return dict(r)

    def detail(self, exam_id: int) -> dict[str, Any]:
        e = self.get(exam_id)
        jobs = self._jobs_by_exam([exam_id])[exam_id]
        st = self.print_state(e, jobs, self._pending())
        e.update(print_state=st, print_state_label=PRINT_STATES[st], pickup_label=PICKUP_STATES[e["pickup_state"]])
        for j in jobs:
            j["state_label"] = JobState(j["state"]).label
            j.pop("settings_json", None)
        hist = [dict(r) for r in self.db.connection().execute(
            "SELECT at, actor, action, detail, job_ids FROM exam_events WHERE exam_id = ? ORDER BY id DESC",
            (exam_id,))]
        series = [dict(r) for r in self.db.connection().execute(
            """SELECT series_uid, modality, COUNT(*) AS n FROM instances WHERE study_uid = ?
               GROUP BY series_uid, modality""", (e["study_uid"],))]
        return {"exam": e, "jobs": jobs, "history": hist, "series": series}

    # ------------------------------------------------------------------ impressão pela recepção
    def _base_jobs(self, jobs: list[dict]) -> list[dict]:
        """Trabalhos originais do exame (um por série/filme), sem reimpressões nem páginas de teste."""
        return [j for j in jobs if j["source_type"] in ("storage", "dicom_print") and j["parent_job_id"] is None]

    def last_print(self, jobs: list[dict]) -> dict | None:
        done = [j for j in jobs if j["state"] in ("spooled", "completed")]
        if not done:
            return None
        j = max(done, key=lambda x: x["submitted_at"] or x["updated_at"])
        return {"at": j["submitted_at"] or j["updated_at"], "printer": j["printer"], "copies": j["copies"],
                "by": j["requested_by"] or "impressão automática", "state": JobState(j["state"]).label,
                "count": len(done)}

    def _replay(self, request_key: str | None):
        if not request_key:
            return None
        r = self.db.connection().execute("SELECT result_json FROM print_requests WHERE request_key = ?",
                                         (request_key,)).fetchone()
        return json.loads(r["result_json"]) if r else None

    def _remember(self, request_key: str | None, exam_id: int, kind: str, actor: str, result: dict) -> None:
        if request_key:
            self.db.connection().execute(
                "INSERT OR IGNORE INTO print_requests(request_key, exam_id, kind, actor, at, result_json) "
                "VALUES (?,?,?,?,?,?)", (request_key, exam_id, kind, actor, utc_now_iso(), json.dumps(result)))

    def print_exam(self, exam_id: int, user, *, request_key: str | None = None, confirm_duplicate: bool = False,
                   reason: str | None = None, printer: str | None = None, copies: int | None = None,
                   now: bool = False) -> dict[str, Any]:
        """IMPRIMIR EXAME (``now=False``) ou IMPRIMIR AGORA (``now=True``: impressão excepcional com
        impressora/cópias escolhidas, sem alterar a regra)."""
        user.require("print_now" if now else "print")
        kind = "print_now" if now else "print"
        with self._lock:
            done = self._replay(request_key)
            if done is not None:
                return {**done, "replayed": True}
            e = self.get(exam_id)
            jobs = self._jobs_by_exam([exam_id])[exam_id]
            st = self.print_state(e, jobs, self._pending())
            if st in ("receiving", "awaiting"):
                raise ValidationError("O exame ainda está sendo recebido. Aguarde a conclusão para imprimir.")
            active = [j for j in jobs if j["state"] in ACTIVE_JOB]
            if active:
                raise ValidationError(f"O exame já está na fila de impressão (trabalho #{active[0]['id']}, "
                                      f"{JobState(active[0]['state']).label}). Nada foi duplicado.")
            base = self._base_jobs(jobs)
            if not base:
                raise ValidationError("Não há imagens disponíveis para imprimir neste exame.")
            last = self.last_print(jobs)
            duplicate = last is not None
            if duplicate:
                if not confirm_duplicate:
                    raise DuplicatePrint(f"Este exame já foi impresso ({last['count']} vez(es); última em "
                                         f"{from_iso(last['at']).astimezone():%d/%m/%Y %H:%M} na "
                                         f"{last['printer'] or 'impressora padrão'}).", last)
                user.require("reprint")
                if self.setting("reception.reprint_reason") and not (reason or "").strip():
                    raise ValidationError("Informe o motivo da reimpressão.")
            if copies is not None and not 1 <= int(copies) <= 99:
                raise ValidationError("Cópias devem estar entre 1 e 99.")
            if printer and self.printers is not None:
                from app.printing.service import is_pdf
                if not is_pdf(printer) and self.printers.get_record(printer) is None:
                    self.printers.refresh()
                    if self.printers.get_record(printer) is None:
                        raise ValidationError(f"Impressora não encontrada: {printer}.")
            created: list[int] = []
            if not duplicate and not now:
                held = [j for j in base if j["state"] == "held"]
                failed = [j for j in base if j["state"] == "failed"]
                for j in held:
                    self.jobs.release(j["id"], actor=user.actor)
                    self._set_requested(j["id"], user.actor)
                    created.append(j["id"])
                for j in failed:
                    self.jobs.retry(j["id"], actor=user.actor)
                    self._set_requested(j["id"], user.actor)
                    created.append(j["id"])
            if not created:
                for j in base:
                    if j["state"] == "cancelled":
                        continue
                    new = self.jobs.reprint(j["id"], actor=user.actor, printer=printer or None,
                                            copies=int(copies) if copies else None)
                    self._set_requested(new, user.actor)
                    created.append(new)
                if not now:
                    for j in base:                   # o original retido deixa de aparecer como pendente
                        if j["state"] == "held":
                            self.jobs.cancel(j["id"], actor=user.actor)
            if not created:
                raise ValidationError("Nenhum trabalho de impressão pôde ser criado para este exame.")
            action = "reprint" if duplicate else ("print_now" if now else "print")
            detail = {"printer": printer, "copies": copies, "reason": reason, "duplicate": duplicate}
            self._event(exam_id, user.actor, action, detail, created)
            if duplicate:
                self.events.add(level="WARNING", category="job", action="reception.duplicate",
                                message=f"Exame #{exam_id} impresso novamente por {user.username}"
                                        + (f" (motivo: {reason})" if reason else "") + ".", actor=user.actor,
                                device_id=e["device_id"])
            result = {"ok": True, "jobs": created, "duplicate": duplicate, "action": action}
            self._remember(request_key, exam_id, kind, user.actor, result)
            return result

    def _set_requested(self, job_id: int, actor: str) -> None:
        self.db.connection().execute("UPDATE jobs SET requested_by = ? WHERE id = ?", (actor, job_id))

    # ------------------------------------------------------------------ retirada
    def set_pickup(self, exam_id: int, user, state: str, *, note: str | None = None,
                   delivered_to: str | None = None, request_key: str | None = None) -> dict[str, Any]:
        if state not in PICKUP_STATES:
            raise ValidationError("Situação de retirada inválida.")
        user.require("pickup_cancel" if state == "entrega_cancelada" else "pickup")
        with self._lock:
            done = self._replay(request_key)
            if done is not None:
                return {**done, "replayed": True}
            e = self.get(exam_id)
            if e["pickup_state"] == "entregue" and state != "entrega_cancelada":
                raise ValidationError("Exame já entregue. Para corrigir, um supervisor deve cancelar a entrega.")
            if state == "entregue" and not (delivered_to or "").strip():
                raise ValidationError("Informe a quem o exame foi entregue (nome ou documento).")
            self.db.connection().execute(
                """UPDATE exams SET pickup_state = ?, pickup_at = ?, pickup_by = ?, pickup_note = ?,
                       delivered_to = CASE WHEN ? = 'entregue' THEN ? ELSE delivered_to END WHERE id = ?""",
                (state, utc_now_iso(), user.actor, note, state, (delivered_to or "").strip() or None, exam_id))
            self._event(exam_id, user.actor, f"pickup.{state}",
                        {"note": note, "delivered_to": (delivered_to or None) if state == "entregue" else None,
                         "from": e["pickup_state"]})
            result = {"ok": True, "pickup_state": state, "label": PICKUP_STATES[state]}
            self._remember(request_key, exam_id, "pickup", user.actor, result)
            return result

    def log_view(self, exam_id: int, user) -> None:
        self._event(exam_id, user.actor, "view", None)

    # ------------------------------------------------------------------ alertas
    def alerts(self) -> list[dict[str, Any]]:
        conn = self.db.connection()
        now = utc_now()
        out: list[dict[str, Any]] = []

        def add(level: str, kind: str, text: str, exam_id: int | None = None) -> None:
            out.append({"level": level, "kind": kind, "text": text, "exam_id": exam_id})

        if self.printers is not None:
            used = {r[0] for r in conn.execute(
                "SELECT DISTINCT p.name FROM jobs j JOIN printers p ON p.id = j.printer_id WHERE j.created_at >= ?",
                (to_iso(now - timedelta(days=7)),))}
            for p in self.printers.list():
                if p.name in used and not p.available:
                    add("error", "printer", f"Impressora indisponível: {p.name}.")
        for r in conn.execute("""SELECT j.id, j.exam_id, j.state_reason FROM jobs j WHERE j.state = 'failed'
                                 AND j.updated_at >= ? ORDER BY j.id DESC LIMIT 20""",
                              (to_iso(now - timedelta(hours=24)),)):
            add("error", "failed", f"Falha de impressão no trabalho #{r['id']}: {(r['state_reason'] or '')[:120]}",
                r["exam_id"])
        stuck = int(self.setting("reception.stuck_minutes"))
        for r in conn.execute("""SELECT id, exam_id, state FROM jobs WHERE state IN
                                 ('received','validating','processing','waiting_print') AND updated_at <= ?""",
                              (to_iso(now - timedelta(minutes=stuck)),)):
            add("warning", "stuck", f"Trabalho #{r['id']} parado na fila há mais de {stuck} min "
                                    f"({JobState(r['state']).label}).", r["exam_id"])
        pend = self._pending()
        incomplete = int(self.setting("reception.incomplete_minutes"))
        for study, last in pend.items():
            if (now - from_iso(last)).total_seconds() > incomplete * 60:
                ex = conn.execute("SELECT id FROM exams WHERE study_uid = ?", (study,)).fetchone()
                add("warning", "incomplete", f"Exame incompleto: sem novas imagens há mais de {incomplete} min e "
                                             "ainda não concluído.", ex["id"] if ex else None)
        for r in conn.execute("""SELECT exam_id, at FROM exam_events WHERE action = 'reprint' AND at >= ?
                                 ORDER BY id DESC LIMIT 10""", (to_iso(now - timedelta(hours=24)),)):
            add("info", "duplicate", "Impressão duplicada registrada (reimpressão).", r["exam_id"])
        try:
            free_gb = shutil.disk_usage(self.storage_root).free / 1024 ** 3
            if free_gb < float(self.setting("reception.min_free_gb")):
                add("error", "disk", f"Espaço em disco insuficiente: {free_gb:.1f} GB livres.")
        except (OSError, AttributeError):
            pass
        hours = int(self.setting("reception.pickup_alert_hours"))
        n = conn.execute("""SELECT COUNT(*) FROM exams WHERE pickup_state = 'pronto' AND pickup_at <= ?
                            AND purged_at IS NULL""", (to_iso(now - timedelta(hours=hours)),)).fetchone()[0]
        if n:
            add("info", "pickup", f"{n} exame(s) pronto(s) aguardando retirada há mais de {hours} h.")
        return out

    storage_root = "."

    # ------------------------------------------------------------------ relatórios
    def report(self, *, group: str, date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
        """Por modalidade, regra/equipamento, impressora, usuário ou dia. Folhas: enviadas ao spooler
        (estimativa de consumo) × confirmadas pelo driver; economia estimada pela impressão sob demanda."""
        cols = {"modality": "COALESCE(j.modality, '—')", "rule": "COALESCE(d.name, '—')",
                "printer": "COALESCE(p.name, '—')", "user": "COALESCE(j.requested_by, 'automática')",
                "day": "substr(j.created_at, 1, 10)"}
        if group not in cols:
            raise ValidationError("Agrupamento inválido.")
        args: list = []
        where = "j.source_type <> 'test_page'"
        if date_from:
            where += " AND j.created_at >= ?"
            args.append(to_iso(from_iso(date_from + "T00:00:00-03:00")))
        if date_to:
            where += " AND j.created_at <= ?"
            args.append(to_iso(from_iso(date_to + "T23:59:59-03:00")))
        rows = [dict(r) for r in self.db.connection().execute(
            f"""SELECT {cols[group]} AS chave, COUNT(*) AS trabalhos,
                       COUNT(DISTINCT j.exam_id) AS exames,
                       SUM(CASE WHEN j.state IN ('spooled','completed') THEN COALESCE(j.page_count,0) * j.copies ELSE 0 END)
                           AS folhas_enviadas,
                       SUM(CASE WHEN j.state = 'completed' THEN COALESCE(j.page_count,0) * j.copies ELSE 0 END)
                           AS folhas_confirmadas,
                       SUM(CASE WHEN j.source_type = 'reprint' THEN 1 ELSE 0 END) AS reimpressoes,
                       SUM(CASE WHEN j.state = 'failed' THEN 1 ELSE 0 END) AS falhas
                FROM jobs j LEFT JOIN devices d ON d.id = j.device_id LEFT JOIN printers p ON p.id = j.printer_id
                WHERE {where} GROUP BY chave ORDER BY trabalhos DESC""", args)]
        saved = self.saved_sheets(date_from, date_to)
        return {"group": group, "rows": rows, "saved_estimate": saved,
                "note": "Folhas enviadas = páginas × cópias aceitas pelo spooler (estimativa de consumo). Folhas "
                        "confirmadas = trabalhos que o driver informou como impressos. Economia = exames sob demanda "
                        "nunca impressos × páginas estimadas pelo layout (estimativa)."}

    def saved_sheets(self, date_from: str | None = None, date_to: str | None = None) -> dict[str, int]:
        args: list = []
        where = "j.state = 'held' AND j.source_type IN ('storage','dicom_print')"
        if date_from:
            where += " AND j.created_at >= ?"
            args.append(to_iso(from_iso(date_from + "T00:00:00-03:00")))
        if date_to:
            where += " AND j.created_at <= ?"
            args.append(to_iso(from_iso(date_to + "T23:59:59-03:00")))
        exams, sheets = set(), 0
        for r in self.db.connection().execute(
                f"""SELECT j.exam_id, j.copies, j.page_count, j.settings_json,
                           (SELECT COUNT(*) FROM job_items ji WHERE ji.job_id = j.id) AS items
                    FROM jobs j WHERE {where}
                      AND NOT EXISTS (SELECT 1 FROM jobs k WHERE k.exam_id = j.exam_id AND k.id <> j.id
                                      AND k.state IN ('spooled','completed'))""", args):
            exams.add(r["exam_id"])
            pages = r["page_count"]
            if not pages:
                try:
                    from app.printing.paper import parse_layout
                    rws, cls = parse_layout(json.loads(r["settings_json"]).get("layout") or "1x1")
                    pages = math.ceil(r["items"] / (rws * cls))
                except Exception:  # noqa: BLE001
                    pages = 1
            sheets += pages * int(r["copies"] or 1)
        return {"exams": len(exams), "sheets": sheets}

    # ------------------------------------------------------------------ retenção
    def purge(self) -> int:
        """Remove os dados de identificação dos exames cujas imagens já foram apagadas."""
        conn = self.db.connection()
        cur = conn.execute(
            """UPDATE exams SET purged_at = ?, patient_name = NULL, patient_id = NULL, accession = NULL,
                   admission_id = NULL, study_desc = NULL, delivered_to = NULL, pickup_note = NULL
               WHERE purged_at IS NULL AND NOT EXISTS (SELECT 1 FROM instances i WHERE i.study_uid = exams.study_uid)
                 AND last_received_at <= ?""", (utc_now_iso(), to_iso(utc_now() - timedelta(hours=1))))
        return cur.rowcount
