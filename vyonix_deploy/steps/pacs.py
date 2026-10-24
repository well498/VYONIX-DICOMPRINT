"""VYONIX PACS no servidor: motor DICOM (Orthanc oficial, sem plugins) como serviço supervisionado e
configuração do Core para usá-lo. Aplicado pela ativação do módulo ``pacs`` (sem reinstalar).

* REST do Orthanc só para a própria máquina (``RemoteAccessAllowed: false``) e com usuário e senha; a senha
  é gerada aqui, guardada no cofre do Core (``pacs_orthanc_password``) e escrita na configuração do Orthanc,
  que só o sistema, os administradores e o serviço podem ler. A porta REST não é aberta no firewall.
* Porta DICOM aberta só na rede local (mesma regra do Core). C-STORE das modalidades é indexado pela
  sincronização do Core (modo edge).
* Nenhum plugin é carregado (ADR-0012); o serviço se recusa a iniciar com plugins configurados.
"""

from __future__ import annotations

import json
from pathlib import Path

from vyonix_deploy.engine import Context, Step
from vyonix_deploy.errors import DeployError

SERVICE = "VyonixPacsEngine"
USER = "vyonix"
SECRET = "pacs_orthanc_password"
HTTP_PORT = 8042
DICOM_PORT = 4242
AET = "VYONIX_PACS"
QR_PORT = 4243           # consulta/recuperação DICOM (C-FIND/C-MOVE) servida pelo Core
QR_AET = "VYONIX_QR"


def storage_dir(ctx: Context) -> Path:
    return ctx.paths.data_dir.parent / "PACS"


def config_file(ctx: Context) -> Path:
    return ctx.paths.data_dir / "pacs" / "orthanc.json"


def binary(ctx: Context) -> Path:
    return ctx.paths.install_dir / "orthanc" / "Orthanc.exe"


def _store(ctx: Context):
    from vyonix.secrets import SecretStore
    return SecretStore(ctx.paths.data_dir)


def engine_config(ctx: Context, password: str) -> dict:
    st = str(storage_dir(ctx))
    return {
        "Name": f"VYONIX PACS ({ctx.cfg.organization})",
        "StorageDirectory": st, "IndexDirectory": st, "StorageCompression": False,
        "HttpServerEnabled": True, "HttpPort": HTTP_PORT, "RemoteAccessAllowed": False,
        "AuthenticationEnabled": True, "RegisteredUsers": {USER: password},
        "DicomServerEnabled": True, "DicomAet": AET, "DicomPort": DICOM_PORT, "DicomCheckCalledAet": True,
        "DicomAlwaysAllowStore": True, "DicomAlwaysAllowEcho": True,
        # Consulta/recuperação DIMSE direto no motor passaria por fora da autorização e do isolamento do Core:
        # desligadas explicitamente e nenhuma modalidade cadastrada (o acesso às imagens é pelo DICOMweb do Core).
        "DicomAlwaysAllowFind": False, "DicomAlwaysAllowFindWorklist": False, "DicomAlwaysAllowGet": False,
        "DicomAlwaysAllowMove": False, "DicomModalities": {},
        "OverwriteInstances": False, "Plugins": [], "LoadPrivateDictionary": True,
        "StableAge": 60, "SaveJobs": True, "DeidentifyLogs": True,
    }


def core_settings() -> dict:
    return {"pacs_orthanc_url": f"http://127.0.0.1:{HTTP_PORT}", "pacs_orthanc_username": USER,
            "pacs_qr_port": QR_PORT, "pacs_qr_aet": QR_AET}


class EngineConfigStep(Step):
    """Configuração do Orthanc (gerada) e senha do usuário REST (cofre do Core)."""
    category = "modulo"
    id = "pacs.engine.config"
    title = "Configuração do motor DICOM do PACS"

    def _expected(self, ctx: Context) -> dict:
        return engine_config(ctx, _store(ctx).get_or_create_text(SECRET))

    def observe(self, ctx: Context) -> dict:
        f = config_file(ctx)
        out = {"binary": binary(ctx).exists(), "config_file": f.exists()}
        if f.exists():
            try:
                cur = json.loads(f.read_text(encoding="utf-8"))
                out["current"] = cur == self._expected(ctx)
                out["plugins"] = cur.get("Plugins", [])
            except ValueError:
                out["current"] = False
        return out

    def desired(self, ctx: Context) -> dict:
        exp = self._expected(ctx)
        exp["RegisteredUsers"] = {USER: "(cofre do Core)"}
        return {"binary": str(binary(ctx)), "config": exp}

    def describe(self, ctx: Context) -> dict:
        return {"current": {k: v for k, v in self.observe(ctx).items()}, "proposed": self.desired(ctx),
                "impact": f"Grava a configuração do Orthanc (REST só local em {HTTP_PORT}, com senha; DICOM {AET} na "
                          f"porta {DICOM_PORT}; sem plugins). Imagens em {storage_dir(ctx)}.",
                "undo": "Remove a configuração gerada agora (as imagens recebidas nunca são apagadas)."}

    def check(self, ctx: Context) -> bool:
        o = self.observe(ctx)
        return bool(o["binary"] and o.get("current"))

    def capture(self, ctx: Context) -> dict:
        return {"config_file": config_file(ctx).exists()}

    def apply(self, ctx: Context) -> None:
        if not binary(ctx).exists():
            raise DeployError(f"Motor DICOM ausente na instalação ({binary(ctx)}). Atualize o VYONIX pelo DEPLOY.")
        f = config_file(ctx)
        f.parent.mkdir(parents=True, exist_ok=True)
        storage_dir(ctx).mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._expected(ctx), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)

    def rollback(self, ctx: Context, before: dict) -> None:
        if not before.get("config_file"):
            config_file(ctx).unlink(missing_ok=True)

    def how_to_check(self) -> str:
        return "Conferir <dados>\\pacs\\orthanc.json (Plugins vazio, RemoteAccessAllowed false)"


