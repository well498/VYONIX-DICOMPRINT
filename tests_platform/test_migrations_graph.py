"""Grafo de migrações com ramos por módulo: o Alembic grava na tabela de versões só as revisões de ponta
(``pacs_0001`` depende de ``core_0001``, então a tabela guarda apenas ``pacs_0001``). A conferência
"banco atualizado" do DEPLOY precisa considerar ancestrais e dependências — sem isso, a instalação no
Windows foi revertida por "estado diferente do esperado" (deploy-windows run 40058503968)."""

import unittest


class MigrationGraph(unittest.TestCase):
    def test_up_to_date_follows_dependencies(self):
        from vyonix.db import migrate
        heads = set(migrate.heads())
        pacs_head = next(h for h in heads if h.startswith("pacs_"))
        self.assertIn("core_0001", heads)
        applied = migrate.applied([pacs_head])
        self.assertIn("core_0001", applied)                                  # dependência entre ramos
        self.assertIn("pacs_0001", applied)                                  # revisão anterior do ramo
        self.assertTrue(migrate.up_to_date([pacs_head]))                     # o que o Alembic realmente grava
        self.assertTrue(migrate.up_to_date(sorted(heads)))
        self.assertFalse(migrate.up_to_date(["core_0001"]))                  # falta o ramo do PACS
        if pacs_head != "pacs_0001":
            self.assertFalse(migrate.up_to_date(["pacs_0001"]))              # ramo do PACS incompleto
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
