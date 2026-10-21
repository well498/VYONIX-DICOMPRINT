"""Gestão comercial por assinatura do VYONIX (compartilhada pelo License Manager e pelo License Server).

* ``states``: estados ATIVA, PRÓXIMA DO VENCIMENTO, EM ATRASO, SUSPENSÃO PROGRAMADA, SUSPENSA,
  EXPIRADA e REATIVADA — cálculo também usado pelo VYONIX DICOM Print sobre a autorização assinada;
* ``engine``: assinaturas, pagamentos confirmados, carência, suspensão controlada, reativação,
  histórico, avisos e autorizações de uso;
* ``billing``: camada opcional de cobrança (Banco Inter).
"""
