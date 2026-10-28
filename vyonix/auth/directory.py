"""Diretório global de logins (Prompt Mestre §7): no servidor com várias instituições, a tela de acesso pede só
usuário e senha e o servidor descobre a instituição pelo login, que por isso é **único na plataforma**.

As contas continuam independentes por instituição (senha, papéis, sessões, situação): o diretório só guarda
login → organização/conta. Um login em uso em outra instituição é recusado com uma mensagem que não revela qual
instituição o usa. Contas desativadas mantêm o login reservado (a auditoria continua apontando para elas).

Todas as funções recebem uma sessão do **papel de serviço** (a tabela não é visível ao papel da aplicação).
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from vyonix.auth.models import LoginDirectory
from vyonix.errors import Conflict


def normalize(login: str) -> str:
    return (login or "").strip().lower()


def resolve(s: Session, login: str) -> uuid.UUID | None:
    """Organização dona do login (``None`` se não estiver no diretório)."""
    return s.execute(select(LoginDirectory.org_id).where(LoginDirectory.login == normalize(login))).scalar()


def available(s: Session, login: str) -> bool:
    return resolve(s, login) is None


def claim(s: Session, login: str, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    key = normalize(login)
    cur = s.get(LoginDirectory, key)
    if cur is not None:
        if cur.user_id == user_id:
            return
        raise Conflict("Este login já está em uso na plataforma VYONIX. Escolha outro identificador.",
                       code="login_taken")
    s.add(LoginDirectory(login=key, org_id=org_id, user_id=user_id))
    s.flush()


def release(s: Session, user_id: uuid.UUID) -> None:
    s.execute(delete(LoginDirectory).where(LoginDirectory.user_id == user_id))


def conflicts(s: Session) -> list[dict]:
    """Logins existentes que estão fora do diretório por se repetirem em mais de uma organização."""
    from sqlalchemy import func

    from vyonix.auth.models import User
    rows = s.execute(select(func.lower(User.username), func.count()).group_by(func.lower(User.username))
                     .having(func.count() > 1)).all()
    return [{"login": login, "organizations": n} for login, n in rows]


class Reservation:
    """Reserva o login antes de criar a conta (outra transação) e a desfaz se a criação falhar:
    ``with Reservation(db, login, org_id, enabled) as user_id: create_user(..., user_id=user_id)``."""

    def __init__(self, db, login: str, org_id: uuid.UUID, enabled: bool = True) -> None:
        self.db, self.login, self.org_id, self.enabled = db, login, org_id, enabled
        self.user_id = uuid.uuid4()

    def __enter__(self) -> uuid.UUID:
        if self.enabled:
            with self.db.service_session() as s:
                claim(s, self.login, self.org_id, self.user_id)
        return self.user_id

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None and self.enabled:
            with self.db.service_session() as s:
                release(s, self.user_id)
