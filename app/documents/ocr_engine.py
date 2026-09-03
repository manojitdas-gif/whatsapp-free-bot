"""
ocr_engine.py — Native OCR and image text extraction.
"""

import os
import subprocess
import sys
from app.config import settings

OCR_SCRIPT = os.path.join(settings.BASE_DIR, "ocr_engine.ps1")

def run_image_ocr(image_path: str) -> str:
    """
    Extracts text from images using Windows native Windows.Media.Ocr via PowerShell,
    with graceful fallback.
    """
    if not os.path.exists(image_path):
        return ""

    if sys.platform == "win32" and os.path.exists(OCR_SCRIPT):
        try:
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", OCR_SCRIPT,
                "-ImagePath", os.path.abspath(image_path)
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace"
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            print(f"[OCR ERROR] {e}")

    # Fallback: check pytesseract if installed
    try:
        import pytesseract
        from PIL import Image
        text = pytesseract.image_to_string(Image.open(image_path))
        return text.strip()
    except Exception:
        pass

    return ""
