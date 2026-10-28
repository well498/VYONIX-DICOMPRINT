"""VYONIX RIS — primeira entrega: agendamento de exames (passo de procedimento agendado) e Modality Worklist.

O pedido continua no cadastro clínico comum (``clinical.orders``). O RIS acrescenta o agendamento com o Study
Instance UID atribuído antes do exame: a modalidade recebe esse UID pela worklist e o estudo chega ao PACS já
ligado ao pedido. Não liberado para uso clínico.
"""
