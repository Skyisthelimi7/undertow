"""Hosted mode: the hourly cycle behind the page published on claude.ai.

The page, its data files, the scanner's database and this source tree all live in the published Artifact. Each hour a
scheduled Claude session reads the source (src/bundle.json, one JSON file) and the database (state/db.0.json to
db.2.json: gzip+base64 shards, so it travels as ordinary JSON), runs one cycle, and publishes the results back to the
same Artifact. The database only moves forward when a run publishes, so a failed run changes nothing and the next one
starts from the last good state.

    python3 -m undertow.cloud cycle --state <folder holding state/db.*.json> --out <folder>
    python3 -m undertow.cloud pack --db undertow.db --out <folder>       # write state/db.*.json from a database
    python3 -m undertow.cloud restore --state <folder> --db undertow.db  # the reverse
    python3 -m undertow.cloud bundle --out src/bundle.json               # this source tree as one JSON file
    python3 -m undertow.cloud review --out <folder>                      # re-run the review of a finished cycle

`cycle` ends with a review of what it is about to publish (every file and what is in it, a check that the page is this
code's own template, a check that the database shards decode, and any text from the data sources that looks like
markup, a link or an instruction), then one line, DONE {...}, and writes publish.json: the page and the files to
publish, as paths. It refuses to start from an empty database unless --allow-fresh is given, so a failed download can
never replace the history with an empty one.
"""
import argparse, base64, csv, gzip, hashlib, importlib.util, json, os, pathlib, re, sqlite3, sys, tempfile, time
from . import config as C

SHARDS = 3                        # always this many state files, so the scheduled run can ask for fixed paths
SHARD_CHARS = 12_000_000          # under the 16 MB limit for one published text file
CADENCE_MIN = 60                  # the scheduled task runs hourly
ROOT = pathlib.Path(__file__).resolve().parents[1]
BUNDLE = ("undertow/*.py", "web/*.css", "web/*.html", "web/*.js", "build_page.py")
# the page is index.html (a few kilobytes) plus its style.css and app.js, so a session that reads the live page before
# publishing over it reads very little
OUTPUTS = (("app.js", "style.css", "data.json", "version.json", "tracker.csv", "observations.csv", "snapshots.csv")
           + tuple(f"snap/{i}.json" for i in range(C.SNAP_BUCKETS)))


def pack(db_path, out_dir):
    """Compact the database, then write it as gzip+base64 split over SHARDS JSON files. Returns the gzip size."""
    con = sqlite3.connect(db_path)
    con.execute("VACUUM")
    con.close()
    raw = gzip.compress(pathlib.Path(db_path).read_bytes(), 9)
    text = base64.b64encode(raw).decode()
    parts = [text[i:i + SHARD_CHARS] for i in range(0, len(text), SHARD_CHARS)] or [""]
    if len(parts) > SHARDS:
        raise SystemExit(f"database too large to carry ({len(raw):,} bytes gzipped)")
    os.makedirs(os.path.join(out_dir, "state"), exist_ok=True)
    for i in range(SHARDS):
        with open(os.path.join(out_dir, "state", f"db.{i}.json"), "w") as f:
            json.dump({"part": i, "of": len(parts), "data": parts[i] if i < len(parts) else ""}, f)
    return len(raw)


def restore(state_dir, db_path):
    """Rebuild the database from its shards. False (and no file) when there are none."""
    parts = []
    for i in range(SHARDS):
        p = os.path.join(state_dir, "state", f"db.{i}.json")
        if os.path.exists(p):
            with open(p) as f:
                parts.append(json.load(f))
    parts.sort(key=lambda p: p["part"])
    text = "".join(p["data"] for p in parts)
    if not text:
        return False
    if len([p for p in parts if p["data"]]) != parts[0]["of"]:
        raise SystemExit("state shards incomplete: refusing to start from a partial database")
    pathlib.Path(db_path).write_bytes(gzip.decompress(base64.b64decode(text)))
    return True


def bundle(out_file):
    files = {}
    for pat in BUNDLE:
        for p in sorted(ROOT.glob(pat)):
            files[str(p.relative_to(ROOT))] = p.read_text()
    os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
    with open(out_file, "w") as f:
        json.dump({"made": time.time(), "files": files}, f)
    return len(files)


