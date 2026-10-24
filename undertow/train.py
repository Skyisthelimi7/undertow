"""Train the Models tab's models (models.py says how they are tested).

    python3 -m undertow.train --db state/undertow.db --dir state/models --history state/history/history.db

Copies the scanner's Buy & sell path into the --history database first, so the training history can outgrow the
TRADE["path_days"] days the scanner itself keeps (up to MODELS["keep_days"]), then trains and tests every model on it
under the live exit and writes each model and summary.json to --dir. The scan picks them up on its next run. The
history lives apart from the models so the scan, which restores the models every run, never downloads it."""
import argparse, json, os, sqlite3, sys, time
from . import config as C, models as MOD

H = 3600


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def sync_history(db_path, hist_path, now, keep_days):
    """Append the scan database's path rows newer than the history's last one; drop rows older than keep_days."""
    h = sqlite3.connect(hist_path)
    h.execute("CREATE TABLE IF NOT EXISTS tpath(ts REAL, mint TEXT, st TEXT, price REAL, liq REAL, c1h REAL, f TEXT)")
    h.execute("CREATE INDEX IF NOT EXISTS ix_hist ON tpath(mint, ts)")
    last = h.execute("SELECT MAX(ts) FROM tpath").fetchone()[0] or 0
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = src.execute("SELECT ts, mint, st, price, liq, c1h, f FROM tpath WHERE ts>? ORDER BY ts", (last,)).fetchall()
    policy = src.execute("SELECT v FROM meta WHERE k='trade_policy'").fetchone()
    src.close()
    h.executemany("INSERT INTO tpath VALUES(?,?,?,?,?,?,?)", rows)
    h.execute("DELETE FROM tpath WHERE ts<?", (now - keep_days * 86400,))
    h.commit()
    n = h.execute("SELECT COUNT(*), MIN(ts) FROM tpath").fetchone()
    out = {}
    for ts, mint, st, price, liq, c1h, f in h.execute("SELECT ts, mint, st, price, liq, c1h, f FROM tpath ORDER BY mint, ts"):
        out.setdefault(mint, []).append((ts, st, price, liq, c1h, json.loads(f) if f else None))
    h.close()
    log(f"history: {len(rows)} new path rows, {n[0]} kept since "
        f"{time.strftime('%d %b %H:%M', time.gmtime(n[1])) if n[1] else 'n/a'} on {len(out)} coins")
    return out, json.loads(policy[0]) if policy else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="state/undertow.db")
    ap.add_argument("--dir", default="state/models")
    ap.add_argument("--history", default="state/history/history.db")
    a = ap.parse_args()
    now = time.time()
    os.makedirs(a.dir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.history)), exist_ok=True)
    old = os.path.join(a.dir, "history.db")            # where the first runs kept it
    if not os.path.exists(a.history) and os.path.exists(old):
        os.replace(old, a.history)
    elif os.path.exists(old):
        os.remove(old)
    path, policy = sync_history(a.db, a.history, now, C.MODELS["keep_days"])
    exits = {e["id"]: e for e in C.EXIT_POOL}
    pol = exits.get((policy or {}).get("exit")) or exits[C.DEFAULT_EXIT]
    log(f"label: {pol['id']} ({MOD.TRD.exit_label(pol)})")
    s = MOD.train_all(path, pol, C.TRADE, C.MODELS, C.MODEL_SETS, a.dir, now, log, C.MODEL_SET_ALGOS)
    ok = [m for m in s.get("entry") or [] if not m.get("error")]
    log(f"done: {s.get('status')}; {len(ok)} entry models, {len(s.get('exit') or [])} exit models"
        + (f" in {s['seconds']}s" if s.get("seconds") is not None else ""))
    bad = [m["id"] + ": " + m["error"] for m in (s.get("entry") or []) + (s.get("exit") or []) if m.get("error")]
    for b in bad:
        log("failed:", b)


if __name__ == "__main__":
    main()
