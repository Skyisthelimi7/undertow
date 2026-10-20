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
PACE = {"geckoterminal": 2.2, "dexscreener": 1.1, "rugcheck": 1.1, "telegram": 0.8, "jupiter": 2.1, "rpc": 0.6,
        "goplus": 1.0}
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

# Entry tracker. GeckoTerminal's free candles only reach back 24 hours, so tracked tokens are polled at least
# hourly; a gap longer than a day loses that day's highs.
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
# rules retired at least retest_after_days ago.
REVIEW = {"every_days": 7, "window_days": 28, "min_group": 30, "min_flat": 100, "min_diff": 0.05, "z": 2.5,
          "flat_diff": 0.03, "flat_z": 1.0, "drop_after": 2, "promote_after": 2, "max_drops": 1, "max_promotions": 1,
          "min_keep": 0.5, "testing": 30, "add_per_review": 4, "retest_after_days": 56}
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
