"""Every threshold lives here and nowhere else. Edit this file to tune the screener."""
import os

# Where the always-live copy of the page runs (GitHub Pages, scanned every 20 minutes, prices refreshed in the
# browser). Copies served anywhere else, such as a claude.ai page, link to it. Set the variable to "" to hide it.
LIVE_URL = os.environ.get("UNDERTOW_LIVE_URL", "https://skyisthelimi7.github.io/undertow/")

# Community features (rug calls, votes, crowd tags) live in Supabase. The URL and the publishable key are public by
# design: the page uses them, and supabase/schema.sql's row-level security decides what visitors may do. The scanner
# also needs the secret key, as the GitHub Actions secret SUPABASE_SECRET_KEY; never put that one here.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://jazltffnxukxyzxmzrey.supabase.co")
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_rvF3MRF-yXr_cVptLTWG-Q_fI3tCtMy")
SUPABASE_X_LOGIN = False          # set True once Supabase's X (Twitter) provider is switched on
CALL_BASE_RATE = 0.10             # rug base rate for scoring calls until a fortnight of passing coins has settled

# Market-cap bands used to group the map. MIN_MCAP..MAX_MCAP defines the scope: which coins are assessed.
# The rug study found a market-cap floor is not a safety check (coins just above $20k were the riskiest in their
# first hours), so the range is treated as scope, not as protection.
BANDS = [
    ("20k-100k", 20_000, 100_000),
    ("100k-1m", 100_000, 1_000_000),
    ("1m-10m", 1_000_000, 10_000_000),
    ("10m-20m", 10_000_000, 20_000_000),
]
MIN_MCAP = 20_000
MAX_MCAP = 20_000_000
MIN_VOL24 = 20_000                # USD traded in 24h
MIN_LIQ_USD = 5_000
MIN_LIQ_PCT_MCAP = 0.02           # liquidity / market cap
MAX_VOL_TO_MCAP = 10.0            # above this, volume is almost always wash trading
MAX_TOP10_PCT = 25.0              # top 10 holders, excluding pools, lockers, burn, CEX
MAX_CREATOR_PCT = 5.0             # deployer wallet share of supply
MAX_LINKED_HOLDER_SHARE = 0.25    # transfer-linked wallets / all holders (RugCheck graph)
MAX_SAME_SIZE_HOLDERS = 3         # bundle signature: near-identical balances in the top 20
MIN_LP_LOCKED_PCT = 90.0          # LP burned or locked, main market
DEV_SELL_DROP = 0.25              # deployer balance fell by this fraction vs the 24h-ago snapshot
TOP_OUTFLOW_PCT_6H = 3.0          # top holders' combined outflow, % of supply, over 6h
MAX_TG_BOT_RISK = 75              # Telegram bot-risk score (0-100) above which the gate fails
# A token in free fall is dropped even if its structure is clean: price change limits per window, in percent.
CRASH_LIMITS = {"h1": -40, "h6": -70, "h24": -80}
# Token-2022 extensions that let an issuer take, freeze or block tokens. A transfer hook only counts when a hook
# program is actually set; defaultAccountState only when new accounts start frozen.
DANGEROUS_EXTENSIONS = ("permanentDelegate", "transferHook", "nonTransferable", "pausableConfig", "defaultAccountState")
MAX_TRANSFER_FEE_PCT = 5.0

# Hysteresis. A token must pass ENTER_SCANS times in a row to enter, and fail EXIT_SCANS
# times in a row to leave (hard gates remove it at once). EXIT_SLACK loosens soft limits
# for tokens already in, so a token hovering on a line does not flicker.
SCAN_MINUTES = 20                 # how often the scheduler runs the scan (cron in .github/workflows/scan.yml)
ENTER_SCANS = 2
EXIT_SCANS = 2
EXIT_SLACK = {
    "mcap_low": 0.85, "mcap_high": 1.10, "vol": 0.80, "liq": 0.80,
    "top10": 2.0, "creator": 1.0, "linked": 0.05, "cluster": 3.0,
}

# Polite client pacing (seconds between calls per host). GeckoTerminal's free tier returned 429
# after about 15 calls in a few seconds, consistent with its published ~30 calls a minute.
# DEX Screener allows 300 requests a minute on its pair and token endpoints and 60 on its boosts, orders and ads
# endpoints, so the two are paced apart.
PACE = {"geckoterminal": 2.2, "dexscreener": 1.1, "dexscreener_tokens": 0.3, "rugcheck": 1.1, "telegram": 0.8,
        "jupiter": 2.1, "rpc": 0.6, "goplus": 1.0, "fxtwitter": 1.0, "vxtwitter": 1.0, "rdap": 1.0}
# Solana's public RPC answers mint lookups (authorities, Token-2022 extensions) for free. Set SOLANA_RPC_URL to a
# free Helius or other endpoint for higher limits.
RPC_URL = "https://api.mainnet-beta.solana.com"

# Discovery covers every Solana launchpad and DEX. Jupiter's category lists (100 tokens each, across pump.fun,
# StonkFun, Meteora DBC, letsbonk, bags and direct DEX launches) run every scan; GeckoTerminal's per-DEX pool lists,
# capped at 10 free pages of 20 per sort, run hourly because they are the slowest calls.
JUP_LISTS = ("toptrending/1h", "toptrending/6h", "toptraded/1h", "toptraded/24h", "toporganicscore/1h",
             "toporganicscore/24h", "recent")
DISCOVERY_DEXES = {"pumpswap": 10, "raydium": 3, "raydium-clmm": 2, "meteora": 3, "meteora-damm-v2": 3, "orca": 2}
DISCOVERY_SORTS = ("h24_volume_usd_desc", "h24_tx_count_desc")
DISCOVERY_EVERY_MIN = 60
# Out of scope: price-pegged assets rather than freely priced coins (Jupiter tags; "rwa" covers tokenised gold).
EXCLUDE_TAGS = {"stable", "lst", "xstocks", "stocks", "equities", "rwa"}
# Launchpads whose graduation pool has its LP burned or locked by the launchpad itself, so that pool cannot be
# pulled whatever a lock feed says about the token's other pools. Meteora DBC is left out: its configs can leave
# part of the LP claimable by the creator or partner, so DBC pools need a lock figure like any other pool.
LP_LOCKED_BY_DESIGN = {"pump.fun", "raydium-launchlab", "letsbonk.fun", "bonk.fun", "stonkfun"}
# DEX Screener ids and labels for bonding curves: a coin still on one has not reached a DEX pool.
CURVE_DEX_IDS = {"pumpfun", "meteoradbc", "launchlab", "moonshot", "boop", "heaven", "bonkfun", "letsbonk", "stonkfun"}
CURVE_LABELS = {"DBC", "LaunchLab", "Bonding curve"}
CONCENTRATED_LABELS = {"CLMM", "DLMM", "wp", "Whirlpool"}
UNIVERSE_TTL_DAYS = 7             # forget tokens not seen in discovery for this long
GT_INFO_TTL_H = 24                # re-read GeckoTerminal token info (socials, categories, holders)
RC_TTL_H_IN = 0.2                 # re-read RugCheck for tokens inside the screener
RC_TTL_H_OUT = 3                  # ... and for tokens outside it
GENERIC_CATEGORIES = {"pump fun", "solana meme", "meme", "memes", "pump-fun", "letsbonk"}

