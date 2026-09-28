from pathlib import Path

import docx
import pdfplumber
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


class ParseError(Exception):
    pass


def parse_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix == ".docx":
        return _parse_docx(path)
    raise ParseError(f"Unsupported file type: {suffix}")


def _parse_pdf(path: Path) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(pages).strip()
    except Exception as e:
        raise ParseError(f"Failed to parse PDF: {e}") from e
    if not text:
        raise ParseError("PDF produced no extractable text (likely scanned/image-only).")
    return text


def _parse_docx(path: Path) -> str:
    try:
        d = docx.Document(path)
        lines = list(_iter_block_text(d.element.body, d))
        text = "\n".join(l for l in lines if l.strip())
    except Exception as e:
        raise ParseError(f"Failed to parse DOCX: {e}") from e
    if not text.strip():
        raise ParseError("DOCX produced no extractable text.")
    return text


def _iter_block_text(parent_elm, document):
    """Walk paragraphs and tables in true document order (tables may be
    nested inside body-level table cells, e.g. a 2-column header layout),
    instead of docx.Document's .paragraphs/.tables which each only return
    top-level items and lose the original ordering when mixed."""
    qn_p = qn("w:p")
    qn_tbl = qn("w:tbl")
    for child in parent_elm.iterchildren():
        if child.tag == qn_p:
            yield Paragraph(child, document).text
        elif child.tag == qn_tbl:
            table = Table(child, document)
            for row in table.rows:
                for cell in row.cells:
                    yield cell.text
