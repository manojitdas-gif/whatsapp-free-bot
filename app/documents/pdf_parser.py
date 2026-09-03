"""
pdf_parser.py — Safe text extraction from PDF files.
"""

import os


def extract_pdf_text(file_path: str) -> str:
    if not os.path.exists(file_path):
        return ""
    try:
        import pypdf
        reader = pypdf.PdfReader(file_path)
        pages_text = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages_text.append(t.strip())
        return "\n".join(pages_text)
    except Exception as e:
        print(f"[PDF PARSER ERROR] {e}")
        return ""
