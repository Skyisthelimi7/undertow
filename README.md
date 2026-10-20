# Undertow: a free, gated screener for Solana tokens

Scans Solana tokens trading on DEX pools, from every launchpad (pump.fun, StonkFun, Meteora DBC, LetsBonk, Bags,
Moonshot and others) and straight-to-DEX launches on PumpSwap, Raydium, Meteora and Orca. It applies a fixed set of
gates, tracks every token from the moment it first passes them, and publishes a single web page: a treemap sized by
float cap, a gate checklist and rug-risk panel per token, a demand and exit read-out, a tracker of entry vs live vs
ATH with an hourly snapshot of every tracked token, a Lab that scores which variables separate risers from fallers,
and a waiting room for tokens that fall out. Every week it reviews its own gates against what happened next, drops
the ones that make no difference, and tests new rules. Signed-in visitors can call rugs on a public scoreboard,
vote and tag tokens; the crowd is shown beside the gates and never changes them. Everything runs on free data.
Python 3.9+, standard library only.

## Run it

    python3 -m undertow.scan run --db undertow.db --out docs/data.json    # also writes the CSVs and docs/snap/
    python3 build_page.py docs/index.html                                 # page that reads data.json beside it
    python3 build_page.py docs/index.html --embed docs/data.json          # ... or one file that also opens offline
    python3 -m undertow.scan inspect <MINT>                               # gate report for one token
    python3 -m unittest discover -s tests

A token needs `ENTER_SCANS` (2) clean scans in a row to enter, so the map is empty until the second run. A run
takes 7 to 10 minutes on free rate limits, most of it waiting on GeckoTerminal; the first run of each hour also
walks GeckoTerminal's per-DEX pool lists, which adds about 5 minutes. Run it every 20 minutes to an hour (below).
Open `docs/index.html` from any web host: it loads `data.json` from its own folder, re-reads it every 5 minutes, and
shows when the last scan ran and whether the next one is overdue. A copy built with `--embed` also opens from disk.

## Keeping it live

The live page is **https://skyisthelimi7.github.io/undertow/**. Two pieces keep it live:

* **GitHub Actions rescans every 20 minutes, free.** `.github/workflows/scan.yml` runs the scan, builds the page and
  deploys it to GitHub Pages. It uses no Claude usage and no paid service. See Free hosting.
