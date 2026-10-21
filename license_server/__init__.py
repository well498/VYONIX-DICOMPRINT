"""VYONIX License Server — validação online e controle comercial centralizado.

Servidor separado do VYONIX DICOM Print das clínicas. Responsável por contratos (assinaturas),
planos, vencimentos, situação financeira confirmada, autorizações de uso assinadas com validade
limitada, suspensões programadas, reativações, histórico, auditoria e integrações de cobrança.

* API HTTPS (TLS 1.2+) — ``/v1/authorize`` para as instalações; ``/v1/admin/*`` autenticada por
  usuário e perfil (administrador comercial, operador financeiro, suporte técnico, consulta);
  ``/v1/billing/inter/<segredo>`` para avisos do Banco Inter (sempre confirmados por consulta).
* Nenhuma imagem, nome de paciente ou dado clínico é recebido ou armazenado.
* A chave de assinatura do servidor (``vyx-srv-…``) só assina autorizações de uso: não emite licenças.
"""

__version__ = "1.0.0"
APP_NAME = "VYONIX License Server"
DEFAULT_PORT = 8743
