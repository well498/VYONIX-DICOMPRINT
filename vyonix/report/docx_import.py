"""TELELAUDO T6 — importação assistida de modelos DOCX.

Converte o documento em seções do modelo (técnica, achados, conclusão) e devolve um **relatório de
incompatibilidades**. O resultado é sempre um **rascunho**: publicar continua exigindo a conferência do texto e da
pré-visualização (T3). Nada do documento é executado.

Segurança: só DOCX (macro ``.docm`` recusado), limite de tamanho, de entradas e de tamanho descompactado (bomba de
compressão), XML sem resolução de entidades (python-docx), sem objetos incorporados nem conteúdo ativo.

Limite conhecido desta etapa: o modelo é texto por seções — negrito, itálico, cores e tabelas viram texto simples
(listados no relatório); cabeçalho e rodapé do documento são extraídos como sugestão para a identidade visual (T2),
não aplicados automaticamente.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

from vyonix.errors import ValidationFailed

MAX_BYTES = 5 * 1024 * 1024
MAX_UNZIPPED = 50 * 1024 * 1024
MAX_ENTRIES = 2000
_HEAD = {"tecnica": "technique", "técnica": "technique", "achados": "findings", "relatorio": "findings",
         "relatório": "findings", "descricao": "findings", "descrição": "findings", "analise": "findings",
         "análise": "findings", "conclusao": "conclusion", "conclusão": "conclusion", "impressao": "conclusion",
         "impressão": "conclusion", "opiniao": "conclusion", "opinião": "conclusion"}
_MERGE = re.compile(r"MERGEFIELD\s+([^\s\\]+)", re.I)
_MAP_MERGE = {"paciente": "paciente.nome", "nome": "paciente.nome", "nomepaciente": "paciente.nome",
              "nascimento": "paciente.nascimento", "datanascimento": "paciente.nascimento", "sexo": "paciente.sexo",
              "idade": "paciente.idade", "modalidade": "exame.modalidade", "exame": "exame.descricao",
              "dataexame": "exame.data", "data": "exame.data", "accession": "exame.accession",
              "solicitante": "exame.solicitante", "medicosolicitante": "exame.solicitante",
              "clinica": "instituicao.nome", "instituicao": "instituicao.nome", "unidade": "unidade.nome"}


def _check_package(data: bytes) -> zipfile.ZipFile:
    if not data or len(data) > MAX_BYTES:
        raise ValidationFailed("Arquivo vazio ou acima de 5 MB.")
    if data[:2] != b"PK":
        raise ValidationFailed("O arquivo não é um DOCX (Word 2007 ou mais recente).")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = z.infolist()
    except zipfile.BadZipFile:
        raise ValidationFailed("DOCX danificado.") from None
    if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise ValidationFailed("DOCX recusado: conteúdo compactado grande demais.")
    names = {i.filename for i in infos}
    if "word/document.xml" not in names:
        raise ValidationFailed("O arquivo não é um documento do Word (DOCX).")
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise ValidationFailed("Documento com macros (DOCM) não é aceito. Salve como DOCX sem macros.")
    return z


def _heading(text: str) -> str | None:
    """Título de seção: o parágrafo inteiro (“Achados”) ou o trecho antes de dois-pontos (“Conclusão: …”)."""
    t = text.strip().lower()
    head = t.split(":", 1)[0] if ":" in t else t
    return _HEAD.get(re.sub(r"[\-–—.\s]+$", "", head).strip())


def convert(data: bytes) -> dict[str, Any]:
    """DOCX → {technique, findings, conclusion, header, footer, issues[], fields[], name}."""
    import docx
    from docx.oxml.ns import qn
    z = _check_package(data)
    names = [i.filename for i in z.infolist()]
    issues: list[str] = []
    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailed(f"Não foi possível ler o DOCX ({type(exc).__name__}).") from None
    sections = {"technique": [], "findings": [], "conclusion": []}
    current, fields, formatting = "findings", set(), False
    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag
        if tag == qn("w:p"):
            from docx.text.paragraph import Paragraph
            p = Paragraph(child, d)
            text = p.text
            for instr in child.iter(qn("w:instrText")):
                m = _MERGE.search(instr.text or "")
                if m:
                    key = re.sub(r"[^a-z]", "", m.group(1).lower())
                    if key in _MAP_MERGE:
                        fields.add(_MAP_MERGE[key])
                        text = text.replace(f"«{m.group(1)}»", "{{" + _MAP_MERGE[key] + "}}")
                        if "{{" + _MAP_MERGE[key] + "}}" not in text:
                            text += " {{" + _MAP_MERGE[key] + "}}"
                    else:
                        issues.append(f"Campo de mesclagem “{m.group(1)}” sem correspondência: virou texto.")
            if any(r.bold or r.italic or r.underline or (r.font.color and r.font.color.rgb) for r in p.runs):
                formatting = True
            if child.find(".//" + qn("w:drawing")) is not None or child.find(".//" + qn("w:pict")) is not None:
                issues.append("Imagem no corpo do documento foi ignorada (use a logomarca/papel timbrado da identidade).")
            if child.find(".//" + qn("w:object")) is not None:
                issues.append("Objeto incorporado foi ignorado (não é executado nem importado).")
            h = _heading(text) if len(text.split(":", 1)[0]) < 40 else None
            if h:
                current = h
                rest = text.split(":", 1)[1].strip() if ":" in text else ""
                if rest:
                    sections[current].append(rest)
                continue
            sections[current].append(text)
        elif tag == qn("w:tbl"):
            from docx.table import Table
            t = Table(child, d)
            for row in t.rows:
                sections[current].append(" | ".join(c.text.strip() for c in row.cells))
            issues.append("Tabela convertida em linhas de texto separadas por “|”.")
        elif tag == qn("w:sdt"):
            sections[current].append("".join(x.text or "" for x in child.iter(qn("w:t"))))
            issues.append("Controle de conteúdo (formulário) convertido em texto simples.")
    if formatting:
        issues.append("Negrito, itálico, sublinhado e cores não são preservados nesta versão (o modelo é texto por "
                      "seções).")
    if any(n.startswith("word/embeddings/") for n in names):
        issues.append("O documento contém arquivos incorporados: foram ignorados.")
    fonts = sorted({r.font.name for p in d.paragraphs for r in p.runs if r.font.name})
    if fonts:
        issues.append(f"Fontes do documento ({', '.join(fonts[:6])}) não são aplicadas: a fonte vem da identidade "
                      "visual.")
    header = " ".join(p.text.strip() for s in d.sections for p in s.header.paragraphs if p.text.strip())
    footer = " ".join(p.text.strip() for s in d.sections for p in s.footer.paragraphs if p.text.strip())
    if header or footer:
        issues.append("Cabeçalho e rodapé do documento foram extraídos como sugestão para a identidade visual "
                      "(não aplicados ao modelo).")

    def clean(lines: list[str]) -> str:
        text = "\n".join(lines)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    out = {k: clean(v) for k, v in sections.items()}
    if not any(out.values()):
        raise ValidationFailed("O documento não tem texto aproveitável.")
    title = (d.core_properties.title or "").strip()
    return {**out, "header": header[:300], "footer": footer[:300], "fields": sorted(fields),
            "issues": list(dict.fromkeys(issues)), "name": title[:120]}
