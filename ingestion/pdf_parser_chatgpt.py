import pymupdf  # PyMuPDF
import uuid
from datetime import datetime
from PIL import Image
import pytesseract


def extract_text_blocks(page):
    """
    Extract structured text using PyMuPDF blocks.
    Returns joined text string.
    """
    blocks = page.get_text("blocks")
    text_blocks = [b[4] for b in blocks if b[4].strip() != ""]
    return "\n".join(text_blocks)


def run_ocr_on_page(page):
    """
    Render page to image and run OCR using Tesseract.
    """
    pix = page.get_pixmap(dpi=300)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    ocr_text = pytesseract.image_to_string(img)
    return ocr_text.strip()


def detect_charts(page):
    """
    Basic heuristic: if page has images, assume potential charts.
    """
    images = page.get_images(full=True)
    return len(images) > 0


def parse_pdf(path: str):
    doc = pymupdf.open(path)
    slides = []

    for i, page in enumerate(doc):
        clean_text = extract_text_blocks(page)

        # OCR fallback only if no extractable text
        if clean_text.strip() == "":
            clean_text = run_ocr_on_page(page)

        slides.append({
            "slide_number": i + 1,
            "raw_text": clean_text,
            "tables": [],  # Table extraction can be added later via pdfplumber
            "has_charts": detect_charts(page),
            "detected_section": None
        })

    deck_json = {
        "deck_id": str(uuid.uuid4()),
        "source_format": "pdf",
        "ingested_at": datetime.utcnow().isoformat(),
        "slide_count": len(slides),
        "slides": slides
    }

    doc.close()
    return deck_json


if __name__ == "__main__":
    import sys
    result = parse_pdf(sys.argv[1])
    print(result)