class CoreSettingsStep(Step):
    """Endereço e usuário do motor na configuração do Core (preservados pelos reparos do Core)."""
    category = "modulo"
    id = "pacs.core.settings"
    title = "Core configurado para o motor DICOM"

    def _file(self, ctx: Context) -> Path:
        return ctx.paths.data_dir / "config.json"

    def observe(self, ctx: Context) -> dict:
        try:
            cur = json.loads(self._file(ctx).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"config_file": False}
        return {"config_file": True, **{k: cur.get(k) for k in core_settings()}}

    def desired(self, ctx: Context) -> dict:
        return {"config_file": True, **core_settings()}

    def check(self, ctx: Context) -> bool:
        return self.observe(ctx) == self.desired(ctx)

    def capture(self, ctx: Context) -> dict:
        return self.observe(ctx)

    def apply(self, ctx: Context) -> None:
        f = self._file(ctx)
        try:
            cur = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DeployError("Configuração do Core ausente: execute o reparo do VYONIX antes.") from exc
        cur.update(core_settings())
        f.write_text(json.dumps(cur, indent=2, ensure_ascii=False), encoding="utf-8")
        restart_core(ctx)

    def rollback(self, ctx: Context, before: dict) -> None:
        f = self._file(ctx)
        try:
            cur = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k in core_settings():
            if before.get(k) is None:
                cur.pop(k, None)
            else:
                cur[k] = before[k]
        f.write_text(json.dumps(cur, indent=2, ensure_ascii=False), encoding="utf-8")


def restart_core(ctx: Context) -> None:
    """O Core lê a configuração na partida: reinicia o serviço se ele estiver em execução."""
    from vyonix_deploy.sysrun import IS_WINDOWS
    if not IS_WINDOWS:
        return
    from vyonix_deploy.plans import CORE_SVC
    from vyonix_deploy.steps.services import SC, query_service, stop_service
    from vyonix_deploy.sysrun import run
    q = query_service(CORE_SVC)
    if q and q["state"] == "Running":
        ctx.log("INFO", "Reiniciando o VYONIX Core para usar o motor DICOM.")
        stop_service(CORE_SVC)
        run([SC, "start", CORE_SVC])


def engine_probe(ctx: Context) -> tuple[bool, str]:
    """O motor responde pela REST local com a senha do cofre e não tem plugins carregados."""
    from vyonix.pacs.orthanc import OrthancBackend
    pw = _store(ctx).get(SECRET)
    b = OrthancBackend(core_settings()["pacs_orthanc_url"], username=USER, password=pw.decode() if pw else None,
                       timeout=5)
    try:
        info = b.ping()
        plugins = [p for p in b.client.get("/plugins").json() if p != "explorer.js"]
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        b.close()
    if plugins:
        return False, f"plugins carregados (proibido pela ADR-0012): {plugins}"
    return True, f"Orthanc {info.get('version')} (DICOM {info.get('dicom_aet')}:{info.get('dicom_port')}), sem plugins"


def engine_steps(ctx: Context) -> list[Step]:
    from vyonix_deploy.steps.core import service_binpath
    from vyonix_deploy.steps.files import ADMINS, SYSTEM, AclGrantStep, AclStep, DirectoryStep
    from vyonix_deploy.steps.firewall import FirewallRuleStep
    from vyonix_deploy.steps.services import ServiceRunningStep, ServiceStep
    svc = f"NT SERVICE\\{SERVICE}"
    p = ctx.paths
    # O serviço é registrado antes das permissões: a conta virtual NT SERVICE\VyonixPacsEngine só existe
    # depois do registro (mesma ordem da instalação do Core). Falha encontrada na aceitação 2.9 do Windows.
    return [
        EngineConfigStep(),
        ServiceStep(SERVICE, "VYONIX PACS (motor DICOM)", "Armazenamento DICOM do VYONIX PACS (Orthanc, sem plugins).",
                    service_binpath(p.install_dir, "pacs-engine", p.data_dir)),
        AclStep("pacs.storage", storage_dir(ctx), "imagens do PACS", [(SYSTEM, "F"), (ADMINS, "F"), (svc, "M")]),
        AclStep("pacs.config", config_file(ctx).parent, "configuração do motor DICOM",
                [(SYSTEM, "F"), (ADMINS, "F"), (svc, "RX")]),
        DirectoryStep("logs", p.data_dir / "logs", "de registros do VYONIX"),
        AclGrantStep("logs.pacs", p.data_dir / "logs", "registros", svc, "M"),
        FirewallRuleStep("pacs-dicom", "PACS DICOM", DICOM_PORT, str(binary(ctx)), ctx.cfg.firewall_sources),
        FirewallRuleStep("pacs-qr", "PACS consulta DICOM", QR_PORT, str(p.core_exe), ctx.cfg.firewall_sources),
        ServiceRunningStep(SERVICE, "VYONIX PACS (motor DICOM)", probe=engine_probe, timeout=120),
        CoreSettingsStep(),
    ]
