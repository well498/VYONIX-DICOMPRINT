"""P0 — desinstalação, atualização e recuperação no Windows (lógica testável fora do Windows; o comportamento real
é exercitado no CI deploy-windows, critério 2.12).

* Remoção de serviço sem deixar o Windows reiniciá-lo: recuperação desligada e início desativado ANTES de parar;
  processo encerrado pelo PID se não parar; "marcado para exclusão" reconhecido.
* Execução interrompida (instalação que caiu no meio) não trava a desinstalação: fica registrada como abandonada.
* A desinstalação também encerra processos esquecidos na pasta do programa (assistente aberto), nunca os próprios.
* Instalador: neutraliza serviços e fecha processos antes de copiar e ao desinstalar; atualização direta sobre a
  instalação existente; atalho Reparar; registro em ProgramData\\VYONIX\\Logs; nunca o DICOM Print.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class RemoveService(unittest.TestCase):
    def run_with(self, states, *, delete_code=0, after_delete=None):
        from vyonix_deploy.steps import services as sv
        from vyonix_deploy.sysrun import Result
        calls = []
        seq = list(states)

        def q(name):
            st = seq.pop(0) if seq else (after_delete if any(c[0] == "delete" for c in calls) else "Stopped")
            return None if st is None else {"state": st, "pid": 4242, "start": "Auto"}

        def run(args, **kw):
            calls.append(tuple(str(a) for a in args[1:]) if args[0] == sv.SC else ("taskkill", *map(str, args[1:])))
            code = delete_code if "delete" in args else 0
            return Result(code, "", "")
        with mock.patch.object(sv, "query_service", side_effect=q), mock.patch.object(sv, "run", side_effect=run), \
                mock.patch.object(sv.time, "sleep"), mock.patch.object(sv, "_wait",
                                                                    side_effect=lambda n, s, t: states_wait.pop(0)):
            states_wait = list(self.waits)
            out = sv.remove_service("VyonixCore", timeout=1)
        return out, calls

    def test_recovery_disabled_before_stop_and_kill_if_stuck(self):
        self.waits = ["Running", "Stopped"]                       # não parou no prazo → encerra pelo PID
        out, calls = self.run_with(["Running", "Running"], after_delete=None)
        names = [c[0] if c[0] != "taskkill" else "taskkill" for c in calls]
        self.assertEqual(names[:3], ["config", "failure", "stop"])      # sem reinício automático antes de parar
        self.assertIn(("config", "VyonixCore", "start=", "disabled"), calls)
        self.assertIn(("failure", "VyonixCore", "reset=", "0", "actions=", '""'), calls)
        self.assertIn(("taskkill", "/F", "/T", "/PID", "4242"), calls)
        self.assertLess(names.index("taskkill"), names.index("delete"))
        self.assertEqual(out, "removed")

    def test_absent_and_pending_reboot(self):
        self.waits = []
        out, calls = self.run_with([None])
        self.assertEqual((out, calls), ("absent", []))
        self.waits = ["Stopped"]
        with mock.patch("vyonix_deploy.steps.services.time.monotonic", side_effect=[0, 0, 100]):
            out, _ = self.run_with(["Running"], after_delete="Stopped")    # continua listado: marcado para exclusão
        self.assertEqual(out, "pending_reboot")

    def test_create_over_service_marked_for_delete_has_clear_message(self):
        from vyonix_deploy.errors import DeployError
        from vyonix_deploy.steps import services as sv
        from vyonix_deploy.sysrun import Result
        step = sv.ServiceStep("VyonixCore", "Core", "d", "x.exe")
        with mock.patch.object(sv, "IS_WINDOWS", True), mock.patch.object(sv, "query_service", return_value=None), \
                mock.patch.object(sv, "run", return_value=Result(1072, "", "[SC] CreateService FAILED 1072")):
            with self.assertRaises(DeployError) as cm:
                step.apply(None)
        self.assertIn("Reinicie o computador", str(cm.exception))


class PendingRun(unittest.TestCase):
    def test_uninstall_abandons_interrupted_run_instead_of_resuming(self):
        import tempfile
        from vyonix_deploy import cli
        from vyonix_deploy.db import DeployDB
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            db = DeployDB(Path(t) / "deploy.db")
            db.x("INSERT INTO runs(id, kind, status, created_at, updated_at, config_json) VALUES ('r1','install','running','1','1','{}')")
            d = mock.Mock()
            d.db = db
            d.saved_config.return_value = None
            d.plan.side_effect = RuntimeError("parou aqui")          # basta chegar ao plano sem retomar
            a = mock.Mock(kind="uninstall", plan_only=False, config=None, approve=None, approve_all=True, silent=True,
                          confirm=[], out=None)
            with self.assertRaises(RuntimeError):
                cli.cmd_run(d, a)
            d.resume_pending.assert_not_called()
            self.assertEqual(db.run("r1")["status"], "abandoned")
            self.assertIsNone(db.unfinished())
            getattr(db, "close", lambda: None)()                 # Windows: arquivo aberto impede apagar a pasta


class Steps(unittest.TestCase):
    def test_uninstall_ends_closing_processes_but_not_itself(self):
        import os
        from vyonix_deploy.steps import update
        self.assertIn(os.getpid(), update._self_pids())
        ctx = mock.Mock()
        ctx.cfg.https_port = 8444
        ctx.paths.install_dir = Path("C:/Program Files/VYONIX/Platform")
        ctx.paths.reports = Path("C:/ProgramData/VYONIX/Deploy/relatorios")
        ids = [s.id for s in update.uninstall_steps(ctx)]
        self.assertEqual(ids[-1], "remove.processes")
        with mock.patch("vyonix_deploy.steps.services.powershell", return_value=[]) as ps:
            from vyonix_deploy.steps.services import kill_install_processes
            kill_install_processes("C:/Program Files/VYONIX/Platform", exclude=(1, 2))
        script, args = ps.call_args[0]
        self.assertEqual((args["ex"], args["kill"]), ([1, 2], True))
        self.assertIn("StartsWith($dir", script)                     # só a pasta do programa


class Installer(unittest.TestCase):
    def setUp(self):
        self.iss = (ROOT / "installer" / "VyonixPlatform.iss").read_text(encoding="utf-8")

    def test_uninstall_neutralizes_services_and_cleans_program_folder(self):
        code = self.iss.split("procedure CurUninstallStepChanged", 1)[1]
        self.assertIn("Neutralize(Services[I], True)", code)
        self.assertIn("KillAppProcesses", code)
        self.assertIn("DelTree(ExpandConstant('{app}')", code)
        self.assertNotIn("VyonixDicomPrint", self.iss.split("[Code]", 1)[1].replace("Nunca inclui o VyonixDicomPrint", ""))
        neut = self.iss.split("procedure Neutralize", 1)[1].split("function PrepareToInstall", 1)[0]
        self.assertLess(neut.index("failure"), neut.index("stop"))     # recuperação desligada antes de parar
        self.assertNotIn("{commonappdata}\\VYONIX'", code.split("DelTree", 1)[1].split(";", 1)[0])   # nunca os dados

    def test_upgrade_in_place_repair_and_logs(self):
        self.assertIn("Atualizar_VYONIX.cmd", self.iss)
        self.assertIn("Check: IsUpgrade", self.iss)
        self.assertIn("VYONIX - Reparar instalacao", self.iss)
        self.assertIn("VYONIX\\Logs\\instalador.log", self.iss)
        for n in ("Atualizar_VYONIX.cmd", "Reparar_VYONIX.cmd"):
            t = (ROOT / "installer" / "common" / n).read_text(encoding="utf-8")
            self.assertIn("-Verb RunAs", t)
        self.assertIn("update --approve-all", (ROOT / "installer" / "common" / "Atualizar_VYONIX.cmd").read_text())
        self.assertIn("vyonix-deploy.exe repair", (ROOT / "installer" / "common" / "Reparar_VYONIX.cmd").read_text())

    def test_recovery_tool_is_read_only_by_default_and_never_touches_data(self):
        ps = (ROOT / "installer" / "recuperacao" / "Recuperar_VYONIX.ps1").read_text(encoding="utf-8-sig")
        body = ps.split("function Aplicar-Recuperacao", 1)[1].split("\nWrite-Host", 1)[0]
        self.assertIn('$c -ne "RECUPERAR"', ps)
        self.assertIn("if ($Aplicar)", ps)
        self.assertNotIn("Remove-Item $dados", body)
        self.assertNotIn("VyonixDicomPrint", ps.split("$servicos = ", 1)[1].split("\n", 1)[0])
        self.assertIn("Rename-Item -Path $app", body)                   # pasta do programa renomeada, não apagada
        self.assertNotIn("Remove-Item -Path $app", body)


if __name__ == "__main__":
    unittest.main()
