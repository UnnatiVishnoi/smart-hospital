"""RAG pipeline: PyMuPDF extraction -> chunking -> pure-stdlib TF-IDF retrieval.

Embeddings are deliberately local (no external calls, no keys): retrieval ranks
indexed chunks with TF-IDF cosine similarity at query time. Scales to thousands
of chunks; each ManualChunk also stores token counts for future vector indexes.
"""
import math
import re
from collections import Counter

import pymupdf

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
TOP_K = 4
MIN_SCORE = 0.06
STOPWORDS = frozenset(
    "a an the and or of to in on for with is are was were be by as at from that this it its into over under "
    "what how when where which who why does do did can should would there their them they you your we our he she "
    "not no yes if then than so such very just about per each any all more most other some only also during".split()
)

_INJECTION_RE = re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.I)


def clean_text(raw):
    text = (raw or "").replace("\x00", " ")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # dehyphenate
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(path):
    """Return [(page_no, text)] using PyMuPDF. Raises ValueError on unreadable PDFs."""
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ValueError(f"Could not open PDF: {exc}") from exc
    pages = []
    try:
        if doc.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported. Upload an unprotected manual.")
        for i, page in enumerate(doc, start=1):
            pages.append((i, clean_text(page.get_text("text"))))
    finally:
        doc.close()
    if not any(t for _, t in pages):
        raise ValueError("No extractable text found — the PDF may be scanned images only.")
    return pages


def _guess_heading(text):
    for line in text.splitlines()[:4]:
        line = line.strip()
        if 4 <= len(line) <= 90 and (line.isupper() or re.match(r"^\d+(\.\d+)*\s+\S", line)):
            return line[:255]
    return ""


def chunk_pages(pages, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split page texts into overlapping chunks, preserving page numbers."""
    chunks = []
    for page_no, text in pages:
        if not text:
            continue
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                cut = text.rfind("\n\n", start + size - 300, end)
                end = cut if cut > start + 200 else end
            piece = text[start:end].strip()
            if len(piece) >= 80:
                chunks.append({
                    "page_no": page_no, "heading": _guess_heading(piece),
                    "content": piece, "token_count": max(1, len(piece) // 4),
                })
            start = end - overlap if end < len(text) else end
    return chunks


def index_manual(manual):
    """(Re)build chunks for a manual from its stored PDF. Returns chunk count."""
    from django.utils import timezone

    pages = extract_pages(manual.file.path)
    pieces = chunk_pages(pages)
    manual.chunks.all().delete()
    from .models import ManualChunk

    ManualChunk.objects.bulk_create([
        ManualChunk(manual=manual, chunk_index=i, page_no=p["page_no"], heading=p["heading"],
                    content=p["content"], token_count=p["token_count"],
                    embedding_model="tfidf-local")
        for i, p in enumerate(pieces)
    ])
    manual.page_count = len(pages)
    manual.is_indexed = True
    manual.indexed_at = timezone.now()
    manual.save(update_fields=["page_count", "is_indexed", "indexed_at"])
    return len(pieces)


def tokenize(text):
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in STOPWORDS and len(t) > 1]


def contains_injection(text):
    return bool(_INJECTION_RE.search(text or ""))


def retrieve(query, chunks, top_k=TOP_K):
    """Rank chunk objects (with .content) by TF-IDF cosine similarity.

    Returns [(chunk, score)] sorted desc, filtered by MIN_SCORE.
    """
    chunks = list(chunks)
    if not chunks or not (query or "").strip():
        return []
    q_terms = tokenize(query)
    if not q_terms:
        return []
    doc_terms = [tokenize(c.content) for c in chunks]
    df = Counter()
    for terms in doc_terms:
        df.update(set(terms))
    n = len(chunks)
    idf = {t: math.log((n + 1) / (f + 1)) + 1 for t, f in df.items()}
    q_vec = Counter(q_terms)
    q_norm = math.sqrt(sum((w * idf.get(t, 0)) ** 2 for t, w in q_vec.items()))
    if not q_norm:
        return []
    scored = []
    for chunk, terms in zip(chunks, doc_terms):
        if not terms:
            continue
        tf = Counter(terms)
        dot = sum(q_vec[t] * tf.get(t, 0) * idf.get(t, 0) ** 2 for t in q_vec if t in tf)
        if not dot:
            continue
        d_norm = math.sqrt(sum((c * idf[t]) ** 2 for t, c in tf.items() if t in idf))
        score = dot / (q_norm * d_norm) if d_norm else 0
        if score >= MIN_SCORE:
            scored.append((chunk, round(score, 4)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
