"""Backup e restauração do PACS, independentes do motor (exportação verificada pelo índice).

* ``export``: para cada instância indexada na organização, lê o arquivo do motor, confere o SHA-256 registrado na
  entrada e grava em ``<destino>/<Study UID>/<Series UID>/<SOP UID>.dcm`` (gravação atômica). Incremental: arquivo já
  presente com o mesmo SHA-256 não é regravado. Instância com integridade violada no motor **não** é copiada e entra
  no relatório. Gera ``manifest.json`` (formato ``vyonix-pacs-backup/1``) com o SHA-256 de cada arquivo.
* ``verify``: confere o backup contra o manifesto (faltando, alterado, sobrando).
* ``restore``: confere o backup e reenvia cada arquivo pela entrada normal do PACS (validação, SHA-256, índice,
  auditoria) — idempotente; nunca sobrescreve conteúdo divergente. Instância já indexada cujo arquivo sumiu do motor
  (armazenamento perdido com o índice intacto) é devolvida ao motor e religada ao índice. Por padrão só restaura na
  mesma organização.

Nada aqui apaga dados no motor, no índice ou no destino. O backup contém dados de pacientes: a pasta de destino
precisa de acesso restrito (o DEPLOY aplica permissões mínimas às pastas que cria).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FORMAT = "vyonix-pacs-backup/1"
MANIFEST = "manifest.json"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(study: str, series: str, sop: str) -> str:
    return f"{study}/{series}/{sop}.dcm"


def export(db, tenant_id: uuid.UUID, backend, dest: Path, *, actor: str = "backup") -> dict[str, Any]:
    from sqlalchemy import select
    from vyonix.audit import service as audit
    from vyonix.pacs.models import PacsInstance, PacsSeries, PacsStudy
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with db.session(tenant_id) as s:
        rows = [(st.study_uid, se.series_uid, it.sop_uid, it.sha256, it.size_bytes, it.backend_id)
                for it, se, st in s.execute(
                    select(PacsInstance, PacsSeries, PacsStudy)
                    .join(PacsSeries, PacsSeries.id == PacsInstance.series_id)
                    .join(PacsStudy, PacsStudy.id == PacsInstance.study_id)
                    .order_by(PacsStudy.study_uid, PacsSeries.series_uid, PacsInstance.sop_uid))]
    entries, copied, kept, failures = [], 0, 0, []
    for study, series, sop, sha, size, bid in rows:
        rel = _rel(study, series, sop)
        target = dest / rel
        if target.exists() and _sha(target) == sha:
            kept += 1
        else:
            data = backend.fetch(bid)
            if hashlib.sha256(data).hexdigest() != sha:
                failures.append({"sop_uid": sop, "reason": "SHA-256 no motor diferente do registrado na entrada"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
            copied += 1
        entries.append({"path": rel, "study_uid": study, "series_uid": series, "sop_uid": sop, "sha256": sha,
                        "size": size})
    manifest = {"format": FORMAT, "organization": str(tenant_id),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "count": len(entries),
                "bytes": sum(e["size"] for e in entries), "entries": entries}
    tmp = dest / (MANIFEST + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, dest / MANIFEST)
    out = {"instances": len(entries), "copied": copied, "already_present": kept, "integrity_failures": failures,
           "bytes": manifest["bytes"]}
    with db.session(tenant_id) as s:
        audit.record(s, actor=actor, action="pacs.backup.export", target_type="pacs",
                     details={k: (len(v) if isinstance(v, list) else v) for k, v in out.items()} | {"dest": str(dest)},
                     tenant_id=tenant_id)
    return out


def verify(src: Path) -> dict[str, Any]:
    src = Path(src)
    try:
        m = json.loads((src / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Backup sem manifesto válido em {src}: {exc}") from exc
    if m.get("format") != FORMAT:
        raise ValueError(f"Formato de backup desconhecido: {m.get('format')}")
    missing, altered = [], []
    listed = set()
    for e in m["entries"]:
        p = src / e["path"]
        listed.add(p.resolve())
        if not p.exists():
            missing.append(e["path"])
        elif _sha(p) != e["sha256"]:
            altered.append(e["path"])
    extra = [str(p.relative_to(src)) for p in src.rglob("*.dcm") if p.resolve() not in listed]
    return {"organization": m["organization"], "created_at": m["created_at"], "instances": m["count"],
            "ok": m["count"] - len(missing) - len(altered), "missing": missing, "altered": altered, "extra": extra,
            "valid": not missing and not altered}


def restore(db, tenant_id: uuid.UUID, backend, src: Path, *, actor: str = "restauração",
            allow_other_organization: bool = False) -> dict[str, Any]:
    from vyonix.audit import service as audit
    from vyonix.pacs import service as pacs
    v = verify(src)
    if v["organization"] != str(tenant_id) and not allow_other_organization:
        raise PermissionError("O backup é de outra organização; a restauração foi recusada (evita associar exames à "
                              "clínica errada).")
    if not v["valid"]:
        raise ValueError(f"Backup com arquivos faltando ({len(v['missing'])}) ou alterados ({len(v['altered'])}); "
                         "nada foi restaurado.")
    from sqlalchemy import select
    from vyonix.pacs.models import PacsInstance
    m = json.loads((Path(src) / MANIFEST).read_text(encoding="utf-8"))
    out = {"indexed": 0, "duplicates": 0, "reinstated": 0, "rejected": []}
    for e in m["entries"]:
        data = (Path(src) / e["path"]).read_bytes()
        with db.session(tenant_id) as s:
            it = s.execute(select(PacsInstance).where(PacsInstance.sop_uid == e["sop_uid"])).scalar_one_or_none()
            if it is not None and it.sha256 == e["sha256"]:
                # Já indexada: o motor ainda tem o arquivo íntegro? (perda do armazenamento com o índice intacto)
                try:
                    present = hashlib.sha256(backend.fetch(it.backend_id)).hexdigest() == it.sha256
                except FileNotFoundError:
                    present = False
                if present:
                    out["duplicates"] += 1
                    continue
                ref = backend.store(data)
                if hashlib.sha256(backend.fetch(ref.backend_id)).hexdigest() != it.sha256:
                    out["rejected"].append({"sop_uid": e["sop_uid"], "reason": "motor guardou conteúdo diferente"})
                    continue
                it.backend_id, it.backend = ref.backend_id, backend.name
                s.flush()
                out["reinstated"] += 1
                continue
            try:
                with s.begin_nested():
                    r = pacs.ingest(s, backend, data, actor=actor, via="stow")
                out["duplicates" if r.duplicate else "indexed"] += 1
            except pacs.InstanceRejected as exc:
                out["rejected"].append({"sop_uid": e["sop_uid"], "reason": str(exc)})
    with db.session(tenant_id) as s:
        audit.record(s, actor=actor, action="pacs.backup.restore", target_type="pacs",
                     details={"src": str(src), "indexed": out["indexed"], "duplicates": out["duplicates"],
                              "reinstated": out["reinstated"],
                              "rejected": len(out["rejected"]), "backup_created_at": v["created_at"]},
                     tenant_id=tenant_id)
    return out