* **The browser refreshes prices every 5 seconds.** Wherever the page may call other sites (GitHub Pages, any web
  host, a copy opened from disk), it asks DEX Screener for prices: tokens on the map first, then every tracked token
  in turn. Market caps, price changes, tile colours, the tracker's "now" and ATH columns and the open X-ray update in
  place; gates, holders and the hourly snapshots come from the last scan, and the stamp says so ("Live prices · 3 s
  ago · gates checked 15:40 UTC"). DEX Screener's CDN keeps each answer for 30 seconds, so the page asks for a fresh
  one (a 5-second bucket in the query string); without that, the same prices came back for half a minute at a time.
  A failed call switches to Jupiter's price feed and back, backing off from 2 seconds to a minute, for as long as the
  page is open; if neither answers (a content blocker or network filter), the stamp says that instead of going quiet.

A claude.ai Artifact cannot call other sites, so a copy published there is a snapshot that links to the live page.
`undertow/cloud.py` can still keep such a copy updating from a Claude scheduled task (it reads the code and the
SQLite file, packed as gzip+base64 shards, from the Artifact itself, scans once, reviews the output and republishes),
but each run is a full Claude session that counts toward your plan's usage, and an hourly task is the fastest it can
go. GitHub does the same job every 20 minutes for nothing.

## Optional settings (environment variables)

| Variable | Effect |
| --- | --- |
| `JUP_API_KEY` | Free key from Jupiter's developer portal; doubles Jupiter's keyless limit (0.5 to 1 request a second) |
| `SOLANA_RPC_URL` | Your own RPC endpoint (a free tier from any provider works). Default: Solana's public mainnet RPC |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Posts each entry and exit, and the weekly review's changes, to your Telegram channel. Without them alerts are only printed |
| `SUPABASE_SECRET_KEY` | Lets the scan list callable tokens in Supabase and price and settle rug calls (Rug calls, below). Without it the community features stay paused |

## Scope

Any Solana token on a DEX pool with a market cap from $20k to $20m and at least $20k of 24h volume, in four bands:
$20k–100k, $100k–1m, $1m–10m and $10m–20m. Coins still on a launchpad bonding curve are out until they reach a
pool. Stablecoins, liquid-staking tokens, tokenised stocks and tokenised gold are excluded by Jupiter tag. Market cap and volume
are scope and liveness filters, not safety checks: the rug study (below) found the $20k floor picks the riskiest
coins in their first hours, and the volume floor is neutral for rugs.

Discovery: Jupiter's category lists (top trending, top traded, top organic score and recent, 100 tokens each) every
run, and GeckoTerminal's pool lists for PumpSwap, Raydium (AMM and CLMM), Meteora (DLMM and DAMM v2) and Orca once
an hour. Everything seen stays in the universe for `UNIVERSE_TTL_DAYS` and is re-priced every run.

## What it checks

Gates come in four groups. Every threshold is in `undertow/config.py`.

* **Structure** (one failure removes a token): trading on a DEX pool, not a bonding curve; mint and freeze
  authority revoked (read from the chain); no permanent delegate, live transfer hook, pause, frozen-by-default or
  non-transferable extension, no authority that could switch one on later or raise the transfer fee, and no transfer
  fee over 5%; liquidity burned or locked; not flagged rugged. GoPlus Security's free Solana check re-reads the
  authorities and Token-2022 settings for tokens inside or close to passing (every 12 hours, 60 calls a run), and
  either source flagging a trap fails the gate.
  The lock is read for the pool the screener prices. A graduation pool from a launchpad that burns or locks its LP
  by design (pump.fun, Raydium LaunchLab and LetsBonk, StonkFun) passes on that basis; otherwise the figure comes
  from RugCheck for that pool, then GeckoTerminal. Meteora DBC pools need a figure, because DBC configs can leave LP
  claimable. A concentrated pool (CLMM, DLMM, Whirlpool) with no lock evidence fails: its providers can withdraw.
* **In range and alive** (two failed scans remove it): market cap, 24h volume, last-hour volume and wallets, and at
  least $50 sold in the last hour (buy-only flow is a farm pattern).
* **Rug risk** (two failed scans): out of its first 60 minutes on a DEX; no more than 3 of the study's six red flags,
  for coins inside what the study measured; liquidity; exit cost of a $500 position; plausible volume; Jupiter
  organic score not low and no Jupiter suspicious flag; not in free fall; developer and top holders not selling;
  Telegram bot-risk.
* **Holder structure** (two failed scans): top-10 concentration (pools, lockers, burn and exchanges removed),
  developer holding, linked wallets, bundle signature. For a launchpad graduate under a day old and under $1m FDV
  they are shown, not gated, because the study found no rug signal in them there; everywhere else they gate, since
  the study says nothing about older or larger coins (`HOLDER_GATES_FOR_LAUNCHPADS` makes them gate everywhere).

Shown but not gated: net buying for 1h, 6h and 24h, wallets trading and the share that are net buyers, holder
change, organic buyers, deployer launch history, whether name and image can still be changed (GoPlus), momentum
score and momentum quality, the rug-risk panel, and the largest wallet cluster: the biggest group of wallets
RugCheck links by token transfers (what InsightX and Bubblemaps draw as one bubble group), marked when it holds 15%
of supply or more. The cluster stays ungated until the Lab shows it helps: on 20 Oct 2026 it would have removed 5 of
the 39 coins inside, two of them on groups of 2,000 and 8,665 wallets (the second "holding" 159% of supply), which
look more like an exchange's or an airdrop's wallets than one team's (`GATE_ON_CLUSTER` switches it on). The Lab tests three rules from a
free rug-check routine shared on X as shadow rules before any of them gates: largest cluster at most 15%, metadata
locked, and a deployer with at most 10 launches. SolSniffer's score and InsightX's cluster API need paid keys at a screener's volume (SolSniffer's
free plan is 100 calls a month), so the X-ray links to both sites and copies the deployer wallet for SolSniffer's
wallet check instead.

