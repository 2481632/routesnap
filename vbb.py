#!/usr/bin/env python3
"""Token-efficient VBB route/delay checker for Hermes.

Uses https://v6.vbb.transport.rest with local station-ID cache.
No third-party dependencies.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = "https://v6.vbb.transport.rest"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "hermes-vbb"
STATION_CACHE = CACHE_DIR / "stations.json"
UA = "HermesAgent-vbb-transport-skill/1.0 (+https://hermes-agent.nousresearch.com)"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def load_cache() -> dict[str, Any]:
    try:
        return json.loads(STATION_CACHE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_cache(cache: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATION_CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def api_get(path: str, params: dict[str, Any], timeout: int = 25) -> Any:
    clean: dict[str, str] = {}
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, bool):
            clean[k] = "true" if v else "false"
        else:
            clean[k] = str(v)
    # compact responses by default
    clean.setdefault("pretty", "false")
    url = BASE_URL + path + "?" + urllib.parse.urlencode(clean)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:800]
        raise SystemExit(f"VBB API HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise SystemExit(f"VBB API network error: {e}")


def is_station_id(s: str) -> bool:
    return bool(re.fullmatch(r"\d{6,12}", s.strip()))


def resolve_station(query: str, *, refresh: bool = False, language: str = "de") -> dict[str, Any]:
    if is_station_id(query):
        # Fetch name if possible, but tolerate ID-only use.
        try:
            data = api_get(f"/stops/{query}", {"language": language})
            return {"id": str(data.get("id", query)), "name": data.get("name", query), "source": "id"}
        except SystemExit:
            return {"id": query, "name": query, "source": "id"}

    key = norm(query)
    cache = load_cache()
    if not refresh and key in cache:
        item = cache[key]
        return {"id": item["id"], "name": item.get("name", query), "source": "cache"}

    results = api_get("/locations", {
        "query": query,
        "results": 5,
        "stops": True,
        "addresses": False,
        "poi": False,
        "linesOfStops": False,
        "language": language,
    })
    stops = [x for x in results if x.get("type") in ("stop", "station") and x.get("id")]
    if not stops:
        raise SystemExit(f"No VBB stop/station found for: {query!r}")
    chosen = stops[0]
    item = {
        "id": str(chosen["id"]),
        "name": chosen.get("name", query),
        "cached_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "alternatives": [{"id": str(x.get("id")), "name": x.get("name")} for x in stops[1:4]],
    }
    cache[key] = item
    save_cache(cache)
    return {"id": item["id"], "name": item["name"], "source": "api", "alternatives": item["alternatives"]}


def parse_time(s: str | None) -> str:
    if not s:
        return "?"
    try:
        return dt.datetime.fromisoformat(s).strftime("%H:%M")
    except Exception:
        return s


def delay_str(seconds: Any) -> str:
    if seconds is None:
        return ""
    try:
        minutes = int(seconds) // 60
    except Exception:
        return ""
    if minutes == 0:
        return "pünktlich"
    if minutes > 0:
        return f"+{minutes} min"
    return f"{minutes} min"


def collect_remarks(obj: Any) -> list[str]:
    out: list[str] = []
    def walk(x: Any) -> None:
        if isinstance(x, dict):
            typ = str(x.get("type", ""))
            txt = x.get("text") or x.get("summary") or x.get("title")
            if txt and (typ in {"warning", "status", "hint"} or x.get("code") or x.get("priority")):
                t = re.sub(r"\s+", " ", str(txt)).strip()
                # Keep the output disruption-oriented. VBB/HAFAS often emits
                # operator names and generic bike/access hints as "remarks";
                # those create token noise and are not disruptions.
                noisy = (
                    t in {"BVG", "DBS", "DB", "VBB", "DB Regio"}
                    or "Fahrradmitnahme möglich" in t
                    or "Fahrzeuggebundene Einstiegshilfe" in t
                    or "WLAN verfügbar" in t
                    or "barrierefrei" in t.lower()
                )
                if t and not noisy and t not in out:
                    out.append(t)
            # recurse into common containers only; avoid huge unrelated structures
            for k in ("remarks", "warnings", "hints"):
                if k in x:
                    walk(x[k])
        elif isinstance(x, list):
            for y in x:
                walk(y)
    walk(obj)
    return out


def leg_summary(leg: dict[str, Any]) -> dict[str, Any]:
    line = leg.get("line") or {}
    is_walk = leg.get("walking")
    line_name = line.get("name") or ("walk" if is_walk else "?")
    leg_type = "walk" if is_walk else "transit"
    origin = (leg.get("origin") or {}).get("name", "?")
    dest = (leg.get("destination") or {}).get("name", "?")
    raw_dep = leg.get("departure") or leg.get("plannedDeparture")
    raw_arr = leg.get("arrival") or leg.get("plannedArrival")
    dep = parse_time(raw_dep)
    arr = parse_time(raw_arr)
    dur_min = 0
    try:
        if raw_dep and raw_arr:
            start = dt.datetime.fromisoformat(raw_dep)
            end = dt.datetime.fromisoformat(raw_arr)
            dur_min = round((end - start).total_seconds() / 60)
    except Exception:
        pass
    d_delay = delay_str(leg.get("departureDelay"))
    a_delay = delay_str(leg.get("arrivalDelay"))
    delay = a_delay or d_delay
    direction = leg.get("direction") or ""
    cancelled = bool(leg.get("cancelled"))
    return {
        "type": leg_type,
        "line": line_name,
        "direction": direction,
        "origin": origin,
        "destination": dest,
        "departure": dep,
        "arrival": arr,
        "duration_min": dur_min,
        "delay": delay,
        "cancelled": cancelled,
        "remarks": collect_remarks(leg),
    }


def summarize_journey(j: dict[str, Any]) -> dict[str, Any]:
    legs = [leg_summary(l) for l in j.get("legs", [])]
    dep = legs[0]["departure"] if legs else "?"
    arr = legs[-1]["arrival"] if legs else "?"
    transfers = max(0, len([l for l in legs if l["line"] != "walk"]) - 1)
    dur_min = None
    try:
        start = dt.datetime.fromisoformat((j.get("legs") or [{}])[0].get("departure"))
        end = dt.datetime.fromisoformat((j.get("legs") or [{}])[-1].get("arrival"))
        dur_min = round((end - start).total_seconds() / 60)
    except Exception:
        pass
    remarks: list[str] = []
    for r in collect_remarks(j):
        if r not in remarks:
            remarks.append(r)
    cancelled = any(l["cancelled"] for l in legs) or bool(j.get("cancelled"))
    return {"departure": dep, "arrival": arr, "duration_min": dur_min, "transfers": transfers, "cancelled": cancelled, "legs": legs, "remarks": remarks[:8]}


def format_text(origin: dict[str, Any], dest: dict[str, Any], data: dict[str, Any], args: argparse.Namespace) -> str:
    stamp = data.get("realtimeDataUpdatedAt")
    if isinstance(stamp, int):
        try:
            rt = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            rt = str(stamp)
    else:
        rt = "unknown"
    basis = args.departure or args.arrival or "now"
    lines = [
        f"VBB route check ({basis}); realtimeDataUpdatedAt: {rt}",
        f"From: {origin['name']} [{origin['id']}] ({origin['source']})",
        f"To:   {dest['name']} [{dest['id']}] ({dest['source']})",
        "",
    ]
    disruptions: list[str] = []
    journeys = [summarize_journey(j) for j in data.get("journeys", [])]
    if not journeys:
        return "\n".join(lines + ["No journeys returned by VBB."])
    for i, j in enumerate(journeys, 1):
        dur = f", {j['duration_min']} min" if j["duration_min"] is not None else ""
        status = " CANCELLED" if j["cancelled"] else ""
        lines.append(f"Option {i}: {j['departure']} → {j['arrival']}{dur}, {j['transfers']} transfer(s){status}")
        if j["cancelled"]:
            disruptions.append(f"Option {i}: cancellation shown")
        for leg in j["legs"]:
            delay = f" | {leg['delay']}" if leg["delay"] else ""
            canc = " | CANCELLED" if leg["cancelled"] else ""
            direction = f" Richtung {leg['direction']}" if leg["direction"] else ""
            lines.append(f"  - {leg['departure']}→{leg['arrival']} {leg['line']}{direction}: {leg['origin']} → {leg['destination']}{delay}{canc}")
            if leg["cancelled"]:
                disruptions.append(f"{leg['line']} {leg['origin']}→{leg['destination']}: cancelled")
            for r in leg["remarks"][:3]:
                lines.append(f"    remark: {r}")
                if r not in disruptions:
                    disruptions.append(r)
        for r in j["remarks"][:5]:
            lines.append(f"  remark: {r}")
            if r not in disruptions:
                disruptions.append(r)
        lines.append("")
    if disruptions:
        lines.append("Disruptions/remarks seen:")
        for r in disruptions[:10]:
            lines.append(f"- {r}")
    else:
        lines.append("Disruptions: none seen in returned journeys.")
    return "\n".join(lines)


def cmd_station(args: argparse.Namespace) -> None:
    st = resolve_station(args.query, refresh=args.refresh, language=args.language)
    print(f"{st['name']} [{st['id']}] source={st['source']}")
    for alt in st.get("alternatives", []):
        print(f"alt: {alt.get('name')} [{alt.get('id')}]")


def cmd_journey(args: argparse.Namespace) -> None:
    if args.departure and args.arrival:
        raise SystemExit("Use either --departure or --arrival, not both.")
    origin = resolve_station(args.from_, refresh=args.refresh, language=args.language)
    dest = resolve_station(args.to, refresh=args.refresh, language=args.language)
    params: dict[str, Any] = {
        "from": origin["id"],
        "to": dest["id"],
        "results": args.results,
        "stopovers": False,
        "remarks": True,
        "polylines": False,
        "tickets": False,
        "language": args.language,
    }
    if args.departure:
        params["departure"] = args.departure
    if args.arrival:
        params["arrival"] = args.arrival
    if args.transfers is not None:
        params["transfers"] = args.transfers
    if args.bike:
        params["bike"] = True
    if args.accessibility:
        params["accessibility"] = args.accessibility
    data = api_get("/journeys", params, timeout=35)
    # Some HAFAS backends may return their default count regardless of the
    # requested `results`; enforce the caller's token budget locally too.
    if isinstance(data.get("journeys"), list):
        data["journeys"] = data["journeys"][: max(0, args.results)]
    normalized = {
        "origin": origin,
        "destination": dest,
        "realtimeDataUpdatedAt": data.get("realtimeDataUpdatedAt"),
        "journeys": [summarize_journey(j) for j in data.get("journeys", [])],
    }
    if args.json:
        print(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")))
    else:
        print(format_text(origin, dest, data, args))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Token-efficient VBB journey/delay checker")
    sub = p.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("station", help="resolve a stop/station name to a cached VBB ID")
    st.add_argument("query")
    st.add_argument("--refresh", action="store_true", help="bypass station cache")
    st.add_argument("--language", default="de")
    st.set_defaults(func=cmd_station)

    j = sub.add_parser("journey", help="check VBB connection options and realtime remarks")
    j.add_argument("--from", dest="from_", required=True, help="origin name or VBB stop ID")
    j.add_argument("--to", required=True, help="destination name or VBB stop ID")
    j.add_argument("--departure", help="ISO date-time; default now")
    j.add_argument("--arrival", help="ISO date-time; mutually exclusive with --departure")
    j.add_argument("--results", type=int, default=3)
    j.add_argument("--transfers", type=int)
    j.add_argument("--bike", action="store_true")
    j.add_argument("--accessibility", choices=["partial", "complete"])
    j.add_argument("--language", default="de")
    j.add_argument("--refresh", action="store_true", help="bypass station cache when resolving names")
    j.add_argument("--json", action="store_true", help="print normalized compact JSON")
    j.set_defaults(func=cmd_journey)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
