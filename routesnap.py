"""RouteSnap – SVG renderer for ÖPNV connections.

Reads normalized JSON from vbb.py and produces a polished, dark-mode
SVG image with a git-graph–style layout (main route left, alternative
branches right).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from typing import Any


# ── Colour palette ──────────────────────────────────────────────────────────

BG          = "#0B0D12"
SURFACE     = "#121722"
TEXT_PRI    = "#F3F6FB"
TEXT_SEC    = "#97A3B6"
TEXT_MUTED  = "#5A6478"
ACCENT_CYAN = "#00E5FF"
WALK_COLOR  = "#5A8A9A"
CANCELLED   = "#FF4060"

LINE_COLORS = {
    "S":    "#39FF14",   # Neon-Green
    "U":    "#FFE500",   # Neon-Yellow
    "M":    "#FF44CC",   # Neon-Magenta  (Tram)
    "TRAM": "#FF44CC",
    "BUS":  "#FF8800",   # Neon-Orange
    "N":    "#FF8800",
    "RE":   "#00AAFF",   # Blue
    "RB":   "#00AAFF",
    "IC":   "#FFFFFF",
    "ICE":  "#FFFFFF",
}
FALLBACK_COLOR = "#00CCFF"  # Neon-Blue


def _esc(text: str) -> str:
    """Escape text for safe SVG embedding (strips HTML tags too)."""
    clean = re.sub(r"<[^>]+>", "", str(text))
    return html.escape(clean, quote=True)


def _short_name(name: str) -> str:
    """Shorten long VBB station names for display."""
    name = re.sub(r"\s*\(Berlin\)\s*$", "", name)
    name = re.sub(r"^(S\+U|S|U)\s+", "", name)
    return name.strip()


def get_line_color(line_name: str) -> str:
    up = line_name.upper().strip()
    for prefix, color in LINE_COLORS.items():
        if up.startswith(prefix):
            return color
    if up.isdigit():
        return LINE_COLORS["BUS"]
    return FALLBACK_COLOR


# ── SVG building blocks ────────────────────────────────────────────────────

def _defs() -> str:
    """SVG <defs> with reusable filters and gradients."""
    return """<defs>
  <filter id="glow-green" x="-50%" y="-50%" width="200%" height="200%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="4" result="blur"/>
    <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="glow-generic" x="-50%" y="-50%" width="200%" height="200%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur"/>
    <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="shadow-card" x="-5%" y="-5%" width="110%" height="115%">
    <feDropShadow dx="0" dy="4" stdDeviation="12" flood-color="#000" flood-opacity="0.5"/>
  </filter>
  <linearGradient id="header-grad" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#0E1420"/>
    <stop offset="100%" stop-color="#151E2E"/>
  </linearGradient>
