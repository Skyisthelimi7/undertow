"""Assemble the page from web/style.*.css, web/body.html, web/app.js and web/trade.* (the Buy & sell tab), plus
web/community.* (rug calls, votes and tags through Supabase) in every build except --fragment.

    python3 build_page.py OUT.html                     loads data.json (and snap/, the CSVs) from its own folder
    python3 build_page.py OUT.html --embed data.json   also carries a data snapshot inside, so it opens offline
    python3 build_page.py OUT.html --fragment          for a claude.ai Artifact, which supplies html/head/body itself
    python3 build_page.py OUT.html --fragment --split  ... with the styles and script as style.css and app.js beside it,
                                                       so the page itself stays a few kilobytes
    python3 build_page.py data.json OUT.html           older form: the same as --embed
"""
import argparse, json, pathlib, sys

W = pathlib.Path(__file__).resolve().parent / "web"
TOP = """<title>Undertow</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..900&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
"""


# shown only if app.js never ran (a host that refuses the separate script file)
GUARD = ("<script>setTimeout(function(){if(!window.__undertow){var s=document.getElementById('stamp');"
         "if(s)s.textContent='The page script did not load; reload the page';}},8000);</script>\n")


def build(out_path, embed=None, fragment=False, split=False):
    css = (W / "style.base.css").read_text() + (W / "style.extra.css").read_text() + (W / "trade.css").read_text()
    js = (W / "app.js").read_text() + "\n" + (W / "trade.js").read_text()     # the Buy & sell tab, in every build
    if not fragment:                                  # rug calls and votes need Supabase, which claude.ai would block
        css += (W / "community.css").read_text()
        js += "\n" + (W / "community.js").read_text()
    data = ""
    if embed:
        raw = pathlib.Path(embed).read_text()
        json.loads(raw)                               # fail early if the snapshot is not valid JSON
        data = '<script type="application/json" id="data">' + raw.replace("</", "<\\/") + "</script>\n"
    if split:
        here = pathlib.Path(out_path).resolve().parent
        (here / "style.css").write_text(css)
        (here / "app.js").write_text(js)
        style, body = '<link rel="stylesheet" href="style.css">\n', (W / "body.html").read_text() + "\n" + data + GUARD + '<script src="app.js"></script>\n'
    else:
        style, body = "<style>\n" + css + "</style>\n", (W / "body.html").read_text() + "\n" + data + "<script>\n" + js + "</script>\n"
    if fragment:
        out = TOP + style + body
    else:
        out = ('<!doctype html>\n<html lang="en-GB"><head><meta charset="utf-8">'
               '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
               + TOP + style + "</head><body>\n" + body + "</body></html>\n")
    pathlib.Path(out_path).write_text(out)
    return len(out)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1].endswith(".json") and not sys.argv[2].startswith("-"):
        n = build(sys.argv[2], embed=sys.argv[1])
        print(f"{sys.argv[2]}: {n / 1024:.0f} KB")
        sys.exit(0)
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--embed")
    ap.add_argument("--fragment", action="store_true")
    ap.add_argument("--split", action="store_true")
    a = ap.parse_args()
    print(f"{a.out}: {build(a.out, a.embed, a.fragment, a.split) / 1024:.0f} KB")
