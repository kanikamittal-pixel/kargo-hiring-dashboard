import io

import docx
import pdfplumber
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


class ParseError(Exception):
    pass


def parse_file(filename: str, file_bytes: bytes) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "pdf":
        return _parse_pdf(file_bytes)
    if suffix == "docx":
        return _parse_docx(file_bytes)
    raise ParseError(f"Unsupported file type: .{suffix}")


def _parse_pdf(file_bytes: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            # Some resume templates fake bold/styled headers by printing text twice at
            # near-identical coordinates; naive extraction interleaves the two overlapping
            # copies into garbage ("Rohan" -> "RROohHaAnN"). dedupe_chars collapses
            # same-text characters stacked within a small tolerance before extraction.
            pages = [page.dedupe_chars(tolerance=1).extract_text() or "" for page in pdf.pages]
        text = "\n".join(pages).strip()
    except Exception as e:
        raise ParseError(f"Failed to parse PDF: {e}") from e
    if not text:
        raise ParseError("PDF produced no extractable text (likely scanned/image-only).")
    return text


def _parse_docx(file_bytes: bytes) -> str:
    try:
        d = docx.Document(io.BytesIO(file_bytes))
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