def _build():
    spec = importlib.util.spec_from_file_location("build_page", ROOT / "build_page.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build


# text from the data sources (token names and symbols, X and Telegram handles) is set by token creators: show the
# publishing session anything in it that looks like markup, a link or an instruction
SUSPECT = re.compile(r"[<>\x00-\x1f]|://|www\.|\b(ignore|instruction|prompt|assistant|claude|system)\b", re.I)


def _sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()[:12]


def _rows(path):
    with open(path, newline="") as f:
        return max(sum(1 for _ in csv.reader(f)) - 1, 0)


def review(files, page):
    """Describe every file this cycle wrote and is about to publish. Returns (lines, problems)."""
    lines, problems, note = [], [], {}
    with open(files["data.json"]) as f:
        d = json.load(f)
    toks, trk = d.get("tokens") or [], d.get("tracker") or []
    note["data.json"] = f"{len(toks)} tokens, {len(trk)} tracked, {len(d.get('transitions') or [])} recent moves"
    for name in ("tracker.csv", "observations.csv", "snapshots.csv"):
        note[name] = f"{_rows(files[name])} rows"
    n_snap = 0
    for i in range(C.SNAP_BUCKETS):
        with open(files[f"snap/{i}.json"]) as f:
            n_snap += sum(len(v["r"]) for v in json.load(f).values())
    note["snap/0.json"] = f"hourly tracker snapshots for the page, {n_snap} rows over {C.SNAP_BUCKETS} files"
    with open(files["version.json"]) as f:
        note["version.json"] = f.read().strip()
    # the page must be this code's own template and nothing else (it reads its data from data.json)
    with tempfile.TemporaryDirectory() as tmp:
        _build()(os.path.join(tmp, "index.html"), fragment=True, split=True)
        diff = [n for n, p in (("index.html", page), ("app.js", files["app.js"]), ("style.css", files["style.css"]))
                if pathlib.Path(tmp, n).read_bytes() != pathlib.Path(p).read_bytes()]
    if diff:
        problems.append(", ".join(diff) + " differ from the page template")
    note["index.html"] = "the page: web/ template, rebuilt and compared: " + ("DIFFERENT: " + ", ".join(diff) if diff else "identical")
    note["app.js"] = note["style.css"] = "the page's script and styles, compared above"
    try:                                     # the database shards must decode to a readable SQLite file
        parts = []
        for i in range(SHARDS):
            with open(files[f"state/db.{i}.json"]) as f:
                parts.append(json.load(f))
        parts.sort(key=lambda p: p["part"])
        raw = gzip.decompress(base64.b64decode("".join(p["data"] for p in parts)))
        with tempfile.NamedTemporaryFile(suffix=".db") as t:
            t.write(raw)
            t.flush()
            con = sqlite3.connect(t.name)
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            counts = ", ".join(f"{n} {con.execute(f'SELECT COUNT(*) FROM {n}').fetchone()[0]}" for n in tables)
            con.close()
        note["state/db.0.json"] = f"the scanner's database, gzip+base64 over {SHARDS} shards: {counts}"
    except Exception as e:                   # report, don't publish
        problems.append(f"database shards do not decode: {e}")
        note["state/db.0.json"] = "DOES NOT DECODE"
    for name, path in [("index.html", page)] + sorted(files.items()):
        lines.append(f"  {name:18s} {os.path.getsize(path):>10,} bytes  sha256 {_sha(path)}  {note.get(name, '')}".rstrip())
    texts = {}
    for t in toks + trk:
        for k in ("symbol", "name"):
            if t.get(k):
                texts[str(t[k])] = k
        for k in ("x", "tg"):
            hd = (t.get(k) or {}).get("handle") if isinstance(t.get(k), dict) else None
            if hd:
                texts[str(hd)] = k + " handle"
    flagged = sorted((s for s in texts if SUSPECT.search(s) or len(s) > 64), key=len)
    lines.append(f"  free text from the data sources: {len(texts)} token names, symbols and handles, all shown by the page as "
                 f"escaped plain text; flagged: {len(flagged)}")
    for s in flagged[:12]:
        lines.append(f"    flagged {texts[s]}: {s[:80]!r}")
    return lines, problems


def cycle(state_dir, out_dir, allow_fresh=False):
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    db = os.path.join(out_dir, "undertow.db")
    if os.path.exists(db):
        os.remove(db)
    had = restore(state_dir, db)
    if not had and not allow_fresh:
        raise SystemExit("no saved database found: refusing to start from empty and overwrite the history")
    from . import scan
    # GeckoTerminal's per-DEX pool lists are the slowest calls (about 50, at its free rate limit); hourly runs walk
    # them every third run and rely on Jupiter's category lists, refreshed every run, in between
    C.DISCOVERY_EVERY_MIN = max(C.DISCOVERY_EVERY_MIN, 3 * CADENCE_MIN - 10)
    doc = scan.run(argparse.Namespace(db=db, out=os.path.join(out_dir, "data.json"), max_enrich=80,
                                      no_discovery=False, cadence=CADENCE_MIN))
    page = os.path.join(out_dir, "index.html")
    _build()(page, fragment=True, split=True)
    size = pack(db, out_dir)
    files = {name: os.path.join(out_dir, name) for name in OUTPUTS}
    files.update({f"state/db.{i}.json": os.path.join(out_dir, "state", f"db.{i}.json") for i in range(SHARDS)})
    lines, problems = review(files, page)
    print("review of what this run publishes (every file below was written by this cycle):", flush=True)
    print("\n".join(lines), flush=True)
    print("review: ok" if not problems else "review: problems: " + "; ".join(problems), flush=True)
    if problems:
        raise SystemExit("not publishing: " + "; ".join(problems))
    manifest = {"file_path": page, "files": files, "restored": had, "db_gzip_bytes": size}
    with open(os.path.join(out_dir, "publish.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print("DONE " + json.dumps({k: v for k, v in manifest.items() if k != "files"}), flush=True)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cycle"); c.add_argument("--state", required=True); c.add_argument("--out", required=True)
    c.add_argument("--allow-fresh", action="store_true", help="start from an empty database (first run only)")
    p = sub.add_parser("pack"); p.add_argument("--db", required=True); p.add_argument("--out", required=True)
    r = sub.add_parser("restore"); r.add_argument("--state", required=True); r.add_argument("--db", required=True)
    b = sub.add_parser("bundle"); b.add_argument("--out", required=True)
    v = sub.add_parser("review"); v.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "cycle":
        cycle(a.state, a.out, a.allow_fresh)
    elif a.cmd == "pack":
        print(pack(a.db, a.out))
    elif a.cmd == "review":
        with open(os.path.join(a.out, "publish.json")) as fh:
            man = json.load(fh)
        ls, ps = review(man["files"], man["file_path"])
        print("\n".join(ls)); print("review: ok" if not ps else "review: problems: " + "; ".join(ps))
    elif a.cmd == "restore":
        print(restore(a.state, a.db))
    else:
        print(bundle(a.out), "files")
