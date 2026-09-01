#!/usr/bin/env python3
"""Render the matched dev-A condition explorer as one self-contained HTML file.

The page ships in the repository and cannot fetch its data at load time, so the
rows are inlined at build time. Substitution is @@NAME@@ rather than str.format
because the template is mostly CSS and JavaScript.
"""

import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from collect import build as collect  # noqa: E402
from collect import governed_cost_estimate  # noqa: E402

TEMPLATE = os.path.join(HERE, "template.html")
DEFAULT_OUT = os.path.join(HERE, "index.html")

DOCUMENT = (
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
    "{head}</head>\n<body>\n{body}</body>\n</html>\n"
)

# Most interesting first: a lone winner or a C4/C5 flip carries an argument,
# an all-wrong question mostly carries a denominator.
ORDER = [
    "only_C2",
    "only_C5",
    "C5_recovers_C4",
    "C5_loses_C4",
    "only_C1",
    "only_C3",
    "only_C4",
    "split",
    "all_correct",
    "all_wrong",
    "all_wrong_with_errors",
]


def _wrap(page):
    """Lift <title> and <style> into a real <head>, leave the rest in <body>."""
    head, rest = [], page
    for tag in ("title", "style"):
        open_tag, close_tag = f"<{tag}", f"</{tag}>"
        while open_tag in rest:
            start = rest.index(open_tag)
            end = rest.index(close_tag, start) + len(close_tag)
            head.append(rest[start:end])
            rest = rest[:start] + rest[end:]
    return DOCUMENT.format(head="\n".join(head) + "\n", body=rest.strip() + "\n")


def render(rows, out_path, body_only=False):
    credit = governed_cost_estimate()
    counts = Counter(r["pattern"] for r in rows)
    patterns = [
        {"name": name, "count": counts[name]}
        for name in ORDER + sorted(set(counts) - set(ORDER))
        if counts[name]
    ]
    with open(TEMPLATE) as fh:
        page = fh.read()
    fields = {
        "DATA": json.dumps(rows, separators=(",", ":")),
        "PATTERNS": json.dumps(patterns, separators=(",", ":")),
        "N": str(len(rows)),
        "CREDIT": json.dumps(credit, separators=(",", ":")),
        "CREDIT_PER": f"${credit['per_attempt_usd']:.2f}" if credit else "no figure",
        "CREDIT_MAX": f"${credit['upper_bound_usd']:.2f}" if credit else "no figure",
    }
    for name, value in fields.items():
        page = page.replace(f"@@{name}@@", value)
    if "@@" in page:
        leftover = page[page.index("@@") : page.index("@@") + 40]
        raise SystemExit(f"unfilled placeholder in template: {leftover!r}")
    if not body_only:
        page = _wrap(page)
    with open(out_path, "w") as fh:
        fh.write(page)
    return patterns


if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if a != "--body-only"]
    out = argv[0] if argv else DEFAULT_OUT
    data = collect()
    pats = render(data, out, body_only="--body-only" in sys.argv)
    print(f"wrote {out}  ({os.path.getsize(out):,} bytes, {len(data)} questions)")
    for p in pats:
        print(f"  {p['count']:>3}  {p['name']}")
