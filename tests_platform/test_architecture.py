"""Regras de arquitetura verificadas no código-fonte (sem banco).

* O DICOM Print (``app``) não depende da plataforma (``vyonix``).
* A plataforma usa do Print somente os componentes de identidade/verificação de licença listados.
* Nada da plataforma importa o License Manager, o License Server, a camada de cobrança ou Qt.
* Módulos de domínio não importam a API; o cadastro clínico não depende de auth nem de licenciamento.
* Nenhuma função de assinatura nem chave privada na plataforma ou na interface web.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED_FROM_PRINT = {"app.core.errors", "app.licensing.hardware", "app.licensing.installation",
                     "app.licensing.keys", "app.licensing.subscription", "app.licensing.time_integrity",
                     "app.licensing.vault", "app.licensing.tpm", "app.licensing.online"}
FORBIDDEN_IN_PLATFORM = ("license_manager", "license_server", "PySide6", "vyonix_commercial.engine",
                         "vyonix_commercial.billing", "vyonix_commercial.schema")


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def py_files(pkg: str) -> list[Path]:
    return sorted(p for p in (ROOT / pkg).rglob("*.py") if "__pycache__" not in p.parts)


class Architecture(unittest.TestCase):
    def test_print_does_not_depend_on_platform(self):
        bad = [f"{p.relative_to(ROOT)}: {m}" for p in py_files("app") for m in imports(p)
               if m == "vyonix" or m.startswith("vyonix.")]
        self.assertEqual(bad, [])

    def test_platform_uses_only_shared_print_components(self):
        bad = []
        for p in py_files("vyonix"):
            for m in imports(p):
                if m.startswith("app.") or m == "app":
                    parent = any(s.startswith(m + ".") for s in SHARED_FROM_PRINT)   # "from app.licensing import x"
                    if not parent and not any(m == s or m.startswith(s + ".") for s in SHARED_FROM_PRINT):
                        bad.append(f"{p.relative_to(ROOT)}: {m}")
                if any(m == f or m.startswith(f + ".") for f in FORBIDDEN_IN_PLATFORM):
                    bad.append(f"{p.relative_to(ROOT)}: {m}")
        self.assertEqual(bad, [])

    def test_platform_does_not_depend_on_deploy(self):
        bad = [f"{p.relative_to(ROOT)}: {m}" for p in py_files("vyonix") for m in imports(p)
               if m == "vyonix_deploy" or m.startswith("vyonix_deploy.")]
        self.assertEqual(bad, [])

    def test_deploy_does_not_import_admin_tools(self):
        bad = [f"{p.relative_to(ROOT)}: {m}" for p in py_files("vyonix_deploy") for m in imports(p)
               if any(m == f or m.startswith(f + ".") for f in FORBIDDEN_IN_PLATFORM)]
        self.assertEqual(bad, [])

    def test_domain_layers(self):
        rules = {"vyonix/clinical": ("vyonix.api", "vyonix.auth", "vyonix.licensing", "vyonix.cli"),
                 "vyonix/audit": ("vyonix.api", "vyonix.auth", "vyonix.clinical", "vyonix.licensing"),
                 "vyonix/events": ("vyonix.api", "vyonix.auth", "vyonix.clinical", "vyonix.licensing"),
                 "vyonix/db": ("vyonix.api", "vyonix.auth.service", "vyonix.clinical.service", "vyonix.cli"),
                 "vyonix/settings": ("vyonix.api", "vyonix.auth", "vyonix.clinical", "vyonix.licensing"),
                 "vyonix/licensing": ("vyonix.api", "vyonix.clinical"),
                 "vyonix/auth": ("vyonix.api", "vyonix.clinical", "vyonix.licensing")}
        bad = []
        for folder, forbidden in rules.items():
            for p in py_files(folder):
                for m in imports(p):
                    if any(m == f or m.startswith(f + ".") for f in forbidden):
                        bad.append(f"{p.relative_to(ROOT)}: {m}")
        self.assertEqual(bad, [])

    def test_no_signing_or_private_keys_in_platform(self):
        bad = []
        for p in py_files("vyonix") + py_files("vyonix_deploy"):
            text = p.read_text(encoding="utf-8")
            for pat in (r"Ed25519PrivateKey", r"build_signed\(", r"BEGIN [A-Z ]*PRIVATE KEY", r"sign_ed25519"):
                if re.search(pat, text):
                    bad.append(f"{p.relative_to(ROOT)}: {pat}")
        for p in (ROOT / "web" / "src").rglob("*"):
            if p.is_file() and "PRIVATE KEY" in p.read_text(encoding="utf-8", errors="ignore"):
                bad.append(str(p.relative_to(ROOT)))
        self.assertEqual(bad, [])

    def test_every_tenant_table_is_protected_by_rls_in_migration(self):
        from vyonix.db import models  # noqa: F401  (registra todas as tabelas)
        from vyonix.db.base import Base
        mig = (ROOT / "vyonix/db/migrations/versions/core_0001_core_inicial.py").read_text(encoding="utf-8")
        listed = set(re.findall(r'"([a-z]+\.[a-z_]+)"', mig.split("TENANT_TABLES = (")[1].split(")")[0]))
        tenant_tables = {f"{t.schema}.{t.name}" for t in Base.metadata.tables.values() if "tenant_id" in t.c}
        self.assertEqual(tenant_tables - listed, set(), "tabela com tenant_id sem row level security")

    def test_module_manifests_consistent(self):
        from vyonix.modules.manifest import DEFAULT_ROLES, MANIFESTS, all_permissions
        from vyonix_protocol import formats as F
        self.assertEqual(set(MANIFESTS) - {"clinical"}, set(F.MODULE_CODES))
        perms = all_permissions()
        for code, (_name, patterns) in DEFAULT_ROLES.items():
            for p in patterns:
                if p != "*" and not p.endswith(".*"):
                    self.assertIn(p, perms, f"papel {code}: permissão inexistente {p}")
        for m in MANIFESTS.values():
            for d in m.depends:
                self.assertIn(d, MANIFESTS)
            for ev in m.publishes:
                self.assertRegex(ev, r"^[a-z]+(\.[a-z_]+)+\.v[1-9][0-9]*$")


if __name__ == "__main__":
    unittest.main()
