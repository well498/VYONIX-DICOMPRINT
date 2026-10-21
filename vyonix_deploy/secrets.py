"""Segredos do DEPLOY (senha do superusuário do PostgreSQL do VYONIX), protegidos com DPAPI de máquina
na pasta do DEPLOY (acesso só de administradores). Mesmo mecanismo do Core."""

from vyonix.secrets import SecretStore as DeploySecrets  # noqa: F401
