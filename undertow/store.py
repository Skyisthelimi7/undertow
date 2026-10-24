"""SQLite persistence. One file, no server, free."""
import json, sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens(
  mint TEXT PRIMARY KEY, symbol TEXT, name TEXT, pool TEXT, dex TEXT,
  first_seen REAL, last_seen REAL, graduated INTEGER,
  gt_json TEXT, gt_ts REAL, rc_json TEXT, rc_ts REAL,
  status TEXT DEFAULT 'OUT', pass_streak INTEGER DEFAULT 0, fail_streak INTEGER DEFAULT 0, status_since REAL,
  gates_json TEXT, ever_in INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS snaps(
  mint TEXT, ts REAL, price REAL, mcap REAL, liq REAL, vol24 REAL, vol1 REAL, chg1 REAL, chg6 REAL, chg24 REAL,
  buys24 INTEGER, sells24 INTEGER, buys1 INTEGER, sells1 INTEGER, holders INTEGER, top10 REAL,
  creator_pct REAL, creator_bal REAL, top20 TEXT);
CREATE INDEX IF NOT EXISTS ix_snaps ON snaps(mint, ts);
CREATE TABLE IF NOT EXISTS tg(handle TEXT, ts REAL, members INTEGER, online INTEGER);
CREATE INDEX IF NOT EXISTS ix_tg ON tg(handle, ts);
CREATE TABLE IF NOT EXISTS transitions(ts REAL, mint TEXT, symbol TEXT, frm TEXT, to_ TEXT, reasons TEXT);
CREATE TABLE IF NOT EXISTS entries(mint TEXT, n INTEGER, in_ts REAL, in_mcap REAL, in_price REAL,
  out_ts REAL, out_mcap REAL, out_reason TEXT);
CREATE INDEX IF NOT EXISTS ix_entries ON entries(mint, n);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS obs(
  ts REAL, mint TEXT, ev TEXT, state TEXT, passed INTEGER, fails TEXT, price REAL, f TEXT, rules TEXT,
  p1 REAL, p6 REAL, p24 REAL, hi REAL, lo REAL, up50_ts REAL, dn80_ts REAL, x2_ts REAL, cross TEXT, done INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_obs_open ON obs(done, mint);
CREATE INDEX IF NOT EXISTS ix_obs_ts ON obs(ts);
CREATE INDEX IF NOT EXISTS ix_obs_mint ON obs(mint, ts);
CREATE TABLE IF NOT EXISTS tsnap(
  ts REAL, mint TEXT, ev TEXT, h REAL, state TEXT, fails TEXT, price REAL, x REAL,
  mc REAL, liq REAL, v1h REAL, v6h REAL, v24h REAL, c1h REAL, bs1h REAL, nf1h REAL, tr1h REAL, brd1h REAL,
  hold REAL, hc1h REAL, top10 REAL, org REAL, lfdv REAL);
CREATE INDEX IF NOT EXISTS ix_tsnap ON tsnap(mint, ts);
CREATE TABLE IF NOT EXISTS tpath(ts REAL, mint TEXT, st TEXT, price REAL, liq REAL, c1h REAL, f TEXT);
CREATE INDEX IF NOT EXISTS ix_tpath ON tpath(mint, ts);
CREATE INDEX IF NOT EXISTS ix_tpath_ts ON tpath(ts);
CREATE TABLE IF NOT EXISTS tsig(id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT, mint TEXT, sym TEXT, in_ts REAL,
  in_price REAL, in_liq REAL, in_mc REAL, f TEXT, ref TEXT, live INTEGER DEFAULT 0, out TEXT, st TEXT,
  miss INTEGER DEFAULT 0, last_price REAL, last_liq REAL, done INTEGER DEFAULT 0, ref_out_ts REAL);
CREATE INDEX IF NOT EXISTS ix_tsig_open ON tsig(done, mint);
CREATE INDEX IF NOT EXISTS ix_tsig_rule ON tsig(rule, mint);
CREATE TABLE IF NOT EXISTS tick(ts REAL, mint TEXT, price REAL, liq REAL, mc REAL, v5 REAL, v1h REAL, b5 INTEGER,
  s5 INTEGER, c5 REAL, c1h REAL, bst INTEGER, gtr5 INTEGER);
CREATE INDEX IF NOT EXISTS ix_tick_ts ON tick(ts);
CREATE TABLE IF NOT EXISTS feed(ts REAL, mint TEXT, kind TEXT, amount REAL, total REAL, impressions REAL, at REAL);
CREATE INDEX IF NOT EXISTS ix_feed ON feed(mint, ts);
CREATE TABLE IF NOT EXISTS pnl_carry(rule TEXT, day INTEGER, n INTEGER, net REAL, wins INTEGER, first_ts REAL,
  last_ts REAL, PRIMARY KEY(rule, day));
"""
# tpath states: I passed every gate, W on watch (failing a soft gate once), E entering, O out, X failed a structure
# gate this scan, G not a candidate this scan (out of range or unpriced: price only)
PATH_STATE = {"IN": "I", "WATCH": "W", "ENTERING": "E", "OUT": "O"}
OBS_OUT = ("p1", "p6", "p24", "hi", "lo", "up50_ts", "dn80_ts", "x2_ts", "cross", "done")
# The tracker's hourly snapshot: keys follow lab.VARIABLES so labels and units are shared with the Lab.
TSNAP_VARS = ("mc", "liq", "v1h", "v6h", "v24h", "c1h", "bs1h", "nf1h", "tr1h", "brd1h", "hold", "hc1h", "top10", "org", "lfdv")
TSNAP_COLS = ("ts", "mint", "ev", "h", "state", "fails", "price", "x") + TSNAP_VARS

# Columns added after the first release; ALTER TABLE keeps existing databases working.
ADDED = [("trk_json", "TEXT"), ("entries_n", "INTEGER DEFAULT 0"), ("last_exit_ts", "REAL"), ("exit_json", "TEXT"),
         ("exit_ts", "REAL"), ("live_price", "REAL"), ("live_mcap", "REAL"), ("live_ts", "REAL"),
         ("entry_json", "TEXT"), ("candles_ts", "REAL"), ("rpc_json", "TEXT"), ("rpc_ts", "REAL"),
         ("lock_json", "TEXT"), ("lock_ts", "REAL"), ("gp_json", "TEXT"), ("gp_ts", "REAL"),
         # attention (see attention.py): the hourly history of boosts, trending ranks, X followers and Telegram
         # members, and the latest DEX Screener orders, X profile and website domain readings
         ("attn_json", "TEXT")]
SETTABLE = {c for c, _ in ADDED}


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(tokens)")}
        for col, typ in ADDED:
            if col not in have:
                self.db.execute(f"ALTER TABLE tokens ADD COLUMN {col} {typ}")
        self.db.commit()

    def commit(self):
        self.db.commit()

    def close(self):
        self.db.commit()
        self.db.close()

    def upsert_seen(self, p, now):
        self.db.execute(
            """INSERT INTO tokens(mint,symbol,name,pool,dex,first_seen,last_seen) VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(mint) DO UPDATE SET last_seen=excluded.last_seen,
                 symbol=COALESCE(tokens.symbol,excluded.symbol), name=COALESCE(tokens.name,excluded.name),
                 pool=COALESCE(NULLIF(excluded.pool,''), tokens.pool), dex=COALESCE(NULLIF(excluded.dex,''), tokens.dex)""",
            (p["mint"], p.get("name"), p.get("name"), p["pool"], p["dex"], now, now))

    def universe(self, since):
        return [dict(r) for r in self.db.execute("SELECT * FROM tokens WHERE last_seen>=? OR ever_in=1", (since,))]

    def get(self, mint):
        r = self.db.execute("SELECT * FROM tokens WHERE mint=?", (mint,)).fetchone()
        return dict(r) if r else None

    def set_json(self, mint, col, data, ts):
        self.db.execute(f"UPDATE tokens SET {col}_json=?, {col}_ts=? WHERE mint=?", (json.dumps(data), ts, mint))

    def set_names(self, mint, symbol, name):
        self.db.execute("UPDATE tokens SET symbol=?, name=? WHERE mint=?", (symbol, name, mint))

    def set_graduated(self, mint, v):
        self.db.execute("UPDATE tokens SET graduated=? WHERE mint=?", (1 if v else 0, mint))

    def add_snap(self, mint, ts, s):
        self.db.execute(
            "INSERT INTO snaps VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mint, ts, s.get("price"), s.get("mcap"), s.get("liq"), s.get("vol24"), s.get("vol1"), s.get("chg1"),
             s.get("chg6"), s.get("chg24"), s.get("buys24"), s.get("sells24"), s.get("buys1"), s.get("sells1"),
             s.get("holders"), s.get("top10"), s.get("creator_pct"), s.get("creator_bal"), json.dumps(s.get("top20") or {})))

    def snaps(self, mint, since):
        return [dict(r) for r in self.db.execute("SELECT * FROM snaps WHERE mint=? AND ts>=? ORDER BY ts", (mint, since))]

    def add_tg(self, handle, ts, members, online):
        self.db.execute("INSERT INTO tg VALUES(?,?,?,?)", (handle, ts, members, online))

    def tg_hist(self, handle, since):
        return [(r["ts"], r["members"]) for r in self.db.execute("SELECT ts,members FROM tg WHERE handle=? AND ts>=? ORDER BY ts", (handle, since))]

    def set_state(self, mint, status, pass_s, fail_s, since, gates):
        self.db.execute("UPDATE tokens SET status=?,pass_streak=?,fail_streak=?,status_since=?,gates_json=?,ever_in=MAX(ever_in,?) WHERE mint=?",
                        (status, pass_s, fail_s, since, json.dumps(gates), 1 if status == "IN" else 0, mint))

    def add_transition(self, ts, mint, symbol, frm, to, reasons):
        self.db.execute("INSERT INTO transitions VALUES(?,?,?,?,?,?)", (ts, mint, symbol, frm, to, json.dumps(reasons)))

    def recent_transitions(self, n=60):
        return [dict(r) for r in self.db.execute("SELECT * FROM transitions ORDER BY ts DESC LIMIT ?", (n,))]

    def prune(self, snaps_before, tg_before=None):
        """Per-run snapshots only feed 24-30h lookbacks (sparkline, holder growth, outflow), so they go after a day
        and a half; Telegram counts are kept longer for growth rates."""
        self.db.execute("DELETE FROM snaps WHERE ts<?", (snaps_before,))
        self.db.execute("DELETE FROM tg WHERE ts<?", (tg_before if tg_before is not None else snaps_before,))

    def get_meta(self, k):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else None

    def set_meta(self, k, v):
        self.db.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))

    # ---- observations for the Lab ------------------------------------------------------------
    def add_obs(self, ts, mint, ev, state, passed, fails, price, feats, rules):
        self.db.execute("INSERT INTO obs(ts,mint,ev,state,passed,fails,price,f,rules) VALUES(?,?,?,?,?,?,?,?,?)",
                        (ts, mint, ev, state, 1 if passed else 0, ",".join(fails), price,
                         json.dumps(feats, separators=(",", ":")), json.dumps(rules, separators=(",", ":"))))

    def open_obs(self):
        out = []
        for r in self.db.execute(f"SELECT rowid, ts, mint, price, {', '.join(OBS_OUT)} FROM obs WHERE done=0"):
            d = dict(r)
            d["cross"] = json.loads(d["cross"]) if d["cross"] else {}
            out.append(d)
        return out

    def update_obs(self, rowid, ch):
        bad = set(ch) - set(OBS_OUT)
        if bad:
            raise ValueError(f"not settable: {bad}")
        vals = [json.dumps(v, separators=(",", ":")) if k == "cross" else v for k, v in ch.items()]
        self.db.execute(f"UPDATE obs SET {', '.join(f'{k}=?' for k in ch)} WHERE rowid=?", (*vals, rowid))

    def obs_rows(self, since=0):
        out = []
        for r in self.db.execute("SELECT * FROM obs WHERE ts>=? ORDER BY ts", (since,)):
            d = dict(r)
            d["f"], d["rules"] = json.loads(d["f"] or "{}"), json.loads(d["rules"] or "{}")
            d["fails"] = [x for x in (d["fails"] or "").split(",") if x]
            d["cross"] = json.loads(d["cross"]) if d.get("cross") else {}
            out.append(d)
        return out

    def lab_rows(self):
        """What the Lab analyses: every entry, plus the first observation per token per day, overall and among
        observations that passed every gate."""
        q = """SELECT * FROM obs WHERE rowid IN (
                 SELECT MIN(rowid) FROM obs WHERE ev IN ('hourly','entry') GROUP BY mint, CAST(ts/86400 AS INTEGER)
                 UNION SELECT MIN(rowid) FROM obs WHERE ev IN ('hourly','entry') AND passed=1
                       GROUP BY mint, CAST(ts/86400 AS INTEGER)
                 UNION SELECT rowid FROM obs WHERE ev='entry') ORDER BY ts"""
        out = []
        for r in self.db.execute(q):
            d = dict(r)
            d["f"], d["rules"] = json.loads(d["f"] or "{}"), json.loads(d["rules"] or "{}")
            d["fails"] = [x for x in (d["fails"] or "").split(",") if x]
            d["cross"] = json.loads(d["cross"]) if d.get("cross") else {}
            out.append(d)
        return out

    def obs_needed(self, mint, ts, passed):
        """The Lab reads the first observation per token per day, and the first that passed every gate. An hourly
        observation is stored only when it is one of those, so the history stays small enough to carry around."""
        day = int(ts // 86400)
        r = self.db.execute("""SELECT COUNT(*), COALESCE(SUM(passed),0) FROM obs WHERE mint=? AND ev IN ('hourly','entry')
                               AND ts>=? AND ts<?""", (mint, day * 86400, (day + 1) * 86400)).fetchone()
        return r[0] == 0 or (passed and r[1] == 0)

    def obs_stats(self):
        r = self.db.execute("SELECT COUNT(*), MIN(ts), SUM(ev='entry'), SUM(done) FROM obs").fetchone()
        return {"rows": r[0], "since": r[1], "entries": r[2] or 0, "closed": r[3] or 0}

    def obs_ends(self, mint):
        """The features a token had at its first recorded entry and at its latest observation (with its time)."""
        e = self.db.execute("SELECT f FROM obs WHERE mint=? AND ev='entry' ORDER BY ts LIMIT 1", (mint,)).fetchone()
        last = self.db.execute("SELECT f, ts FROM obs WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,)).fetchone()
        return (json.loads(e["f"]) if e else None, json.loads(last["f"]) if last else None, last["ts"] if last else None)

    def symbols(self):
        return {r["mint"]: r["symbol"] for r in self.db.execute("SELECT mint, symbol FROM tokens")}

    def thin_obs(self, before):
        """Older than `before`: keep entries, exits and the first hourly row per token per day, so the Lab's
        long-run sample keeps growing while the file stays small."""
        self.db.execute("""DELETE FROM obs WHERE ts<? AND ev='hourly' AND rowid NOT IN (
                             SELECT MIN(rowid) FROM obs WHERE ev='hourly' GROUP BY mint, CAST(ts/86400 AS INTEGER))""", (before,))

    # ---- tracker snapshots: every tracked token once an hour ------------------------------------
    def add_tsnap(self, ts, mint, ev, h, state, fails, price, x, f):
        vals = (ts, mint, ev, h, state, ",".join(fails or []), price, x) + tuple(f.get(k) for k in TSNAP_VARS)
        self.db.execute(f"INSERT INTO tsnap({','.join(TSNAP_COLS)}) VALUES({','.join('?' * len(TSNAP_COLS))})", vals)

    def tsnaps(self, mint=None):
        q, a = ("SELECT * FROM tsnap WHERE mint=? ORDER BY ts", (mint,)) if mint else ("SELECT * FROM tsnap ORDER BY mint, ts", ())
        return [dict(r) for r in self.db.execute(q, a)]

    def tsnap_count(self):
        return self.db.execute("SELECT COUNT(*) FROM tsnap").fetchone()[0]

    def thin_tsnap(self, full_h):
        """Hourly for the first full_h hours after entry, then one snapshot per 6 hours; entry rows always stay."""
        self.db.execute("""DELETE FROM tsnap WHERE h>? AND ev!='entry' AND rowid NOT IN (
                             SELECT MIN(rowid) FROM tsnap WHERE h>? AND ev!='entry'
                             GROUP BY mint, CAST((h-?)/6 AS INTEGER))""", (full_h, full_h, full_h))

    # ---- buy and sell signals: the path each scan, and every paper trade ---------------------------
    def add_tpath(self, rows):
        """rows: (ts, mint, state, price, liq, c1h, features or None)."""
        self.db.executemany("INSERT INTO tpath VALUES(?,?,?,?,?,?,?)",
                            [(*r[:6], json.dumps(r[6], separators=(",", ":")) if r[6] else None) for r in rows])

    def tpath(self, since):
        """{mint: [(ts, state, price, liq, c1h, features)]} ascending, since `since`."""
        out = {}
        for r in self.db.execute("SELECT ts, mint, st, price, liq, c1h, f FROM tpath WHERE ts>=? ORDER BY mint, ts", (since,)):
            out.setdefault(r["mint"], []).append((r["ts"], r["st"], r["price"], r["liq"], r["c1h"], json.loads(r["f"]) if r["f"] else None))
        return out

    def tpath_recent(self, since):
        """Coins that passed every gate (or were on watch) at some scan since `since`."""
        return {r[0] for r in self.db.execute("SELECT DISTINCT mint FROM tpath WHERE ts>=? AND st IN ('I','W')", (since,))}

    def tpath_stats(self):
        r = self.db.execute("SELECT COUNT(*), MIN(ts), COUNT(DISTINCT mint), SUM(st='I') FROM tpath").fetchone()
        return {"rows": r[0], "since": r[1], "coins": r[2], "passing_rows": r[3] or 0}

    def prune_tpath(self, before):
        self.db.execute("DELETE FROM tpath WHERE ts<?", (before,))

    _SIG_JSON = ("f", "out", "st")

    def _sig(self, r):
        d = dict(r)
        for k in self._SIG_JSON:
            d[k] = json.loads(d[k]) if d.get(k) else {}
        return d

    def add_sig(self, rule, mint, sym, ts, price, liq, mc, f, ref, live, st):
        cur = self.db.execute("""INSERT INTO tsig(rule,mint,sym,in_ts,in_price,in_liq,in_mc,f,ref,live,out,st,last_price,last_liq)
                                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                              (rule, mint, sym, ts, price, liq, mc, json.dumps(f, separators=(",", ":")), ref, 1 if live else 0,
                               "{}", json.dumps(st, separators=(",", ":")), price, liq))
        return cur.lastrowid

    def update_sig(self, sid, out, st, miss, last_price, last_liq, done, ref_out_ts):
        self.db.execute("UPDATE tsig SET out=?, st=?, miss=?, last_price=?, last_liq=?, done=?, ref_out_ts=? WHERE id=?",
                        (json.dumps(out, separators=(",", ":")), json.dumps(st, separators=(",", ":")), miss, last_price,
                         last_liq, 1 if done else 0, ref_out_ts, sid))

    def set_sig_out(self, sid, out):
        self.db.execute("UPDATE tsig SET out=? WHERE id=?", (json.dumps(out, separators=(",", ":")), sid))

    def open_sigs(self):
        return [self._sig(r) for r in self.db.execute("SELECT * FROM tsig WHERE done=0")]

    def sigs(self, since=0):
        return [self._sig(r) for r in self.db.execute("SELECT * FROM tsig WHERE in_ts>=? ORDER BY in_ts", (since,))]

    def busy_rules(self, now, reentry_h):
        """{(rule, mint)} that cannot open a new trade: the rule's last trade on the coin is still open under the
        policy that governs it, or it opened less than reentry_h hours ago."""
        q = """SELECT rule, mint FROM tsig WHERE ref_out_ts IS NULL OR in_ts>?"""
        return {(r[0], r[1]) for r in self.db.execute(q, (now - reentry_h * 3600,))}

    def prune_sigs(self, before, models_before=None):
        """Settled paper trades of rules that were not live when they opened, once older than `before`; the models'
        (many more of them) once older than `models_before`. Each one's result is carried first (pnl_carry), so a
        rule's running profit and loss since it started still counts it."""
        where = [("in_ts<? AND live=0 AND done=1", (before,))]
        if models_before:
            where.append(("in_ts<? AND live=0 AND done=1 AND rule LIKE 'm:%'", (models_before,)))
        for cond, args in where:
            self._carry(self.db.execute(f"SELECT rule, in_ts, ref, out FROM tsig WHERE {cond}", args).fetchall())
            self.db.execute(f"DELETE FROM tsig WHERE {cond}", args)

    def _carry(self, rows):
        """Add pruned trades' results (net % under the exit each was held to) to pnl_carry, by rule and entry day."""
        add = {}
        for rule, in_ts, ref, out in rows:
            o = (json.loads(out) if out else {}).get(ref)
            if not o:
                continue
            k = (rule, int(in_ts // 86400))
            a = add.setdefault(k, [0, 0.0, 0, in_ts, o[3]])
            a[0] += 1
            a[1] += o[0]
            a[2] += 1 if o[0] > 0 else 0
            a[3], a[4] = min(a[3], in_ts), max(a[4], o[3])
        for (rule, day), (n, net, wins, t0, t1) in add.items():
            self.db.execute(
                """INSERT INTO pnl_carry(rule, day, n, net, wins, first_ts, last_ts) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(rule, day) DO UPDATE SET n=n+excluded.n, net=net+excluded.net, wins=wins+excluded.wins,
                   first_ts=MIN(first_ts, excluded.first_ts), last_ts=MAX(last_ts, excluded.last_ts)""",
                (rule, day, n, net, wins, t0, t1))

    def pnl_carried(self):
        """{rule: [(day, n, net % summed, wins, first entry, last close)]}: the results of trades pruned from tsig."""
        out = {}
        for r in self.db.execute("SELECT rule, day, n, net, wins, first_ts, last_ts FROM pnl_carry ORDER BY rule, day"):
            out.setdefault(r[0], []).append(tuple(r[1:]))
        return out

    def sigs_before(self, before):
        """Paper trades opened before `before` (the ones older than the pages' window that are still stored)."""
        return [self._sig(r) for r in self.db.execute("SELECT * FROM tsig WHERE in_ts<? ORDER BY in_ts", (before,))]

    def prune_attention(self, before):
        """Drop the attention records of coins last read before `before` (no longer candidates), keeping each record's
        website reading, which does not go stale. Returns how many were thinned."""
        n = 0
        for r in self.db.execute("SELECT mint, attn_json FROM tokens WHERE attn_json IS NOT NULL").fetchall():
            a = json.loads(r[1])
            last = max([(a.get("hist") or [[0]])[-1][0]] + [(a.get(k) or {}).get("ts") or 0 for k in ("orders", "x")])
            if last < before and (a.get("hist") or a.get("orders") or a.get("x")):
                keep = {"web": a["web"]} if a.get("web") else None
                self.db.execute("UPDATE tokens SET attn_json=? WHERE mint=?", (json.dumps(keep) if keep else None, r[0]))
                n += 1
        return n

    # ---- minute data (fast.py): one reading a minute for the watched coins, and DEX Screener's boosts and ads feeds --
    def add_ticks(self, rows):
        from .minute import TICK_COLS
        self.db.executemany(f"INSERT INTO tick({','.join(TICK_COLS)}) VALUES({','.join('?' * len(TICK_COLS))})",
                            [tuple(r.get(c) for c in TICK_COLS) for r in rows])

    def ticks(self, since, until=None, mints=None):
        """Minute readings in time order (dicts), since `since` (exclusive) and up to `until` (inclusive)."""
        q, a = "SELECT * FROM tick WHERE ts>?", [since]
        if until is not None:
            q += " AND ts<=?"
            a.append(until)
        if mints is not None:
            mints = list(mints)
            if not mints:
                return []
            q += f" AND mint IN ({','.join('?' * len(mints))})"
            a += mints
        return [dict(r) for r in self.db.execute(q + " ORDER BY ts, mint", a)]

    def ticks_by_coin(self, since, mints=None):
        """Each coin's minute readings since `since`, one coin at a time: yields (mint, [dict]) in mint order, so a long
        window never sits in memory at once."""
        q, a = "SELECT * FROM tick WHERE ts>?", [since]
        if mints is not None:
            mints = sorted(mints)
            if not mints:
                return
            q += f" AND mint IN ({','.join('?' * len(mints))})"
            a += mints
        cur, rows = None, []
        for r in self.db.execute(q + " ORDER BY mint, ts", a):
            if r["mint"] != cur:
                if rows:
                    yield cur, rows
                cur, rows = r["mint"], []
            rows.append(dict(r))
        if rows:
            yield cur, rows

    def add_feeds(self, rows):
        """Feed entries (ts, mint, kind, amount, total, impressions, at); an entry already stored is skipped."""
        for r in rows:
            ts, mint, kind, amount, total, imp, at = r
            if self.db.execute("SELECT 1 FROM feed WHERE mint=? AND kind=? AND COALESCE(at,0)=COALESCE(?,0) "
                               "AND COALESCE(total,0)=COALESCE(?,0) AND COALESCE(impressions,0)=COALESCE(?,0) LIMIT 1",
                               (mint, kind, at, total, imp)).fetchone():
                continue
            self.db.execute("INSERT INTO feed VALUES(?,?,?,?,?,?,?)", r)

    def feeds(self, since):
        return [tuple(r) for r in self.db.execute("SELECT ts, mint, kind, amount, total, impressions, at FROM feed "
                                                  "WHERE ts>=? ORDER BY ts", (since,))]

    def tick_stats(self):
        r = self.db.execute("SELECT COUNT(*), MIN(ts), MAX(ts), COUNT(DISTINCT mint) FROM tick").fetchone()
        return {"rows": r[0], "since": r[1], "last": r[2], "coins": r[3]}

    def prune_ticks(self, ticks_before, feeds_before):
        self.db.execute("DELETE FROM tick WHERE ts<?", (ticks_before,))
        self.db.execute("DELETE FROM feed WHERE ts<?", (feeds_before,))

    def scan_passing(self, before):
        """The latest scan before `before` (from the path): its time and {mint: the variables the rules read} for every
        coin that passed every gate at it. (None, {}) when the path is empty."""
        r = self.db.execute("SELECT MAX(ts) FROM tpath WHERE ts<?", (before,)).fetchone()
        if not r or r[0] is None:
            return None, {}
        rows = self.db.execute("SELECT mint, f FROM tpath WHERE ts=? AND st='I'", (r[0],))
        return r[0], {x[0]: json.loads(x[1]) if x[1] else {} for x in rows}

    def passing_sets(self, since):
        """[(scan time, {mints that passed every gate})] ascending, for every scan since `since`."""
        out = {}
        for ts, mint, st in self.db.execute("SELECT ts, mint, st FROM tpath WHERE ts>=? ORDER BY ts", (since,)):
            s = out.setdefault(ts, set())
            if st == "I":
                s.add(mint)
        return sorted(out.items())

    def fast_last(self, rules):
        """{(rule, mint): (latest entry time, whether a trade of the pair is still open under its rule's exit)} for the
        given rules: what decides whether a quick rule may buy the coin again."""
        rules = list(rules)
        if not rules:
            return {}
        q = (f"SELECT rule, mint, MAX(in_ts), SUM(ref_out_ts IS NULL) FROM tsig WHERE rule IN ({','.join('?' * len(rules))}) "
             "GROUP BY rule, mint")
        return {(r[0], r[1]): (r[2], bool(r[3])) for r in self.db.execute(q, rules)}

    def insert_sig(self, s):
        """A paper trade worked out in full elsewhere (the minute ledger): every column at once. Returns its id."""
        sid = self.add_sig(s["rule"], s["mint"], s.get("sym"), s["in_ts"], s["in_price"], s.get("in_liq"), s.get("in_mc"),
                           s.get("f") or {}, s["ref"], s.get("live"), s.get("st") or {})
        self.update_sig(sid, s.get("out") or {}, s.get("st") or {}, s.get("miss") or 0, s.get("last_price"),
                        s.get("last_liq"), s.get("done"), s.get("ref_out_ts"))
        return sid

    def watch_list(self, since):
        """Coins the minute sampler reads: inside the screener or entering, passing at some scan since `since`, or
        holding an open paper trade; coins inside first."""
        inside = [r[0] for r in self.db.execute("SELECT mint FROM tokens WHERE status='IN' OR pass_streak>0 "
                                                "ORDER BY status='IN' DESC, mint")]
        recent = [r[0] for r in self.db.execute("SELECT DISTINCT mint FROM tpath WHERE ts>=? AND st IN ('I','W')", (since,))]
        held = [r[0] for r in self.db.execute("SELECT DISTINCT mint FROM tsig WHERE done=0")]
        return list(dict.fromkeys(inside + held + recent))

    def live_open_mints(self):
        return {r[0] for r in self.db.execute("SELECT DISTINCT mint FROM tsig WHERE live=1 AND ref_out_ts IS NULL")}

    # ---- tracker ---------------------------------------------------------------------------
    def set_cols(self, mint, **kw):
        bad = set(kw) - SETTABLE
        if bad:
            raise ValueError(f"not settable: {bad}")
        cols = ", ".join(f"{k}=?" for k in kw)
        self.db.execute(f"UPDATE tokens SET {cols} WHERE mint=?", (*kw.values(), mint))

    def open_entry(self, mint, n, ts, mcap, price):
        self.db.execute("INSERT INTO entries(mint,n,in_ts,in_mcap,in_price) VALUES(?,?,?,?,?)", (mint, n, ts, mcap, price))

    def close_entry(self, mint, ts, mcap, reason):
        self.db.execute("""UPDATE entries SET out_ts=?, out_mcap=?, out_reason=? WHERE rowid=(
                           SELECT rowid FROM entries WHERE mint=? AND out_ts IS NULL ORDER BY n DESC LIMIT 1)""",
                        (ts, mcap, reason, mint))

    def tracked(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM tokens WHERE trk_json IS NOT NULL")]

    def first_entry_backfill(self):
        """Tokens that entered before the tracker existed: rebuild entry time, price and market cap from the
        first OUT->IN transition and the snapshot taken in that same run."""
        rows = self.db.execute("""SELECT t.mint, MIN(x.ts) AS ts FROM tokens t JOIN transitions x ON x.mint=t.mint
                                  WHERE t.trk_json IS NULL AND x.to_='IN' GROUP BY t.mint""").fetchall()
        out = []
        for r in rows:
            s = self.db.execute("SELECT price, mcap FROM snaps WHERE mint=? AND ts=?", (r["mint"], r["ts"])).fetchone()
            if s and s["price"] and s["mcap"]:
                n = self.db.execute("SELECT COUNT(*) FROM transitions WHERE mint=? AND to_='IN'", (r["mint"],)).fetchone()[0]
                out.append((r["mint"], r["ts"], s["price"], s["mcap"], n))
        return out
