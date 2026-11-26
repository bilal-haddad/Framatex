"""Visionneuse documentaire : aperçus rendus côté serveur, à chaque requête sous contrôle des droits.

La consultation (document.read) donne accès aux aperçus ; le fichier original reste réservé au
téléchargement (document.download) par la route existante. Aucun contenu actif n'est exécuté :
PDF rendus en images (PyMuPDF), classeurs lus par openpyxl sans calcul ni macro, Word converti en
blocs de texte échappés, images ré-encodées sans métadonnées, emails lus en texte.
Tailles et nombres de pages, lignes et colonnes bornés pour limiter la mémoire.
"""
from __future__ import annotations

import csv
import email
import io
from email import policy
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .core import get_current_user, get_db
from .models import DocumentVersion, User

router = APIRouter()
MAX_BYTES = 40 * 1024 * 1024
TEXT_LIMIT = 300_000
SHEET_COLS = 60
HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
KINDS = {".pdf": "pdf", ".xlsx": "excel", ".xlsm": "excel", ".docx": "word", ".png": "image", ".jpg": "image",
         ".jpeg": "image", ".txt": "text", ".csv": "csv", ".eml": "email"}


def _version(db: Session, user: User, version_id: str):
    from .access import must_access
    from .main import STORAGE, must
    version = db.get(DocumentVersion, version_id)
    if not version or version.deleted_at is not None or version.document.deleted_at is not None:
        raise HTTPException(404, "Version introuvable")
    document = version.document
    must_access(db, user, document.folder.launch_id)
    must(user, "document.read", document.folder.slug)
    path = STORAGE / version.disk_name
    if not path.is_file():
        raise HTTPException(503, "Fichier indisponible dans le stockage")
    if path.stat().st_size > MAX_BYTES:
        raise HTTPException(413, "Fichier trop volumineux pour un aperçu : téléchargez-le si vous y êtes autorisé")
    db.commit()                         # droits vérifiés : connexion rendue au pool pendant le rendu
    return version, document, path


def _kind(version) -> str:
    return KINDS.get(Path(version.original_name).suffix.lower(), "other")


@router.get("/api/document-versions/{version_id}/preview")
def preview(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .main import permitted
    version, document, path = _version(db, user, version_id)
    kind = _kind(version)
    out = {"kind": kind, "name": version.original_name, "version": version.number, "size": version.size,
           "document_id": document.id, "version_id": version.id,
           "can_download": bool(permitted(user, "document.download", document.folder.slug))}
    if kind == "pdf":
        import fitz
        with fitz.open(path) as pdf:
            out["pages"] = pdf.page_count
            out["sizes"] = [[round(p.rect.width), round(p.rect.height)] for p in pdf][:2000]
    elif kind == "excel":
        from openpyxl import load_workbook
        with path.open("rb") as handle:        # fichier stocké sans extension : lecture par flux
            workbook = load_workbook(handle, read_only=True, data_only=True, keep_vba=False)
            out["sheets"] = [{"name": ws.title, "rows": ws.max_row or 0, "cols": min(ws.max_column or 0, SHEET_COLS)} for ws in workbook.worksheets]
            workbook.close()
    elif kind == "word":
        out["blocks"], out["truncated"] = _word_blocks(path)
        out["notice"] = "Aperçu du texte, des titres et des tableaux : mise en page, images et en-têtes ne sont pas reproduits fidèlement."
    elif kind == "text":
        raw = path.read_bytes()[:TEXT_LIMIT]
        out["text"], out["truncated"] = _decode(raw), path.stat().st_size > TEXT_LIMIT
    elif kind == "csv":
        raw = _decode(path.read_bytes()[:TEXT_LIMIT])
        try:
            dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(raw), dialect))[:2000]
        out["rows"], out["truncated"] = [row[:SHEET_COLS] for row in rows], path.stat().st_size > TEXT_LIMIT or len(rows) == 2000
    elif kind == "email":
        out["email"] = _email(path)
    return out


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


@router.get("/api/document-versions/{version_id}/preview/page/{number}")
def pdf_page(version_id: str, number: int, zoom: float = Query(1.4, ge=.5, le=3),
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    import fitz
    version, _, path = _version(db, user, version_id)
    if _kind(version) != "pdf":
        raise HTTPException(415, "Aperçu de page réservé aux PDF")
    with fitz.open(path) as pdf:
        if not 1 <= number <= pdf.page_count:
            raise HTTPException(404, "Page introuvable")
        page = pdf[number - 1]
        scale = min(zoom, 2400 / max(page.rect.width, 1))             # largeur rendue plafonnée
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, annots=True)
        return Response(pixmap.tobytes("png"), media_type="image/png", headers=HEADERS)


