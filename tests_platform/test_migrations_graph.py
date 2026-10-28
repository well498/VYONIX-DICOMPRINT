"""Grafo de migrações com ramos por módulo: o Alembic grava na tabela de versões só as revisões de ponta
(``pacs_0001`` depende de ``core_0001``, então a tabela guarda apenas ``pacs_0001``). A conferência
"banco atualizado" do DEPLOY precisa considerar ancestrais e dependências — sem isso, a instalação no
Windows foi revertida por "estado diferente do esperado" (deploy-windows run 40058503968)."""

import unittest


class MigrationGraph(unittest.TestCase):
    def test_up_to_date_follows_dependencies(self):
        """Vale para qualquer número de ramos de módulo (core, pacs, ris, …)."""
        from vyonix.db import migrate
        heads = sorted(migrate.heads())
        core_head = [h for h in heads if h.startswith("core_")]
        self.assertEqual(len(core_head), 1)                                 # o core é um ramo só (core_0001 → …)
        module_heads = [h for h in heads if not h.startswith("core_")]
        self.assertGreaterEqual(len(module_heads), 2)                       # pacs e ris
        # os ramos de módulo dependem de core_0001; revisões posteriores do core também precisam estar aplicadas
        self.assertIn("core_0001", migrate.applied(module_heads))
        self.assertEqual(migrate.up_to_date(module_heads), core_head == ["core_0001"])
        self.assertTrue(migrate.up_to_date(heads))
        for h in module_heads:
            self.assertIn("core_0001", migrate.applied([h]))                 # dependência entre ramos
            others = core_head + [x for x in module_heads if x != h]
            self.assertFalse(migrate.up_to_date(others), f"falta o ramo de {h}")
        self.assertIn("pacs_0001", migrate.applied([next(h for h in heads if h.startswith("pacs_"))]))
        self.assertFalse(migrate.up_to_date(["core_0001"]))
        self.assertFalse(migrate.up_to_date([]))

    def test_every_head_is_reachable_from_recorded_tip(self):
        """Cada ramo de módulo depende do core: aplicar todos os ramos cobre todas as revisões."""
        from alembic.script import ScriptDirectory
        from vyonix.db import migrate
        script = ScriptDirectory.from_config(migrate.alembic_config("", "vyonix"))
        every = {r.revision for r in script.walk_revisions()}
        self.assertEqual(migrate.applied(migrate.heads()), every)


if __name__ == "__main__":
    unittest.main()
