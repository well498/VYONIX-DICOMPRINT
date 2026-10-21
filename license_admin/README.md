# license_admin/ — emissão de licenças (uso exclusivo do fornecedor)

Esta pasta **nunca** é empacotada no build do cliente (`Vyonix.spec` a exclui e o pipeline verifica), e a
chave privada **nunca** é versionada (`.gitignore`: `license_admin/keys/`, `*.pem`, `*.key`).

```
pip install -r license_admin/requirements.txt
python -m license_admin keygen --key-id prod-1 --out D:\cofre\vyonix --passphrase
python -m license_admin issue --key D:\cofre\vyonix\vyonix-prod-1.private.pem --key-id prod-1 --ask-passphrase ^
    --request "VYXR1-..." --licensee "Clínica Exemplo Ltda" --edition profissional --days 365 --out licenca.vylic
python -m license_admin verify licenca.vylic
```

Edições: `essencial` (recepção + impressão, 2 equipamentos), `profissional` (+ Print SCP e regras,
10 equipamentos), `corporativo` (tudo, sem limite). `--feature` e `--max-devices` sobrepõem a edição.

A chave pública correspondente precisa estar em `app/licensing/keys.py` (o comando `keygen` mostra a linha).
A chave de homologação `hml-2026` foi entregue separadamente ao responsável pelo projeto; troque-a por uma
chave de produção antes da distribuição comercial.
