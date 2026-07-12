DIMENSIONS = {
    "originality": {"weight": 0.20, "label": "原创性"},
    "methodology": {"weight": 0.25, "label": "方法严谨性"},
    "evidence": {"weight": 0.25, "label": "证据充分性"},
    "coherence": {"weight": 0.15, "label": "论证连贯性"},
    "writing": {"weight": 0.15, "label": "写作质量"},
}

SCORE_TO_DECISION = {
    (80, 100): "Accept",
    (65, 79): "Minor Revision",
    (50, 64): "Major Revision",
    (0, 49): "Reject",
}

def score_to_decision(weighted_score: float) -> str:
    for (low, high), decision in SCORE_TO_DECISION.items():
        if low <= weighted_score <= high:
            return decision
    return "Reject"

def calculate_weighted_score(dimension_scores: dict) -> float:
    total = 0.0
    for dim, info in DIMENSIONS.items():
        total += dimension_scores.get(dim, 0) * info["weight"]
    return round(total, 1)
