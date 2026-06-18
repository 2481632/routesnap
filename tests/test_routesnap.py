"""Tests for routesnap.py – the RouteSnap renderer."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

# Path to the script under test
SCRIPT = Path(__file__).resolve().parent.parent / "routesnap.py"

# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def single_route_data():
    """One journey with two transit legs and a walk."""
    return {
        "origin": {"name": "S+U Alexanderplatz Bhf (Berlin)"},
        "destination": {"name": "S Ostkreuz Bhf (Berlin)"},
        "journeys": [
            {
                "departure": "08:15",
                "arrival": "08:41",
                "duration_min": 26,
                "transfers": 2,
                "cancelled": False,
                "legs": [
                    {
                        "type": "transit",
                        "line": "S3",
                        "direction": "S Erkner Bhf",
                        "origin": "S+U Alexanderplatz Bhf (Berlin)",
                        "destination": "S+U Jannowitzbrücke (Berlin)",
                        "departure": "08:15",
                        "arrival": "08:20",
                        "duration_min": 5,
                        "delay": "pünktlich",
                        "cancelled": False,
                        "remarks": [],
                    },
                    {
                        "type": "walk",
                        "line": "walk",
                        "direction": "",
                        "origin": "S+U Jannowitzbrücke (Berlin)",
                        "destination": "U Jannowitzbrücke (Berlin)",
                        "departure": "08:20",
                        "arrival": "08:23",
                        "duration_min": 3,
                        "delay": "",
                        "cancelled": False,
                        "remarks": [],
                    },
                    {
                        "type": "transit",
                        "line": "U8",
                        "direction": "Hermannstraße",
                        "origin": "U Jannowitzbrücke (Berlin)",
                        "destination": "S Ostkreuz Bhf (Berlin)",
                        "departure": "08:25",
                        "arrival": "08:41",
                        "duration_min": 16,
                        "delay": "+3 min",
                        "cancelled": False,
                        "remarks": ["Bauarbeiten auf Linie U8"],
                    },
                ],
                "cancelled": False,
                "remarks": [],
            }
        ],
    }


@pytest.fixture
def two_route_data():
    """Two journeys sharing the same start, splitting after Alex."""
    return {
        "origin": {"name": "S+U Alexanderplatz Bhf (Berlin)"},
        "destination": {"name": "S Ostkreuz Bhf (Berlin)"},
        "journeys": [
            {
                "departure": "08:15",
                "arrival": "08:41",
                "duration_min": 26,
                "transfers": 1,
                "cancelled": False,
                "legs": [
                    {
                        "type": "transit",
                        "line": "S3",
                        "direction": "S Erkner Bhf",
                        "origin": "S+U Alexanderplatz Bhf (Berlin)",
                        "destination": "S Ostkreuz Bhf (Berlin)",
                        "departure": "08:15",
                        "arrival": "08:27",
                        "duration_min": 12,
                        "delay": "",
                        "cancelled": False,
                        "remarks": [],
                    },
                ],
                "cancelled": False,
                "remarks": [],
            },
            {
                "departure": "08:15",
                "arrival": "08:45",
                "duration_min": 30,
                "transfers": 1,
                "cancelled": False,
                "legs": [
                    {
                        "type": "transit",
                        "line": "U5",
                        "direction": "Hönow",
                        "origin": "S+U Alexanderplatz Bhf (Berlin)",
                        "destination": "U Frankfurter Allee (Berlin)",
                        "departure": "08:15",
                        "arrival": "08:25",
                        "duration_min": 10,
                        "delay": "",
                        "cancelled": False,
                        "remarks": [],
                    },
                    {
                        "type": "transit",
                        "line": "S41",
                        "direction": "Ring",
                        "origin": "U Frankfurter Allee (Berlin)",
                        "destination": "S Ostkreuz Bhf (Berlin)",
                        "departure": "08:30",
                        "arrival": "08:45",
                        "duration_min": 15,
                        "delay": "",
                        "cancelled": False,
                        "remarks": [],
                    },
                ],
                "cancelled": False,
                "remarks": [],
            },
        ],
    }


@pytest.fixture
def cancelled_route_data():
    """A journey with a cancelled leg."""
    return {
        "origin": {"name": "S+U Alexanderplatz Bhf (Berlin)"},
        "destination": {"name": "S Potsdam Hauptbahnhof"},
        "journeys": [
            {
                "departure": "15:48",
                "arrival": "16:29",
                "duration_min": None,
                "transfers": 1,
                "cancelled": True,
                "legs": [
                    {
                        "type": "transit",
                        "line": "S5",
                        "direction": "S Westkreuz (Berlin)",
                        "origin": "S+U Alexanderplatz Bhf (Berlin)",
                        "destination": "S Charlottenburg Bhf (Berlin)",
                        "departure": "15:48",
                        "arrival": "16:04",
                        "duration_min": 16,
                        "delay": "",
                        "cancelled": True,
                        "remarks": ["S5: Fällt aus"],
                    },
                    {
                        "type": "transit",
                        "line": "RE1",
                        "direction": "Magdeburg, Hauptbahnhof",
                        "origin": "S Charlottenburg Bhf (Berlin)",
                        "destination": "S Potsdam Hauptbahnhof",
                        "departure": "16:10",
                        "arrival": "16:29",
                        "duration_min": 19,
                        "delay": "pünktlich",
                        "cancelled": False,
                        "remarks": [],
                    },
                ],
                "cancelled": True,
                "remarks": ["Ein Abschnitt dieser Verbindung fällt aus."],
            }
        ],
    }


@pytest.fixture
def empty_data():
    """No journeys at all."""
    return {
        "origin": {"name": "Nirgendwo"},
        "destination": {"name": "Auch Nirgendwo"},
        "journeys": [],
    }


# ── helpers ─────────────────────────────────────────────────────────────────

def _run_render(tmp_path, data, extra_args=None):
    """Write JSON to file, run routesnap render, return (returncode, svg)."""
    json_path = tmp_path / "route.json"
    svg_path = tmp_path / "route.svg"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    cmd = ["python3", str(SCRIPT), "render", str(json_path),
           "--out", str(svg_path)]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(cmd, capture_output=True, text=True)
    svg_content = svg_path.read_text(encoding="utf-8") if svg_path.exists() else ""
    return result.returncode, svg_content


# ── unit tests (import-based) ──────────────────────────────────────────────

def test_get_line_color():
    import importlib.util
    spec = importlib.util.spec_from_file_location("routesnap", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.get_line_color("S3") == "#39FF14"
    assert mod.get_line_color("U5") == "#FFE500"
    assert mod.get_line_color("M10") == "#FF44CC"
    assert mod.get_line_color("RE1") == "#00AAFF"
    assert mod.get_line_color("XYZ") == "#00CCFF"  # fallback


def test_short_name():
    import importlib.util
    spec = importlib.util.spec_from_file_location("routesnap", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod._short_name("S+U Alexanderplatz Bhf (Berlin)") == "Alexanderplatz Bhf"
    assert mod._short_name("S Ostkreuz Bhf (Berlin)") == "Ostkreuz Bhf"
    assert mod._short_name("U Hermannstraße") == "Hermannstraße"
    assert mod._short_name("Potsdam Hauptbahnhof") == "Potsdam Hauptbahnhof"


def test_rank_journeys_handles_none_duration():
    import importlib.util
    spec = importlib.util.spec_from_file_location("routesnap", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    journeys = [
        {
            "duration_min": None, "transfers": 1, "arrival": "16:00",
            "legs": [{"origin": "A (Berlin)", "destination": "B (Berlin)", "line": "S1"}],
        },
        {
            "duration_min": 10, "transfers": 0, "arrival": "15:50",
            "legs": [{"origin": "A (Berlin)", "destination": "C (Berlin)", "line": "U5"}],
        },
    ]
    ranked = mod._rank_journeys(journeys)
    assert ranked[0]["duration_min"] == 10
    assert ranked[1]["duration_min"] is None


def test_rank_journeys_dedupes_same_path():
    """Later departures on the same route are not treated as alternatives."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("routesnap", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    leg_u3 = {
        "type": "transit", "line": "U3",
        "origin": "U Dahlem-Dorf (Berlin)",
        "destination": "U Fehrbelliner Platz (Berlin)",
    }
    leg_walk = {
        "type": "walk", "line": "walk",
        "origin": "U Fehrbelliner Platz (Berlin)",
        "destination": "U Fehrbelliner Platz (Berlin)",
    }
    leg_u7 = {
        "type": "transit", "line": "U7",
        "origin": "U Fehrbelliner Platz (Berlin)",
        "destination": "S+U Rathaus Spandau (Berlin)",
    }
    legs = [leg_u3, leg_walk, leg_u7]

    journeys = [
        {"duration_min": 36, "transfers": 1, "arrival": "16:57", "legs": legs},
        {"duration_min": 36, "transfers": 1, "arrival": "17:02", "legs": legs},
        {"duration_min": 38, "transfers": 1, "arrival": "17:09", "legs": legs},
    ]
    ranked = mod._rank_journeys(journeys)
    assert len(ranked) == 1
    assert ranked[0]["arrival"] == "16:57"