@router.get("/api/document-versions/{version_id}/preview/search")
def pdf_search(version_id: str, q: str = Query(min_length=2, max_length=120),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    import fitz
    version, _, path = _version(db, user, version_id)
    if _kind(version) != "pdf":
        raise HTTPException(415, "Recherche réservée aux PDF")
    hits = []
    with fitz.open(path) as pdf:
        for index, page in enumerate(pdf):
            rects = page.search_for(q)[:50]
            if rects:
                w, h = page.rect.width, page.rect.height
                hits.append({"page": index + 1, "boxes": [[r.x0 / w, r.y0 / h, r.width / w, r.height / h] for r in rects]})
            if len(hits) >= 200:
                break
    return {"query": q, "hits": hits, "has_text": any(True for _ in hits) or None}


@router.get("/api/document-versions/{version_id}/preview/sheet")
def excel_sheet(version_id: str, sheet: str = Query(max_length=120), offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=500),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    version, _, path = _version(db, user, version_id)
    if _kind(version) != "excel":
        raise HTTPException(415, "Feuilles réservées aux classeurs Excel")
    # Valeurs mises en cache par Excel et formules lues séparément : rien n'est recalculé ni exécuté.
    values = load_workbook(io.BytesIO(path.read_bytes()), read_only=True, data_only=True, keep_vba=False)
    formulas = load_workbook(io.BytesIO(path.read_bytes()), read_only=True, data_only=False, keep_vba=False)
    if sheet not in values.sheetnames:
        raise HTTPException(404, "Feuille introuvable")
    vs, fs = values[sheet], formulas[sheet]
    cols = min(vs.max_column or 1, SHEET_COLS)
    rows = []
    for vrow, frow in zip(vs.iter_rows(min_row=offset + 1, max_row=offset + limit, max_col=cols, values_only=True),
                          fs.iter_rows(min_row=offset + 1, max_row=offset + limit, max_col=cols, values_only=True)):
        rows.append([{"v": _cell(v), **({"f": f} if isinstance(f, str) and f.startswith("=") else {})} for v, f in zip(vrow, frow)])
    total = vs.max_row or 0
    values.close(); formulas.close()
    return {"sheet": sheet, "offset": offset, "rows": rows, "total_rows": total, "columns": [get_column_letter(i) for i in range(1, cols + 1)],
            "has_more": offset + limit < total, "truncated_cols": (vs.max_column or 0) > SHEET_COLS}


def _cell(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value if isinstance(value, (int, float, bool)) else str(value)


@router.get("/api/document-versions/{version_id}/preview/image")
def image(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from PIL import Image
    version, _, path = _version(db, user, version_id)
    if _kind(version) != "image":
        raise HTTPException(415, "Aperçu réservé aux images")
    with Image.open(path) as source:
        source.thumbnail((2400, 2400))
        picture = source.convert("RGB")
        buffer = io.BytesIO()
        picture.save(buffer, "JPEG", quality=86)                      # ré-encodage : aucune métadonnée conservée
    return Response(buffer.getvalue(), media_type="image/jpeg", headers=HEADERS)


def _word_blocks(path: Path):
    from docx import Document as Docx
    doc = Docx(str(path))
    blocks, size = [], 0
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit('}', 1)[-1]
        if tag == "p":
            from docx.text.paragraph import Paragraph
            paragraph = Paragraph(child, doc)
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
            level = next((n for n in range(1, 4) if f"heading {n}" in style or f"titre {n}" in style), 0)
            blocks.append({"type": f"h{level}" if level else "p", "text": text})
            size += len(text)
        elif tag == "tbl":
            from docx.table import Table
            table = Table(child, doc)
            rows = [[cell.text.strip() for cell in row.cells][:SHEET_COLS] for row in table.rows[:300]]
            blocks.append({"type": "table", "rows": rows})
            size += sum(len(c) for r in rows for c in r)
        if size > TEXT_LIMIT or len(blocks) > 3000:
            return blocks, True
    return blocks, False


def _email(path: Path) -> dict:
    message = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    body = message.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        text = body.get_content()
        if body.get_content_type() == "text/html":
            import html
            import re
            text = html.unescape(re.sub(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", " ", text, flags=re.S | re.I))
            text = re.sub(r"[ \t]+\n", "\n", re.sub(r"[ \t]{2,}", " ", text))
    attachments = [{"name": part.get_filename() or "pièce jointe", "type": part.get_content_type(),
                    "size": len(part.get_payload(decode=True) or b"")} for part in message.iter_attachments()]
    return {"subject": str(message.get("subject", "")), "from": str(message.get("from", "")), "to": str(message.get("to", "")),
            "date": str(message.get("date", "")), "body": text[:TEXT_LIMIT].strip(), "attachments": attachments}