## The rug study's signals

From a study of 9,467 early Solana tokens (10–29 June 2026, mostly pump.fun coins minutes after graduation). A rug
there means the price closed 80% below entry before it ever traded 50% above it, within a day.

* **Liquidity ÷ FDV ("dump headroom").** Twice the pool's share of supply in a constant-product pool. If every
  other holder sold, the price would end at the square of that share: −96% at 0.41, −80% at 0.9, −75% at 1.0. Below
  0.9 the study saw 41.6% rugs, at or above it 3.6%. A pump.fun coin starts on PumpSwap at about 0.41 and the ratio
  then depends on its price, so it reaches 0.9 only below about $9k FDV (at a SOL price near $105): almost every
  pump.fun coin in this scope is "red". The screener therefore shows the dial and the worst case, counts the ratio
  as one red flag, and does not gate on it.
* **Six red flags** (thresholds chosen in-sample, scored out of sample): L/FDV under 0.97, over 98 wallets trading
  in 10 minutes, sells under 33% of recent volume, younger than 4.6 minutes, over 103 holders, top-5 buyers under
  21% of buy volume. Out of sample, 0 flags rugged 0.0%, 2 flags 13.1%, 4 flags 44.2%, 6 flags 59.1%; doubling
  stayed between 17% and 35% at every count. The count gates (at most 3) and the rates are shown only for coins
  under 24 hours old and under $1m FDV, which is what the study covered. Even there they are a guide: the study's
  coins were mostly minutes old, while past the first hour (which the age gate requires) the age flag cannot fire
  and the holder flag nearly always does.
* **First hour and two-way trading** became gates (74% of the study's rugs finished within an hour; buy-only flow
  under $50 sold in the last hour marked dead coins).
* Wallet counts and top-5 buyer share come from GeckoTerminal's last 300 trades for a pool, fetched each run for up
  to 30 coins inside the study's range that are in the screener or close to passing. For a busy coin those trades
  can cover less than 10 minutes, so the wallet count is scaled up and marked as estimated.

## The tracker

The first time a token passes every gate, the scanner records the time, price and market cap. From then on it
follows the token for `TRACK_DAYS` (14), in or out of the screener: live market cap every run, the ATH since entry
(with its time) from GeckoTerminal's 5-minute candles, the worst point since entry, the multiple of the entry price
at +1h, +6h, +24h and +7d, and whether it rugged or doubled on day one by the study's definitions.
`tracker.csv` adds the gate and study values each token had when it entered: the dataset you need to test whether
the thresholds hold on the screener's own picks.

Once an hour the scanner also snapshots every tracked token, in or out of the screener: market cap, liquidity,
volume (1h, 6h, 24h), price change, buys per sell, net buying, wallets trading and the share that net-bought,
holders and their change, top-10 share, organic score, liquidity / FDV, the multiple of the entry price, the screener
state and which gates it was failing. Holders and top-10 share come from Jupiter in every snapshot, so a series
never switches source halfway. Snapshots are hourly for the first `TSNAP_FULL_H` (72) hours after entry, then one
every 6 hours to day 14. The tracker's "Hour by hour" view lines every token up at its entry: a chart of each
token's multiple by hours since entry with the median and middle half, the share above entry at +1h, +3h, +6h,
+12h, +24h, +48h, +72h and +7d, and a side-by-side grid. Each token's X-ray adds its numbers at entry, +1h, +6h,
+24h and now, a small chart per variable and every snapshot. `snapshots.csv` has every row.

## The Lab: what separates risers from fallers

