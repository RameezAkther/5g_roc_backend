import pdfplumber
from pypdf import PdfReader


def extract_text_from_pdf(path: str) -> str:
    text = ""

    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
    except:
        reader = PdfReader(path)
        for page in reader.pages:
            text += page.extract_text() or ""

    return text


def extract_text_from_file(path: str) -> str:
    if path.endswith(".pdf"):
        return extract_text_from_pdf(path)
    else:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
