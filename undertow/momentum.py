"""Momentum = average percentile rank of five live signals, so no arbitrary scales."""


def _rank(values):
    """percentile 0-100 of each value among the non-None values; None stays None."""
    pairs = sorted((v, i) for i, v in enumerate(values) if v is not None)
    n = len(pairs)
    out = [None] * len(values)
    for r, (_, i) in enumerate(pairs):
        out[i] = 50.0 if n == 1 else 100.0 * r / (n - 1)
    return out


def score_all(rows):
    """rows: list of dicts with keys chg1h, chg6h, vol_accel, flow_pct, breadth, holder_growth, tg_growth.
    Adds row['momentum'] = {'score', 'label', 'parts'}. Needs >= 6 rows to rank; otherwise score is None."""
    keys = [("chg1h", "Price 1h"), ("chg6h", "Price 6h"), ("vol_accel", "Volume pace"), ("flow_pct", "Net buying 1h"),
            ("breadth", "Buyer breadth"), ("holder_growth", "Holder growth"), ("tg_growth", "Telegram growth")]
    ranks = {k: _rank([r.get(k) for r in rows]) for k, _ in keys}
    for i, r in enumerate(rows):
        parts = {lab: round(ranks[k][i]) for k, lab in keys if ranks[k][i] is not None}
        if len(rows) < 6 or len(parts) < 3:
            r["momentum"] = {"score": None, "label": "n/a", "parts": parts}
            continue
        sc = round(sum(parts.values()) / len(parts))
        r["momentum"] = {"score": sc, "label": "Heating" if sc >= 65 else ("Cooling" if sc < 40 else "Steady"), "parts": parts}