def test_build_node_list():
    import importlib.util
    spec = importlib.util.spec_from_file_location("routesnap", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    legs = [
        {"type": "transit", "line": "S3", "origin": "A (Berlin)",
         "destination": "B (Berlin)", "departure": "08:00", "arrival": "08:10"},
        {"type": "walk", "line": "walk", "origin": "B (Berlin)",
         "destination": "C (Berlin)", "departure": "08:10", "arrival": "08:12"},
    ]
    nodes = mod._build_node_list(legs)
    assert len(nodes) == 3
    assert nodes[0]["role"] == "start"
    assert nodes[1]["role"] == "transfer"
    assert nodes[2]["role"] == "destination"
    assert nodes[0]["name"] == "A"
    assert nodes[2]["name"] == "C"


# ── CLI integration tests ──────────────────────────────────────────────────

def test_single_route_render(tmp_path, single_route_data):
    rc, svg = _run_render(tmp_path, single_route_data, ["--title", "Nach Hause"])
    assert rc == 0
    assert "<svg" in svg
    assert "Nach Hause" in svg
    assert "Alexanderplatz" in svg
    assert "Ostkreuz" in svg
    assert "Fußweg" in svg        # walk leg present
    assert "U8" in svg            # transit line present
    assert "pünktlich" in svg     # delay indicator
    assert "+3 min" in svg        # delay indicator


def test_two_routes_render(tmp_path, two_route_data):
    rc, svg = _run_render(tmp_path, two_route_data, ["--title", "Split Test"])
    assert rc == 0
    assert "<svg" in svg
    assert "Split Test" in svg
    assert "Alexanderplatz" in svg
    assert "Frankfurter Allee" in svg   # alternative branch station
    assert "Alternative" in svg         # header subtitle
    assert "S3" in svg
    assert "U5" in svg


def test_cancelled_route_render(tmp_path, cancelled_route_data):
    rc, svg = _run_render(tmp_path, cancelled_route_data)
    assert rc == 0
    assert "<svg" in svg
    assert "FÄLLT AUS" in svg
    assert 'text-decoration="line-through"' in svg
    assert "Alexanderplatz" in svg
    # One cancellation label per cancelled leg, beside the departure time
    assert svg.count("FÄLLT AUS") == 1


def test_empty_journeys(tmp_path, empty_data):
    rc, svg = _run_render(tmp_path, empty_data)
    assert rc == 0
    assert "Keine Verbindungen" in svg


def test_title_defaults_to_destination(tmp_path, single_route_data):
    rc, svg = _run_render(tmp_path, single_route_data)
    assert rc == 0
    # Title should be the shortened destination name
    assert "Ostkreuz" in svg


def test_stdin_mode(tmp_path, single_route_data):
    svg_path = tmp_path / "stdin_out.svg"
    result = subprocess.run(
        ["python3", str(SCRIPT), "render", "--stdin", "--out", str(svg_path),
         "--title", "Stdin Test"],
        input=json.dumps(single_route_data),
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert svg_path.exists()
    svg = svg_path.read_text()
    assert "Stdin Test" in svg
    assert "<svg" in svg


def test_dynamic_canvas_height(tmp_path, single_route_data):
    """SVG height should adapt to content, not be fixed at 1920."""
    rc, svg = _run_render(tmp_path, single_route_data)
    assert rc == 0
    # Should NOT be the old hardcoded 1920
    assert 'height="1920"' not in svg


def test_identical_path_renders_single_route(tmp_path):
    """Same stops/lines at different times should not show a spurious branch."""
    bug_path = Path(__file__).resolve().parent.parent / "bug.json"
    data = json.loads(bug_path.read_text(encoding="utf-8"))
    rc, svg = _run_render(tmp_path, data, ["--title", "Spandau"])
    assert rc == 0
    assert "Alternative" not in svg
    assert "Dahlem-Dorf" in svg
    assert "Fehrbelliner" in svg
    assert "U3" in svg
    assert "U7" in svg


def test_svg_has_glow_filters(tmp_path, single_route_data):
    """Check that SVG defs contain the glow filters."""
    rc, svg = _run_render(tmp_path, single_route_data)
    assert rc == 0
    assert 'id="glow-generic"' in svg
    assert 'id="shadow-card"' in svg
