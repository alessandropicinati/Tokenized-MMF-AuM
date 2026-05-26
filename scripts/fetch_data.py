#!/usr/bin/env python3
"""
Weekly AuM fetcher for tokenized money market funds / tokenized treasuries.

Data source: DeFiLlama free API (no key required).
  - https://api.llama.fi/protocols          -> list of all protocols (slug, name, category, tvl)
  - https://api.llama.fi/protocol/{slug}     -> full historical TVL series for one protocol

What it does, in order:
  1. Reads funds.json (your curated list).
  2. For each fund, pulls the full historical series. If the configured slug 404s,
     it self-heals by matching on 'match' keywords and prints the slug it used so
     you can correct funds.json.
  3. Resamples to weekly (configurable) and writes data/aum_history.json.
  4. Merges with the previous file so a fund that temporarily drops out of the API
     (or exits) keeps its last known history instead of vanishing.
  5. Scans the whole RWA category and FLAGS any fund above your threshold that is
     NOT in your list -- so new entrants get noticed without auto-polluting the chart.

It only uses the Python standard library, so the GitHub Action needs no pip install.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

API = "https://api.llama.fi"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "funds.json")
OUT_PATH = os.path.join(ROOT, "data", "aum_history.json")
UA = "tokenized-mmf-aum-tracker/1.0 (+github actions; data from DeFiLlama)"


def log(msg):
    print(msg, flush=True)


def http_json(url, retries=4, backoff=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise
            log(f"  http {e.code} on {url} (attempt {attempt+1})")
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"  error on {url}: {e} (attempt {attempt+1})")
        time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last}")


def to_series(protocol_json):
    """DeFiLlama protocol payload -> [{date: 'YYYY-MM-DD', aum: int}] sorted ascending."""
    raw = protocol_json.get("tvl") or []
    pts = []
    for d in raw:
        ts = d.get("date")
        val = d.get("totalLiquidityUSD", d.get("totalLiquidity"))
        if ts is None or val is None:
            continue
        day = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        pts.append((day, float(val)))
    pts.sort(key=lambda x: x[0])
    return pts


def resample_weekly(points):
    """Keep the last observation of each ISO week."""
    bucket = {}
    for day, val in points:
        dt = datetime.strptime(day, "%Y-%m-%d")
        iso = dt.isocalendar()
        key = (iso[0], iso[1])
        bucket[key] = (day, val)  # later days overwrite -> last in week
    return [{"date": day, "aum": round(val)} for day, val in sorted(bucket.values())]


def resolve_slug(fund, protocols_by_slug, protocols):
    """Return (slug, protocol_json) using config slug, else keyword match within RWA.

    If the configured slug fails, try each keyword-matched candidate in order
    (best first) until one returns usable data. Always print the candidates we
    considered so the run log tells you the exact slug to lock into funds.json.
    """
    slug = fund.get("defillama_slug", "")
    if slug:
        try:
            return slug, http_json(f"{API}/protocol/{slug}")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            log(f"  slug '{slug}' returned 404 -- searching for the right slug")

    # Build keyword candidates, prefer RWA category then highest TVL.
    kws = [k.lower() for k in fund.get("match", [])] or [fund["name"].lower()]
    scored = []
    for p in protocols:
        name = (p.get("name") or "").lower()
        sym = (p.get("symbol") or "").lower()
        hay = f"{name} {sym}"
        if any(k in hay for k in kws):
            cat = (p.get("category") or "").upper()
            score = (1 if "RWA" in cat else 0, p.get("tvl") or 0)
            scored.append((score, p))
    scored.sort(key=lambda c: c[0], reverse=True)

    if scored:
        log(f"  candidates for '{fund['name']}':")
        for _, p in scored[:5]:
            log(f"      slug='{p.get('slug')}'  name='{p.get('name')}'  "
                f"cat='{p.get('category')}'  tvl=${(p.get('tvl') or 0)/1e6:,.0f}M")
    else:
        log(f"  NO candidates matched keywords {kws} for '{fund['name']}'")
        return None, None

    # Try candidates in order until one fetches successfully.
    for _, p in scored:
        cand = p.get("slug")
        if not cand:
            continue
        try:
            payload = http_json(f"{API}/protocol/{cand}")
            log(f"  -> using slug '{cand}' for '{fund['name']}'  "
                f"(set defillama_slug to this in funds.json to lock it in)")
            return cand, payload
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
    return None, None


def load_previous():
    if os.path.exists(OUT_PATH):
        try:
            with open(OUT_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            pass
    return {"funds": []}


def detect_new_entrants(protocols, config, threshold):
    known = {(f.get("defillama_slug") or "").lower() for f in config["funds"]}
    known |= {tok for f in config["funds"] for tok in (f.get("match") or [])}
    flagged = []
    KEYS = ("treasur", "money market", "t-bill", "tbill", "govt", "government", "rwa")
    for p in protocols:
        cat = (p.get("category") or "").upper()
        name = (p.get("name") or "")
        slug = (p.get("slug") or "").lower()
        tvl = p.get("tvl") or 0
        if tvl < threshold:
            continue
        looks_relevant = "RWA" in cat or any(k in name.lower() for k in KEYS)
        if not looks_relevant:
            continue
        if slug in known or any(tok in slug for tok in known if tok):
            continue
        flagged.append((name, slug, tvl))
    if flagged:
        log("\n=== POSSIBLE NEW ENTRANTS not in funds.json (review, add if relevant) ===")
        for name, slug, tvl in sorted(flagged, key=lambda x: -x[2]):
            log(f"  + {name:<42} slug='{slug}'  AuM=${tvl/1e6:,.0f}M")
        log("=== end new-entrant scan ===\n")
    else:
        log("New-entrant scan: nothing new above threshold.")


def main():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    threshold = config.get("min_aum_usd", 0)
    weekly = config.get("resample", "weekly") == "weekly"

    log("Fetching protocol index from DeFiLlama ...")
    protocols = http_json(f"{API}/protocols")
    by_slug = {p.get("slug"): p for p in protocols}
    log(f"  {len(protocols)} protocols indexed.")

    previous = {f["key"]: f for f in load_previous().get("funds", [])}
    out_funds = []
    resolved, missing = [], []

    for fund in config["funds"]:
        log(f"- {fund['name']} ...")
        try:
            slug, payload = resolve_slug(fund, by_slug, protocols)
            series = resample_weekly(to_series(payload)) if weekly else \
                [{"date": d, "aum": round(v)} for d, v in to_series(payload)]
        except Exception as e:  # noqa: BLE001
            series, slug = [], None
            log(f"  FAILED: {e}")

        latest = series[-1]["aum"] if series else None
        if series and latest is not None and latest >= threshold:
            out_funds.append({
                "key": fund["key"], "name": fund["name"], "ticker": fund.get("ticker", ""),
                "color": fund.get("color", "#888888"), "slug_used": slug, "series": series,
            })
            resolved.append(f"{fund['name']} (${latest/1e6:,.0f}M, {len(series)} pts)")
        else:
            # Keep previous history so the line doesn't disappear on a transient miss.
            prev = previous.get(fund["key"])
            if prev and prev.get("series"):
                prev["stale"] = True
                out_funds.append(prev)
                missing.append(f"{fund['name']} (kept previous data)")
            else:
                missing.append(f"{fund['name']} (no data)")

    detect_new_entrants(protocols, config, threshold)

    payload = {
        "source": "defillama",
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "currency": "USD",
        "funds": out_funds,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))

    log("\nSUMMARY")
    log("  resolved: " + ("; ".join(resolved) if resolved else "none"))
    log("  missing : " + ("; ".join(missing) if missing else "none"))
    log(f"  wrote {OUT_PATH} ({os.path.getsize(OUT_PATH)//1024} KB)")
    if not resolved:
        log("ERROR: no funds resolved -- not overwriting with empty chart.")
        sys.exit(1)


if __name__ == "__main__":
    main()