# ---- Demand, exit and tracker settings (added 18 Oct 2026) ------------------------------------
# Jupiter's keyless API allows 0.5 requests a second; a free key (env JUP_API_KEY) doubles that.
# lite-api.jup.ag is being retired, so the scanner uses api.jup.ag.
JUP_BASE = "https://api.jup.ag"
ORDER_USD = 500                   # position size for the exit-cost gate
MAX_EXIT_COST_PCT = 10.0          # selling ORDER_USD of the token may cost at most this, impact and fees included
DEFAULT_FEE_PCT = 0.3             # pool fee assumed when there is no measured quote
EXIT_QUOTE_TTL_H = 1              # re-measure the exit cost hourly
MIN_VOL1H = 2_000                 # still trading: USD volume in the last hour
MIN_TRADERS_1H = 30               # enough traders: distinct wallets trading in the last hour
OVEREXTENDED = 0.5                # price this far above its 6h average reads as overextended

# Entry tracker. GeckoTerminal's free 5-minute candles reach back about three and a half days for an active pool
# (1,000 candles); tracked tokens are polled at least hourly, and the tracker treats a gap of over a day as lost.
TRACK_DAYS = 14                   # keep updating ATH and outcomes this long after first entry
TRACK_REFRESH_H_OUT = 1           # tokens no longer in the screener: candles hourly (in-screener tokens every run)
CANDLE_BUDGET = 40                # GeckoTerminal candle calls per run
OUTCOME_HOURS = (1, 6, 24, 168)   # multiples recorded this long after first entry

# ---- Rug-study signals (added 19 Oct 2026) -----------------------------------------------------
# From a study of 9,467 early-stage Solana tokens, 10-29 June 2026: "rug" = closes 80% below entry before ever
# trading 50% above it, within a day. Thresholds below are the study's; rates are its out-of-sample figures.
MIN_AGE_MIN = 60                  # 74% of rugs finished within an hour of detection: no entry in the first hour
MIN_SOLD_1H = 50                  # liveness: under $50 sold in the last hour, 95% of coins never traded again
LFDV_RED, LFDV_GREEN, LFDV_THIN = 0.9, 1.0, 0.2   # liquidity / FDV display zones
RISK_FLAGS = {"lfdv": 0.97, "wallets_10m": 98, "sell_share": 0.33, "age_min": 4.6, "holders": 103, "top5_share": 0.21}
RUG_RATE_BY_FLAGS = {0: 0.0, 1: 2.7, 2: 13.1, 3: 27.5, 4: 44.2, 5: 56.4, 6: 59.1}      # % rugged, 22-29 June
DOUBLED_RATE_BY_FLAGS = {0: 17.0, 1: 22.7, 2: 26.6, 3: 34.7, 4: 27.0, 5: 30.3, 6: 34.8}
CALIBRATED_MAX_AGE_H = 24         # the study measured coins in their first day ...
CALIBRATED_MAX_FDV = 1_000_000    # ... and almost none above $1m, so its rates only apply inside these limits
MAX_RISK_FLAGS = 3                # gate inside the calibrated region: 4+ flags rugged 44-59% of the time
# The study found top-10 share, bundler and insider shares and developer holdings do not predict rugs among fresh
# launchpad graduates. Inside the study's range (a launchpad graduate under a day old and under $1m FDV) they are
# shown, not gated. Everywhere else, including every coin launched straight onto a DEX, they keep gating: the study
# says nothing about older or larger coins. Set True to gate everywhere.
HOLDER_GATES_FOR_LAUNCHPADS = False
TRADES_BUDGET = 30                # GeckoTerminal trade-list calls per run, spent only inside the study's range
GT_INFO_BUDGET = 12               # GeckoTerminal token-info calls per run (sector tags only now)

# ---- The Lab: every variable over time, outcomes, shadow rules (added 19 Oct 2026) -------------------
# Every candidate is observed once an hour, and every entry and exit as it happens, with about 45 variables. Later
# runs fill in what happened next (+1h, +6h, +24h and the 24h high and low), so the Lab can show which variables
# separate risers from fallers. Shadow rules are candidate gates recorded for every observation but never applied:
# the Lab measures whether each would have helped before anyone switches it on.
OBS_EVERY_MIN = 60                # every candidate is checked hourly; the Lab keeps its first observation of each day
OBS_TOL_MIN = 40                  # an outcome at +1h/+6h/+24h is read from the first run within this window after it
                                  # (widened to the scan interval plus 10 minutes when scans run less often)
OBS_FULL_DAYS = 14                # keep every observation this long; older ones thin to one per token per day
SOL_MINT = "So11111111111111111111111111111111111111112"   # SOL's 24h change records the market backdrop
# Verdict rules: no verdict below min_n rows (min_test in the later half). A variable "works" with an AUC at least
# min_auc_gap from 0.5 and more than z standard errors from it, and a line found on the earlier half that lifts the
# share of risers by min_lift on both halves while keeping at least min_keep of them. A shadow rule "helps" when a
# two-proportion test gives z or more and the lift holds in both halves. z is 2.5 rather than 1.96 because dozens
# of variables and rules are tested at once. At 60 rows only effects of about 25 points can show; telling a 10-point
# improvement from luck needs about 400.
LAB = {"min_n": 60, "min_test": 30, "min_keep": 0.3, "min_auc_gap": 0.08, "min_lift": 0.08, "z": 2.5}
# (id, label, variable, operator, threshold). Variables are the keys in lab.VARIABLES; % changes are in percent.
SHADOW_RULES = [
    ("v24_100k", "24h volume at least $100k", "v24h", ">=", 100_000),
    ("v24_250k", "24h volume at least $250k", "v24h", ">=", 250_000),
    ("v1h_10k", "1h volume at least $10k", "v1h", ">=", 10_000),
    ("v6h_50k", "6h volume at least $50k", "v6h", ">=", 50_000),
    ("pace_1h", "Last hour's volume at or above its 24h hourly average", "v1h_24", ">=", 1.0),
    ("pace_6h", "Last 6h volume at or above its 24h average pace", "v6h_24", ">=", 1.0),
    ("netbuy_1h", "Net buying in the last hour", "nf1h", ">", 0),
    ("netbuy_6h", "Net buying over the last 6h", "nf6h", ">", 0),
    ("breadth", "At least half of the last hour's traders net-bought", "brd1h", ">=", 0.5),
    ("buys_1h", "At least as many buys as sells in the last hour", "bs1h", ">=", 1.0),
    ("not_buy_only", "No more than 2 buys per sell in the last hour", "bs1h", "<=", 2.0),
    ("holders_up", "Holder count up over 24h", "hc24h", ">", 0),
    ("not_pumped", "Not up more than 100% in 24h", "c24h", "<=", 100),
    ("not_falling", "Not down more than 20% in 6h", "c6h", ">=", -20),
    ("near_high", "Within 50% of its highest price in 24h", "dd24s", ">=", -0.5),
    ("organic_50", "Jupiter organic score at least 50", "org", ">=", 50),
    ("deep_liq", "Liquidity at least 10% of market cap", "liq_pct", ">=", 0.10),
    ("liq_100k", "Liquidity at least $100k", "liq", ">=", 100_000),
    ("mc_300k", "Market cap at least $300k", "mc", ">=", 300_000),
    ("day_old", "On a DEX for more than a day", "age", ">=", 24),
    ("week_old", "On a DEX for more than a week", "age", ">=", 168),
    ("flags_2", "At most 2 rug-study flags", "rf", "<=", 2),
    ("top10_25", "Top 10 holders at most 25%", "top10", "<=", 25),
    ("market_up", "At least 40% of candidates rising in the last hour", "mkt1h", ">=", 0.4),
    # the free rug-check routine shared on X (InsightX clusters, SolSniffer's deployer check, GoPlus's metadata flag)
    ("cluster_15", "Largest wallet cluster holds at most 15% of supply", "clu", "<=", 15),
    ("meta_locked", "Name, symbol and image can't be changed", "metamut", "<=", 0),
    ("dev_launches_10", "Deployer has launched at most 10 tokens", "devm", "<=", 10),
]

