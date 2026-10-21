"""CI (Windows, após a instalação): ativação de módulo pelo DEPLOY com direito assinado.

A licença é emitida por um License Manager de teste (chave descartável); o objeto de licenciamento
com essa chave pública é injetado no fluxo de ativação — o executável instalado continua aceitando
somente as chaves oficiais. Resultado em <out>/activation.json."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    out = Path(ap.parse_args().out)
    res: dict = {}
    tmp = Path(tempfile.mkdtemp(prefix="vyx-act-"))
    try:
        from tests.licensing_support import make_manager
        from vyonix.licensing.service import Licensing, Machine
        from vyonix_deploy.modules import _core, activate
        from vyonix_deploy.service import Deploy
        from vyonix_protocol import formats as F
        d = Deploy()
        cfg = d.saved_config()
        lm, admin, keys, cid = make_manager(tmp / "lm")
        lic = Licensing(Machine.build(d.paths.licensing), public_keys=keys,
                        key_scopes={k: F.ALL_SCOPES for k in keys})
        ctx = d.context(cfg)
        db, tid = _core(ctx)
        from vyonix.modules import registry
        with db.session(tid) as s:
            res["before_enabled"] = registry.is_enabled(s, "print")
        r0 = activate(d, "print", approve_all=True, licensing=lic)
        res["refused_without_license"] = r0["status"] != "succeeded"
        res["without_license"] = {"status": r0["status"], "message": r0["message"]}
        req = lic.request(modules=["core", "print"], demo_days=None, organization="Clínica CI",
                          contact={"name": "CI", "email": "ci@exemplo.com"})
        info = lm.import_request(admin, req["code"])
        doc = lm.issue(admin, info.request_id, cid, ltype="annual", edition="Profissional",
                       modules={"core": {"kind": "contract"}})["document"]
        with db.session(tid) as s:
            lic.install(s, doc, actor="CI")
        r = activate(d, "print", approve_all=True, licensing=lic)
        res.update(status=r["status"], message=r["message"], run_id=r["run_id"], report=r["report"]["pdf"])
        steps = d.db.steps(r["run_id"])
        res["steps"] = [(s["step_id"], s["status"], s.get("verify_msg")) for s in steps]
        with db.session(tid) as s:
            res["after_enabled"] = registry.is_enabled(s, "print")
        db.dispose()
        lm.close()
        d.close()
    except Exception as exc:  # noqa: BLE001
        import traceback
        res["status"] = "error"
        res["error"] = traceback.format_exc()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    (out / "activation.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0 if res.get("status") == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
