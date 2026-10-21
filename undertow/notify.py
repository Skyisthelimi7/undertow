"""Optional Telegram alerts when a token enters or leaves the screener. Free: a bot made with @BotFather posting
to your own channel. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID; without them, messages are only printed."""
import json, os, sys, urllib.request


def _usd(v):
    if v is None:
        return "n/a"
    return f"${v / 1e6:.2f}M" if v >= 1e6 else f"${v / 1e3:.0f}k"


def format_event(e):
    """e: symbol, mint, frm, to, mcap, reasons, since_x (multiple vs first entry, or None)."""
    head = f"UNDERTOW · {e['symbol']} "
    if e["to"] == "IN":
        body = head + f"passed every gate at {_usd(e['mcap'])} market cap"
        if e.get("since_x") is not None:
            body += f" (re-entry; {e['since_x']:.2f}x its first entry)"
    else:
        body = head + f"dropped out at {_usd(e['mcap'])}"
        if e.get("since_x") is not None:
            body += f", {e['since_x']:.2f}x its first entry"
        body += "\nFailing: " + "; ".join(e["reasons"][:3])
    return body + f"\nhttps://dexscreener.com/solana/{e['mint']}\nInformation only, not a recommendation. Most memecoins go to zero."


def send(events):
    _post([format_event(e) for e in events])


def review(changes):
    """One message per weekly-review change: a gate dropped or restored, a rule promoted, retired or added."""
    _post([f"UNDERTOW · weekly gate review: {c['what']} {c['label']}\n{c['reason']}" for c in changes or []
           if c["what"] != "testing"])


def trade(changes, page, now):
    """Live paper trades opened by this scan, and the trade review's changes (a rule going live or retiring, the exit
    switching). Rules still under test never alert. Sales alert as they happen (closes, minute)."""
    page = page or {}
    out = []
    fresh = [x for x in page.get("open") or [] if abs(x["in_ts"] - now) < 1]
    if len(fresh) > 5:                    # one message rather than a burst when a live rule matches many coins at once
        out.append(f"UNDERTOW · {len(fresh)} buy signals (paper) this scan: " + ", ".join(x["sym"] or x["mint"][:6] for x in fresh[:30])
                   + f"\nExit: {page.get('exit', {}).get('label', '')}\nA rule's paper record, not a recommendation.")
        fresh = []
    for x in fresh:
        lv = x.get("levels") or {}
        stop = f"; stop {lv['stop']:.3g}" if lv.get("stop") else ""
        out.append(f"UNDERTOW · buy signal (paper): {x['sym']} at {x['in_price']:.4g}, {_usd(x.get('in_mc'))} market cap"
                   f"\nRule: {x['rule']}; exit: {page.get('exit', {}).get('label', '')}{stop}"
                   f"\nhttps://dexscreener.com/solana/{x['mint']}\nA rule's paper record, not a recommendation. Most memecoins go to zero.")
    out += [f"UNDERTOW · trade review: {c['what']} {c['label']}\n{c['reason']}" for c in changes or []
            if c["what"] not in ("testing", "redefined")]
    _post(out)


def _held(h):
    return f"{h * 60:.0f} min" if h < 1 else f"{h:.1f}h"


def _sell(s, o):
    return (f"UNDERTOW · sell signal (paper): {s.get('sym') or s['mint'][:6]} {o[2]} after {_held(o[1])}, "
            f"{o[0]:+.1f}% after costs\nhttps://dexscreener.com/solana/{s['mint']}")


def closes(closed):
    """Live paper trades just closed under the policy that governs them: [(trade, [net, hours, reason, ts, price])]."""
    _post([_sell(s, o) for s, o in closed or []])


def minute(kind, s, info, exits):
    """A live paper trade opened or closed between scans, on the minute data, sent as it happens. kind "buy": info is
    the quick rule; kind "sell": info is the trade's result under its governing policy."""
    if kind == "sell":
        _post([_sell(s, info)])
        return
    pol = exits.get(s["ref"]) or {}
    from .trade import exit_label            # notify stays importable on its own
    _post([f"UNDERTOW · quick buy signal (paper): {s.get('sym') or s['mint'][:6]} at {s['in_price']:.4g}, "
           f"{_usd(s.get('in_mc'))} market cap\nRule: {info.get('label', info.get('id'))}\nExit: {exit_label(pol) if pol else s['ref']}"
           f"\nhttps://dexscreener.com/solana/{s['mint']}\nA rule's paper record, not a recommendation. Most memecoins go to zero."])


def _post(texts):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    for text in texts:
        if not (token and chat):
            print("[alert, not sent]", text.replace("\n", " | "), file=sys.stderr)
            continue
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                     data=json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as x:          # an alert failing must never break the scan
            print("telegram send failed:", x, file=sys.stderr)