# ---- The weekly gate review (added 20 Oct 2026; undertow/review.py says how verdicts are reached) ---------------
# Every every_days the scanner judges each rug-risk and holder gate on the coins it alone blocked over the last
# window_days, and each candidate rule on the coins that passed every gate. min_group settled coins per side before
# any verdict; min_flat per side before "no effect"; differences of min_diff with z at least z count. A gate is dropped
# (or a rule promoted) only after drop_after (promote_after) reviews in a row agree, at most max_drops and
# max_promotions per review; a promoted rule must keep at least min_keep of passing coins. The bench holds testing
# rules; add_per_review new ones join each week from CANDIDATE_POOL, then from the Lab's own suggested lines, then
# rules retired at least retest_after_days ago. A rule still "collecting" after stale_after reviews (it removes almost
# no passing coin, or almost all) gives up its place.
REVIEW = {"every_days": 7, "window_days": 28, "min_group": 30, "min_flat": 100, "min_diff": 0.05, "z": 2.5,
          "flat_diff": 0.03, "flat_z": 1.0, "drop_after": 2, "promote_after": 2, "max_drops": 1, "max_promotions": 1,
          "min_keep": 0.5, "testing": 30, "add_per_review": 4, "retest_after_days": 56, "stale_after": 6}
PINNED_GATES = ()                 # gate ids the review may report on but never drop
# Lab variables a rule may be tested on but never promoted to a gate: the momentum read-outs and market-wide figures
# come later in a scan than the gates, and the crowd's calls, votes and tags must never gate a token (a crowd that
# could gate could be organised to)
NOT_GATEABLE = {"mom", "ext", "dd24", "dd24s", "sol24", "mkt1h", "crs", "crn", "cvn", "cfl"}
# Rules queued for testing, after the shadow rules already running. Each week the review adds up to add_per_review.
CANDIDATE_POOL = [
    ("cluster_10", "Largest wallet cluster holds at most 10% of supply", "clu", "<=", 10),
    ("ss15_60", "Sells at most 60% of the last 15 minutes' volume", "ss15", "<=", 0.6),
    ("w10_50", "At least 50 wallets traded in the last 10 minutes", "w10", ">=", 50),
    ("t5_40", "Top-5 buyers at most 40% of buying", "t5", "<=", 0.4),
    ("tgr_50", "Telegram bot-risk at most 50", "tgr", "<=", 50),
    ("hc1h_up", "Holder count rising in the last hour", "hc1h", ">", 0),
    ("liq_steady", "Liquidity not down more than 10% in the last hour", "liqc1h", ">=", -10),
    ("ob24_100", "At least 100 organic buyers in 24h", "ob24h", ">=", 100),
    ("bs24_1", "At least as many buys as sells over 24h", "bs24h", ">=", 1.0),
    ("nf24_pos", "Net buying over 24h", "nf24h", ">", 0),
    ("nfl_2", "Last hour's net buying at least 2% of liquidity", "nf1h_liq", ">=", 0.02),
    ("turn_3", "24h volume at most 3x market cap", "turn", "<=", 3.0),
    ("exit_5", "Selling $500 costs at most 5%", "exit", "<=", 5.0),
    ("dev_1", "Developer holds at most 1%", "dev", "<=", 1.0),
    ("rf_1", "At most 1 rug-study flag", "rf", "<=", 1),
    ("age_6h", "On a DEX for at least 6 hours", "age", ">=", 6),
    ("org_70", "Jupiter organic score at least 70", "org", ">=", 70),
    ("crowd_rug_half", "Under half of open crowd calls say rug", "crs", "<", 0.5),
    ("crowd_flags_0", "No 'bundled' or 'rug suspected' tags from the crowd", "cfl", "<=", 0),
    ("crowd_watch", "More 'worth watching' than 'avoid' votes", "cvn", ">", 0),
]

# ---- Second opinion and wallet clusters (added 20 Oct 2026) -----------------------------------------
# GoPlus Security's free Solana check (keyless, one token per call) re-reads the structure from a second source.
# Either source flagging a trap fails the structure gate, including an authority that could switch one on later
# (raise the transfer fee, add a transfer hook, make new accounts start frozen, change balances). GoPlus also says
# whether name, symbol and image can still be changed: shown and tested in the Lab, not gated, because many
# established coins keep that ability.
GP_BUDGET = 60                    # GoPlus calls per run, spent on tokens inside or about to enter
GP_TTL_H = 12                     # re-read GoPlus for a token this often
# RugCheck groups wallets linked by token transfers (InsightX and Bubblemaps draw the same groups as bubbles); the
# shared X routine skips a coin when one group holds 15% or more. It is shown and tested in the Lab, not gated: on
# 20 Oct 2026 it would have removed 5 of the 39 coins inside, two of them on groups of 2,000 and 8,665 wallets (the
# second "holding" 159% of supply), which look more like an exchange's or an airdrop's wallets than one team's. Set
# True to gate on it like the other holder checks once the Lab's shadow rule cluster_15 shows it helps.
MAX_CLUSTER_PCT = 15.0
GATE_ON_CLUSTER = False

# ---- Hourly tracker snapshots and storage (added 19 Oct 2026) ---------------------------------------
# Every tracked token, in or out of the screener, is snapshotted once an hour for TRACK_DAYS after its first entry:
# market cap, liquidity, volume, net buying, wallets, holders, top-10 share (Jupiter's, so one source runs through
# the whole series), organic score, liquidity / FDV, the multiple of the entry price and the screener state.
TSNAP_EVERY_MIN = 60
TSNAP_FULL_H = 72                 # hourly for the first 3 days after entry, then one snapshot per 6 hours
SNAP_BUCKETS = 8                  # the page loads a token's hourly snapshots from one of this many files
SNAP_KEEP_H = 36                  # per-run snapshots only feed 24-30h lookbacks (sparkline, holder growth, outflow)
TG_KEEP_DAYS = 8                  # Telegram member counts, for growth rates

