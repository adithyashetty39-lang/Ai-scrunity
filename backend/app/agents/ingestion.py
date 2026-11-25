from app.graph.state import ScrutinyState
from app.services.parser import parse_metadata, parse_questions, split_sets


def ingest_node(state: ScrutinyState) -> dict:
    text = state.get("paper_text", "")
    anomalies = list(state.get("formatting_anomalies") or [])
    meta = parse_metadata(text)

    questions = parse_questions(text)
    if not questions:
        anomalies.append(
            "Parser extracted zero questions. Check table layout or upload a text/DOCX copy."
        )

    # Set B may arrive as a separate document or with a 'SET B' heading inside the paper.
    text_b = state.get("paper_text_b") or ""
    questions_b = parse_questions(text_b, set_label="B") if text_b.strip() else []

    if questions and not questions_b and not any(q.set_label == "B" for q in questions):
        inner = split_sets(text)
        if len(inner) >= 2:
            questions = parse_questions(inner["A"], set_label="A")
            questions_b = parse_questions(inner["B"], set_label="B")

    if questions and not any(q.set_label for q in questions):
        for q in questions:
            q.set_label = "A"

    if not questions_b:
        anomalies_b: list[str] = []
    else:
        anomalies_b = []

    for q in questions_b:
        q.set_label = "B"

    return {
        "metadata": meta.model_dump(),
        "metadata_b": parse_metadata(text_b).model_dump() if text_b.strip() else {},
        "parsed_questions": [q.model_dump() for q in questions],
        "parsed_questions_b": [q.model_dump() for q in questions_b],
        "formatting_anomalies": anomalies,
    }
