"""Fundação do CORE: isolamento por clínica, auditoria, autenticação, configurações, módulos, eventos."""

from __future__ import annotations

import time
import unittest
import uuid
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from tests_platform.support import ADMIN_PW, new_org, require_db


def setUpModule():
    global db
    db = require_db()


class TenantIsolation(unittest.TestCase):
    def test_rls_isolates_organizations(self):
        from vyonix.auth.models import User
        from vyonix.tenancy.models import Organization
        a, b = new_org(db), new_org(db)
        with db.session(a) as s:
            self.assertEqual([o.id for o in s.execute(select(Organization)).scalars()], [a])
            self.assertEqual(len(s.execute(select(User)).scalars().all()), 1)
        with db.session(b) as s:
            self.assertEqual([o.id for o in s.execute(select(Organization)).scalars()], [b])

    def test_no_tenant_sees_nothing_and_cannot_write(self):
        from vyonix.tenancy.models import Organization
        new_org(db)
        with db.session() as s:
            self.assertEqual(s.execute(select(Organization)).scalars().all(), [])
        with self.assertRaises(DBAPIError):
            with db.session() as s:
                s.execute(text("INSERT INTO tenancy.sites (id, tenant_id, name, timezone, active, row_version) "
                               "VALUES (gen_random_uuid(), gen_random_uuid(), 'x', 'UTC', true, 1)"))

    def test_cannot_write_into_other_tenant(self):
        a, b = new_org(db), new_org(db)
        with self.assertRaises(DBAPIError):
            with db.session(a) as s:
                s.execute(text("INSERT INTO tenancy.sites (id, tenant_id, name, timezone, active, row_version) "
                               "VALUES (gen_random_uuid(), :b, 'invasora', 'UTC', true, 1)"), {"b": b})

    def test_app_role_is_not_owner_and_cannot_disable_rls(self):
        with self.assertRaises(ProgrammingError):
            with db.session() as s:
                s.execute(text("ALTER TABLE auth.users DISABLE ROW LEVEL SECURITY"))
        with db.session() as s:
            row = s.execute(text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user")).one()
            self.assertEqual(tuple(row), (False, False))
            forced = s.execute(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                    "WHERE n.nspname IN ('tenancy','auth','clinical','platform','audit','licensing') "
                                    "AND c.relkind = 'r' AND c.relforcerowsecurity")).scalar()
            self.assertGreaterEqual(forced, 24)

    def test_resolve_organization(self):
        from vyonix.tenancy import service as tenancy
        code = f"res-{uuid.uuid4().hex[:6]}"
        tid = new_org(db, code)
        self.assertEqual(tenancy.resolve(db, code), tid)
        self.assertEqual(tenancy.resolve(db, code.upper()), tid)
        self.assertIsNone(tenancy.resolve(db, "nao-existe"))


class AuditChain(unittest.TestCase):
    def test_chain_and_tamper_detection(self):
        from vyonix.audit import service as audit
        t = new_org(db)
        with db.session(t) as s:
            for i in range(5):
                audit.record(s, actor="teste", action="x.test", details={"i": i, "nome": "ação"})
        with db.session(t) as s:
            self.assertEqual(audit.verify(s), [])
            rows = audit.query(s, action="x.*")
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[-1].prev_hash, s.execute(text(
                "SELECT hash FROM audit.audit_log WHERE tenant_id = :t AND action = 'user.create'"), {"t": t}).scalar())
        with self.assertRaises(DBAPIError):          # app não altera nem apaga
            with db.session(t) as s:
                s.execute(text("UPDATE audit.audit_log SET actor = 'outro' WHERE tenant_id = :t"), {"t": t})
        with self.assertRaises(DBAPIError):
            with db.session(t) as s:
                s.execute(text("DELETE FROM audit.audit_log WHERE tenant_id = :t"), {"t": t})
        with self.assertRaises(DBAPIError):          # nem o papel de serviço (gatilho)
            with db.service_session(t) as s:
                s.execute(text("UPDATE audit.audit_log SET actor = 'outro' WHERE tenant_id = :t"), {"t": t})

    def test_verify_detects_change_made_outside(self):
        from sqlalchemy import create_engine
        from tests_platform.support import ADMIN_URL, _state
        from vyonix.audit import service as audit
        from vyonix.db.session import _url
        t = new_org(db)
        with db.session(t) as s:
            audit.record(s, actor="a", action="x.one")
            seq = audit.record(s, actor="a", action="x.two").seq
            audit.record(s, actor="a", action="x.three")
        # um superusuário desliga o gatilho e altera um registro: a verificação aponta
        u = ADMIN_URL.rsplit("/", 1)[0] + "/" + _state["name"]
        eng = create_engine(_url(u), isolation_level="AUTOCOMMIT")
        with eng.connect() as c:
            c.execute(text("ALTER TABLE audit.audit_log DISABLE TRIGGER audit_log_immutable"))
            c.execute(text("UPDATE audit.audit_log SET actor = 'adulterado' WHERE seq = :q"), {"q": seq})
            c.execute(text("ALTER TABLE audit.audit_log ENABLE TRIGGER audit_log_immutable"))
        eng.dispose()
        with db.session(t) as s:
            self.assertEqual(audit.verify(s), [seq])


