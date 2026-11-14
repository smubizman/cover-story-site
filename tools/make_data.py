#!/usr/bin/env python3
"""Build the public data file for the Cover Story site.

Usage: python3 tools/make_data.py <folder with dash/ and picks/ JSON files> <output data.json>

The input folder holds the dashboard records as saved by ArtifactData with out_dir
(dash/<doc>.json and picks/<doc>.json, each either {"json": {...}} or the bare fields).
Only an allowlist of records is copied, and every field about the owner's own
bets, stakes, prices paid or bankroll is removed. The script refuses to write the
file if anything that looks private is still present.
"""
import json, os, re, sys, glob, datetime

DASH_ALLOW = ["header", "buyStrip", "nextPicks", "radar", "recentPicks", "scorecard",
              "sportStatus", "stories", "apSummary", "power", "health", "bargain", "spicy"]
HEADER_KEEP = ["footer", "updated", "weekOf"]
DROP_KEYS = re.compile(r"^(mine|bet|bets|betsNet|betsStaked|betsTip|stake|stakeAmt|toWin|toWinAmt|paid|paidC|amt|own|"
                       r"bankroll|bankrollTip|change|changeUp|history0|allTime|allTimeUp|week|weekUp|weekNote|weekCount|"
                       r"owner|adj)$")
PRIVATE_TEXT = re.compile(r"robinhood|bankroll|my bet|your bet|scott|hensley|i paid|you paid", re.I)


def unwrap(d):
    return d["json"] if isinstance(d, dict) and set(d.keys()) <= {"json", "version", "id"} and "json" in d else d


def scrub(o):
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items() if not DROP_KEYS.match(k)}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    return o


def private_hits(o, path=""):
    hits = []
    if isinstance(o, dict):
        for k, v in o.items():
            hits += private_hits(v, path + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            hits += private_hits(v, path + "/%d" % i)
    elif isinstance(o, str) and PRIVATE_TEXT.search(o):
        hits.append(path)
    return hits


def blank_private_strings(o):
    """Replace any free-text value that mentions the owner's bets or bankroll with an empty string."""
    if isinstance(o, dict):
        return {k: blank_private_strings(v) for k, v in o.items()}
    if isinstance(o, list):
        return [blank_private_strings(v) for v in o]
    if isinstance(o, str) and PRIVATE_TEXT.search(o):
        return ""
    return o


def main(src, out):
    snap = {"dash": {}, "picks": {}, "btm": {}}
    for name in DASH_ALLOW:
        f = os.path.join(src, "dash", name + ".json")
        if not os.path.exists(f):
            continue
        d = unwrap(json.load(open(f)))
        if name == "header":
            d = {k: d[k] for k in HEADER_KEEP if k in d}
        snap["dash"][name] = blank_private_strings(scrub(d))
    snap["dash"]["betsStrip"] = {"bets": []}
    for f in sorted(glob.glob(os.path.join(src, "picks", "*.json"))):
        name = os.path.basename(f)[:-5]
        if name == "today":
            continue
        snap["picks"][name] = blank_private_strings(scrub(unwrap(json.load(open(f)))))
    left = private_hits(snap)
    if left:
        sys.exit("NOT WRITTEN: private-looking text still present at: " + ", ".join(left[:10]))
    snap["built"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump(snap, open(out, "w"), ensure_ascii=False, separators=(",", ":"))
    print("wrote", out, os.path.getsize(out), "bytes;", len(snap["dash"]), "dash records,", len(snap["picks"]), "pick records")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
