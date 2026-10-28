"""CI Windows — instalador de HOMOLOGAÇÃO INTERNA: executa, no Windows real e pelo instalador gerado, o mesmo roteiro
que o proprietário vai seguir (docs/homologacao/Roteiro_Homologacao_Interna_Plataforma.md):

instalar → preparar módulos (PACS, RIS, Laudos) → entrar como gestor da clínica fictícia → cadastrar técnico,
médico e paciente fictícios → enviar estudo sintético pelo simulador (C-STORE real ao motor DICOM) → o estudo
aparece sozinho na Central de Exames → Viewer e DICOMweb → comentário, anexo, checklist → encaminhar → o médico vê o
exame na fila de laudos.

Uso: python tools/ci_homolog_acceptance.py --setup VYONIX_Homologacao_Setup_x64.exe --out dist\\acceptance
Resultado: <out>/homologacao.json e <out>/homologacao.md (passo a passo com Aprovado/Reprovado). Dados fictícios.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import ssl
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vyonix_deploy.paths import default_paths  # noqa: E402

PATHS = default_paths()
PF = Path(os.environ.get("ProgramW6432", r"C:\Program Files"))
APP = PF / "VYONIX" / "Platform"
ADMIN, ADMIN_PW = "gestor.alfa", "Gestor-Alfa-2026!"
STEPS: list[dict] = []
OUT = Path(".")


def step(name):
    def deco(fn):
        t0 = time.monotonic()
        try:
            detail = fn()
            STEPS.append({"step": name, "result": "Aprovado", "detail": str(detail or "")[:600],
                          "seconds": round(time.monotonic() - t0, 1)})
            print(f"[OK] {name}: {detail}")
            print(f"::notice title=Homologação — {name}::{str(detail or '')[:300]}")
        except Exception as exc:  # noqa: BLE001
            STEPS.append({"step": name, "result": "Reprovado", "detail": f"{type(exc).__name__}: {exc}"[:900],
                          "seconds": round(time.monotonic() - t0, 1)})
            print(f"[FALHA] {name}: {exc}\n{traceback.format_exc()[-1500:]}")
            print(f"::error title=Homologação — {name}::{type(exc).__name__}: {str(exc)[:600]}")
        return fn
    return deco


def run(args, *, timeout=1800, env=None):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout, env=e,
                       encoding="utf-8", errors="replace")
    with open(OUT / "comandos.log", "a", encoding="utf-8") as f:
        f.write(f"\n$ {' '.join(map(str, args))}\n[código {p.returncode}]\n{p.stdout[-5000:]}\n{p.stderr[-3000:]}\n")
    if p.returncode != 0:
        raise AssertionError(f"{Path(str(args[0])).name} código {p.returncode}: {(p.stdout + p.stderr)[-700:]}")
    return p


class Client:
    def __init__(self, port=8444):
        self.base = f"https://localhost:{port}"
        ctx = ssl.create_default_context(cafile=str(PATHS.data_dir / "tls" / "server.crt"))
        self.op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), urllib.request.ProxyHandler({}),
                                              urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ""

    def raw(self, method, path, body=None, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": ctype, "X-CSRF-Token": self.csrf})
        try:
            with self.op.open(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def call(self, method, path, body=None, ok=(200, 201)):
        st, data = self.raw(method, "/api/v1" + path, body)
        if st not in ok:
            raise AssertionError(f"{method} {path} → {st}: {data[:400]!r}")
        return json.loads(data or b"null")

    def login(self, user, pw):
        me = self.call("POST", "/auth/login", {"username": user, "password": pw})
        self.csrf = me["csrf"]
        return me


def first_login(user, temp, final):
    c = Client()
    me = c.login(user, temp)
    if me["stage"] == "password_change":
        c.call("POST", "/auth/password", {"current": temp, "new": final})
    c = Client()
    c.login(user, final)
    return c


def main() -> int:
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    OUT = Path(a.out).resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = OUT / "opcoes-homologacao.json"
    cfg.write_text(json.dumps({"organization": "clinica-alfa", "organization_name": "Clínica Alfa (fictícia)",
                               "admin_user": ADMIN, "https_port": 8444, "pg_port": 5544}, ensure_ascii=False),
                   encoding="utf-8")
    s: dict = {}

    @step("1. Instalar pelo VYONIX_Homologacao_Setup_x64.exe")
    def _():
        run([Path(a.setup).resolve(), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DEPLOYCONFIG={cfg}",
             f"/LOG={OUT / 'setup.log'}"], env={"VYONIX_ADMIN_PASSWORD": ADMIN_PW})
        for f in ("Preparar_Homologacao.cmd", "Enviar_Exame_Simulado.cmd", "LEIA-ME_HOMOLOGACAO.txt"):
            assert (APP / f).exists(), f"{f} ausente"
        return f"instalado em {APP}"

    @step("2. Sistema no ar como homologação interna")
    def _():
        c = Client()
        for _ in range(60):
            st, data = c.raw("GET", "/api/v1/health")
            if st == 200:
                h = json.loads(data)
                assert h["flavor"] == "homologacao", h
                return h
            time.sleep(3)
        raise AssertionError("o VYONIX não respondeu em https://localhost:8444")

    @step("3. Preparar módulos (PACS com Viewer, RIS, Laudos) — mesmo comando do atalho")
    def _():
        out = []
        for m in ("pacs", "ris", "report"):
            p = run([APP / "vyonix-deploy.exe", "activate-module", m, "--approve-all"], timeout=1200)
            out.append(f"{m}: {json.loads(p.stdout[p.stdout.index('{'):])['status']}")
        return "; ".join(out)

    @step("4. Gestor da clínica fictícia entra só com usuário e senha; módulos em homologação")
    def _():
        c = Client()
        me = c.login(ADMIN, ADMIN_PW)
        lic = c.call("GET", "/license")
        states = {m["module"]: m["state"] for m in lic["modules"] if m["module"] in ("pacs", "ris", "report")}
        assert set(states.values()) == {"homologacao"}, states
        mods = {m["code"]: m["status"] for m in c.call("GET", "/modules")}
        assert all(mods.get(x) == "enabled" for x in ("pacs", "ris", "report")), mods
        s["admin"] = c
        return f"{me['display_name']}; módulos {mods}"

    @step("5. Cadastrar técnico e médico fictícios (e o cadastro médico com vínculo)")
    def _():
        c = s["admin"]
        for u, name, role in (("tecnico.alfa", "Técnico Fictício", "tecnico"), ("dra.ficticia", "Dra. Ficticia Teste", "medico")):
            c.call("POST", "/users", {"username": u, "display_name": name, "password": "Provisoria-2026x",
                                      "roles": [{"role": role}]})
        uid = next(u["id"] for u in c.call("GET", "/users") if u["username"] == "dra.ficticia")
        pid = c.call("POST", "/report/physicians", {"user_id": uid, "full_name": "Dra. Ficticia Teste", "crm": "000001",
                                                   "crm_uf": "PB"})["id"]
        c.call("POST", f"/report/physicians/{pid}/links", {"valid_from": "2026-01-01"})
        return "tecnico.alfa e dra.ficticia criados; médico com vínculo vigente"

    @step("6. Cadastrar paciente fictício (prontuário HML-001)")
    def _():
        p = s["admin"].call("POST", "/patients", {"name": "Maria Ficticia", "birth_date": "1980-01-01", "sex": "F",
                                                  "identifiers": [{"issuer": "PRONTUARIO", "value": "HML-001"}]})
        s["patient"] = p["id"]
        return p["id"]

    @step("7. Enviar exame simulado (C-STORE do simulador ao motor DICOM, porta 4242)")
    def _():
        p = run([APP / "VyonixPlatform.exe", "homolog-enviar", "--paciente-id", "HML-001", "--nome", "Maria Ficticia"])
        r = json.loads(p.stdout[p.stdout.index("{"):p.stdout.rindex("}") + 1])
        assert r["sent"] == 8 and r["failed"] == 0, r
        s["uid"] = r["study_instance_uid"]
        return r

    @step("8. Exame aparece sozinho na Central de Exames do técnico, identificado e com 8 imagens")
    def _():
        t = first_login("tecnico.alfa", "Provisoria-2026x", "Tecnico-Alfa-2026!")
        s["tec"] = t
        end = time.monotonic() + 420
        last = None
        while time.monotonic() < end:
            q = t.call("GET", "/ris/prep")
            it = next((x for x in q["items"] if x.get("study_instance_uid") == s["uid"]), None)
            if it and it["images"] == 8:
                d = t.call("GET", f"/ris/prep/{it['study_id']}")
                checks = {c["code"]: c["ok"] for c in d["system_checks"]}
                last = checks
                if all(checks.values()):
                    s["study"] = it["study_id"]
                    return f"etapa {it['stage']}, {it['images']} imagens, equipamento {it['station']}; verificações {checks}"
            time.sleep(10)
        raise AssertionError(f"estudo não ficou pronto na Central de Exames (última verificação: {last})")

    @step("9. Viewer e DICOMweb abrem o estudo")
    def _():
        t = s["tec"]
        st, body = t.raw("GET", "/viewer/")
        assert st == 200 and b"<html" in body.lower(), st
        st, body = t.raw("GET", f"/api/v1/pacs/dicomweb/studies?StudyInstanceUID={s['uid']}")
        assert st == 200 and s["uid"].encode() in body, st
        return "/viewer/ 200; estudo listado pelo QIDO-RS"

    @step("10. Painel de ações: comentário, anexo PDF fictício e checklist")
    def _():
        t, sid = s["tec"], s["study"]
        t.call("POST", f"/ris/prep/{sid}/comments", {"text": "Comentário de homologação (fictício)."})
        st, body = t.raw("POST", f"/api/v1/ris/prep/{sid}/attachments?kind=document&filename=pedido-ficticio.pdf",
                         b"%PDF-1.4\n%ficticio\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n", ctype="application/pdf")
        assert st == 201, (st, body[:200])
        for code in ("patient_identity", "procedure", "quality"):
            t.call("POST", f"/ris/prep/{sid}/check", {"code": code, "done": True})
        d = t.call("GET", f"/ris/prep/{sid}")
        return f"{len(d['comments'])} comentário(s), {len(d['attachments'])} anexo(s), checklist " + \
            ", ".join(f"{i['code']}={i['done']}" for i in d["checklist"] if i["required"])

    @step("11. Encaminhar para a fila de laudos")
    def _():
        r = s["tec"].call("POST", f"/ris/prep/{s['study']}/forward")
        assert r["status"] in ("forwarded", "assigned"), r
        return r

    @step("12. Médica fictícia vê o exame na fila de laudos")
    def _():
        m = first_login("dra.ficticia", "Provisoria-2026x", "Medica-Ficticia-2026!")
        wl = m.call("GET", "/report/worklist")["items"]
        assert any(x["study_id"] == s["study"] for x in wl), [x["study_id"] for x in wl]
        s["med"] = m
        return f"{len(wl)} exame(s) na fila; o exame encaminhado está nela"

    @step("13. Médica redige e libera o laudo (confirmação por senha) e baixa o PDF")
    def _():
        m = s["med"]
        rep = m.call("POST", "/report/reports", {"study_id": s["study"]})
        rep = m.call("PUT", f"/report/reports/{rep['id']}", {"body": "Achados: estudo sintético de homologação.\n"
                                                                 "Conclusão: teste, sem valor diagnóstico.",
                                                         "row_version": rep["row_version"]})
        fin = m.call("POST", f"/report/reports/{rep['id']}/finalize", {"password": "Medica-Ficticia-2026!",
                                                                      "row_version": rep["row_version"]})
        assert fin["status"] == "final", fin
        st, pdf = m.raw("GET", f"/api/v1/report/reports/{rep['id']}/pdf")
        assert st == 200 and pdf[:5] == b"%PDF-", st
        return f"laudo liberado (versão {fin['version']}); PDF {len(pdf)} bytes"

    ok = all(x["result"] == "Aprovado" for x in STEPS)
    (OUT / "homologacao.json").write_text(json.dumps({"approved": ok, "steps": STEPS}, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    lines = ["# Roteiro de homologação executado no instalador (Windows do CI)", "",
             "| Passo | Resultado | Detalhe | s |", "|---|---|---|---|"]
    lines += [f"| {x['step']} | {x['result']} | {x['detail'].replace('|', '/')} | {x['seconds']} |" for x in STEPS]
    (OUT / "homologacao.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nResultado: {'APROVADO' if ok else 'REPROVADO'} ({sum(x['result'] == 'Aprovado' for x in STEPS)}/{len(STEPS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