class Auth(unittest.TestCase):
    def setUp(self):
        self.t = new_org(db)

    def _login(self, user="admin", pw=ADMIN_PW):
        from vyonix.auth import service as auth
        with db.session(self.t) as s:
            tok, ses, u = auth.login(s, user, pw, ip="10.0.0.1")
        return tok

    def _principal(self, tok):
        from vyonix.auth import service as auth
        with db.session(auth.tenant_of_token(tok)) as s:
            return auth.authenticate(s, tok)

    def _fail(self, user, pw):
        from vyonix.auth import service as auth
        from vyonix.errors import Unauthorized
        s_ctx = db.session(self.t)
        s = s_ctx.__enter__()
        try:
            with self.assertRaises(Unauthorized) as cm:
                auth.login(s, user, pw)
            s.commit()             # a API confirma a tentativa mesmo com falha
        finally:
            s_ctx.__exit__(None, None, None)
        return str(cm.exception)

    def test_login_session_and_permissions(self):
        tok = self._login()
        self.assertTrue(tok.startswith(str(self.t) + "."))
        p = self._principal(tok)
        self.assertEqual(p.stage, "ok")
        self.assertTrue(p.has("core.users.manage"))
        self.assertTrue(p.has("clinical.patients.merge"))
        from vyonix.auth.models import AuthSession
        from vyonix.auth.service import token_hash
        with db.session(self.t) as s:
            ses = s.execute(select(AuthSession)).scalar_one()
            self.assertEqual(ses.token_hash, token_hash(tok))
            self.assertNotIn(tok.split(".", 1)[1], str(ses.__dict__))

    def test_generic_message_and_lockout(self):
        m1 = self._fail("ninguem", "x")
        m2 = self._fail("admin", "errada")
        self.assertEqual(m1, m2)
        for _ in range(4):
            self._fail("admin", "errada")
        self._fail("admin", ADMIN_PW)                     # bloqueada: senha certa também falha
        from vyonix.auth import service as auth
        from vyonix.auth.models import User
        with db.session(self.t) as s:
            u = s.execute(select(User)).scalar_one()
            self.assertIsNotNone(u.locked_until)
            auth.unlock(s, u.id, actor="teste")
        self._login()
        from vyonix.audit.models import AuditEntry
        with db.session(self.t) as s:
            n = s.execute(select(AuditEntry).where(AuditEntry.action == "auth.login_failed")).scalars().all()
            self.assertEqual(len(n), 7)

    def test_role_scoped_by_site(self):
        from vyonix.auth import service as auth
        from vyonix.tenancy import service as tenancy
        with db.session(self.t) as s:
            a = tenancy.sites(s)[0]
            b = tenancy.save_site(s, name="Unidade B", actor="t")
            auth.create_user(s, username="rec", display_name="Rec", password="Recepcao-123",
                             roles=[("recepcionista", b.id)], must_change=False, actor="t")
            a_id, b_id = a.id, b.id
        p = self._principal(self._login("rec", "Recepcao-123"))
        self.assertTrue(p.has("clinical.patients.write", b_id))
        self.assertFalse(p.has("clinical.patients.write", a_id))
        self.assertFalse(p.has("core.users.read"))
        self.assertEqual(p.sites_for("clinical.patients.write"), {b_id})

    def test_must_change_password_stage(self):
        from vyonix.auth import service as auth
        from vyonix.errors import Forbidden
        with db.session(self.t) as s:
            auth.create_user(s, username="novo", display_name="Novo", password="Inicial-1234",
                             roles=[("tecnico", None)], actor="t")
        tok = self._login("novo", "Inicial-1234")
        p = self._principal(tok)
        self.assertEqual(p.stage, "password_change")
        with self.assertRaises(Forbidden):
            auth.require(p, "clinical.studies.read")
        with db.session(self.t) as s:
            auth.change_password(s, p, "Inicial-1234", "Trocada-5678")
        self.assertEqual(self._principal(tok).stage, "ok")

    def test_mfa_totp_flow(self):
        from vyonix.auth import service as auth, totp
        from vyonix.errors import Unauthorized
        key = b"k" * 32
        tok = self._login()
        p = self._principal(tok)
        with db.session(self.t) as s:
            info = auth.mfa_enroll_start(s, p, key)
        self.assertTrue(info["uri"].startswith("otpauth://totp/"))
        now = time.time()
        code = totp.code_at(info["secret"], totp.current_step(now))
        with db.session(self.t) as s:
            recovery = auth.mfa_enroll_confirm(s, p, key, code)
        self.assertEqual(len(recovery), 10)
        tok2 = self._login()
        p2 = self._principal(tok2)
        self.assertEqual(p2.stage, "mfa_verify")
        self.assertFalse(p2.has("core.users.read"))
        with self.assertRaises(Unauthorized):            # mesmo código não vale duas vezes
            with db.session(self.t) as s:
                auth.mfa_verify(s, p2, key, code)
        with db.session(self.t) as s:
            auth.mfa_verify(s, p2, key, recovery[0])
        self.assertEqual(self._principal(tok2).stage, "ok")
        p3 = self._principal(self._login())
        with self.assertRaises(Unauthorized):            # código de recuperação é de uso único
            with db.session(self.t) as s:
                auth.mfa_verify(s, p3, key, recovery[0])

    def test_mfa_required_forces_enrollment(self):
        from vyonix.auth import service as auth
        from vyonix.auth.models import User
        with db.session(self.t) as s:
            u = s.execute(select(User)).scalar_one()
            auth.update_user(s, u.id, mfa_required=True, actor="t")
        self.assertEqual(self._principal(self._login()).stage, "mfa_enroll")

    def test_session_expiry_and_logout(self):
        from vyonix.auth import service as auth
        from vyonix.auth.models import AuthSession
        from vyonix.db.base import utcnow
        from vyonix.errors import Unauthorized
        tok = self._login()
        p = self._principal(tok)
        with db.session(self.t) as s:
            auth.logout(s, p)
        with self.assertRaises(Unauthorized):
            self._principal(tok)
        tok = self._login()
        with db.session(self.t) as s:
            ses = s.execute(select(AuthSession).where(AuthSession.ended_at.is_(None))).scalar_one()
            ses.expires_at = utcnow() - timedelta(seconds=1)
        with self.assertRaises(Unauthorized):
            self._principal(tok)
        with self.assertRaises(Unauthorized):       # token de outra clínica não acha a sessão
            other = new_org(db)
            with db.session(other) as s:
                auth.authenticate(s, self._login())

    def test_last_admin_protected(self):
        from vyonix.auth import service as auth
        from vyonix.auth.models import User
        from vyonix.errors import Conflict
        with self.assertRaises(Conflict):
            with db.session(self.t) as s:
                u = s.execute(select(User)).scalar_one()
                auth.set_roles(s, u.id, [("tecnico", None)], actor="t")
        with self.assertRaises(Conflict):
            with db.session(self.t) as s:
                u = s.execute(select(User)).scalar_one()
                auth.update_user(s, u.id, active=False, actor="t")

    def test_weak_password_rejected(self):
        from vyonix.auth import service as auth
        from vyonix.errors import ValidationFailed
        for pw in ("curta1A", "semnumeroAAAA", "123456789012"):
            with self.assertRaises(ValidationFailed):
                with db.session(self.t) as s:
                    auth.create_user(s, username="fraco", display_name="F", password=pw, roles=[], actor="t")


