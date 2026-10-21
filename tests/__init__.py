
# Os testes funcionais (DICOM, impressão, fila) rodam sem a suspensão por licença; os testes de
# licenciamento ativam a política explicitamente (enforced=True / VYONIX_LICENSE_ENFORCE=1).
import os as _os

_os.environ.setdefault("VYONIX_LICENSE_ENFORCE", "0")
