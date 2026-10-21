"""Regras de negócio do cadastro de equipamentos (§5).

Toda alteração é validada, gravada com histórico (``change_history``) e auditada (``events``).
Excluir um equipamento que já possui imagens ou trabalhos não é permitido: ele é desativado,
preservando a rastreabilidade.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from app.core.errors import SettingsValidationError, ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventFilter, EventRecord, EventRepository
from app.database.repositories.settings_repo import ChangeHistoryRepository
from app.devices.repository import ANY_AE, EDITABLE, Device, DeviceRepository
from app.security import validators as v
from app.utils.logging_setup import get_logger

log = get_logger("devices")

MODALITIES: tuple[tuple[str, str], ...] = (
    ("CT", "Tomografia computadorizada"), ("MR", "Ressonância magnética"),
    ("CR", "Radiografia computadorizada"), ("DX", "Radiografia digital"), ("US", "Ultrassom"),
    ("MG", "Mamografia"), ("XA", "Angiografia"), ("RF", "Radiofluoroscopia"),
    ("NM", "Medicina nuclear"), ("PT", "PET"), ("OT", "Outros"),
)
EXPORT_FORMAT = "vyonix-devices"


class DeviceService:
    def __init__(self, db: Database, events: EventRepository,
                 echo: Callable[[Device], dict[str, Any]] | None = None,
                 device_limit: Callable[[], int | None] | None = None,
                 settings_get: Callable[[str], Any] | None = None) -> None:
        self.device_limit = device_limit
        self.settings_get = settings_get
        self.db = db
        self.repo = DeviceRepository(db)
        self.history = ChangeHistoryRepository(db)
        self.events = events
        self._echo = echo
        self._listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------------ consulta
    def list(self, include_inactive: bool = False) -> list[Device]:
        return self.repo.list(include_inactive)

    def get(self, device_id: int) -> Device:
        d = self.repo.get(device_id)
        if d is None:
            raise ValidationError(f"Equipamento {device_id} não encontrado.")
        return d

    def history_events(self, device_id: int, limit: int = 200) -> list[EventRecord]:
        return self.events.query(EventFilter(device_id=device_id, limit=limit))

    # ----------------------------------------------------------------- validação
    def validate(self, data: Mapping[str, Any], *, device_id: int | None = None) -> dict[str, Any]:
        errors: dict[str, str] = {}
        clean: dict[str, Any] = {}

        def run(key: str, fn: Callable[[Any], Any], optional: bool = True) -> None:
            value = data.get(key)
            if optional and (value is None or (isinstance(value, str) and not value.strip())):
                clean[key] = None
                return
            try:
                clean[key] = fn(value)
            except ValidationError as exc:
                errors[key] = str(exc)

        def required_text(label: str, n: int):
            def _f(value: Any) -> str:
                text = v.free_text(n, label)(value)
                if not text:
                    raise ValidationError(f"{label} é obrigatório.")
                return text
            return _f

        run("name", required_text("Nome da regra", 120), optional=False)
        called = data.get("called_ae")
        if called is None or (isinstance(called, str) and not called.strip()):
            # Sem destino informado: AE padrão do serviço (compatível com cadastros da 1.0.0).
            data = {**dict(data), "called_ae": self._default_ae(data.get("service") or "store")}
        run("called_ae", v.validate_ae_title, optional=False)
        calling = data.get("ae_title")
        if calling in (None, "", "*") or (isinstance(calling, str) and not calling.strip()):
            clean["ae_title"] = ANY_AE
        else:
            run("ae_title", v.validate_ae_title)
        for key, label, n in (("manufacturer", "Fabricante", 120), ("model", "Modelo", 120),
                              ("site", "Unidade", 120), ("department", "Setor", 120),
                              ("notes", "Observações", 2000)):
            run(key, v.free_text(n, label))
        run("ip_address", v.validate_ip_restriction)
        run("port", v.validate_port)
        run("listen_port", v.validate_port)
        service = data.get("service") or "store"
        if service not in ("store", "print"):
            errors["service"] = "Serviço inválido (C-STORE ou DICOM Print)."
        clean["service"] = service
        modality = data.get("modality")
        if modality in (None, ""):
            clean["modality"] = None
        elif modality not in dict(MODALITIES):
            errors["modality"] = "Modalidade inválida."
        else:
            clean["modality"] = modality
        for key in ("printer_id", "print_profile_id"):
            value = data.get(key)
            clean[key] = int(value) if value not in (None, "") else None

        if not errors:
            self._check_route(clean, device_id, errors)
        if errors:
            raise SettingsValidationError(errors)
        return clean

    def _default_ae(self, service: str) -> str:
        get = self.settings_get
        if get is None:
            return "VYONIX" if service == "store" else "VYONIX_PRINT"
        return str(get("dicom.storage.ae_title" if service == "store" else "dicom.print.ae_title"))

    def default_port(self, service: str) -> int:
        get = self.settings_get
        if get is None:
            return 11112 if service == "store" else 11113
        return int(get("dicom.storage.port" if service == "store" else "dicom.print.port"))

    def _check_route(self, clean: dict[str, Any], device_id: int | None, errors: dict[str, str]) -> None:
        """Sem ambiguidade silenciosa (porta + Called AE + Calling AE) e sem conflito de portas entre serviços."""
        from app.dicom import routing
        svc = clean["service"]
        cand = Device(id=device_id, name=clean["name"], ae_title=clean["ae_title"], called_ae=clean["called_ae"],
                      listen_port=clean.get("listen_port"), service=svc, active=True,
                      ip_address=clean.get("ip_address"))
        dup = routing.conflicts(self.repo.routes(svc), cand, self.default_port(svc))
        if dup:
            errors["called_ae"] = (f"Já existe a regra “{dup[0].name}” com o mesmo AE Title de destino, porta e "
                                   "Calling AE Title. Use outro AE Title de destino ou informe um Calling AE Title "
                                   "(ou faixas de IP sem sobreposição) em Restrições de origem.")
            errors["ae_title"] = errors["called_ae"]
        other = "print" if svc == "store" else "store"
        port = cand.effective_port(self.default_port(svc))
        other_ports = {self.default_port(other)} | {r.listen_port for r in self.repo.routes(other) if r.listen_port}
        if port in other_ports:
            errors["listen_port"] = (f"A porta {port} é usada pelo serviço "
                                     f"{'DICOM Print' if other == 'print' else 'C-STORE'}; escolha outra.")

    # ------------------------------------------------------------------- escrita
    def _check_limit(self) -> None:
        limit = self.device_limit() if self.device_limit else None
        if limit is None:
            return
        n = self.db.connection().execute(
            "SELECT COUNT(*) FROM devices WHERE active = 1 AND authorized = 1").fetchone()[0]
        if n >= limit:
            from app.core.errors import ValidationError
            raise ValidationError(f"A licença permite {limit} equipamento(s) autorizado(s). Bloqueie outro "
                                  "equipamento ou amplie a licença.")

    def _match_import(self, item) -> Device | None:
        svc = item.get("service") or "store"
        called = str(item.get("called_ae") or "")
        calling = item.get("ae_title") or ANY_AE
        for d in self.repo.routes(svc):
            if (d.called_ae or "") == called and (d.ae_title or ANY_AE) == calling and \
                    (d.listen_port or None) == (item.get("listen_port") or None):
                return d
        return None

    def create(self, data: Mapping[str, Any], *, actor: str, authorized: bool = False) -> Device:
        clean = self.validate(data)
        if authorized:
            self._check_limit()
        with self.db.transaction():
            device_id = self.repo.insert(Device(id=None, authorized=authorized, **clean))
            self.history.record(entity_type="device", entity_id=str(device_id), field="created",
                                old_value=None, new_value=clean, actor=actor)
            self.events.add(level="INFO", category=Category.DEVICE, action="device.create",
                            message=f"Regra DICOM \"{clean['name']}\" criada (destino {clean['called_ae']}).",
                            device_id=device_id, actor=actor)
        self._notify()
        return self.get(device_id)

    def update(self, device_id: int, data: Mapping[str, Any], *, actor: str) -> Device:
        current = self.get(device_id)
        merged = {**{k: getattr(current, k) for k in EDITABLE}, **dict(data)}
        clean = self.validate(merged, device_id=device_id)
        diff = {k: (getattr(current, k), val) for k, val in clean.items() if getattr(current, k) != val}
        if diff:
            with self.db.transaction():
                self.repo.update_fields(device_id, {k: n for k, (_, n) in diff.items()})
                for key, (old, new) in diff.items():
                    self.history.record(entity_type="device", entity_id=str(device_id), field=key,
                                        old_value=old, new_value=new, actor=actor)
                self.events.add(level="INFO", category=Category.DEVICE, action="device.update",
                                message=f"Regra DICOM \"{clean['name']}\" alterada.",
                                device_id=device_id, actor=actor,
                                details={"fields": sorted(diff)})
            self._notify()
        return self.get(device_id)

    def set_authorized(self, device_id: int, authorized: bool, *, actor: str) -> Device:
        d = self.get(device_id)
        if authorized and not d.authorized:
            self._check_limit()
        if d.authorized != authorized:
            with self.db.transaction():
                self.repo.update_fields(device_id, {"authorized": authorized})
                self.history.record(entity_type="device", entity_id=str(device_id),
                                    field="authorized", old_value=d.authorized, new_value=authorized,
                                    actor=actor)
                self.events.add(level="INFO" if authorized else "WARNING", category=Category.SECURITY,
                                action="device.authorize" if authorized else "device.block",
                                message=f"Regra DICOM \"{d.name}\" "
                                        f"{'habilitada' if authorized else 'desabilitada'}.",
                                device_id=device_id, actor=actor)
            self._notify()
        return self.get(device_id)

    def remove(self, device_id: int, *, actor: str) -> str:
        """Exclui se não houver referências; caso contrário, desativa. Retorna a ação feita."""
        d = self.get(device_id)
        with self.db.transaction():
            if self.repo.has_references(device_id):
                self.repo.update_fields(device_id, {"active": False, "authorized": False})
                action = "deactivated"
            else:
                self.repo.delete(device_id)
                action = "deleted"
            self.history.record(entity_type="device", entity_id=str(device_id), field=action,
                                old_value=d.to_dict(), new_value=None, actor=actor)
            self.events.add(level="INFO", category=Category.DEVICE, action=f"device.{action}",
                            message=f"Regra DICOM \"{d.name}\" "
                                    f"{'desativada (possui histórico)' if action == 'deactivated' else 'excluída'}.",
                            device_id=device_id if action == "deactivated" else None, actor=actor)
        self._notify()
        return action

    # ------------------------------------------------------------ conectividade
    def echo(self, device_id: int, *, actor: str) -> dict[str, Any]:
        """C-ECHO do VYONIX para o equipamento (requer IP e porta cadastrados)."""
        d = self.get(device_id)
        if not d.ip_address or not d.port:
            raise ValidationError("Cadastre o endereço IP e a porta do equipamento para testar.")
        if self._echo is None:
            raise ValidationError("Cliente DICOM indisponível.")
        result = self._echo(d)
        status = "ok" if result.get("ok") else "falha"
        self.repo.set_status(device_id, f"echo {status}")
        if result.get("ok"):
            self.repo.touch_seen(device_id, "echo ok")
        self.events.add(level="INFO" if result.get("ok") else "WARNING", category=Category.DICOM,
                        action="device.echo", message=f"C-ECHO para \"{d.name}\": {result.get('detail')}",
                        device_id=device_id, actor=actor,
                        details={k: result.get(k) for k in ("ok", "status", "ms")})
        return result

    # ----------------------------------------------------- importar / exportar
    def export_json(self, path: Path) -> int:
        items = []
        for d in self.repo.list(include_inactive=False):
            item = {k: getattr(d, k) for k in EDITABLE if k not in ("printer_id", "print_profile_id")}
            item["authorized"] = d.authorized
            items.append(item)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"format": EXPORT_FORMAT, "format_version": 1, "devices": items},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        return len(items)

    def import_json(self, path: Path, *, actor: str) -> dict[str, int]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SettingsValidationError({"arquivo": f"Não foi possível ler o arquivo: {exc}"})
        if not isinstance(payload, dict) or payload.get("format") != EXPORT_FORMAT:
            raise SettingsValidationError({"arquivo": "Arquivo não é uma exportação de equipamentos do VYONIX."})
        created = updated = 0
        errors: dict[str, str] = {}
        items = payload.get("devices") or []
        default_ae = self.settings_get("dicom.storage.ae_title") if self.settings_get else "VYONIX"
        for item in items:                      # exportações da 1.0.0: o destino era o AE local
            if isinstance(item, dict) and not item.get("called_ae"):
                item["called_ae"] = default_ae
        # Valida tudo antes de gravar qualquer coisa.
        for i, item in enumerate(items):
            try:
                existing = self._match_import(item)
                self.validate(item, device_id=existing.id if existing else None)
            except SettingsValidationError as exc:
                errors[f"item {i + 1}"] = "; ".join(f"{k}: {m}" for k, m in exc.errors.items())
        if errors:
            raise SettingsValidationError(errors)
        with self.db.transaction():
            for item in items:
                existing = self._match_import(item)
                data = {k: item.get(k) for k in EDITABLE if k in item}
                if existing:
                    self.update(existing.id, data, actor=actor)
                    updated += 1
                else:
                    self.create(data, actor=actor, authorized=bool(item.get("authorized")))
                    created += 1
        return {"created": created, "updated": updated}

    # ----------------------------------------------------------------- ouvintes
    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                log.exception("Falha em ouvinte de equipamentos")


__all__ = ["DeviceService", "MODALITIES", "Device", "replace"]
