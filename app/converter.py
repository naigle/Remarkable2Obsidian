"""
Pipeline: rmapi get → .rmdoc → rmscene render → PIL images → Surya OCR → Markdown
"""

import io
import logging
import os
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw
from rmscene import read_blocks, SceneLineItemBlock

log = logging.getLogger(__name__)

CONVERTED_DIR = os.environ.get("CONVERTED_DIR", "/data/converted")
RMAPI_CONFIG  = os.environ.get("RMAPI_CONFIG",  "/data/rmapi-config/rmapi.conf")
RCLONE_CONFIG = os.environ.get("RCLONE_CONFIG", "/data/rclone-config/rclone.conf")

# reMarkable canvas dimensions
RM_WIDTH  = 1404
RM_HEIGHT = 1872

# Surya models — loaded once
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
        capture_output=True, text=True, env=env, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"rmapi {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def list_documents():
    """
    Returns list of dicts: {id, title, path, last_modified}.
    Uses ddvk rmapi which outputs lines like:
        [f]  /Folder/NotebookName
        [d]  /Folder
    """
    raw = _rmapi("find", "/")
    documents = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("[f]"):
            continue
        path = line[3:].strip()
        title = path.rsplit("/", 1)[-1]
        # Use path as stable ID; get modification time via stat
        last_modified = ""
        try:
            stat_raw = _rmapi("stat", path)
            for sline in stat_raw.splitlines():
                if "ModifiedClient" in sline or "Modified" in sline:
                    last_modified = sline.split(":", 1)[-1].strip()
                    break
        except Exception:
            pass
        documents.append({
            "id": path,
            "title": title,
            "path": path,
            "last_modified": last_modified,
        })
    return documents


def _render_rm_page(rm_data: bytes) -> Image.Image:
    """Render a single .rm stroke page to a PIL Image."""
    img = Image.new("RGB", (RM_WIDTH, RM_HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    x_offset = RM_WIDTH / 2
    try:
        blocks = list(read_blocks(io.BytesIO(rm_data)))
        for block in blocks:
            if not isinstance(block, SceneLineItemBlock):
                continue
            if block.item is None or block.item.value is None:
                continue
            line = block.item.value
            pts = getattr(line, "points", [])
            if len(pts) < 2:
                continue
            coords = [(int(p.x + x_offset), int(p.y)) for p in pts]
            stroke_width = max(1, int(getattr(pts[0], "width", 16) / 8))
            draw.line(coords, fill="black", width=stroke_width)
    except Exception as e:
        log.warning("Stroke render error: %s", e)
    return img


def _rmdoc_to_images(rmdoc_path: str) -> list:
    """Extract and render all pages from a .rmdoc zip."""
    images = []
    with zipfile.ZipFile(rmdoc_path) as z:
        rm_files = sorted(n for n in z.namelist() if n.endswith(".rm"))
        for rm_name in rm_files:
            rm_data = z.read(rm_name)
            images.append(_render_rm_page(rm_data))
    return images


def _ocr_page(img: Image.Image) -> str:
    """Run Surya OCR on a PIL image, return text."""
    from surya.ocr import run_ocr
    det_model, det_proc, rec_model, rec_proc = _get_surya_models()
    results = run_ocr([img], [["en"]], det_model, det_proc, rec_model, rec_proc)
    if not results:
        return ""
    return "\n".join(line.text for line in results[0].text_lines)


def export_and_convert(doc_path, title, ocr_enabled=True):
    """
    Full pipeline for one document.
    Returns (output_dir: str, page_count: int).
    """
    safe_title = _safe_filename(title)
    output_dir = Path(CONVERTED_DIR) / safe_title
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        # ddvk rmapi: `rmapi get <path>` downloads as <name>.rmdoc
        _rmapi("get", doc_path, tmp)
        rmdocs = list(Path(tmp).glob("*.rmdoc"))
        if not rmdocs:
            raise RuntimeError(f"No .rmdoc produced for {doc_path!r}")
        rmdoc_path = str(rmdocs[0])

        images = _rmdoc_to_images(rmdoc_path)
        page_count = len(images)

        md_parts = _frontmatter(title)

        for i, img in enumerate(images):
            page_num = i + 1
            svg_name = f"page-{page_num:02d}.png"  # PNG embeds better in Obsidian than SVG from rmscene
            img_path = output_dir / svg_name

            # Save page image for Obsidian embedding
            img.save(str(img_path), format="PNG")
            md_parts.append(f"![[{svg_name}]]")
            md_parts.append("")

            if ocr_enabled:
                try:
                    text = _ocr_page(img)
                    if text.strip():
                        md_parts.append(text.strip())
                        md_parts.append("")
                except Exception as e:
                    log.warning("OCR failed on page %d of %r: %s", page_num, title, e)

            md_parts.append("---")
            md_parts.append("")

    md_path = output_dir / f"{safe_title}.md"
    md_path.write_text("\n".join(md_parts), encoding="utf-8")
    log.info("Converted %r → %s (%d pages)", title, output_dir, page_count)
    return str(output_dir), page_count


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
