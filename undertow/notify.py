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
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    for e in events:
        text = format_event(e)
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
