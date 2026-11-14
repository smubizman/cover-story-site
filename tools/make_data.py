#!/usr/bin/env python3
"""Build the public data file for the Cover Story site.

Usage: python3 tools/make_data.py <folder with dash/ and picks/ JSON files> <output data.json>

The input folder holds the dashboard records as saved by ArtifactData with out_dir
(dash/<doc>.json and picks/<doc>.json, each either {"json": {...}} or the bare fields).
Only an allowlist of records is copied into the public part, and every field about
the owner's own bets, stakes, prices paid or bankroll is removed. The script refuses
to write the file if anything that looks private is still present in the public part.

If keys.json exists beside index.html (made once by the owner on setup.html), the full,
unscrubbed data is ALSO added under "locked", encrypted so that only someone with the
owner's passcode can read it: a fresh AES-256-GCM key per build, wrapped with the
owner's RSA public key. No passcode or private key is ever needed here.
"""
import json, os, re, sys, glob, datetime, base64, subprocess

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


def full_snap(src):
    """Everything the private dashboard shows, unscrubbed (dash, picks, and The Arena's btm and surv if present)."""
    full = {"dash": {}, "picks": {}, "btm": {}, "surv": {}}
    for coll in ("dash", "picks", "btm", "surv"):
        for f in sorted(glob.glob(os.path.join(src, coll, "*.json"))):
            name = os.path.basename(f)[:-5]
            if coll == "picks" and name == "today":
                continue
            full[coll][name] = unwrap(json.load(open(f)))
    # the owner's saved favorite teams and bankroll adjustments (nothing else from "ui")
    full["ui"] = {}
    for name in ("favs", "bank"):
        f = os.path.join(src, "ui", name + ".json")
        if os.path.exists(f):
            full["ui"][name] = unwrap(json.load(open(f)))
    return full


def lock(obj, keys):
    try:
        from cryptography.hazmat.primitives import hashes, serialization
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", "cryptography"], check=True)
        from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    pub = serialization.load_der_public_key(base64.b64decode(keys["pub"]))
    key, iv = os.urandom(32), os.urandom(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), None)
    wk = pub.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    e = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "wk": e(wk), "iv": e(iv), "ct": e(ct)}


def mode():
    """tools/mode.txt holds one word. "mirror" = publish the owner's full private view in the clear
    (the owner chose this on Nov 14 2026 while he is the only visitor). Anything else = public, scrubbed."""
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mode.txt")
    return open(f).read().strip().lower() if os.path.exists(f) else "public"


def main(src, out):
    if mode() == "mirror":
        snap = full_snap(src)
        snap["mode"] = "full"
        snap["built"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        json.dump(snap, open(out, "w"), ensure_ascii=False, separators=(",", ":"))
        print("wrote", out, os.path.getsize(out), "bytes; MIRROR mode (owner's full view, not scrubbed);",
              len(snap["dash"]), "dash,", len(snap["picks"]), "picks,", len(snap["btm"]), "arena records")
        return
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
    left = private_hits(snap)  # checked BEFORE the encrypted owner view is attached
    if left:
        sys.exit("NOT WRITTEN: private-looking text still present at: " + ", ".join(left[:10]))
    snap["built"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    note = ""
    keys = os.path.join(os.path.dirname(os.path.abspath(out)), "keys.json")
    if os.path.exists(keys):
        try:
            snap["locked"] = lock(full_snap(src), json.load(open(keys)))
            note = " + locked owner view"
        except Exception as e:  # never block the public update
            note = " (owner view skipped: %s)" % type(e).__name__
    json.dump(snap, open(out, "w"), ensure_ascii=False, separators=(",", ":"))
    print("wrote", out, os.path.getsize(out), "bytes;", len(snap["dash"]), "dash records,", len(snap["picks"]), "pick records" + note)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