# ---- Buy and sell signals (added 21 Oct 2026; undertow/trade.py says how a rule earns a live signal) ------------------
# Paper trades only. Every rule on the bench records what following it would have returned after costs on a usd-sized
# position; the live ledger is the record of the rules that earned it. fee_pct is a per-side allowance for pool,
# protocol and creator fees: PumpSwap charges 0.25% plus a creator fee that falls with market cap (0.95% under $300k,
# 0.05% above $20M), other venues 0.25% to 1%; a trading bot adds about 1% a side on top, which this leaves out.
# tx_usd is the network fee a transaction (base fee plus a modest priority fee). Price impact comes on top, from the
# pool's liquidity, so it is the one cost a smaller position shrinks. The ledger is kept at $100 a trade (it was $500
# until 22 Oct 2026; every recorded result was priced again at $100 then, scan.reprice_ledger), and the Buy & sell tab
# shows the same entries at each of sizes. A rule goes live only on its forward record (trades opened after it joined
# the bench): min_trades settled trades averaging at least min_edge % after costs with t >= z, in promote_after reviews
# in a row.
# A rule trades a coin at most once every reentry_h hours (and never while its last trade there is open), so one
# coin's readings cannot fill a rule's record. Coins are followed for follow_h hours after they leave the screener;
# the path is kept path_days, and paper trades keep_days (the live rules' trades for good).
TRADE = {"usd": 100, "fee_pct": 1.0, "tx_usd": 0.05, "sizes": (25, 100, 500), "reentry_h": 24, "follow_h": 48,
         "max_miss": 3, "liq_pull": 0.5, "path_days": 14, "window_days": 28, "keep_days": 60, "every_days": 7, "min_trades": 30, "min_edge": 1.0, "z": 2.0,
         "promote_after": 2, "retire_after": 2, "max_promotions": 1, "max_live": 2, "testing": 40, "add_per_review": 4,
         "stale_after": 6, "retest_after_days": 56, "switch_min_gain": 1.0, "switch_after": 2,
         "var_min_n": 300, "var_min_rho": 0.05, "var_retire_after": 3, "warn_gap": 2.0}


def _rule(rid, label, *conds):
    return {"id": rid, "label": label, "all": [list(c) for c in conds], "source": "pool"}