</defs>"""


def _line_badge(x: int, y: int, line_name: str, color: str) -> str:
    """Render a small pill-shaped line badge (e.g. 'S3', 'U5')."""
    text = _esc(line_name)
    w = max(56, len(text) * 16 + 20)
    r = 14
    return (
        f'<rect x="{x}" y="{y - r}" width="{w}" height="{r * 2}" rx="{r}" '
        f'fill="{color}" fill-opacity="0.18" stroke="{color}" stroke-width="1.5"/>'
        f'<text x="{x + w // 2}" y="{y + 6}" fill="{color}" '
        f'font-family="Inter,SF Pro,Segoe UI,sans-serif" font-size="18" '
        f'font-weight="700" text-anchor="middle" letter-spacing="0.5">{text}</text>'
    )


def _node_circle(cx: int, cy: int, filled: bool, color: str = TEXT_PRI, r: int = 10) -> str:
    """Render a station dot."""
    if filled:
        return (
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" '
            f'stroke="{color}" stroke-width="3" filter="url(#glow-generic)"/>'
        )
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{BG}" '
        f'stroke="{color}" stroke-width="3"/>'
    )


def _edge_line(x1: int, y1: int, x2: int, y2: int, color: str,
               is_walk: bool = False) -> str:
    """Draw a vertical segment between two nodes."""
    attrs = f'stroke="{color}" stroke-width="4" stroke-linecap="round"'
    if is_walk:
        attrs += ' stroke-dasharray="6 8"'
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" {attrs}/>'


def _curve_branch(x_from: int, y_from: int, x_to: int, y_to: int,
                  color: str) -> str:
    """Draw a smooth bezier branch-off curve (git-graph style)."""
    mid_y = y_from + (y_to - y_from) * 0.5
    return (
        f'<path d="M {x_from} {y_from} C {x_from} {mid_y}, '
        f'{x_to} {mid_y}, {x_to} {y_to}" '
        f'fill="none" stroke="{color}" stroke-width="4" '
        f'stroke-linecap="round" filter="url(#glow-generic)"/>'
    )


# ── Data helpers ────────────────────────────────────────────────────────────

def _rank_journeys(journeys: list[dict]) -> list[dict]:
    """Pick the best two journeys by (duration, transfers, walk, arrival)."""
    def key(j: dict) -> tuple:
        dur = j.get("duration_min")
        dur = dur if dur is not None else 9999
        transfers = j.get("transfers")
        transfers = transfers if transfers is not None else 99
        walk = sum((l.get("duration_min") or 0)
                   for l in j.get("legs", []) if l.get("type") == "walk")
        arr = j.get("arrival") or "23:59"
        return (dur, transfers, walk, arr)
    return sorted(journeys, key=key)[:2]


def _build_node_list(legs: list[dict]) -> list[dict]:
    """Flatten legs into an ordered list of nodes with edge metadata."""
    nodes: list[dict] = []
    for i, leg in enumerate(legs):
        nodes.append({
            "name": _short_name(leg.get("origin", "?")),
            "time": leg.get("departure"),
            "role": "start" if i == 0 else "transfer",
            "edge": leg,   # edge *after* this node
        })
    if legs:
        nodes.append({
            "name": _short_name(legs[-1].get("destination", "?")),
            "time": legs[-1].get("arrival"),
            "role": "destination",
            "edge": None,
        })
    return nodes


def _find_split_index(nodes_a: list[dict], nodes_b: list[dict]) -> int:
    """Find the last shared node index (where the branch splits)."""
    split = 0
    for i in range(min(len(nodes_a), len(nodes_b))):
        if nodes_a[i]["name"] != nodes_b[i]["name"]:
            break
        split = i
        ea = nodes_a[i].get("edge")
        eb = nodes_b[i].get("edge")
        if ea is None or eb is None:
            break
        if ea.get("line") != eb.get("line"):
            break
    return split


def _walk_minutes(journey: dict) -> int:
    return sum((l.get("duration_min") or 0)
               for l in journey.get("legs", []) if l.get("type") == "walk")


# ── Main renderer ──────────────────────────────────────────────────────────

CANVAS_W = 1080
NODE_SPACING = 130          # vertical spacing between nodes
GRAPH_X = 120               # x-position of the main graph rail
BRANCH_OFFSET = 200         # horizontal offset for alternative branch
LABEL_X = GRAPH_X + 36      # text starts right of the node dot
BRANCH_LABEL_X = GRAPH_X + BRANCH_OFFSET + 36

FONT = 'font-family="Inter,SF Pro Display,Segoe UI,sans-serif"'


class RouteSnapRenderer:
    """Produces a polished SVG for one or two ÖPNV routes."""

    def __init__(self, title: str, data: dict[str, Any]):
        self.title = title
        self.data = data
        self.parts: list[str] = []
        self.y = 0  # current drawing cursor

    # ── public API ──────────────────────────────────────────────────────

    def render(self) -> str:
        journeys = _rank_journeys(self.data.get("journeys", []))
        if not journeys:
            return (f'<svg width="{CANVAS_W}" height="400" '
                    f'xmlns="http://www.w3.org/2000/svg">'
                    f'<rect width="100%" height="100%" fill="{BG}"/>'
                    f'<text x="{CANVAS_W//2}" y="200" fill="{TEXT_SEC}" '
                    f'{FONT} font-size="28" text-anchor="middle">'
                    f'Keine Verbindungen gefunden</text></svg>')

        self.parts = []
        self.y = 0

        # -- header --
        self._draw_header(journeys)

        # -- graph --
        if len(journeys) == 1:
            nodes = _build_node_list(journeys[0]["legs"])
            self._draw_rail(nodes, GRAPH_X, LABEL_X)
        else:
            nodes_a = _build_node_list(journeys[0]["legs"])
            nodes_b = _build_node_list(journeys[1]["legs"])
            split = _find_split_index(nodes_a, nodes_b)

            # Shared trunk – draw nodes up to & including split, but
            # suppress the last node's outgoing edge (that belongs to
            # the individual branches).
            trunk = nodes_a[: split + 1]
            self._draw_rail(trunk, GRAPH_X, LABEL_X, suppress_last_edge=True)

            # Remember Y of the split point
            split_y = self.y

            # Main branch (continues straight down on the left rail).
            # skip_first=True → don't redraw the split node, but DO
            # draw its outgoing edge.
            branch_a = nodes_a[split:]
            self._draw_rail(branch_a, GRAPH_X, LABEL_X, skip_first=True)
            end_y_a = self.y

            # Alternative branch (drawn next to the first option, no connecting curve)
            self.y = split_y
            branch_x = GRAPH_X + 460
            branch_label_x = branch_x + 36

            branch_b = nodes_b[split:]
            # We set skip_first=False so that the alternative branch draws
            # the split node again on its side, providing a clear starting point.
            self._draw_rail(branch_b, branch_x, branch_label_x, skip_first=False)
            end_y_b = self.y

            self.y = max(end_y_a, end_y_b)

        # -- remarks --
        self._draw_remarks(journeys)

        # -- footer line --
        self.y += 30
        self.parts.append(
            f'<line x1="80" y1="{self.y}" x2="{CANVAS_W - 80}" y2="{self.y}" '
            f'stroke="{TEXT_MUTED}" stroke-width="1" stroke-opacity="0.3"/>')
        self.y += 40
        self.parts.append(
            f'<text x="{CANVAS_W // 2}" y="{self.y}" fill="{TEXT_MUTED}" '
            f'{FONT} font-size="16" text-anchor="middle" letter-spacing="2">'
            f'ROUTESNAP</text>')
        self.y += 50

        # Wrap in <svg>
        height = max(self.y, 600)
        header = (
            f'<svg width="{CANVAS_W}" height="{height}" '
            f'xmlns="http://www.w3.org/2000/svg">\n'
            f'<rect width="100%" height="100%" fill="{BG}"/>\n'
            f'{_defs()}\n'
        )
        return header + "\n".join(self.parts) + "\n</svg>"

    # ── header ──────────────────────────────────────────────────────────

    def _draw_header(self, journeys: list[dict]) -> None:
        j1 = journeys[0]
        dur = j1.get("duration_min") or 0
        transfers = j1.get("transfers") or 0
        walk = _walk_minutes(j1)
        dep = j1.get("departure", "?")
        arr = j1.get("arrival", "?")

        self.y = 48

        # Card background
        self.parts.append(
            f'<rect x="40" y="32" width="{CANVAS_W - 80}" height="200" '
            f'rx="20" fill="url(#header-grad)" filter="url(#shadow-card)" '
            f'stroke="{TEXT_MUTED}" stroke-width="0.5" stroke-opacity="0.3"/>')

        # Title
        self.y = 88
        self.parts.append(
            f'<text x="80" y="{self.y}" fill="{TEXT_PRI}" {FONT} '
            f'font-size="38" font-weight="700" letter-spacing="-0.5">'
            f'{_esc(self.title)}</text>')

        # Subtitle line 1
        self.y += 44
        if len(journeys) == 1:
            sub = f"{dur} min · {transfers} Umstiege · {walk} min Fußweg"
        else:
            j2 = journeys[1]
            arr2 = j2.get("arrival", "?")
            sub = f"{dur} min · 1 Alternative"
            arr = f"{arr} / {arr2}"
        self.parts.append(
            f'<text x="80" y="{self.y}" fill="{TEXT_SEC}" {FONT} '
            f'font-size="24">{_esc(sub)}</text>')

        # Subtitle line 2 – times
        self.y += 36
        self.parts.append(
            f'<text x="80" y="{self.y}" fill="{ACCENT_CYAN}" {FONT} '
            f'font-size="26" font-weight="600">{dep} → {arr}</text>')

        self.y = 280  # space below the card

    # ── rail drawing ────────────────────────────────────────────────────

    def _draw_rail(self, nodes: list[dict], rail_x: int, label_x: int, *,
                   suppress_last_edge: bool = False,
                   skip_first: bool = False) -> None:
        """Draw a vertical sequence of nodes + edges.

        suppress_last_edge – if True the outgoing edge of the *last*
            node in ``nodes`` is not drawn.  Used for the shared trunk
            so both branches can draw their own first edge.
        skip_first – if True the first node circle/label is omitted
            (because the trunk already drew it) but its outgoing edge
            IS drawn.
        """
        last_idx = len(nodes) - 1
        for idx, node in enumerate(nodes):
            if idx == 0 and skip_first:
                # Don't redraw the split node, but do draw the first edge
                edge = node.get("edge")
                if edge:
                    self._draw_edge_segment(rail_x, label_x, edge)
                continue

            # ── node circle ─────────────────────────────────────────────
            is_terminal = node["role"] in ("start", "destination")
            # Determine colour from the edge leaving this node (or arriving)
            edge = node.get("edge")
            if edge:
                if edge.get("type") == "walk":
                    circle_color = WALK_COLOR
                else:
                    circle_color = get_line_color(edge.get("line", ""))
            else:
                circle_color = TEXT_PRI

            self.parts.append(
                _node_circle(rail_x, self.y, filled=is_terminal,
                             color=circle_color if is_terminal else TEXT_SEC,
                             r=11 if is_terminal else 8))

            # ── station name + time ─────────────────────────────────────
            name = _esc(node["name"])
            time_str = node.get("time", "")

            name_size = 26 if is_terminal else 22
            name_weight = "700" if is_terminal else "500"
            name_fill = TEXT_PRI if is_terminal else TEXT_SEC

            self.parts.append(
                f'<text x="{label_x}" y="{self.y + 6}" fill="{name_fill}" '
                f'{FONT} font-size="{name_size}" font-weight="{name_weight}">'
                f'{name}</text>')

            if time_str:
                self.parts.append(
                    f'<text x="{label_x}" y="{self.y + 30}" fill="{TEXT_MUTED}" '
                    f'{FONT} font-size="18">{time_str}</text>')

            # Show delay/cancelled badge next to time
            if edge and edge.get("delay") and edge["delay"] not in ("", "pünktlich"):
                delay_text = _esc(edge["delay"])
                delay_color = CANCELLED if edge.get("cancelled") else "#FFA040"
                tx = label_x + len(time_str) * 11 + 20 if time_str else label_x
                self.parts.append(
                    f'<text x="{tx}" y="{self.y + 30}" fill="{delay_color}" '
                    f'{FONT} font-size="18" font-weight="700">{delay_text}</text>')
            elif edge and edge.get("delay") == "pünktlich":
                tx = label_x + len(time_str) * 11 + 20 if time_str else label_x
                self.parts.append(
                    f'<text x="{tx}" y="{self.y + 30}" fill="#39FF14" '
                    f'{FONT} font-size="16" font-weight="600" opacity="0.7">'
                    f'pünktlich</text>')

            # Cancelled strike-through overlay
            if edge and edge.get("cancelled"):
                self.parts.append(
                    f'<text x="{label_x}" y="{self.y + 50}" fill="{CANCELLED}" '
                    f'{FONT} font-size="16" font-weight="700">FÄLLT AUS</text>')

            # ── edge segment ────────────────────────────────────────────
            if edge and not (suppress_last_edge and idx == last_idx):
                self._draw_edge_segment(rail_x, label_x, edge)

    def _draw_edge_segment(self, rail_x: int, label_x: int,
                           edge: dict) -> None:
        """Draw the connecting line + edge label between two nodes."""
        is_walk = edge.get("type") == "walk"
        color = WALK_COLOR if is_walk else get_line_color(edge.get("line", ""))
        dur = edge.get("duration_min") or 0

        seg_start = self.y + 16
        self.y += NODE_SPACING
        seg_end = self.y - 16

        # The line itself
        self.parts.append(
            _edge_line(rail_x, seg_start, rail_x, seg_end, color,
                       is_walk=is_walk))

        # Edge label (midpoint)
        mid_y = (seg_start + seg_end) // 2

        if is_walk:
            self.parts.append(
                f'<text x="{label_x}" y="{mid_y}" fill="{WALK_COLOR}" '
                f'{FONT} font-size="18" font-style="italic">'
                f'Fußweg · {dur} min</text>')
        else:
            line_name = edge.get("line", "?")
            # Line badge
            self.parts.append(_line_badge(label_x, mid_y - 12, line_name, color))

            # Direction
            direction = edge.get("direction", "")
            if direction:
                short_dir = _short_name(direction)
                self.parts.append(
                    f'<text x="{label_x}" y="{mid_y + 18}" fill="{TEXT_MUTED}" '
                    f'{FONT} font-size="16">→ {_esc(short_dir)}</text>')

            # Duration
            self.parts.append(
                f'<text x="{label_x}" y="{mid_y + 38}" fill="{TEXT_MUTED}" '
                f'{FONT} font-size="16">{dur} min</text>')

    # ── remarks ─────────────────────────────────────────────────────────

    def _draw_remarks(self, journeys: list[dict]) -> None:
        """Draw a compact remarks section at the bottom."""
        remarks: list[str] = []
        for j in journeys:
            for r in j.get("remarks", []):
                clean = re.sub(r"<[^>]+>", "", str(r)).strip()
                if clean and clean not in remarks and len(clean) < 200:
                    remarks.append(clean)
            for leg in j.get("legs", []):
                for r in leg.get("remarks", []):
                    clean = re.sub(r"<[^>]+>", "", str(r)).strip()
                    if clean and clean not in remarks and len(clean) < 200:
                        remarks.append(clean)
        remarks = remarks[:3]
        if not remarks:
            return

        self.y += 50
        self.parts.append(
            f'<text x="80" y="{self.y}" fill="{TEXT_SEC}" {FONT} '
            f'font-size="20" font-weight="700" letter-spacing="1.5">'
            f'HINWEISE</text>')

        for r in remarks:
            self.y += 32
            # Truncate long remarks
            display = _esc(r[:100] + ("…" if len(r) > 100 else ""))
            self.parts.append(
                f'<text x="100" y="{self.y}" fill="{TEXT_MUTED}" {FONT} '
                f'font-size="17">· {display}</text>')


# ── CLI ─────────────────────────────────────────────────────────────────────

def render_cmd(args: argparse.Namespace) -> None:
    if args.stdin:
        data = json.load(sys.stdin)
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)

    title = args.title
    if not title:
        dest = data.get("destination", {})
        title = _short_name(dest.get("name", "Route"))

    renderer = RouteSnapRenderer(title, data)
    svg_data = renderer.render()

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg_data)
    print(f"Rendered → {args.out}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RouteSnap – ÖPNV connection renderer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("render", help="Render a route SVG/PNG")
    rp.add_argument("input", nargs="?", help="Input JSON file")
    rp.add_argument("--stdin", action="store_true",
                    help="Read JSON from stdin")
    rp.add_argument("--out", required=True,
                    help="Output file path (e.g. route.svg)")
    rp.add_argument("--title", help="Override the title text")

    args = parser.parse_args()
    if args.cmd == "render":
        if not args.stdin and not args.input:
            parser.error("Provide an input file or use --stdin")
        render_cmd(args)


if __name__ == "__main__":
    main()
