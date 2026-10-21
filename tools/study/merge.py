"""Merge the study-candles workflow's artifacts (candles-0 ... candles-5, each with c/<mint>.json and ds-<n>.json) into
one study folder: <out>/c/<mint>.json and <out>/ds.json.

How the buy/sell study behind config.TRADE_STUDY was run (the study scripts need numpy and scipy):
  gh workflow run study-candles.yml        then  gh run download <run id> -D artifacts
  gh workflow run export-db.yml            then  gh run download <run id> -n undertow-db  and gunzip it
  python3 tools/study/merge.py artifacts study
  python3 -I tools/study/study_run.py   study undertow.db     baselines and one variable at a time
  python3 -I tools/study/study_rules.py study undertow.db     pushes, pullbacks and entry rules as trades
  python3 -I tools/study/study_tp.py    study undertow.db     take-profit exits and entry filters on matured entries
  python3 -I tools/study/study_stops.py study undertow.db     stops and trailing stops on matured entries
Usage: python3 tools/study/merge.py <artifacts dir> <out dir>"""
import glob, json, os, shutil, sys

src, out = sys.argv[1], sys.argv[2]
os.makedirs(os.path.join(out, "c"), exist_ok=True)
ds, n = {}, 0
for d in sorted(glob.glob(os.path.join(src, "candles-*"))):
    for f in glob.glob(os.path.join(d, "ds-*.json")):
        ds.update(json.load(open(f)))
    for f in glob.glob(os.path.join(d, "c", "*.json")):
        shutil.copy(f, os.path.join(out, "c", os.path.basename(f)))
        n += 1
json.dump(ds, open(os.path.join(out, "ds.json"), "w"))
print(f"{n} candle files, {len(ds)} DEX Screener records -> {out}")
