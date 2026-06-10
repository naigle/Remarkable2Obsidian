"""
Pipeline: rmapi export → PDF → per-page SVG + PNG → Surya OCR → Markdown
"""

import logging
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

log = logging.getLogger(__name__)

CONVERTED_DIR = os.environ.get("CONVERTED_DIR", "/data/converted")
RMAPI_CONFIG = os.environ.get("RMAPI_CONFIG", "/data/rmapi-config")
RCLONE_CONFIG = os.environ.get("RCLONE_CONFIG", "/data/rclone-config/rclone.conf")

# Surya models — loaded once and reused
_surya_models = None


def _get_surya_models():
    global _surya_models
    if _surya_models is None:
        log.info("Loading Surya OCR models (first run may take a while)...")
        from surya.model.detection.segformer import load_model as load_det, load_processor as load_det_proc
        from surya.model.recognition.model import load_model as load_rec
        from surya.model.recognition.processor import load_processor as load_rec_proc
        _surya_models = (load_det(), load_det_proc(), load_rec(), load_rec_proc())
        log.info("Surya models ready")
    return _surya_models


def _rmapi(*args):
    env = {**os.environ, "RMAPI_CONFIG": RMAPI_CONFIG}
    result = subprocess.run(
        ["rmapi"] + list(args),
        capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        raise RuntimeError(f"rmapi {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def list_documents():
    """
    Returns list of dicts: {id, title, last_modified}.

    rmapi find returns one path per line, e.g.:
        /My Notes/Shopping List
        /Quick Notes

    rmapi stat <path> returns JSON metadata including ID and ModifiedClient.
    """
    raw = _rmapi("find")
    paths = [line.strip() for line in raw.splitlines() if line.strip()]

    documents = []
    for path in paths:
        try:
            meta_raw = _rmapi("stat", path)
            meta = _parse_stat(meta_raw)
            documents.append({
                "id": meta.get("ID", path),
                "title": path.rsplit("/", 1)[-1],
                "path": path,
                "last_modified": meta.get("ModifiedClient", ""),
            })
        except Exception as e:
            log.warning("Could not stat %s: %s", path, e)

    return documents


def _parse_stat(raw):
    """
    Parse rmapi stat output into a dict.
    rmapi stat returns key: value lines.
    """
    meta = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


def export_and_convert(doc_path, title, ocr_enabled=True):
    """
    Export one document and run the full conversion pipeline.
    Returns (output_dir: str, page_count: int).
    """
    safe_title = _safe_filename(title)
    output_dir = Path(CONVERTED_DIR) / safe_title
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        # Export as PDF
        _rmapi("export", doc_path, tmp)
        pdfs = list(Path(tmp).glob("*.pdf"))
        if not pdfs:
            raise RuntimeError(f"No PDF produced for {doc_path!r}")
        pdf_path = pdfs[0]

        doc = fitz.open(str(pdf_path))
        page_count = len(doc)
        md_parts = _frontmatter(title)

        for i, page in enumerate(doc):
            page_num = i + 1
            svg_name = f"page-{page_num:02d}.svg"
            png_name = f"page-{page_num:02d}.png"

            # SVG for Obsidian embedding
            svg_data = page.get_svg_image(matrix=fitz.Matrix(1, 1))
            (output_dir / svg_name).write_text(svg_data, encoding="utf-8")

            md_parts.append(f"![[{svg_name}]]")
            md_parts.append("")

            if ocr_enabled:
                # PNG at 2× scale for better OCR accuracy
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                png_path = output_dir / png_name
                pix.save(str(png_path))
                try:
                    text = _ocr_page(png_path)
                    if text.strip():
                        md_parts.append(text.strip())
                        md_parts.append("")
                except Exception as e:
                    log.warning("OCR failed on page %d of %r: %s", page_num, title, e)
                finally:
                    png_path.unlink(missing_ok=True)

            md_parts.append("---")
            md_parts.append("")

        doc.close()

    md_path = output_dir / f"{safe_title}.md"
    md_path.write_text("\n".join(md_parts), encoding="utf-8")
    log.info("Converted %r → %s (%d pages)", title, output_dir, page_count)
    return str(output_dir), page_count


def _ocr_page(png_path):
    from surya.ocr import run_ocr
    det_model, det_proc, rec_model, rec_proc = _get_surya_models()
    img = Image.open(str(png_path))
    results = run_ocr([img], [["en"]], det_model, det_proc, rec_model, rec_proc)
    if not results:
        return ""
    return "\n".join(line.text for line in results[0].text_lines)


def rclone_push(gdrive_path):
    """Push converted dir to Google Drive via rclone."""
    result = subprocess.run(
        [
            "rclone", "sync",
            CONVERTED_DIR,
            f"gdrive:{gdrive_path}",
            "--config", RCLONE_CONFIG,
            "--log-level", "INFO",
        ],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"rclone sync failed:\n{result.stderr.strip()}")
    log.info("rclone push complete")


def _frontmatter(title):
    return [
        "---",
        f"title: {title}",
        f"date: {datetime.utcnow().strftime('%Y-%m-%d')}",
        "tags: [remarkable]",
        "---",
        "",
    ]


def _safe_filename(title):
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in title).strip()