class SettingsAndModules(unittest.TestCase):
    def setUp(self):
        self.t = new_org(db)

    def test_settings_validation_history_and_conflict(self):
        from vyonix.errors import Conflict, ValidationFailed
        from vyonix.settings import service as settings
        with db.session(self.t) as s:
            d = settings.describe(s, "core", "security")
            self.assertEqual(d["value"]["lockout_attempts"], 5)
            self.assertEqual(d["row_version"], 0)
            settings.put(s, "core", "security", {**d["value"], "lockout_attempts": 3}, actor="t", reason="política")
        with self.assertRaises(ValidationFailed):
            with db.session(self.t) as s:
                settings.put(s, "core", "security", {"lockout_attempts": 1}, actor="t")
        with self.assertRaises(ValidationFailed):
            with db.session(self.t) as s:
                settings.put(s, "core", "security", {"inventado": 1}, actor="t")
        with self.assertRaises(Conflict):
            with db.session(self.t) as s:
                settings.put(s, "core", "security", {"lockout_attempts": 4}, actor="t", expected_version=0)
        with db.session(self.t) as s:
            self.assertEqual(settings.get(s, "core", "security")["lockout_attempts"], 3)
            h = settings.history(s, "core", "security")
            self.assertEqual(len(h), 1)
            self.assertEqual(h[0]["reason"], "política")

    def test_module_enable_rules(self):
        from vyonix.errors import Conflict, NotLicensed, ValidationFailed
        from vyonix.modules import registry
        no = lambda s, c: (False, "sem licença")        # noqa: E731
        yes = lambda s, c: (True, "")                   # noqa: E731
        with db.session(self.t) as s:
            self.assertTrue(registry.is_enabled(s, "core"))
            self.assertFalse(registry.is_enabled(s, "print"))
        with self.assertRaises(NotLicensed):
            with db.session(self.t) as s:
                registry.enable(s, "print", actor="t", license_check=no)
        with self.assertRaises(ValidationFailed):
            with db.session(self.t) as s:
                registry.enable(s, "notify", actor="t", license_check=yes)    # planejado
        with self.assertRaises(ValidationFailed):
            with db.session(self.t) as s:
                registry.disable(s, "core", actor="t")
        with db.session(self.t) as s:
            registry.enable(s, "print", actor="t", license_check=yes)
            self.assertTrue(registry.is_enabled(s, "print"))
            registry.disable(s, "print", actor="t")
            self.assertFalse(registry.is_enabled(s, "print"))