# Entry rules waiting to be tested, in order. Each condition is (variable, operator, threshold) on trade.VARIABLES; all
# must hold, on a coin that passes every gate. Price changes and the path variables are in %, dd24s is a fraction.
# The first ones are what lost least in the candle study (TRADE_STUDY): coins that had not just been pushed, with deep
# pools and low turnover. The rest test common ideas (breakouts, dips, flows, holders) the study could not settle or
# found losing, so the forward record can confirm or overturn it.
ENTRY_POOL = [
    _rule("unpushed_liquid", "Not pushed (under 15% off its 6h low), liquidity at least $100k", ("ru6", "<", 15), ("liq", ">=", 100_000)),
    _rule("unpushed_flat_busy", "Not pushed, flat over the hour (within 5%), volume at or above its usual pace",
          ("ru6", "<", 15), ("c1h", ">=", -5), ("c1h", "<=", 5), ("v1h_24", ">=", 1)),
    _rule("liquid_low_turnover", "Liquidity at least $100k, 24h volume at most half its market cap, not pushed",
          ("liq", ">=", 100_000), ("turn", "<=", 0.5), ("ru6", "<", 20)),
    _rule("old_liquid_calm", "A week old or more, liquidity at least $100k, swings under 3% a scan",
          ("age", ">=", 168), ("liq", ">=", 100_000), ("vola", "<", 3)),
    _rule("bigcap_unpushed", "Market cap $1m+, not pushed", ("mc", ">=", 1_000_000), ("ru6", "<", 15)),
    _rule("calm_liquid", "Calm and liquid: swings under 2.5% a scan, liquidity at least $100k", ("vola", "<", 2.5), ("liq", ">=", 100_000)),
    _rule("buyers_unpushed", "Buyers in charge: net buying, most traders net buyers, more buys than sells, not pushed, liquidity $50k+",
          ("nf1h", ">", 0), ("brd1h", ">=", 0.5), ("bs1h", ">=", 1), ("ru6", "<", 20), ("liq", ">=", 50_000)),
    _rule("holders_growing", "Holders rising, price up 0-10% in the hour, not pushed", ("hc1h", ">", 0), ("c1h", ">=", 0), ("c1h", "<=", 10), ("ru6", "<", 25)),
    _rule("organic_quiet", "Organic score 70+, not pushed, flat or up over the hour", ("org", ">=", 70), ("ru6", "<", 20), ("c1h", ">=", 0)),
    _rule("net_buy_deep", "Net buying at least 2% of liquidity in the hour, not pushed", ("nf1h_liq", ">=", 0.02), ("ru6", "<", 25)),
    _rule("unpushed_wild", "Not pushed but swinging hard (4%+ a scan): lottery tickets", ("ru6", "<", 15), ("vola", ">=", 4)),
    _rule("old_breadth", "A week old or more, 55%+ of traders net buyers, up over the hour", ("age", ">=", 168), ("brd1h", ">=", 0.55), ("c1h", ">", 0)),
    _rule("market_up_calm", "Market rising (half of candidates up over the hour), coin calm and not pushed",
          ("mkt1h", ">=", 0.5), ("vola", "<", 3), ("ru6", "<", 20)),
    _rule("flow6_old", "Net buying over 6h, two days old or more, not pushed", ("nf6h", ">", 0), ("age", ">=", 48), ("ru6", "<", 25)),
    _rule("quiet_since_high", "Its 24h high was 6h+ ago, now within 10% of its 6h high, swings under 2%",
          ("hi_h", ">=", 6), ("dd6", ">=", -10), ("vola", "<", 2)),
    _rule("tight_near_high", "Within 5% of its 6h high, swings under 2%", ("dd6", ">=", -5), ("vola", "<", 2)),
    _rule("few_flags_flat", "At most 1 rug-study flag, not pushed, flat or up over the hour", ("rf", "<=", 1), ("ru6", "<", 20), ("c1h", ">=", 0)),
    _rule("volume_before_price", "Volume at 2x its usual pace, price up 0-15% in the hour", ("v1h_24", ">=", 2), ("c1h", ">=", 0), ("c1h", "<=", 15)),
    _rule("steady_climb", "Steady climber: up over 24h and 6h, within 10% of its 6h high, swings under 4%",
          ("c24h", ">", 0), ("c6h", ">", 0), ("dd6", ">=", -10), ("vola", "<", 4)),
    _rule("dip_uptrend", "Dip in an uptrend: up 20%+ over 24h, 15-35% below its 6h high",
          ("c24h", ">=", 20), ("dd6", "<=", -15), ("dd6", ">=", -35)),
    _rule("early_breakout", "Early breakout: up 10-40% in the hour on 1.5x usual volume, under 60% off its 6h low",
          ("c1h", ">=", 10), ("c1h", "<=", 40), ("v1h_24", ">=", 1.5), ("ru6", "<", 60)),
    _rule("bounce", "Bounce: down 30%+ over 24h, up 5%+ in the hour, under 40% off its 6h low",
          ("c24h", "<=", -30), ("c1h", ">=", 5), ("ru6", "<", 40)),
    _rule("deep_pool_calm", "Liquidity at least 15% of market cap, swings under 3%", ("liq_pct", ">=", 0.15), ("vola", "<", 3)),
    _rule("momentum_unpushed", "Momentum score 70+, under 30% off its 6h low", ("mom", ">=", 70), ("ru6", "<", 30)),
    # queued for later reviews
    _rule("unpushed_liquid_old", "Not pushed, liquidity $100k+, three days old or more", ("ru6", "<", 15), ("liq", ">=", 100_000), ("age", ">=", 72)),
    _rule("unpushed_buying", "Not pushed, net buying over the hour, liquidity $50k+", ("ru6", "<", 15), ("nf1h", ">", 0), ("liq", ">=", 50_000)),
    _rule("low_turnover_up", "24h volume at most 1x market cap, swings under 3%, up over 6h", ("turn", "<=", 1), ("vola", "<", 3), ("c6h", ">", 0)),
    _rule("organic_bigcap", "Organic score 80+, market cap $500k+", ("org", ">=", 80), ("mc", ">=", 500_000)),
    _rule("ticking_up_calm", "Up since the last scan and over 3h, swings under 3%, not pushed",
          ("r15", ">", 0), ("r3h", ">=", 0), ("vola", "<", 3), ("ru6", "<", 20)),
    _rule("not_pushed_high", "Not pushed (under 15% off its 6h low) and within 25% of its 24h high", ("ru6", "<", 15), ("dd24s", ">=", -0.25)),
    _rule("holders_liquid", "Holders rising over 24h, liquidity $100k+, not pushed", ("hc24h", ">", 0), ("liq", ">=", 100_000), ("ru6", "<", 20)),
    _rule("market_up_liquid", "Market rising, liquidity $100k+, not pushed", ("mkt1h", ">=", 0.5), ("liq", ">=", 100_000), ("ru6", "<", 15)),
]
# Exit policies on the bench. Every paper trade is priced under each, so they are compared on the same entries.
# sl: stop (% below entry); tp: target (% above); trail: sell this far below the peak once up `arm`%; cool: after a
# push of this many %, sell on the first scan that falls cool_drop %; fade: sell after a fall of this many % in an hour;
# max_h: sell after this many hours whatever happens. In the candle study a +10% target sold within 8h lost least and
# stops on their own changed little at a 15-minute scan cadence, so most of the bench sells into strength.
EXIT_POOL = [
    {"id": "tp10_8h", "tp": 10, "max_h": 8}, {"id": "tp15_8h", "tp": 15, "max_h": 8}, {"id": "tp20_8h", "tp": 20, "max_h": 8},
    {"id": "tp10_4h", "tp": 10, "max_h": 4}, {"id": "tp10_24h", "tp": 10, "max_h": 24}, {"id": "tp20_24h", "tp": 20, "max_h": 24},
    {"id": "tp10_sl50_8h", "tp": 10, "sl": 50, "max_h": 8}, {"id": "tp10_sl15_24h", "tp": 10, "sl": 15, "max_h": 24},
    {"id": "hold4h", "max_h": 4}, {"id": "hold8h", "max_h": 8}, {"id": "hold24h", "max_h": 24},
    {"id": "tp30_sl25", "tp": 30, "sl": 25, "max_h": 24},
    {"id": "trail25_arm20", "trail": 25, "arm": 20, "sl": 30, "max_h": 24},
    {"id": "cool20_d5_8h", "cool": 20, "cool_drop": 5, "sl": 25, "max_h": 8},
    {"id": "fade20", "fade": 20, "sl": 30, "max_h": 24},
    # quick exits (added 21 Oct 2026), stepped every minute on the minute data between scans
    {"id": "q15m", "max_h": 0.25}, {"id": "q5_30m", "tp": 5, "max_h": 0.5},
    {"id": "q5_sl5_1h", "tp": 5, "sl": 5, "max_h": 1}, {"id": "q10_sl7_2h", "tp": 10, "sl": 7, "max_h": 2},
    {"id": "qtrail7_arm5_2h", "trail": 7, "arm": 5, "sl": 7, "max_h": 2},
]
DEFAULT_EXIT = "tp10_8h"
# Sell-side warnings: states that were followed by falls. Each review re-measures them on coins passing every gate.
SELL_WARNINGS = [
    {"id": "pushed30", "label": "Up 30% or more from its 6h low", "all": [["ru6", ">=", 30]]},
    {"id": "pushed60", "label": "Up 60% or more from its 6h low", "all": [["ru6", ">=", 60]]},
    {"id": "hot_hour", "label": "Up 20% or more in the last hour", "all": [["c1h", ">=", 20]]},
    {"id": "pushed_turning", "label": "Up 30% or more from its 6h low, and down since the last scan",
     "all": [["ru6", ">=", 30], ["r15", "<", 0]]},
    # attention (added 21 Oct 2026): is peak attention, or attention someone paid for, followed by falls?
    {"id": "boost_bought", "label": "DEX Screener boosts bought in the last hour", "all": [["bst_d1h", ">=", 1]]},
    {"id": "ad_bought", "label": "DEX Screener ad paid in the last 3 hours", "all": [["ad_new", ">=", 1]]},
    {"id": "trend_peak", "label": "Top 5 on GeckoTerminal's 5-minute trending list after a 30%+ push",
     "all": [["gtr5", ">=", 16], ["ru6", ">=", 30]]},
    {"id": "jup_trend_pushed", "label": "Top 20 on Jupiter's 1h trending list after a 30%+ push",
     "all": [["jtr", ">=", 81], ["ru6", ">=", 30]]},
    {"id": "x_spike", "label": "X followers jumping: last hour's growth 2+ points an hour above the day's",
     "all": [["xf_spike", ">=", 2]]},
]
# What the candle study behind the first bench found, shown on the Buy & sell tab. Replayed on GeckoTerminal's
# 5-minute candles for every coin the scanner had seen in range, each from the moment the scanner first saw it, priced
# once every 15 minutes as a scan would, with this file's costs.
TRADE_STUDY = {
    "period": "18 Oct 2026 16:45 to 21 Oct 2026 04:30 UTC",
    "sample": "493 coins in range, 31,309 readings 15 minutes apart, 2,293 sample entries (each coin's first reading in "
              "each 6-hour block)",
    "findings": [
        "Pushes cooled off. Coins up 30-60% from their 6-hour low fell 8.2% on average over the next 4 hours (median "
        "-9.0%, 68% no higher); up 60-100%, they fell 12.1% (74% no higher). Coins within 10% of their 6-hour low were flat "
        "(+0.4%, half higher). Coins that had tripled or more were lottery tickets: most fell (median -19.8%), a few "
        "kept running.",
        "No buy rule cleared costs. Nine entry rules, each tried with 15 exits, and 22 entry filters with a +20% "
        "target all lost money on average at $500 a trade. The least bad (coins not pushed, with $100k+ of "
        "liquidity or flat on busy volume) lost about 1.7-1.8% a trade with a +20% target sold within 8 hours.",
        "Costs decide most of it: at $500 a side cost a median 2.2% (a 1% allowance for fees plus price impact), so a round trip "
        "needs about +4.5% just to break even; at $100 it is about 2.5%.",
        "Selling into strength beat holding: a +10% target sold within 8 hours lost 5.4% a trade on the sample entries "
        "against 8.9% for holding 8 hours. Stops did little on their own (-8.7% with a 15% stop) and selling 15% "
        "below the peak (-7.2%) still trailed the target: at one price every 15 minutes, a stop fills after the drop.",
        "One market: the coins in range fell 13% on average over 24 hours in this window. Rules that lost here could "
        "work in a rising market, which is why the bench keeps testing them forward.",
    ],
}

# ---- Attention (added 21 Oct 2026; undertow/attention.py lists the sources and what each variable means) ---------
# Visitor counts for a project's website, X account or DEX Screener page are not published anywhere, so attention is
# read from what is public: paid DEX Screener boosts, ads, profiles and community takeovers; the trending ranks of
# GeckoTerminal (ranked on user engagement on its own site as well as trading) and Jupiter; X followers through a
# free mirror; Telegram members; and the age of the website's domain. Boosts and trending ranks come every scan for
# every candidate. The rest are read for coins inside the screener or close to passing: DEX Screener orders every
# orders_ttl_h hours, X hourly for coins inside (x_ttl_h for the others), a domain once (again after web_retry_days if
# the lookup failed), all within per-run budgets so a scan stays inside free limits.
ATTN = {"orders_ttl_h": 3, "orders_budget": 30, "x_ttl_h_in": 1, "x_ttl_h": 3, "x_budget": 40, "web_retry_days": 7,
        "web_budget": 15, "gt_pages_1h": 2, "gt_pages_5m": 1, "keep_days": 3}
