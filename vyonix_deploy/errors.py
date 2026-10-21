class DeployError(Exception):
    """Erro de implantação com mensagem para o administrador."""


class Blocked(DeployError):
    """Impeditivo de compatibilidade: a execução não pode prosseguir."""


class NotApproved(DeployError):
    pass
