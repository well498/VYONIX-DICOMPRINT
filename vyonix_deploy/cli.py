"""``vyonix-deploy`` — mesmas operações do assistente, sem interface.

    vyonix-deploy inventory [--out inventario.json]
    vyonix-deploy install --config opcoes.json --plan-only --out plano.json
    vyonix-deploy install --config opcoes.json --approve plano.json --silent
    vyonix-deploy install --config opcoes.json --approve-all [--confirm network.static_ip="ALTERAR IP"]
    vyonix-deploy update --approve-all --silent        (após o VYONIX_Setup copiar a nova versão)
    vyonix-deploy diagnose [--json]
    vyonix-deploy repair [--approve-all]
    vyonix-deploy uninstall --approve-all --silent     (dados preservados)
    vyonix-deploy resume                               (execução interrompida)
    vyonix-deploy backups                              (lista os backups do DEPLOY)
    vyonix-deploy restore --backup <pasta> --approve-all --confirm backup.restore="RESTAURAR <pasta>"
    vyonix-deploy verify-reports
    vyonix-deploy wizard [--diagnose]                  (assistente no navegador, 127.0.0.1)

Senhas: ``VYONIX_ADMIN_PASSWORD`` (primeiro administrador) e ``VYONIX_PFX_PASSWORD`` (certificado da
instituição) ou digitadas quando pedidas. Nunca são gravadas em plano, relatório ou manifesto.
Códigos de saída: 0 sucesso · 1 falha · 2 impeditivo/recusado · 3 plano não aprovado.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from vyonix_deploy import __version__
from vyonix_deploy.errors import Blocked, DeployError, NotApproved
from vyonix_deploy.service import Deploy, dump_plan_file, env_secrets, load_config

KINDS = ("install", "repair", "update", "uninstall", "reconfigure", "restore")


def _print(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _log(silent: bool):
    def f(level: str, msg: str) -> None:
        if not silent or level in ("ERROR", "WARN"):
            _print(f"[{level}] {msg.splitlines()[0] if level != 'ERROR' else msg}")
    return f


def show_plan(plan: dict) -> None:
    _print(f"Plano {plan['run_id']} ({plan['kind']}) — SHA-256 {plan['plan_sha'][:16]}…")
    for f in plan["compatibility"]:
        if f["level"] != "ok":
            _print(f"  [{f['level']}] {f['title']}: {f['detail']}")
    for i in plan["items"]:
        mark = "=" if i["already"] else "+"
        extra = f"  (confirmação: digite “{i['confirm']}”)" if i.get("confirm") and not i["already"] else ""
        _print(f"  {mark} {i['id']}: {i['title']}{extra}")
        if not i["already"] and i.get("impact"):
            _print(f"      {i['impact']}")
    _print("  (= já conforme, + será aplicado)")


def _confirmations(values: list[str]) -> dict[str, str]:
    out = {}
    for v in values or []:
        k, _, t = v.partition("=")
        out[k.strip()] = t.strip().strip('"')
    return out


def _extra(kind: str, need_admin: bool, silent: bool) -> dict:
    ex = env_secrets()
    if need_admin and "admin_password" not in ex:
        if silent:
            raise DeployError("Instalação silenciosa: defina VYONIX_ADMIN_PASSWORD para o primeiro administrador.")
        a = getpass.getpass("Senha do primeiro administrador do VYONIX: ")
        if a != getpass.getpass("Repita: "):
            raise DeployError("As senhas não conferem.")
        ex["admin_password"] = a
    return ex


def cmd_run(d: Deploy, a) -> int:
    pending = d.db.unfinished()
    if pending and not a.plan_only:
        _print(f"Há uma execução interrompida ({pending['id']}, {pending['kind']}): retomando antes de qualquer outra.")
        r = d.resume_pending(extra=env_secrets())
        _print(json.dumps(r, ensure_ascii=False, indent=2))
        if r["status"] != "succeeded":
            return 1
    cfg = load_config(a.config, d.saved_config())
    if a.kind == "restore":
        cfg.restore_backup = a.backup
    if a.kind != "install" and d.saved_config() is None and a.kind != "uninstall":
        raise DeployError("Nenhuma instalação registrada pelo DEPLOY neste servidor: use install.")
    if a.kind == "repair" and not a.approve:
        diag = d.diagnose(cfg)
        if not diag["problems"]:
            _print("Diagnóstico: nenhum problema encontrado. Nada a reparar.")
            return 0
        plan, ids, cfg = d.repair_plan(diag, cfg)
    else:
        plan = d.plan(a.kind, cfg)
        ids = None
    if a.out:
        dump_plan_file(a.out, plan)
    if not a.silent:
        show_plan(plan)
    if a.plan_only:
        rep = d.report_only(plan["run_id"])
        _print(f"Plano gravado{' em ' + a.out if a.out else ''}. Relatório: {rep['pdf']}")
        return 0
    conf = _confirmations(a.confirm)
    if a.approve:
        with open(a.approve, encoding="utf-8") as f:
            pf = json.load(f)
        approved = pf.get("approved_items")
        # o plano aprovado em arquivo é comparado com o plano gerado agora (mesmo conteúdo proposto)
        d.approve(plan["run_id"], cfg, items=approved if approved is not None else ids, confirmations=conf,
                  expected_sha=pf["plan_sha"], via=f"arquivo {a.approve}")
    elif a.approve_all:
        d.approve(plan["run_id"], cfg, items=ids, confirmations=conf, via="linha de comando (--approve-all)")
    else:
        if not sys.stdin.isatty():
            _print("Plano não aprovado (use --approve plano.json ou --approve-all).")
            d.report_only(plan["run_id"])
            return 3
        if input("Aprovar e aplicar o plano? Digite SIM: ").strip().upper() != "SIM":
            _print("Plano não aprovado. Nada foi alterado.")
            d.report_only(plan["run_id"])
            return 3
        for i in plan["items"]:
            if i.get("confirm") and not i["already"] and i["id"] not in conf:
                conf[i["id"]] = input(f"{i['title']}: digite “{i['confirm']}” para confirmar: ")
        d.approve(plan["run_id"], cfg, items=ids, confirmations=conf, via="linha de comando (interativo)")
    need_admin = a.kind == "install" and not any(i["id"] == "core.database" and i["already"] for i in plan["items"])
    r = d.execute(plan["run_id"], extra=_extra(a.kind, need_admin, a.silent))
    _print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["status"] == "succeeded" else 1


def cmd_startup(a) -> int:
    """``abrir``: sistema funcionando → navegador em https://localhost:PORTA; senão relatório HTML com o que falhou.
    ``verificar``: só o diagnóstico (texto, JSON ou HTML)."""
    import os
    import tempfile
    from vyonix_deploy import startup
    if a.cmd == "abrir":
        _print("Verificando o VYONIX…")
    res = startup.wait_until_ready(a.porta, pg_port=a.porta_banco, timeout=a.esperar or (90 if a.cmd == "abrir" else 0))
    if a.json:
        _print(startup.as_json(res))
    else:
        _print(startup.to_text(res))
    html_path = a.html
    if a.cmd == "abrir" and not res.web_ok and not html_path:
        html_path = os.path.join(tempfile.gettempdir(), "VYONIX-diagnostico-inicializacao.html")
    if html_path:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(startup.render_html(res))
    if a.cmd == "abrir" and not a.sem_navegador:
        from vyonix_deploy.wizard import open_browser_url
        if res.web_ok:
            open_browser_url(f"https://localhost:{a.porta}/")
        else:
            import webbrowser
            webbrowser.open("file:///" + os.path.abspath(html_path).replace("\\", "/"))
    return 0 if res.web_ok else 1


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):              # saída sempre em UTF-8 (redirecionada por scripts/CI)
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    p = argparse.ArgumentParser(prog="vyonix-deploy", description=f"VYONIX DEPLOY {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inventory")
    i.add_argument("--out")
    for k in KINDS:
        s = sub.add_parser(k)
        s.add_argument("--config")
        s.add_argument("--plan-only", action="store_true")
        s.add_argument("--out")
        s.add_argument("--approve", metavar="PLANO.json")
        s.add_argument("--approve-all", action="store_true")
        s.add_argument("--confirm", action="append", default=[], metavar='ITEM="TEXTO"')
        s.add_argument("--silent", action="store_true")
        if k == "restore":
            s.add_argument("--backup", required=True, help="nome da pasta em ProgramData\\VYONIX\\Backups")
    sub.add_parser("backups")
    dg = sub.add_parser("diagnose")
    dg.add_argument("--json", action="store_true")
    sub.add_parser("resume")
    sub.add_parser("verify-reports")
    sub.add_parser("runs")
    w = sub.add_parser("wizard")
    w.add_argument("--diagnose", action="store_true")
    w.add_argument("--no-browser", action="store_true")
    w.add_argument("--port", type=int, default=0)
    for name, hlp in (("abrir", "abre o VYONIX no navegador ou, se não estiver funcionando, o diagnóstico"),
                      ("verificar", "diagnóstico de inicialização (somente leitura, sem administrador)")):
        v = sub.add_parser(name, help=hlp)
        v.add_argument("--porta", type=int, default=8444)
        v.add_argument("--porta-banco", type=int, default=5544)
        v.add_argument("--esperar", type=int, default=0, help="segundos para aguardar o sistema iniciar")
        v.add_argument("--json", action="store_true")
        v.add_argument("--html")
        v.add_argument("--sem-navegador", action="store_true")
    m = sub.add_parser("activate-module")
    m.add_argument("module")
    m.add_argument("--approve-all", action="store_true")
    m.add_argument("--silent", action="store_true")
    a = p.parse_args(argv)
    silent = getattr(a, "silent", False)
    if a.cmd == "inventory":                      # somente leitura: não cria nem abre o banco do DEPLOY
        from vyonix_deploy.inventory import collect
        from vyonix_deploy.paths import default_paths
        try:
            txt = json.dumps(collect(default_paths()), ensure_ascii=False, indent=2, default=str)
        except DeployError as exc:
            _print(f"Erro: {exc}")
            return 1
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(txt)
        else:
            _print(txt)
        return 0
    if a.cmd in ("abrir", "verificar"):            # sem administrador e sem abrir o banco do DEPLOY
        return cmd_startup(a)
    d = Deploy(log=_log(silent))
    try:
        if a.cmd in KINDS:
            a.kind = a.cmd
            return cmd_run(d, a)
        if a.cmd == "diagnose":
            r = d.diagnose()
            if a.json:
                _print(json.dumps({k: v for k, v in r.items() if k != "observed"}, ensure_ascii=False, indent=2,
                                  default=str))
            else:
                _print(f"Diagnóstico {r['run_id']}: {len(r['problems'])} problema(s).")
                for pr in r["problems"]:
                    _print(f"  [{pr['severity']}] {pr['title']}: {pr['detail']} → {pr['repair']}")
                _print(f"Relatório: {r['report']['pdf']}")
            return 0 if not r["problems"] else 1
        if a.cmd == "resume":
            r = d.resume_pending(extra=env_secrets())
            _print(json.dumps(r, ensure_ascii=False, indent=2) if r else "Nenhuma execução interrompida.")
            return 0 if (r is None or r["status"] == "succeeded") else 1
        if a.cmd == "verify-reports":
            from vyonix_deploy.report import verify_chain
            probs = verify_chain(d.db)
            _print("Relatórios e manifestos íntegros." if not probs else "\n".join(probs))
            return 0 if not probs else 1
        if a.cmd == "backups":
            from vyonix_deploy.steps.update import list_backups
            _print(json.dumps(list_backups(d.paths), ensure_ascii=False, indent=2))
            return 0
        if a.cmd == "runs":
            _print(json.dumps(d.db.runs(), ensure_ascii=False, indent=2))
            return 0
        if a.cmd == "wizard":
            from vyonix_deploy.wizard import serve
            return serve(d, port=a.port, open_browser=not a.no_browser, start="diagnose" if a.diagnose else None)
        if a.cmd == "activate-module":
            from vyonix_deploy.modules import activate
            r = activate(d, a.module, approve_all=a.approve_all, silent=silent)
            _print(json.dumps(r, ensure_ascii=False, indent=2))
            return 0 if r["status"] == "succeeded" else 1
    except Blocked as exc:
        info = json.loads(str(exc))
        _print("Impeditivos — nada foi alterado:")
        for b in info["blockers"]:
            _print(f"  {b['title']}: {b['detail']}")
        _print(f"Relatório: {info['report']['pdf']}")
        return 2
    except NotApproved as exc:
        _print(f"Recusado: {exc}")
        return 2
    except DeployError as exc:
        _print(f"Erro: {exc}")
        return 1
    finally:
        d.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