# Candidate gates on attention, tested from the scan the data starts (outside the weekly intake, so the record starts
# now) and judged like every candidate: among coins passing every gate, did the ones a rule would remove rug more often?
ATTENTION_CANDIDATES = [
    ("attn_trending", "On GeckoTerminal's 1h trending list", "gtr", ">=", 1),
    ("attn_jup_trending", "On Jupiter's 1h trending list", "jtr", ">=", 1),
    ("attn_no_boost", "No paid DEX Screener boosts running", "bst", "<=", 0),
    ("attn_profile", "Paid for a DEX Screener profile", "dsp", ">=", 1),
    ("attn_links_2", "At least 2 links on its DEX Screener profile", "nlinks", ">=", 2),
    ("attn_x_1k", "At least 1,000 X followers", "xf", ">=", 1000),
    ("attn_x_growing", "X followers not falling over 6h", "xfg", ">=", 0),
    ("attn_tg_online", "At least 2% of Telegram members online", "tgo", ">=", 0.02),
    ("attn_domain_30d", "Website domain registered at least 30 days ago", "web_age", ">=", 30),
    ("attn_own_domain", "Website on its own domain, not a free host or link page", "web_free", "<=", 0),
    ("attn_domain_new", "Website domain bought for the launch, not older than the coin", "web_new", ">=", 1),
]
# Entry rules on attention, put on the Buy & sell bench the scan the data starts (outside the weekly intake).
ATTENTION_RULES = [
    _rule("trending_unpushed", "On GeckoTerminal's 1h trending list, not pushed (under 20% off its 6h low)",
          ("gtr", ">=", 1), ("ru6", "<", 20)),
    _rule("trend_new", "Joined GeckoTerminal's 1h trending list in the last hour, under 30% off its 6h low",
          ("trend_new", ">=", 1), ("ru6", "<", 30)),
    _rule("hot_5m_unpushed", "Top 10 on GeckoTerminal's 5-minute trending list, under 25% off its 6h low",
          ("gtr5", ">=", 11), ("ru6", "<", 25)),
    _rule("jup_trending_liquid", "Top 50 on Jupiter's 1h trending list, liquidity $50k+, not pushed",
          ("jtr", ">=", 51), ("liq", ">=", 50_000), ("ru6", "<", 20)),
    _rule("boosted_unpushed", "Paid DEX Screener boosts running, not pushed", ("bst", ">=", 1), ("ru6", "<", 15)),
    _rule("fresh_boost", "Boosts bought in the last hour, under 25% off its 6h low", ("bst_d1h", ">=", 1), ("ru6", "<", 25)),
    _rule("fresh_ad", "DEX Screener ad paid in the last 3h, under 25% off its 6h low", ("ad_new", ">=", 1), ("ru6", "<", 25)),
    _rule("x_growing", "X followers growing 0.5%+ an hour over 6h, 1,000+ followers, not pushed",
          ("xfg", ">=", 0.5), ("xf", ">=", 1000), ("ru6", "<", 20)),
    _rule("x_spike", "X followers jumping (last hour's growth 1+ point an hour above the day's), under 25% off its 6h low",
          ("xf_spike", ">=", 1), ("ru6", "<", 25)),
    _rule("tg_growing", "Telegram members growing 1%+ an hour, not pushed", ("tgg", ">=", 1), ("ru6", "<", 20)),
    _rule("quiet_liquid", "No attention: not trending on GeckoTerminal or Jupiter, no boosts, liquidity $100k+, not pushed",
          ("gtr", "<=", 0), ("jtr", "<=", 0), ("bst", "<=", 0), ("liq", ">=", 100_000), ("ru6", "<", 15)),
    _rule("own_domain_old", "Website on its own domain registered 30+ days ago, not pushed",
          ("web_free", "<=", 0), ("web_age", ">=", 30), ("ru6", "<", 15)),
    _rule("cto_liquid", "Community takeover on DEX Screener, liquidity $50k+, not pushed",
          ("cto", ">=", 1), ("liq", ">=", 50_000), ("ru6", "<", 15)),
]

# Rules on mid-sized pools (added 22 Oct 2026). Repriced at $100, the bench's entries on pools of $20k to $100k made
# +4.2% a trade before costs over 21-22 Oct (380 entries) and about +1% after costs, while deep pools lost before costs
# and $500 positions lost everywhere. These test that forward: the band on its own (a baseline), the band when the
# coin is not pushed, and the band when it has not just run up from its 30-minute low (the minute data's clearest
# pattern: short runs fall back). They join the bench at once, so their records start with them.
SIZE_RULES = [
    _rule("mid_pool", "Pool of $20k to $100k (the band's baseline)", ("liq", ">=", 20_000), ("liq", "<", 100_000)),
    _rule("mid_pool_unpushed", "Pool of $20k to $100k, not pushed (under 15% off its 6h low)",
          ("liq", ">=", 20_000), ("liq", "<", 100_000), ("ru6", "<", 15)),
    _rule("mid_pool_no_run", "Pool of $20k to $100k, not just run up (under 5% off its 30-min low)",
          ("liq", ">=", 20_000), ("liq", "<", 100_000), ("up30", "<", 5)),
]

# ---- Correlations (added 21 Oct 2026; undertow/corr.py) ---------------------------------------------------------
# Worked out once an hour from the Buy & sell path (every scan's reading of every coin passing every gate), one
# reading per coin per hour, so a coin's minute-by-minute readings do not count as independent evidence.
CORR = {"every_min": 60, "horizons_h": (1, 4, 12), "min_n": 200, "min_coins": 20, "z": 2.0, "min_rho": 0.05,
        # the minute data (corr.analyse_fast): one reading per coin every fast_every_min minutes, against the next 5,
        # 15 and 30 minutes, on coins that passed every gate at a scan no more than fast_stale_min minutes old
        "fast_horizons_min": (5, 15, 30), "fast_every_min": 15, "fast_stale_min": 45}

# ---- Models (added 21 Oct 2026; undertow/models.py says how they are trained and tested) ---------------------------
# A separate job (.github/workflows/train.yml) retrains every model every_h hours from the Buy & sell path; the scan
# scores every coin passing every gate with the latest models and opens a paper trade when a score is in the top
# top_share of what the training data scored. Walk-forward: test windows of at least fold_h hours tile the later half
# of the history, each trained only on trades that had closed before it opened (purging), so no training label reaches
# into a test window. Training starts at min_samples labelled samples on min_coins coins. The models' settled paper
# trades are kept keep_trade_days (they far outnumber the rules': about 60 a model a day, so 99 models open some 6,000
# a day; 14 days since 27 Oct, when the return twins took the count from 70 to 99), so a model's forward record covers
# its last 14 days while its profit and loss since it started keeps counting the pruned ones (store.pnl_carry); the
# training history is kept keep_days.
MODELS = {"every_h": 6, "min_samples": 1200, "min_coins": 40, "fold_h": 8, "min_train": 400, "min_test": 100,
          "keep_days": 60, "top_share": 0.2, "luck_draws": 200, "exit_every": 2, "max_exit_rows": 60_000,
          "seq_steps": 8, "max_age_h": 30, "exit_thr": 0.5, "keep_trade_days": 14,
          # the scan asks for a training run when GitHub has not run the schedule on time (scan.train_request): models
          # older than every_h + 1 hours, a collecting summary older than retry_collecting_h, at most once per ask_every_h
          "retry_collecting_h": 2, "ask_every_h": 1.5,
          # the rug model (27 Oct, models.train_rug): does a coin passing every gate lose half its liquidity
          # (rug_liq of the reading's) within rug_h hours? Its filter keeps a coin out when the score is in the top
          # rug_share of what the training data scored. On the path to 27 Oct (9,167 readings on 436 coins, 295 of them
          # pulled) a random forest scored AUC 0.954 out of sample, 0.948 with every test coin unseen in training; at
          # 15% it kept out 16% of readings with 93% of their rugs, and the readings it kept averaged -4.1% after costs
          # against -16.5% for those it kept out (-6.1% for all). Age alone scores 0.94: most of what it knows is that
          # a coin a few hours old is the one likely to collapse.
          "rug_h": 8, "rug_liq": 0.5, "rug_share": 0.15}
