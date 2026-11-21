"""OWID/Microsoft AI-user share CSV -> index.html (data inlined into template.html)."""
import csv, json, os
h = os.path.dirname(os.path.abspath(__file__))
d = {}
for r in csv.DictReader(open(os.path.join(h, "ai_share.csv"))):
    if r["entity"] != "World":
        d.setdefault(r["entity"], {})[r["day"]] = float(r["ai_user_share"])
days = ["2025-06-30", "2025-12-31", "2026-03-31"]
data = {k: [v.get(x) for x in days] for k, v in sorted(d.items())}
assert all(None not in v for v in data.values())
open(os.path.join(h, "index.html"), "w", encoding="utf-8").write(
    open(os.path.join(h, "template.html"), encoding="utf-8").read().replace("__DATA__", json.dumps(data, separators=(",", ":"))))
print(len(data), "countries")
