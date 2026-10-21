"""Linha de comando do licenciamento (instalador, suporte e validação automatizada).

* ``--installation install --fresh|--upgrade`` — executado pelo instalador (administrador): cria a
  chave do TPM (se houver TPM e ela ainda não existir) e define o Installation ID conforme a
  instalação seja nova ou atualização.
* ``--installation uninstall`` — executado pelo desinstalador: encerra a ativação local.
* ``--license status|request|install|demo|diagnostic|revalidation|revocation|authorization|online|
  export`` — mesmas ações da página Licença (nenhuma ação de emissão): ``authorization`` importa o
  arquivo de renovação (.vyauth), ``online`` consulta o License Server agora e ``export`` copia os
  exames armazenados para a pasta ``--file`` (disponível mesmo com a assinatura suspensa).
"""

from __future__ import annotations

import json
from pathlib import Path


def add_arguments(p) -> None:
    p.add_argument("--installation", choices=["install", "uninstall"],
                   help="uso do instalador: registra a instalação (nova/atualização) ou encerra a ativação")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--fresh", action="store_true", help="com --installation install: instalação nova")
    g.add_argument("--upgrade", action="store_true", help="com --installation install: atualização")
    p.add_argument("--license", dest="license_action",
                   choices=["status", "request", "install", "demo", "diagnostic", "revalidation", "revocation",
                            "authorization", "online", "export"],
                   help="licenciamento: situação, solicitação, instalação de licença, demonstração, diagnóstico")
    p.add_argument("--file", help="arquivo de entrada/saída para --license")


def run(args) -> int:
    from app.bootstrap import bootstrap
    from app.core.errors import VyonixError
    from app.database.repositories.events_repo import Category
    report: dict = {"ok": False}
    try:
        ctx = bootstrap(data_dir=args.data_dir, role="installer" if args.installation else "check")
    except VyonixError as exc:
        report["error"] = str(exc)
        return _done(args, report, 3)
    try:
        lic = ctx.license
        if args.installation == "install":
            legacy = ctx.settings.repo.get_raw("system.installation_id")
            legacy = json.loads(legacy) if isinstance(legacy, str) and legacy.startswith('"') else legacy
            tpm_info = lic.tpm.provision() if hasattr(lic.tpm, "provision") else {"available": False}
            mode = "upgrade" if args.upgrade else "fresh"
            rec, what = lic.installation.provision(mode, legacy_id=str(legacy) if legacy else None)
            ctx.settings.repo.upsert("system.installation_id", rec["installation_id"], "installer")
            ctx.events.add(level="INFO", category=Category.LICENSE, action=f"installation.{mode}",
                           message=f"Instalador: {what} ({rec['installation_id']}).", actor="installer",
                           details={"origin": rec.get("origin"), "tpm": tpm_info.get("available")})
            report.update(ok=True, mode=mode, result=what, installation_id=rec["installation_id"],
                          tpm={k: v for k, v in tpm_info.items() if k != "pub"},
                          hardware_id=lic.profile(refresh=True).hardware_id)
        elif args.installation == "uninstall":
            n = lic.end_activation("desinstalação do VYONIX DICOM Print")
            rec = lic.installation.uninstall()
            ctx.events.add(level="WARNING", category=Category.LICENSE, action="installation.uninstall",
                           message="Desinstalação: ativação local encerrada; uma reinstalação exigirá nova licença.",
                           actor="installer")
            report.update(ok=True, ended_licenses=n, retired=rec.get("installation_id") if rec else None)
        else:
            act = args.license_action
            out = Path(args.file) if args.file else None
            try:
                _license_action(lic, act, out, report, ctx)
            except (VyonixError, OSError, ValueError) as exc:
                report["ok"] = False
                report["error"] = str(exc)
            v = lic.verdict(refresh=True)
            prof = lic.profile()
            report["status"] = {"state": v.status.state.value, "message": v.status.message, "active": v.status.active,
                                "commercial": v.status.commercial, "connectivity": v.status.connectivity,
                                "enforced": lic.enforced, "license_id": v.status.license_id,
                                "kind": v.status.kind, "remaining_s": v.status.remaining_s}
            report["hardware_id"] = prof.hardware_id
            report["components"] = {k: bool(val) for k, val in prof.available.items()}
            report["installation_id"] = lic.installation_id()
            report["tpm"] = {k: v2 for k, v2 in (lic.tpm.info() if lic.tpm else {}).items() if k != "pub"}
    except (VyonixError, OSError, ValueError) as exc:
        report["error"] = str(exc)
    finally:
        ctx.close()
    return _done(args, report, 0 if report.get("ok") else 1)


def _license_action(lic, act: str, out: Path | None, report: dict, ctx=None) -> None:
    from app.core.errors import VyonixError
    if act in ("install", "revalidation", "revocation", "authorization") and not (out and out.is_file()):
        raise VyonixError("Informe o arquivo com --file.")
    if act == "request":
        text = lic.request_file()
        if out:
            out.write_text(text, encoding="utf-8")
        report.update(ok=True, request=json.loads(text)["summary"], code=json.loads(text)["code"])
    elif act == "install":
        st = lic.install(out.read_text(encoding="utf-8"), actor="cli")
        report.update(ok=st.active, state=st.state.value, message=st.message)
    elif act == "demo":
        st = lic.start_demo(actor="cli")
        report.update(ok=True, state=st.state.value, message=st.message)
    elif act == "diagnostic":
        d = lic.diagnostic()
        if out:
            out.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        report.update(ok=True, request_id=d["request_id"], time=d["time"], integrity=d["integrity"])
    elif act == "revalidation":
        report.update(ok=True, message=lic.apply_revalidation(out.read_text(encoding="utf-8"), actor="cli"))
    elif act == "revocation":
        report.update(ok=True, message=lic.apply_revocation(out.read_text(encoding="utf-8"), actor="cli"))
    elif act == "authorization":
        st = lic.import_authorization(out.read_text(encoding="utf-8"), actor="cli")
        report.update(ok=True, state=st.state.value, commercial=st.commercial)
    elif act == "online":
        r = lic.check_online(actor="cli")
        report.update(ok=r.result == "ok", result=r.result, message=r.message)
    elif act == "export":
        if not out or not out.is_dir():
            raise VyonixError("Informe a pasta de destino com --file.")
        res = ctx.exporter.export(out, actor="cli")
        report.update(ok=True, folder=str(res.folder), studies=res.studies, files=res.files,
                      missing=len(res.missing), mismatched=len(res.mismatched))
    else:
        report["ok"] = True


def _done(args, report: dict, code: int) -> int:
    from app.main import _emit, _write_report
    _emit(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    _write_report(args.report, report)
    return code