# The variable sets the algorithms are trained on, so the page can show what each set adds. The last four (24 Oct)
# take apart the set the best forward record came from (attention and the price path): the price path alone,
# attention alone, the two with the pool's size, and the price path with the minute data. They train the algorithms
# in MODEL_SET_ALGOS, one of each family, the LSTM and a return model, rather than all fifteen: each extra model adds
# to the luck any one of them can show, and fifteen close relatives answer the same question as six. On 25 Oct each
# set gained the return twins of its win-or-lose models (models.PAIRS): does training on the return, which counts a
# rug's loss in full, beat training on whether the trade wins?
MODEL_SETS = {"all": "every variable", "no_attention": "every variable except attention",
              "attention_price": "attention and the price path only",
              "price": "the price path only", "attention": "attention only",
              "attention_price_size": "attention, the price path and the pool's size",
              "minute_price": "the price path with the minute data"}
MODEL_SET_ALGOS = {k: ("logit", "rf", "lgbm", "mlp", "lstm", "lgbm_ret",
                       # 25 Oct: the return twins of those five, so every family has both labels on every set
                       "ridge", "rf_ret", "lgbm_l2", "mlp_ret", "lstm_ret")
                   for k in ("price", "attention", "attention_price_size", "minute_price")}
# What the offline study of the algorithms found before the first training run (tools/study/study_ml.py), shown on the
# Models tab.
ML_STUDY = {
    "period": "18 Oct 2026 16:45 to 20 Oct 2026 20:15 UTC",
    "sample": "7,476 sample entries on 419 coins (each coin's first reading in each hour) replayed on GeckoTerminal's "
              "5-minute candles, in 4 walk-forward folds; 44% of the sample trades made money after costs, averaging "
              "-5.3%. Attention was not recorded yet, so the study used the market and price variables only",
    "findings": [
        "The models found ranking signal that random scores did not: random forest ranked winners above losers with an "
        "out-of-sample AUC of 0.673, gradient boosting, XGBoost and LightGBM 0.666-0.667 and logistic regression 0.627, "
        "against 0.498 for random scores.",
        "None of it paid after costs. Every model's top fifth of picks still lost money on average: gradient boosting "
        "-3.7% a trade and random forest -4.5%, against -5.1% for all test trades. Models of the return itself came "
        "closest: random forest on returns averaged -0.7% on 1,173 trades (t -1.1), still a loss.",
        "Boosted trees overfit most: training AUCs of 0.89-0.97 against about 0.67 out of sample, which is why every tree "
        "model here is shallow with large leaves. k nearest neighbours memorised its training set (training AUC 1.000) "
        "and made no picks out of sample; naive Bayes, the neural network and the LSTM ranked worse (0.56-0.60).",
        "Exit models did not beat a +10% target sold within 8 hours: following them changed the average by -0.20 to "
        "+0.18 points a trade (t under 1) on 5,989 trades.",
        "So ranking beats chance, but the edge found so far is smaller than the 4-5% a round trip costs at $500. A model "
        "earns a live signal only if its forward picks clear those costs; on this evidence the likeliest result is that "
        "they will not, and the tab will show it either way.",
    ],
    # every algorithm's out-of-sample result in the study (k nearest neighbours used distance weights then, which made
    # it score its own training labels and pick nothing; the live models use uniform weights)
    "entry": [
        {"algo": "Logistic regression", "auc": 0.627, "auc_sd": 0.049, "train_auc": 0.694, "accuracy": 0.606, "balanced_acc": 0.589,
         "brier": 0.239, "picks": 709, "pick_win": 0.595, "pick_net": -7.57, "pick_t": -3.4, "base_net": -5.14},
        {"algo": "Random forest", "auc": 0.673, "auc_sd": 0.067, "train_auc": 0.809, "accuracy": 0.642, "balanced_acc": 0.636,
         "brier": 0.227, "picks": 631, "pick_win": 0.681, "pick_net": -4.45, "pick_t": -2.6, "base_net": -5.14},
        {"algo": "Extra trees", "auc": 0.649, "auc_sd": 0.07, "train_auc": 0.717, "accuracy": 0.621, "balanced_acc": 0.613,
         "brier": 0.235, "picks": 631, "pick_win": 0.664, "pick_net": -5.38, "pick_t": -2.7, "base_net": -5.14},
        {"algo": "Gradient boosting", "auc": 0.667, "auc_sd": 0.047, "train_auc": 0.891, "accuracy": 0.628, "balanced_acc": 0.621,
         "brier": 0.232, "picks": 717, "pick_win": 0.66, "pick_net": -3.71, "pick_t": -2.7, "base_net": -5.14},
        {"algo": "XGBoost", "auc": 0.666, "auc_sd": 0.042, "train_auc": 0.936, "accuracy": 0.625, "balanced_acc": 0.619,
         "brier": 0.237, "picks": 714, "pick_win": 0.629, "pick_net": -5.07, "pick_t": -3.6, "base_net": -5.14},
        {"algo": "LightGBM", "auc": 0.666, "auc_sd": 0.038, "train_auc": 0.973, "accuracy": 0.628, "balanced_acc": 0.621,
         "brier": 0.242, "picks": 582, "pick_win": 0.637, "pick_net": -5.01, "pick_t": -3.2, "base_net": -5.14},
        {"algo": "k nearest neighbours", "auc": 0.603, "auc_sd": 0.045, "train_auc": 1.0, "accuracy": 0.565, "balanced_acc": 0.56,
         "brier": 0.242, "picks": 0, "pick_win": None, "pick_net": None, "pick_t": None, "base_net": -5.14},
        {"algo": "Naive Bayes", "auc": 0.56, "auc_sd": 0.067, "train_auc": 0.658, "accuracy": 0.552, "balanced_acc": 0.535,
         "brier": 0.35, "picks": 1045, "pick_win": 0.505, "pick_net": -7.68, "pick_t": -4.8, "base_net": -5.14},
        {"algo": "Neural network (MLP)", "auc": 0.56, "auc_sd": 0.092, "train_auc": 0.69, "accuracy": 0.551, "balanced_acc": 0.547,
         "brier": 0.281, "picks": 1033, "pick_win": 0.533, "pick_net": -5.1, "pick_t": -4.1, "base_net": -5.14},
        {"algo": "LSTM (8 scans)", "auc": 0.597, "auc_sd": 0.089, "train_auc": 0.673, "accuracy": 0.56, "balanced_acc": 0.561,
         "brier": 0.243, "picks": 1061, "pick_win": 0.529, "pick_net": -5.27, "pick_t": -4.6, "base_net": -5.14},
        {"algo": "Random scores (control)", "auc": 0.498, "auc_sd": 0.015, "train_auc": 0.52, "accuracy": 0.497, "balanced_acc": 0.497,
         "brier": 0.333, "picks": 1216, "pick_win": 0.431, "pick_net": -5.8, "pick_t": -6.4, "base_net": -5.14},
        {"algo": "Ridge regression", "ic": 0.008, "train_ic": 0.187, "picks": 1563,
         "pick_win": 0.335, "pick_net": -2.97, "pick_t": -4.5, "base_net": -5.14},
        {"algo": "Random forest (return)", "ic": 0.04, "train_ic": 0.307, "picks": 1173,
         "pick_win": 0.435, "pick_net": -0.72, "pick_t": -1.1, "base_net": -5.14},
        {"algo": "Gradient boosting (return)", "ic": 0.125, "train_ic": 0.455, "picks": 677,
         "pick_win": 0.669, "pick_net": -3.61, "pick_t": -2.1, "base_net": -5.14},
        {"algo": "XGBoost (return)", "ic": 0.075, "train_ic": 0.682, "picks": 739,
         "pick_win": 0.602, "pick_net": -3.58, "pick_t": -2.5, "base_net": -5.14},
        {"algo": "LightGBM (return)", "ic": 0.044, "train_ic": 0.407, "picks": 803,
         "pick_win": 0.578, "pick_net": -2.9, "pick_t": -2.3, "base_net": -5.14},
    ],
    "exit": [
        {"algo": "Logistic regression", "auc": 0.547, "train_auc": 0.627, "accuracy": 0.524,
         "trades": 5989, "net": -5.1, "base_net": -5.14, "gain": 0.05, "gain_t": 0.2},
        {"algo": "Random forest", "auc": 0.579, "train_auc": 0.832, "accuracy": 0.556,
         "trades": 5989, "net": -4.97, "base_net": -5.14, "gain": 0.18, "gain_t": 0.6},
        {"algo": "Gradient boosting", "auc": 0.561, "train_auc": 0.897, "accuracy": 0.55,
         "trades": 5989, "net": -5.07, "base_net": -5.14, "gain": 0.07, "gain_t": 0.2},
        {"algo": "LightGBM", "auc": 0.56, "train_auc": 0.949, "accuracy": 0.546,
         "trades": 5989, "net": -5.29, "base_net": -5.14, "gain": -0.15, "gain_t": -0.4},
        {"algo": "Neural network (MLP)", "auc": 0.555, "train_auc": 0.85, "accuracy": 0.539,
         "trades": 5989, "net": -5.34, "base_net": -5.14, "gain": -0.2, "gain_t": -0.6},
    ],
}

