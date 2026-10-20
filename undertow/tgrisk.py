"""Telegram bot-risk heuristic. Free signals only, uncalibrated: treat as a flag, not a verdict.
Calibrate against outcomes once a few weeks of snapshots exist."""
from statistics import median


def bot_risk(members, online, holders, history):
    """history: list of (ts_seconds, members) oldest first, current point last. Returns (score 0-100, reasons)."""
    if not members:
        return None, []
    score, why = 0, []
    if online is not None and members >= 500:
        r = online / members
        if r < 0.005:
            score += 35; why.append(f"only {r:.1%} online for {members:,} members")
        elif r < 0.01:
            score += 20; why.append(f"{r:.1%} online is low for {members:,} members")
        elif r < 0.02:
            score += 8; why.append(f"{r:.1%} online is on the low side")
    if holders and holders >= 200:
        ratio = members / holders
        if ratio > 4:
            score += 25; why.append(f"{members:,} members vs {holders:,} holders ({ratio:.1f}x)")
        elif ratio > 2:
            score += 10; why.append(f"members are {ratio:.1f}x holders")
    if len(history) >= 5:
        steps = [(history[i][1] - history[i - 1][1]) / max(history[i - 1][1], 1) for i in range(1, len(history))]
        last, base = steps[-1], median(steps[:-1])
        if members >= 500 and last > max(0.08, 3 * max(base, 0)):
            score += 20; why.append(f"jumped {last:.0%} since the last scan")
    return min(score, 100), why


def growth_per_hour(history):
    """members/hour over the window, as a fraction of members."""
    if len(history) < 2:
        return None
    (t0, m0), (t1, m1) = history[0], history[-1]
    hrs = (t1 - t0) / 3600
    return ((m1 - m0) / max(m0, 1)) / hrs if hrs >= 0.5 else None
