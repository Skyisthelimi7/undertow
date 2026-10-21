"""Research helper: 5-minute GeckoTerminal candles (about 83 hours back from now) for every token the scanner has seen
in range, for offline studies of entry and exit signals. Run by .github/workflows/study-candles.yml, split across
several runners because GeckoTerminal rate-limits each address.
Usage: python3 tools/fetch_candles.py <db> <out dir> <shard> <shards>"""
import json, os, sqlite3, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from undertow import sources as S
from undertow.http import fetch

db_path, out, shard, shards = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
os.makedirs(os.path.join(out, "c"), exist_ok=True)
db = sqlite3.connect(db_path)
mints = sorted({r[0] for r in db.execute("SELECT DISTINCT mint FROM snaps UNION SELECT DISTINCT mint FROM obs "
                                        "UNION SELECT mint FROM tokens WHERE trk_json IS NOT NULL")})
mine = [m for i, m in enumerate(mints) if i % shards == shard]
pools = dict(db.execute("SELECT mint, pool FROM tokens"))
ds = S.ds_tokens(mine)
json.dump(ds, open(os.path.join(out, f"ds-{shard}.json"), "w"))
t0, empty = time.time(), 0
for n, m in enumerate(mine, 1):
    pair = (ds.get(m) or {}).get("pair") or pools.get(m)
    cs = None
    if pair:
        d = fetch("geckoterminal", f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair}/ohlcv/minute"
                                   f"?aggregate=5&limit=1000&currency=usd&token={m}")
        lst = (((d or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list")
        cs = sorted(([int(c[0])] + [float(x) for x in c[1:6]] for c in lst), key=lambda c: c[0]) if lst else None
    empty += cs is None
    json.dump({"pair": pair, "c": cs, "at": time.time()}, open(os.path.join(out, "c", m + ".json"), "w"))
    if n % 25 == 0:
        print(f"{n}/{len(mine)} in {time.time() - t0:.0f}s, {empty} empty", flush=True)
print(f"shard {shard}: {len(mine)} tokens, {empty} empty, {time.time() - t0:.0f}s")