Passing every gate removes traps; it does not make a token rise. To learn what does, the scanner checks every
candidate once an hour and records an observation for every entry and exit as it happens: the price and about 45
variables (`undertow/lab.py`, `VARIABLES`), plus the result of each shadow rule (`SHADOW_RULES` in the config: candidate
gates that are recorded but never applied). Every later run folds the new price into the open observations: the
multiple at +1h, +6h and +24h, the 24h high and low, and the first time it reached +10/20/30/50/100% or fell
10/20/30/50/80%.

The Lab view and `observations.csv` turn that into evidence, in three views (each token's first entry; one
observation per token per day while it passed every gate; one per token per day for every candidate):

* **Variables**: AUC (0.5 is a coin flip), rank correlation, the share that rose in each fifth, and the single line
  that gave the most risers in the earlier half of the data, scored on the later half.
* **Shadow rules**: the share that rose with and without each rule, in both halves.
* **Exit rules**: every take-profit and stop pair on the grid against holding for 24 hours.

Verdicts stay "collecting" until a view has `LAB["min_n"]` (60) observations with an outcome. A variable "works" when
its AUC is more than 2.5 standard errors from 0.5 and its line holds on later data; a shadow rule "helps" when a
two-proportion test clears 2.5 standard errors and the lift holds in both halves (2.5 rather than 1.96, because
dozens of variables and rules are tested at once). At 60 observations only differences of about 25 points can show;
telling a 10-point improvement from luck needs about 400. Only the observations the Lab reads are stored (each
token's first of the day, its first passing one, entries and exits), so the history stays small enough to carry
between runs. Each observation also records every gate's own result, gating or not, which is what the weekly review
reads.

## The weekly gate review: which gates stay, which go, what to test next

Every 7 days (`REVIEW` in the config, `undertow/review.py`) the scan judges each gate and each candidate rule on the
last 28 days of observations, against two outcomes from the rug study: rugged (fell 80% below the observed price
before it ever traded 50% above it, within a day) and reached +50% within a day.

* **Gates** are judged on the coins each one alone blocked, against the coins that passed every gate. *Protects*:
  its coins rugged at least 5 points more often (2.5 standard errors). *Costs*: its coins reached +50% clearly more
  often without rugging more, or rugged clearly less. *No effect*: at least 100 settled coins on each side and rug
  rates within 3 points. *Collecting*: fewer than 30 settled coins on either side. Otherwise *unclear*.
* **Dropping and restoring.** Two reviews in a row of "no effect" or "costs" drop a rug-risk or holder gate. A
  dropped gate is still computed and shown, marked "not gated" with the date and the reason, and two reviews in a row
  of "protects" bring it back. At most one gate is dropped and one restored per review. The structure gates (a live
  mint authority, a pullable pool) and the scope gates never change automatically: a rug rate cannot judge a
  mechanism, and scope decides which coins are assessed at all. `PINNED_GATES` protects others.
* **New variables.** A bench of up to 30 candidate rules is tested on the coins that passed every gate: the shadow
  rules first, then `CANDIDATE_POOL` (20 more, from cluster size and sell pressure to organic buyers and the crowd),
  then lines the Lab finds itself (a variable whose best line on the earlier half of the data held on the later
  half). A new rule is judged at once on the stored observations. Two reviews in a row of "would protect" promote it
  to a rug-risk gate, provided it keeps at least half the passing coins; two of "no effect" or "would cost" retire it
  and the next rule takes its place, at most four new ones a week. A promoted rule is re-judged weekly on the coins
  that passed everything else and is removed the same way; it never blocks a token for a missing value. A rule still
  collecting after 6 reviews (it removes almost no passing coin, or almost all) gives up its place. Retired rules
  come back for another test after 8 weeks, once the queue is empty, since thresholds drift with the market.
  Rules on the crowd's calls, votes and tags, and on figures the scan computes after the gates, are tested but can
  never gate.

The Lab view's "Weekly gate review" table shows each gate's verdict with its numbers, every rule under test, and a
log of each change and why it happened; changes are also posted to Telegram when alerts are set up. Expect
"collecting" for most gates in the first weeks: a gate needs 30 settled coins that it alone blocked, and most gates
rarely block a coin on their own.

## Rug calls, votes and tags

From a token's X-ray, signed-in visitors can:

* **Call it**: "rugs within 24h" or "holds 24h". A call is priced at the next scan, so nobody calls with hindsight,
  and settles 24 hours later on the study's definition. Points use r, the share of passing coins that rugged within a
  day over the last fortnight: a right rug call scores (1 − r) / r and a wrong one −1; a right hold call +1 and a
  wrong one −(1 − r) / r. Guessing at the base rate scores nothing on average, so the Callers scoreboard ranks skill,
  not activity (from 5 settled calls). Ten calls a day, one open call per token, no cancelling; until a call settles
  only the counts are public, not who made it; a token that stopped being priced for the last quarter of its day
  voids the call.
  Points only: no money, stakes or prizes.
* **Vote** "worth watching" or "avoid", and **tag** it: dev active, real community, community takeover, bundled, rug
  suspected, fake volume. Fixed tags rather than free-text comments keep moderation small.

The crowd never touches the gates. Its counts are shown beside them and recorded as Lab variables (the share of open
calls saying rug, open calls, net votes, bad tags), so the weekly review can test whether the crowd predicts
anything; a crowd that could gate a token could be organised to, so those rules are never promoted.

Sign-in is by emailed link (or X, once switched on), never a wallet. Everything lives in a free Supabase project:
`supabase/schema.sql` creates the tables, row-level security and the four functions that are the only way a visitor
can write (pick a name, call, vote, tag). The scan, holding the secret key, lists the callable tokens and prices and
settles calls. Public names are visitors' own words: rename or delete one in Supabase's Table Editor (`profiles`).

Setting it up, once:

1. Supabase → SQL Editor → New query: paste `supabase/schema.sql` and run it (confirm the prompt about destructive
   operations: it only drops and recreates its own policies). Until then the page is the plain screener. The
   Security Advisor will flag the three views as security definer views; that is deliberate, since they publish
   counts that row-level security hides row by row, and they expose no user ids, emails or open calls.
2. Authentication → URL Configuration: set the Site URL to `https://skyisthelimi7.github.io/undertow/` and add the
   same address under Redirect URLs, so sign-in links come back to the page.
3. GitHub → Settings → Secrets and variables → Actions → New repository secret: `SUPABASE_SECRET_KEY`, set to the
   secret key from Supabase → Settings → API Keys (it starts `sb_secret_`). It stays in GitHub; the page uses only
   the publishable key in `config.py`. Until this is set, calls are paused and the X-ray says so.
4. Email for everyone else: Supabase's built-in mailer delivers only to members of your Supabase team, at about 2
   emails an hour. Before inviting the public, add custom SMTP (Authentication → SMTP settings): a free tier from a
   sending service such as Resend or Brevo with your own domain, or a dedicated Gmail account with an app password.
   Or switch on X sign-in (Authentication → Providers → X / Twitter (OAuth 2.0); it needs an X developer app with
   the callback `https://<project>.supabase.co/auth/v1/callback`, a privacy policy and terms URL) and set
   `SUPABASE_X_LOGIN = True` in `config.py`.

## When a source is down

RugCheck has been unreachable from some networks. After three failed calls in a run the scanner stops calling it:
authorities and extensions come from the chain, the liquidity lock from GeckoTerminal or the launchpad pool,
top-10 and developer shares from Jupiter, and the linked-wallet, bundle and rugged checks are marked "not checked"
and pass. The page says so in its summary line. GeckoTerminal and Jupiter rate limits only slow a run down.

## Free hosting

`.github/workflows/scan.yml` scans, deploys `site/` to GitHub Pages, and then starts the next run itself, so a new
scan begins as soon as one ends (about every 15 to 20 minutes). GitHub's own scheduler often drops crons this
frequent, so the cron in the file (three times an hour) is only a backup that restarts the chain if a run times out;
a failed run waits 10 minutes before starting the next. Pushes that change the code also run it, and it can be
started by hand (Actions → scan → Run workflow). To stop it, disable the workflow under Actions. To set it up on a new repository: make it
**public** (unlimited Actions minutes; a private one gets 2,000 a month, which this schedule exceeds), and under
Settings → Pages set the source to GitHub Actions. Scanning needs no secrets; rug calls need `SUPABASE_SECRET_KEY`.

The SQLite file is carried between runs in the Actions cache. When the cache is empty (the first run, or after
7 days without a run, when GitHub evicts it) the scan starts from `seed/undertow.db.gz`, the history as it stood when
the seed was last committed. To refresh the seed, download a run's database or copy one from a local run:
`gzip -9c undertow.db > seed/undertow.db.gz`. GitHub can delay or skip scheduled runs when it is busy; the stamp on
the page shows when the last scan ran and warns when one is overdue.

## Layout

    undertow/config.py     every threshold, in one place
    undertow/sources.py    GeckoTerminal, DEX Screener, Jupiter, Solana RPC, RugCheck, GoPlus, Telegram: one function each
    undertow/gates.py      metrics -> pass/fail per gate (pure)
    undertow/signals.py    exit cost, rug-study signals, buyer breadth, candle stats, momentum quality (pure)
    undertow/tracker.py    entry tracker maths and day-one outcomes (pure)
    undertow/lab.py        Lab variables, outcome updates, exit rules and statistics (pure)
    undertow/tgrisk.py     Telegram bot-risk heuristic (pure)
    undertow/momentum.py   percentile-rank momentum (pure)
    undertow/review.py     the weekly gate review: verdicts, drops, promotions, the testing bench (pure)
    undertow/community.py  the scan's side of rug calls: list tokens, price and settle calls, read the crowd
    undertow/notify.py     optional Telegram alerts
    undertow/store.py      SQLite
    undertow/scan.py       discover -> refresh -> enrich -> gate -> track -> observe -> snapshot -> export
    undertow/cloud.py      the claude.ai copy's cycle: restore the saved state, scan once, build, review, save the state
    seed/undertow.db.gz    the history a fresh GitHub Actions cache starts from
    supabase/schema.sql    tables, security rules and functions for rug calls, votes and tags
    web/                   page source (style, body, app.js; community.* only in the GitHub build); build_page.py inlines it

## Known limits (read before trusting a result)

* **The study's calibration is narrow**: three weeks of June 2026, one market regime, mostly coins minutes old.
  Its rates are shown only inside that range and should be re-checked against the tracker before you rely on them.
* **Coverage.** The free lists reach the most active few hundred tokens per pass and the universe builds up across
  runs. Quiet tokens near the volume floor can be missed.
* **GeckoTerminal rate limits are per IP**, and shared IPs (CI runners, proxies) hit them sooner. The scanner backs
  off and carries on, so a run just takes longer.
* **Candles reach back 24 hours** on the free tier. If the scanner is down for more than a day, that day's highs are
  lost and some outcome multiples are recorded as missed.
* **Exit cost** takes the worse of a constant-product pool model and Jupiter's quoted price impact. Quotes for the
  same token move by a point or two minute to minute; the gate's 10% limit sits well clear of that noise.
* **Bundling is inferred**, from RugCheck's wallet-link graph and near-identical balances in the top holders. It is
  not traced from launch transactions.
* **The copycat-ticker check** from the study is not implemented: Jupiter's free search returns at most 20 matches.
* **Heuristics are uncalibrated**: Telegram bot-risk, momentum quality and the non-study thresholds.
* **X data is not free**, so only the handle is used (and checked for reuse across tokens).
* **The weekly review tests many things at once.** Two reviews in a row and 2.5 standard errors cut the false
  alarms, they do not remove them, and four weeks of one market regime is still one regime.
* **The crowd can be gamed** (sock-puppet accounts, coordinated tags). That is why it never gates, and why calls are
  scored against the base rate rather than counted.

Information only; not investment advice.
