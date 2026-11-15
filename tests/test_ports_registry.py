"""src/nems_open/ports.json drives which part stands behind each engine piece: a port lands by data, not by code."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
fid = pytest.importorskip("fidelity")

GRADED = {"port:industrial": {}, "port:ngmm": {}, "own:dispatch": {}, "stand:demand_stub": {}, "stand:natural_gas": {},
          "stand:electricity": {}}


def test_every_module_names_a_known_port_and_a_known_stand_in():
    reg = fid.REGISTRY
    for name, m in reg["modules"].items():
        assert m.get("port") is None or m["port"] in reg["ports"], name
        kind, key = m["fallback"].split(":")
        assert kind == "stand" and key in fid.STANDINS, name
        assert m.get("own") is None or m["own"] in fid.OWN, name


@pytest.mark.parametrize("module, ported, elec, part", [
    ("industrial", [], "standin", "stand:demand_stub"),            # graded port, but this run did not use it
    ("industrial", ["industrial"], "standin", "port:industrial"),  # the run says it ported industrial: green
    ("natural_gas", ["ngmm"], "standin", "port:ngmm"),             # the port key works as well as the module name
    ("electricity", [], "lp", "own:dispatch"),
    ("electricity", ["electricity"], "lp", "own:dispatch"),        # ECP not graded yet (no tests): falls through
    ("oil", ["oil"], "standin", "stand:oil"),
])
def test_a_module_flips_only_when_its_port_is_graded_and_the_run_lists_it(module, ported, elec, part):
    parts = {**GRADED, "stand:oil": {}}
    assert fid.resolve(module, {"ported": ported, "elec": elec}, parts) == part


def test_the_real_set_reads_what_it_ported_from_its_own_metadata():
    meta = json.loads((ROOT / "web" / "data" / "real_meta.json").read_text())
    assert fid.set_info("real")["ported"] == meta["ported"]


def test_fidelity_json_carries_the_registry_the_pages_resolve_from():
    data = json.loads((ROOT / "web" / "data" / "fidelity.json").read_text())
    reg = data["registry"]
    assert set(reg) == set(fid.REGISTRY["modules"])
    for m in reg.values():
        assert m["fallback"] in data["parts"] and (m["port"] is None or m["port"] in data["parts"])