class Events(unittest.TestCase):
    def setUp(self):
        self.t = new_org(db)

    def _drain(self, bus):
        from vyonix.events.worker import process_batch
        n = 0
        while (k := process_batch(db, bus)):
            n += k
        return n

    def test_outbox_is_transactional(self):
        from vyonix.events.bus import publish
        from vyonix.events.models import OutboxEvent
        with self.assertRaises(RuntimeError):
            with db.session(self.t) as s:
                publish(s, "test.thing.done.v1", {"a": 1}, source="test")
                raise RuntimeError("desfaz")
        with db.session(self.t) as s:
            self.assertEqual(s.execute(select(OutboxEvent).where(OutboxEvent.type == "test.thing.done.v1"))
                             .scalars().all(), [])
        with self.assertRaises(ValueError):
            with db.session(self.t) as s:
                publish(s, "SemVersao", {}, source="test")

    def test_delivery_dedup_and_retry(self):
        from vyonix.events.bus import Bus, publish
        from vyonix.events.models import OutboxEvent
        bus = Bus()
        got, flaky = [], {"n": 0}

        @bus.subscribe("test.ev.*.v1", "coletor")
        def collect(s, ev):
            got.append((ev.type, ev.data["i"], ev.tenant_id))

        @bus.subscribe("test.ev.created.v1", "instavel")
        def unstable(s, ev):
            flaky["n"] += 1
            if flaky["n"] == 1:
                raise RuntimeError("falha temporária")

        with db.session(self.t) as s:
            publish(s, "test.ev.created.v1", {"i": 1}, source="test")
            publish(s, "test.ev.updated.v1", {"i": 2}, source="test")
        self._drain(bus)
        with db.service_session() as s:
            ev = s.execute(select(OutboxEvent).where(OutboxEvent.tenant_id == self.t,
                                                     OutboxEvent.type == "test.ev.created.v1")).scalar_one()
            self.assertIsNone(ev.published_at)
            self.assertEqual(ev.attempts, 1)
            self.assertIn("falha temporária", ev.last_error)
            ev.available_at = ev.available_at - timedelta(hours=2)     # antecipa a nova tentativa
        self._drain(bus)
        self.assertEqual(sorted(x[1] for x in got), [1, 2])           # coletor não repetiu o evento 1
        self.assertEqual(flaky["n"], 2)
        self.assertTrue(all(x[2] == self.t for x in got))
        with db.service_session() as s:
            pending = s.execute(select(OutboxEvent).where(OutboxEvent.tenant_id == self.t,
                                                          OutboxEvent.published_at.is_(None))).scalars().all()
            self.assertEqual([e.type for e in pending if e.type.startswith("test.")], [])

    def test_concurrent_workers_do_not_double_process(self):
        import threading
        from vyonix.events.bus import Bus, publish
        bus, seen, lock = Bus(), [], threading.Lock()

        @bus.subscribe("test.par.*.v1", "paralelo")
        def h(s, ev):
            time.sleep(0.01)
            with lock:
                seen.append(ev.id)

        with db.session(self.t) as s:
            for i in range(40):
                publish(s, "test.par.item.v1", {"i": i}, source="test")
        threads = [threading.Thread(target=self._drain, args=(bus,)) for _ in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(seen), 40)
        self.assertEqual(len(set(seen)), 40)


if __name__ == "__main__":
    unittest.main()