# ---- Minute data and quick trades (added 21 Oct 2026; undertow/fast.py reads, undertow/minute.py works out) -------
# A sampler reads DEX Screener every every_s seconds for up to max_coins coins (inside the screener, entering, passing
# at some scan in the last watch_recent_h hours, or holding a paper trade) while each scan works out its gates, and
# every slow_every rounds GeckoTerminal's 5-minute trending list and DEX Screener's boosts and ads feeds. Every open
# paper trade is stepped on those minutes, and the quick rules below may buy coins that passed every gate at the
# previous scan (whose gates were known by then), provided that scan is no more than stale_scan_min minutes old. A
# quick rule buys a coin again only once its last trade on it has closed and reentry_min minutes have passed since it
# bought. Quick rules trade only pools holding min_liq dollars or more: at $500 a side, a round trip costs about 4.6%
# at $75k (fees plus price impact), so a +5% target barely breaks even there and loses below it (at $20k a +10% target
# still loses 2%). The floor was set when the ledger was kept at $500; at $100 the same round trip costs about 2.6%. Quick exits are compared on quick trades against baseline_exit. Minute readings are kept keep_h
# hours, feed entries feed_keep_days days. A scan rule's buy fills at the scan's decision time at the coin's latest
# minute price, if that price is no more than fill_lag_s seconds old (else at the scan's own reading).
FAST = {"every_s": 60, "slow_every": 2, "max_coins": 240, "watch_recent_h": 2, "keep_h": 24, "feed_keep_days": 7,
        "stale_scan_min": 45, "reentry_min": 30, "baseline_exit": "q5_sl5_1h", "min_liq": 75_000, "fill_lag_s": 180}


def _quick(rid, label, exit_id, *conds, random=None):
    r = {**_rule(rid, label, *conds, ("liq", ">=", FAST["min_liq"])), "fast": True, "exit": exit_id,
         "source": "quick rule, minute data"}
    if random:
        r["random"] = random
    return r


# Quick entry rules, checked every minute on coins that passed every gate at the previous scan and hold min_liq in their
# pool. Each is judged on its own exit (quick ones, 30 minutes to 2 hours), on trades it made after joining the bench,
# against the same bar as every rule. fast_random buys a random 0.5% of coin-minutes on the same coins (about 10
# trades an hour): what any quick entry has to beat. Changing a quick rule here redefines it on the bench and restarts
# its record (trade.sync_rules), as long as it is still under test.
FAST_RULES = [
    _quick("fast_breakout", "Quick breakout: up 3%+ in 5 min on 2x the hour's volume pace, buyers ahead, under 25% off "
           "its 30-min low", "q10_sl7_2h", ("m5", ">=", 3), ("v5x", ">=", 2), ("bs5", ">=", 1.2), ("up30", "<", 25)),
    _quick("fast_trend_climb", "Climbing GeckoTerminal's 5-min trending list (5+ places in 15 min), not falling, under "
           "20% off its 30-min low", "q5_sl5_1h", ("gtr5_d15", ">=", 5), ("m5", ">=", 0), ("up30", "<", 20)),
    _quick("fast_boost_fresh", "Boosts bought in the last 15 min, under 15% off its 30-min low", "q5_30m",
           ("bst_d15", ">=", 1), ("up30", "<", 15)),
    _quick("fast_dip_buy", "Dip turning: 10%+ under its 30-min high, up since the last minute, buyers at least even",
           "q5_sl5_1h", ("dn30", "<=", -10), ("m1", ">", 0), ("bs5", ">=", 1)),
    _quick("fast_quiet_accum", "Quiet accumulation: flat over 15 min (within 2%), 5-min volume 1.5x the hour's pace, "
           "1.5 buys per sell", "q10_sl7_2h", ("m15", ">=", -2), ("m15", "<=", 2), ("v5x", ">=", 1.5), ("bs5", ">=", 1.5)),
    _quick("fast_momentum", "Momentum: up 5%+ in 15 min and still rising, volume 1.5x the hour's pace, under 30% off "
           "its 30-min low", "qtrail7_arm5_2h", ("m15", ">=", 5), ("m5", ">=", 1), ("v5x", ">=", 1.5), ("up30", "<", 30)),
    _quick("fast_ad_running", "A DEX Screener ad seen in the last day, under 15% off its 30-min low", "q5_sl5_1h",
           ("ad_imp", ">=", 1), ("up30", "<", 15)),
    _quick("fast_random", "Random control: a random 0.5% of minutes on coins passing every gate, pools of $75k+",
           "q5_sl5_1h", random=0.005),
]
