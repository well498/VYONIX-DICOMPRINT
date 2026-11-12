"""P0 BLOQUEANTE 0.3.2 — isolamento por unidade (decisão do proprietário de 05/11/2026).

Cenário fictício: instituição com Unidade A e Unidade B, mais uma segunda instituição (fronteira RLS).
Usuários: tec_a (técnico@A), tec_b (técnico@B), tec_ab (técnico@A e @B), tec_g (técnico em todas as unidades),
med_a (médico com vínculo só na A), coord_a (coordenação@A), fin (financeiro), recep_a (recepcionista@A).
Exames: s_a (unidade A), s_b (unidade B), s_n (SEM unidade) e s_x (outra instituição); pedidos o_a/o_b/o_n
(atendimento na A, na B e pedido sem atendimento).

Regras verificadas POR API DIRETA (não por menu):
 1. cada usuário só lista/lê/altera exames das unidades autorizadas;
 2. quem tem várias unidades alcança exclusivamente essas;
 3. exame sem unidade: só quem tem a permissão em TODAS as unidades (papel global) — regra proposta, a confirmar;
 4. PACS (QIDO/WADO), visualizador, laudos e RIS respeitam a unidade;
 5. nada atravessa instituições;
 6. toda alteração revalida permissão + unidade e não muda o estado;
 7. financeiro não lê dados clínicos nem pessoais;
 8. a tentativa negada fica na auditoria (ação proposta: ``access.denied``).

Testes marcados "falha esperada antes da correção" documentam o comportamento atual (develop 0464c16) que viola o
P0. ATENÇÃO: ``test_m2_security.test_r04_technician_limited_to_own_unit`` exige hoje o contrário da regra 3 (exame
sem unidade alcançado por papel de qualquer unidade, A07 V-03) e terá de ser revisto junto com a correção.
Dados 100% sintéticos; PostgreSQL de teste; motor PACS dublê; sem rede.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import tests_platform.test_ris_prep as _prep
from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import new_org

PW, NEW = _prep.PW, _prep.NEW
BRT = timezone(timedelta(hours=-3))
DW = "/api/v1/pacs/dicomweb"
DENIED = (403, 404)


def setUpModule():
    _prep.setUpModule()


def _uids(resp) -> set[str]:
    if resp.status_code == 204:
        return set()
    return {((d.get("0020000D") or {}).get("Value") or [None])[0] for d in resp.json()}


class UnitIsolation(_prep.Prep):
    """Nomes ``test_pNN_`` curtos: ApiBase deriva o código da organização dos 20 primeiros caracteres do nome."""
    locals().update({n: None for n in dir(_prep.Prep) if n.startswith("test_")})   # só os testes desta classe

    # ------------------------------------------------------------------ cenário
    def setUp(self):
        super().setUp()
        from vyonix.clinical import service as clinical
        from vyonix.clinical.models import Study
        self.A, self.B = self._site("Unidade A Ficticia"), self._site("Unidade B Ficticia")
        A, B = self.A, self.B
        self.admin.post("/api/v1/role-templates/financeiro/activate")
        self.u = {}
        for login, roles in (("tec_a", [("tecnico", A)]), ("tec_b", [("tecnico", B)]),
                             ("tec_ab", [("tecnico", A), ("tecnico", B)]), ("tec_g", [("tecnico", None)]),
                             ("coord_a", [("coordenador_cdi", A)]), ("fin", [("financeiro", None)]),
                             ("recep_a", [("recepcionista", A)]), ("med_a", [("medico", A)])):
            self.u[login] = self._user(login, roles)
        # médico com vínculo só na Unidade A
        mid = self._uid_of("med_a")
        self.med_a_pid = self.admin.post("/api/v1/report/physicians", json={
            "user_id": mid, "full_name": "Dr. Medico A Ficticio", "crm": "9001", "crm_uf": "PB"}).json()["id"]
        r = self.admin.post(f"/api/v1/report/physicians/{self.med_a_pid}/links",
                            json={"site_id": A, "valid_from": "2026-01-01"})
        self.assertIn(r.status_code, (200, 201), r.text)
        # estudos (mesmo paciente: também exercita anteriores e histórico) e pedidos com atendimento por unidade
        self.s = {"a": self.study(1), "b": self.study(2), "n": self.study(3)}
        self.uid = {"a": uid(71), "b": uid(72), "n": uid(73)}
        self.o = {}
        with _prep.db.session(self.t) as s:
            for k, site in (("a", A), ("b", B), ("n", None)):
                enc = clinical.create_encounter(s, patient_id=self.pat, site_id=uuid.UUID(site),
                                                actor="t").id if site else None
                o = clinical.create_order(s, patient_id=self.pat, encounter_id=enc, actor="recepcao")
                self.o[k] = str(o.id)
                st = s.get(Study, uuid.UUID(self.s[k]))
                st.site_id, st.order_id = (uuid.UUID(site) if site else None), o.id
        # preparação concluída e encaminhada pelo técnico global (para a fila de laudos)
        for k in ("a", "b", "n"):
            u = f"/api/v1/ris/prep/{self.s[k]}"
            for code in ("patient_identity", "procedure", "quality"):
                self.assertEqual(self.u["tec_g"].post(u + "/check", json={"code": code}).status_code, 200)
            self.u["tec_g"].post(u + "/duplicate", json={})        # "não é duplicado" (mesmo paciente, mesma data)
            r = self.u["tec_g"].post(u + "/forward")
            self.assertEqual(r.status_code, 200, f"{k}: {r.text}")
        # anexo, suspeita e comentário no exame da B (alvos de leitura/alteração indevida)
        ub = f"/api/v1/ris/prep/{self.s['b']}"
        r = self.u["tec_g"].post(ub + "/attachments?kind=document&filename=pedido-b.pdf", content=_prep.pdf())
        self.assertEqual(r.status_code, 201, r.text)
        self.att_b = r.json()["id"]
        self.u["tec_g"].post(ub + "/comments", json={"text": "Comentário ficticio da unidade B."})
        # segunda instituição, com estudo próprio
        self.t2 = new_org(_prep.db, f"outra-{uuid.uuid4().hex[:6]}")
        from vyonix.pacs import service as pacs
        with _prep.db.session(self.t2) as s:
            pacs.ingest(s, MemoryBackend(), make_dicom(study=uid(95), series=uid(95, 1), sop=uid(95, 1, 1),
                                                       patient_id="OUTRA1"), actor="pacs-sync", via="dimse")
            st = clinical.register_study(s, study_instance_uid=uid(95), modality="CT", actor="t")
            self.s["x"], self.uid["x"] = str(st.id), uid(95)

    def login(self, *a, **kw):
        # o cenário cria muitos usuários seguidos; o limite de 20 logins/min por IP (app.py RateLimiter) é zerado
        # só neste cliente de teste — o limite em si é coberto por test_auth_password_security
        self.client.app.state.login_limiter.hits.clear()
        return super().login(*a, **kw)

    def _site(self, name):
        r = self.admin.post("/api/v1/sites", json={"name": name})
        self.assertIn(r.status_code, (200, 201), r.text)
        return r.json()["id"]

    def _uid_of(self, login):
        return next(x["id"] for x in self.admin.get("/api/v1/users").json() if x["username"] == login)

    def _user(self, login, roles):
        r = self.admin.post("/api/v1/users", json={"username": login, "display_name": login, "password": PW,
                                                   "roles": [{"role": ro, "site_id": si} for ro, si in roles]})
        self.assertEqual(r.status_code, 201, r.text)
        c = self.login(login, PW)
        c.post("/api/v1/auth/password", json={"current": PW, "new": NEW})
        return self.login(login, NEW)

    def denied(self, r, what):
        self.assertIn(r.status_code, DENIED, f"{what}: esperado 403/404, obtido {r.status_code} {r.text[:200]}")

    # quem deve alcançar cada exame (regra 3: sem unidade só global)
    SCOPE = {"tec_a": {"a"}, "tec_b": {"b"}, "tec_ab": {"a", "b"}, "tec_g": {"a", "b", "n"},
             "recep_a": {"a"}, "coord_a": {"a"}, "med_a": {"a"}}

    def _today(self):
        return datetime.now(BRT).date()

    # ------------------------------------------------------------------ controles positivos (passam hoje)
    def test_p01_positive_controls_authorized_access_still_works(self):
        for login, keys in (("tec_a", {"a"}), ("tec_b", {"b"}), ("tec_ab", {"a", "b"}), ("tec_g", {"a", "b", "n"})):
            c = self.u[login]
            items = {x["study_id"] for x in c.get("/api/v1/ris/prep").json()["items"]}
            for k in keys:
                with self.subTest(user=login, study=k):
                    self.assertIn(self.s[k], items)
                    self.assertEqual(c.get(f"/api/v1/ris/prep/{self.s[k]}").status_code, 200)
                    self.assertEqual(c.get(f"/api/v1/ris/studies/{self.s[k]}/timeline").status_code, 200)
                    self.assertEqual(c.get(f"{DW}/studies/{self.uid[k]}/metadata").status_code, 200)
        wl = {x["study_id"] for x in self.u["med_a"].get("/api/v1/report/worklist").json()["items"]}
        self.assertIn(self.s["a"], wl)

    # ------------------------------------------------------------------ listas
    def _lists(self, login):
        """Itens (por chave a/b/n/x) que cada lista devolve ao usuário."""
        c, out = self.u[login], {}
        inv_s = {v: k for k, v in self.s.items()}
        inv_u = {v: k for k, v in self.uid.items()}
        inv_o = {v: k for k, v in self.o.items()}
        r = c.get("/api/v1/ris/prep")
        if r.status_code == 200:
            out["/ris/prep"] = {inv_s[x["study_id"]] for x in r.json()["items"] if x["study_id"] in inv_s}
        d = self._today()
        r = c.get("/api/v1/ris/exam-center", params={"date_from": (d - timedelta(days=1)).isoformat(),
                                                     "date_to": (d + timedelta(days=1)).isoformat()})
        if r.status_code == 200:
            out["/ris/exam-center"] = {inv_o[x["order_id"]] for x in r.json()["items"] if x["order_id"] in inv_o}
        day = (datetime.now(timezone.utc) - timedelta(minutes=10)).astimezone(BRT).date()
        r = c.get("/api/v1/ris/technician-panel", params={"day": day.isoformat()})
        if r.status_code == 200:
            out["/ris/technician-panel"] = {inv_u[x["study_uid"]] for x in r.json().get("received", [])
                                            if x["study_uid"] in inv_u}
        r = c.get("/api/v1/studies")
        if r.status_code == 200:
            out["/studies"] = {inv_s[x["id"]] for x in r.json() if x["id"] in inv_s}
        r = c.get("/api/v1/orders")
        if r.status_code == 200:
            out["/orders"] = {inv_o[x["id"]] for x in r.json() if x["id"] in inv_o}
        r = c.get("/api/v1/report/worklist")
        if r.status_code == 200:
            out["/report/worklist"] = {inv_s[x["study_id"]] for x in r.json()["items"] if x.get("study_id") in inv_s}
        r = c.get(f"{DW}/studies")
        if r.status_code in (200, 204):
            out["QIDO /studies"] = {inv_u[u] for u in _uids(r) if u in inv_u}
        return out

    def _assert_lists(self, login):
        allowed = self.SCOPE[login]
        bad = {ep: sorted(got - allowed) for ep, got in self._lists(login).items() if got - allowed}
        self.assertEqual(bad, {}, f"{login} vê itens fora da autorização (a=UnidA b=UnidB n=sem unidade)")

    def test_p02_lists_tec_a(self):                  # falha esperada antes da correção (exam-center, panel, QIDO, orders, sem unidade)
        self._assert_lists("tec_a")

    def test_p03_lists_tec_b(self):                  # falha esperada antes da correção
        self._assert_lists("tec_b")

    def test_p04_lists_tec_ab(self):                 # falha esperada antes da correção (sem unidade visível)
        self._assert_lists("tec_ab")

    def test_p05_lists_tec_global_sees_all_but_other_institution(self):
        got = self._lists("tec_g")
        for ep in ("/ris/prep", "/studies", "QIDO /studies"):
            with self.subTest(ep=ep):
                self.assertEqual(got[ep], {"a", "b", "n"})

    def test_p06_lists_recep_a(self):                # falha esperada antes da correção (/orders, exam-center, /studies sem unidade)
        self._assert_lists("recep_a")

    def test_p07_lists_coord_a(self):                # falha esperada antes da correção
        self._assert_lists("coord_a")

    def test_p08_lists_med_a(self):                  # falha esperada antes da correção (QIDO / exam-center sem filtro)
        self._assert_lists("med_a")

    # ------------------------------------------------------------------ leitura por id
    def _reads(self, c, k):
        sid, suid = self.s[k], self.uid[k]
        return {
            "prep": c.get(f"/api/v1/ris/prep/{sid}"),
            "timeline": c.get(f"/api/v1/ris/studies/{sid}/timeline"),
            "priors": c.get(f"/api/v1/ris/studies/{sid}/priors"),
            "eligible": c.get(f"/api/v1/ris/prep/{sid}/eligible-physicians"),
            "wado_meta": c.get(f"{DW}/studies/{suid}/metadata"),
            "qido_series": c.get(f"{DW}/studies/{suid}/series"),
            "viewer_launch": c.get("/api/v1/pacs/viewer/launch", params={"study_uid": suid, "preview": "true"}),
            "quality": c.get(f"/api/v1/pacs/studies/{suid}/quality"),
        }

    def _assert_reads_denied(self, login, keys):
        c = self.u[login]
        for k in keys:
            for name, r in self._reads(c, k).items():
                with self.subTest(user=login, study=k, ep=name):
                    self.denied(r, f"{login} {name} exame {k}")

    def test_p09_read_by_id_tec_a_other_unit(self):          # falha esperada antes da correção (WADO, viewer, series)
        self._assert_reads_denied("tec_a", ("b",))

    def test_p10_read_by_id_tec_b_other_unit(self):          # falha esperada antes da correção
        self._assert_reads_denied("tec_b", ("a",))

    def test_p11_read_by_id_unitless_only_global(self):      # falha esperada antes da correção (V-03 libera sem unidade)
        for login in ("tec_a", "tec_b", "tec_ab", "recep_a", "coord_a", "med_a"):
            self._assert_reads_denied(login, ("n",))
        self.assertEqual(self.u["tec_g"].get(f"/api/v1/ris/prep/{self.s['n']}").status_code, 200)

    def test_p12_read_by_id_med_a_other_unit(self):          # falha esperada antes da correção (WADO/viewer: access != linked)
        self._assert_reads_denied("med_a", ("b",))

    def test_p13_attachment_of_other_unit(self):          # falha esperada antes da correção (financeiro baixa anexo)
        for login in ("tec_a", "med_a", "recep_a", "fin"):
            with self.subTest(user=login):
                self.denied(self.u[login].get(f"/api/v1/ris/prep/attachments/{self.att_b}"), f"{login} anexo B")

    def test_p14_priors_and_history_restrict_other_units(self):   # falha esperada antes da correção
        c = self.u["tec_a"]
        pr = c.get(f"/api/v1/ris/studies/{self.s['a']}/priors").json()["items"]
        for it in pr:
            if it["study_id"] in (self.s["b"], self.s["n"]):
                with self.subTest(prior=it["study_id"]):
                    self.assertTrue(it.get("restricted"), f"anterior fora da unidade exposto: {it}")
                    self.assertIsNone(it.get("study_instance_uid"))
        h = c.get(f"/api/v1/ris/patients/{self.pat}/history")
        self.assertEqual(h.status_code, 200, h.text)
        for it in h.json()["items"]:
            if it.get("kind") == "study" and it.get("study_id") in (self.s["b"], self.s["n"]):
                with self.subTest(history=it["study_id"]):
                    self.assertTrue(it["restricted"], f"histórico expõe exame fora da unidade: {it}")

    def test_p15_comments_of_other_unit_not_leaked(self):
        r = self.u["tec_a"].get(f"/api/v1/ris/prep/{self.s['b']}")
        self.denied(r, "tec_a detalhe/comentários B")

    # ------------------------------------------------------------------ alterações
    def _writes(self, c, k):
        sid = self.s[k]
        u = f"/api/v1/ris/prep/{sid}"
        return {
            "check": lambda: c.post(u + "/check", json={"code": "series"}),
            "comment": lambda: c.post(u + "/comments", json={"text": "indevido"}),
            "flag": lambda: c.post(u + "/flags", json={"code": "artifacts", "note": "indevido"}),
            "attachment": lambda: c.post(u + "/attachments?kind=document&filename=x.pdf", content=_prep.pdf()),
            "priority": lambda: c.post(u + "/priority", json={"priority": "stat", "reason": "indevido"}),
            "physician": lambda: c.post(u + "/physician", json={"physician_id": self.docs["ana"][1],
                                                                 "reason": "indevido"}),
            "forward": lambda: c.post(u + "/forward"),
            "duplicate": lambda: c.post(u + "/duplicate", json={}),
            "read": lambda: c.post(u + "/read"),
            "cancel": lambda: c.post(u + "/cancel", json={"reason": "indevido"}),
            "return": lambda: c.post(u + "/return", json={"reason": "indevido"}),
            "reconcile": lambda: c.post(f"/api/v1/studies/{sid}/reconcile", json={"order_id": self.o[k]}),
            "claim": lambda: c.post(f"/api/v1/report/queue/{sid}/claim"),
            "report_open": lambda: c.post("/api/v1/report/reports", json={"study_id": sid}),
        }

    def _snapshot(self, k):
        d = self.u["tec_g"].get(f"/api/v1/ris/prep/{self.s[k]}").json()
        return (d.get("stage"), d.get("priority"), (d.get("physician") or {}).get("id") if isinstance(
            d.get("physician"), dict) else d.get("physician"), len(d.get("comments") or []),
            len(d.get("flags") or []), len(d.get("attachments") or []))

    def _assert_writes_denied(self, login, k):
        before = self._snapshot(k)
        for name, call in self._writes(self.u[login], k).items():
            with self.subTest(user=login, study=k, op=name):
                self.denied(call(), f"{login} {name} exame {k}")
        with self.subTest(user=login, study=k, op="estado inalterado"):
            self.assertEqual(self._snapshot(k), before, f"{login} alterou o exame {k}")

    def test_p16_writes_tec_a_other_unit(self):
        self._assert_writes_denied("tec_a", "b")

    def test_p17_writes_tec_b_other_unit(self):
        self._assert_writes_denied("tec_b", "a")

    def test_p18_writes_unitless_by_site_roles(self):        # falha esperada antes da correção (V-03 libera sem unidade)
        for login in ("tec_a", "tec_ab", "coord_a", "recep_a", "med_a"):
            self._assert_writes_denied(login, "n")

    def test_p19_writes_coord_a_and_med_a_other_unit(self):
        self._assert_writes_denied("coord_a", "b")
        self._assert_writes_denied("med_a", "b")

    def test_p20_flag_resolve_and_share_delete_other_unit(self):
        g = self.u["tec_g"]
        fid = g.post(f"/api/v1/ris/prep/{self.s['b']}/flags", json={"code": "artifacts", "note": "B"}).json()["id"]
        self.denied(self.u["tec_a"].post(f"/api/v1/ris/prep/flags/{fid}/resolve"), "tec_a resolve suspeita B")
        self.assertIn(fid, [f["id"] for f in g.get(f"/api/v1/ris/prep/{self.s['b']}").json()["flags"]
                            if not f.get("resolved_at")])

    def test_p21_report_of_other_unit(self):
        ana = self.docs["ana"][0]
        r = ana.post("/api/v1/report/reports", json={"study_id": self.s["b"]})
        self.assertEqual(r.status_code, 201, r.text)
        rid = r.json()["id"]
        rv = ana.get(f"/api/v1/report/reports/{rid}").json()["row_version"]
        base = f"/api/v1/report/reports/{rid}"
        for login in ("med_a", "tec_a", "coord_a", "fin"):
            c = self.u[login]
            with self.subTest(user=login):
                self.denied(c.get(base), f"{login} lê laudo B")
                self.denied(c.put(base, json={"body": "indevido", "row_version": rv}), f"{login} edita laudo B")
                self.denied(c.post(base + "/finalize", json={"password": NEW, "row_version": rv}),
                            f"{login} libera laudo B")
                self.denied(c.get(base + "/draft-pdf"), f"{login} pdf rascunho B")

    # ------------------------------------------------------------------ instituição
    def test_p22_other_institution_invisible_to_everyone(self):
        for login in ("tec_g", "coord_a", "med_a"):
            c = self.u[login]
            for name, r in self._reads(c, "x").items():
                with self.subTest(user=login, ep=name):
                    self.denied(r, f"{login} {name} outra instituição")
            with self.subTest(user=login, ep="lists"):
                self.assertFalse(any("x" in v for v in self._lists(login).values()))
        self.assertEqual(self.admin.get(f"/api/v1/ris/prep/{self.s['x']}").status_code, 404)

    # ------------------------------------------------------------------ financeiro
    def test_p23_financeiro_no_clinical_or_personal_data(self):   # falha esperada antes da correção (F-03)
        c = self.u["fin"]
        d = self._today()
        eps = {
            "prep_detail": c.get(f"/api/v1/ris/prep/{self.s['a']}"),
            "timeline": c.get(f"/api/v1/ris/studies/{self.s['a']}/timeline"),
            "priors": c.get(f"/api/v1/ris/studies/{self.s['a']}/priors"),
            "history": c.get(f"/api/v1/ris/patients/{self.pat}/history"),
            "patients": c.get("/api/v1/patients"),
            "patient": c.get(f"/api/v1/patients/{self.pat}"),
            "prep_list": c.get("/api/v1/ris/prep"),
            "exam_center": c.get("/api/v1/ris/exam-center", params={"date_from": d.isoformat(),
                                                                    "date_to": d.isoformat()}),
            "technician_panel": c.get("/api/v1/ris/technician-panel"),
            "ris_worklist": c.get("/api/v1/ris/worklist"),
            "studies": c.get("/api/v1/studies"),
            "qido": c.get(f"{DW}/studies"),
            "report_worklist": c.get("/api/v1/report/worklist"),
        }
        for name, r in eps.items():
            with self.subTest(ep=name):
                if r.status_code == 200:          # se a rota for liberada no futuro, não pode trazer dado pessoal
                    self.assertNotIn("Paciente Prep", r.text, f"financeiro lê dado pessoal em {name}")
                    self.assertNotIn("patient_name", r.text, f"financeiro lê dado pessoal em {name}")
                else:
                    self.denied(r, f"financeiro {name}")

    # ------------------------------------------------------------------ auditoria
    def test_p24_denied_access_is_audited(self):             # falha esperada antes da correção (sem 'access.denied')
        from vyonix.audit import service as audit
        self.denied(self.u["tec_a"].get(f"/api/v1/ris/prep/{self.s['b']}"), "tec_a detalhe B")
        self.denied(self.u["tec_a"].post(f"/api/v1/ris/prep/{self.s['b']}/priority",
                                         json={"priority": "stat", "reason": "indevido"}), "tec_a prioridade B")
        with _prep.db.session(self.t) as s:
            ev = [e for e in audit.query(s, action="access.denied", limit=100)
                  if e.actor == "tec_a" and e.target_id == self.s["b"]]
        self.assertGreaterEqual(len(ev), 2, "tentativas negadas por escopo de unidade não auditadas")
        self.assertTrue(all((e.details or {}).get("reason") or (e.details or {}).get("code") for e in ev), ev)

    def test_p25_backfill_simulation_then_approved_apply(self):
        """Estudos antigos sem unidade: simulação só leitura; aplicação só do arquivo aprovado (SHA-256), auditada."""
        import tempfile
        from pathlib import Path
        from vyonix.clinical import service as clinical
        from vyonix.clinical import site_backfill as sb
        from vyonix.clinical.models import Study, StudySiteAssignment
        from vyonix.tenancy.models import Organization
        with _prep.db.session(self.t) as s:          # estudo antigo sem unidade, pedido com atendimento na A
            st = clinical.register_study(s, study_instance_uid=uid(81), modality="CT", actor="t")
            st.order_id = uuid.UUID(self.o["a"])
            old = str(st.id)
            code = s.get(Organization, self.t).code
        def sem_unidade():
            with _prep.db.session(self.t) as s:
                return {str(x.id) for x in s.query(Study).filter(Study.site_id.is_(None))}
        before = sem_unidade()
        self.assertIn(old, before)
        sim = sb.simulate(_prep.db, self.t)
        self.assertEqual(sem_unidade(), before, "a simulação não pode gravar")
        row = next(r for r in sim["linhas"] if r["study_id"] == old)
        self.assertEqual((row["status"], row["decisao"], row["unidade_proposta_id"]), ("proposta", "aplicar", self.A))
        self.assertNotIn(self.s["x"], {r["study_id"] for r in sim["linhas"]}, "outra instituição na simulação")
        blob = Path(tempfile.mkdtemp()) / "sim.json"
        h = sb.write_outputs(sim, blob)
        self.assertNotIn("Paciente", blob.read_text(encoding="utf-8"))
        with self.assertRaises(sb.BackfillRefused):
            sb.load_approved(blob, "0" * 64, org_code=code, tenant_id=self.t)
        with self.assertRaises(sb.BackfillRefused):
            sb.load_approved(blob, h, org_code="outra", tenant_id=self.t)
        sim2, h2 = sb.load_approved(blob, h, org_code=code, tenant_id=self.t)
        out = sb.apply(_prep.db, self.t, sim2, h2, approved_by="proprietario (teste)", actor="teste")
        self.assertGreaterEqual(out["aplicados"], 1)
        with _prep.db.session(self.t) as s:
            st = s.get(Study, uuid.UUID(old))
            self.assertEqual((str(st.site_id), st.site_source), (self.A, "simulacao"))
            self.assertEqual(s.query(StudySiteAssignment).filter_by(study_id=st.id).count(), 1)
            self.assertIsNone(s.get(Study, uuid.UUID(self.s["n"])).site_id, "sem evidência: continua sem unidade")
        again = sb.apply(_prep.db, self.t, sim2, h2, approved_by="proprietario (teste)", actor="teste")
        self.assertEqual(again["aplicados"], 0)
        # depois da vinculação, a unidade A passa a ver o exame; a B continua sem ver
        self.assertEqual(self.u["tec_a"].get(f"/api/v1/ris/prep/{old}").status_code, 200)
        self.assertIn(self.u["tec_b"].get(f"/api/v1/ris/prep/{old}").status_code, DENIED)

    # ------------------------------------------------------------------ revisão independente A04 (N1–N6)
    def _order_b_without_study(self):
        from vyonix.clinical import service as clinical
        from vyonix.ris import service as ris
        with _prep.db.session(self.t) as s:
            enc = clinical.create_encounter(s, patient_id=self.pat, site_id=uuid.UUID(self.B), actor="t").id
            o = clinical.create_order(s, patient_id=self.pat, encounter_id=enc, requester="Dr Solicitante B Fict",
                                      actor="recepcao")
            sc = ris.schedule(s, o.id, scheduled_at=datetime.now(timezone.utc) + timedelta(hours=2),
                              room="SALA-B-FICT", modality="CT", actor="recepcao")
            return str(o.id), o.accession, str(sc.id)

    def test_p26_history_hides_orders_of_other_unit(self):          # A04 N1
        _oid, acc, _ = self._order_b_without_study()
        r = self.u["tec_a"].get(f"/api/v1/ris/patients/{self.pat}/history")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.text
        self.assertNotIn(acc, body, "número de acesso de pedido da B no histórico da A")
        self.assertNotIn("Dr Solicitante B Fict", body)
        self.assertNotIn("SALA-B-FICT", body)
        self.assertTrue(any(x["kind"] == "order" and x["restricted"] for x in r.json()["items"]))
        r = self.u["tec_b"].get(f"/api/v1/ris/patients/{self.pat}/history")
        self.assertIn(acc, r.text, "a própria unidade continua vendo o pedido")

    def test_p27_mixed_roles_cannot_cancel_other_unit(self):         # A04 N2
        _o, _a, sid = self._order_b_without_study()
        c = self._user("mix_ab", [("recepcionista", self.A), ("tecnico", self.B)])
        r = c.patch(f"/api/v1/ris/schedules/{sid}/status", json={"status": "cancelled", "reason": "indevido"})
        self.assertIn(r.status_code, DENIED, r.text)
        r = c.patch(f"/api/v1/ris/schedules/{sid}/status", json={"status": "arrived"})
        self.assertEqual(r.status_code, 200, "o técnico da B registra a chegada na B: " + r.text)

    def test_p28_global_role_physician_limited_to_links(self):      # A04 N3
        c = self._user("med_g", [("medico", None)])
        pid = self.admin.post("/api/v1/report/physicians", json={
            "user_id": self._uid_of("med_g"), "full_name": "Dr. Global Ficticio", "crm": "9002",
            "crm_uf": "PB"}).json()["id"]
        self.admin.post(f"/api/v1/report/physicians/{pid}/links", json={"site_id": self.A, "valid_from": "2026-01-01"})
        st = {x["id"] for x in c.get("/api/v1/studies").json()}
        self.assertIn(self.s["a"], st)
        self.assertNotIn(self.s["b"], st)
        self.assertNotIn(self.s["n"], st)
        u = _uids(c.get(DW + "/studies"))
        self.assertIn(self.uid["a"], u)
        self.assertFalse({self.uid["b"], self.uid["n"]} & u, u)
        self.assertIn(c.get(DW + f"/studies/{self.uid['b']}/metadata").status_code, DENIED)
        self.assertIn(c.get(f"/api/v1/pacs/viewer/launch?study_uid={self.uid['b']}").status_code, DENIED)
        self.assertIn(c.get(f"/api/v1/ris/prep/{self.s['b']}").status_code, DENIED)
        self.assertIn(c.post("/api/v1/report/reports", json={"study_id": self.s["b"]}).status_code, DENIED)
        wl = {x["study_id"] for x in c.get("/api/v1/report/worklist").json()["items"]}
        self.assertFalse({self.s["b"], self.s["n"]} & wl, wl)

    def test_p29_production_all_requires_every_unit(self):           # A04 N5
        c = self._user("sup_a", [("supervisor", self.A)])
        self.assertIn(c.get("/api/v1/report/production/physicians").status_code, DENIED)
        self.assertIn(c.get(f"/api/v1/report/production?physician_id={self.med_a_pid}").status_code, DENIED)

    def test_p30_unlinked_patients_only_by_directed_search(self):    # A04 N6
        from vyonix.clinical import service as clinical
        with _prep.db.session(self.t) as s:
            clinical.create_patient(s, name="Paciente Sem Vinculo Ficticio", actor="t")
        names = [p["name"] for p in self.u["recep_a"].get("/api/v1/patients").json()]
        self.assertNotIn("Paciente Sem Vinculo Ficticio", names)
        names = [p["name"] for p in self.u["recep_a"].get("/api/v1/patients?q=Vinculo").json()]
        self.assertIn("Paciente Sem Vinculo Ficticio", names, "a recepção ainda encontra para cadastrar o pedido")


if __name__ == "__main__":
    import unittest
    unittest.main()
