"""Local TF-IDF vectorstore for syllabus modules, COs, and historical papers."""

from __future__ import annotations

import json
import re
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.config import HISTORICAL_DIR
from app.services.parser import parse_syllabus_units


class CorpusIndex:
    def __init__(self, documents: list[tuple[str, str]]):
        self.ids = [d[0] for d in documents]
        self.texts = [d[1] for d in documents]
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)
        if self.texts and any(t.strip() for t in self.texts):
            self.matrix = self.vectorizer.fit_transform(self.texts)
        else:
            self.matrix = None

    def query(self, text: str, k: int = 3) -> list[tuple[str, float, str]]:
        if self.matrix is None or not text.strip():
            return []
        q = self.vectorizer.transform([text])
        scores = cosine_similarity(q, self.matrix)[0]
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:k]
        return [(self.ids[i], float(score), self.texts[i]) for i, score in ranked]


def _chunk_unit_body(name: str, body: str, max_chars: int = 700) -> list[tuple[str, str]]:
    """Subdivide large syllabus bodies (>1000 chars) into overlapping passages
    to prevent vector-length dilution in TF-IDF cosine matching."""
    if len(body) <= 1200:
        return [(name, body)]
    docs: list[tuple[str, str]] = []
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    curr_lines: list[str] = []
    curr_len = 0
    for line in lines:
        curr_lines.append(line)
        curr_len += len(line)
        if curr_len >= max_chars:
            docs.append((name, "\n".join(curr_lines)))
            curr_lines = curr_lines[-2:]  # 2 lines overlap
            curr_len = sum(len(l) for l in curr_lines)
    if curr_lines:
        docs.append((name, "\n".join(curr_lines)))
    return docs


def build_syllabus_index(syllabus_text: str) -> CorpusIndex:
    units = parse_syllabus_units(syllabus_text)
    # Exclude non-unit 'General' introductory text if real modules exist
    module_units = {k: v for k, v in units.items() if k != "General"}
    if not module_units:
        module_units = units
    docs: list[tuple[str, str]] = []
    for name, body in module_units.items():
        if body.strip():
            docs.extend(_chunk_unit_body(name, body))
    return CorpusIndex(docs)


def extract_co_descriptions(syllabus_text: str) -> dict[str, str]:
    cos: dict[str, str] = {}
    for match in re.finditer(
        r"(CO\s*([1-6]))\s*[:\-–]\s*(.+?)(?=\n\s*CO\s*[1-6]|\n\s*Module|\Z)",
        syllabus_text,
        re.I | re.S,
    ):
        key = f"CO{match.group(2)}"
        cos[key] = re.sub(r"\s+", " ", match.group(3)).strip()[:500]

    # Enrich CO descriptions with corresponding Module content if available
    units = parse_syllabus_units(syllabus_text)
    for key in list(cos.keys()):
        num = re.search(r"\d+", key)
        if num:
            mod_key = f"Module {num.group(0)}"
            if mod_key in units:
                cos[key] = f"{cos[key]} {units[mod_key]}"

    return cos


def load_historical_questions() -> list[dict]:
    items: list[dict] = []
    if not HISTORICAL_DIR.exists():
        return items
    for path in sorted(HISTORICAL_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            year = data.get("year", path.stem)
            for q in data.get("questions", []):
                items.append({
                    "year": year,
                    "q_no": q.get("q_no", ""),
                    "text": q.get("question_text", ""),
                })
        except Exception:
            continue
    return items


def historical_matches(question_text: str, threshold: float = 0.72) -> list[tuple[str, float]]:
    corpus = load_historical_questions()
    if not corpus:
        return []
    index = CorpusIndex([(f"{c['year']}::{c['q_no']}", c["text"]) for c in corpus])
    hits = index.query(question_text, k=3)
    return [(hid, score) for hid, score, _ in hits if score >= threshold]
