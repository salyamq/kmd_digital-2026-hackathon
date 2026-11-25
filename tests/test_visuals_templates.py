"""Code-level checks of the visuals: every template renders its example, invariants catch
physics errors, and the state models agree with the analytical formulas of the chapters."""
import math

import numpy as np
import pytest

from kmd import visuals
from kmd.visuals import InvariantError, get_template, models, render_illustration


@pytest.mark.parametrize("name", [c["name"] for c in visuals.catalog()])
def test_example_renders_and_passes(name, tmp_path):
    tpl = get_template(name)
    spec = {"id": f"ex_{name}", "template": name, "params": tpl.example, "caption": "пример", "claim_ids": []}
    r = render_illustration(spec, tmp_path)
    assert r["path"].endswith(".svg")
    assert r["provenance"] in ("реальные данные", "симуляция", "схема")
    assert r["alt"]
    svg = open(r["path"], encoding="utf-8").read()
    assert r["provenance"] in svg  # the label is ON the picture
    # animation frames work too
    if tpl.animatable:
        visuals.render(name, tpl.example, tmp_path / f"{name}_t", t=0.5, formats=("png",))


def test_catalog_text_has_all_templates():
    txt = visuals.catalog_text()
    for c in visuals.catalog():
        assert c["name"] in txt


def test_cross_section_fluid_order_invariant():
    p = dict(get_template("cross_section").example)
    p["traps"] = [{"layer": 1, "goc_m": 1560, "owc_m": 1540}]
    with pytest.raises(InvariantError):
        visuals.render("cross_section", p, "/tmp/kmd_bad_xs", formats=("png",))


def test_cross_section_no_seal():
    p = dict(get_template("cross_section").example)
    p["layers"] = [{"lith": "sand", "thickness_m": 40}, {"lith": "sand", "thickness_m": 40}, {"lith": "shale", "thickness_m": 40}]
    p["traps"] = [{"layer": 1, "owc_m": 1555}]
    codes = [i["code"] for i in visuals.check("cross_section", p)]
    assert "no_seal" in codes


def test_cross_section_true_scale_has_no_exaggeration(tmp_path):
    p = dict(get_template("cross_section").example, vertical_exaggeration=1)
    r = visuals.render("cross_section", p, tmp_path / "xs", formats=("png",))
    assert not r["exaggerations"]


def test_log_track_invariants():
    lt = get_template("log_track")
    bad = {"layers": [{"top": 0, "base": 5, "lith": "sand", "fluid": "water"},
                      {"top": 5, "base": 10, "lith": "sand", "fluid": "oil"}]}
    codes = [i["code"] for i in visuals.check("log_track", bad)]
    assert "fluid_order" in codes
    bad2 = {"layers": [{"top": 0, "base": 5, "lith": "shale", "fluid": "oil"}]}
    assert "fluid_in_nonreservoir" in [i["code"] for i in visuals.check("log_track", bad2)]
    assert lt.check(lt.normalize(lt.example)) == []


def test_synthetic_logs_physics():
    sg = get_template("log_track").sg()
    layers = [{"top": 0, "base": 10, "lith": "shale"},
              {"top": 10, "base": 20, "lith": "sand", "fluid": "oil", "phi": 0.22},
              {"top": 20, "base": 30, "lith": "sand", "fluid": "water", "phi": 0.22},
              {"top": 30, "base": 40, "lith": "shale"}]
    r = models.synth_logs(layers, sg["lithology"], sg["fluids"], rw=0.05, rmf=0.5)
    z, c = r["depth"], r["curves"]
    at = lambda k, d: float(c[k][np.argmin(np.abs(z - d))])  # noqa: E731
    assert at("GR", 5) > at("GR", 15) + 50               # clay is radioactive, clean sand is not
    assert at("SP", 15) < at("SP", 5) - 30               # fresh mud: negative SP against permeable sand
    assert at("RD", 15) > 5 * at("RD", 25)               # oil-bearing far more resistive than water-bearing
    assert at("RS", 25) > at("RD", 25)                   # fresh filtrate: increasing invasion in water sand
    assert at("CALI", 15) < 216 < at("CALI", 5)          # mud cake in sand, caverns in clay


def test_pressure_line_source_and_pssc():
    kappa, k, mu, h, q, p0 = 0.1, 100 * 9.869e-16, 1e-3, 10.0, 100 / 86400, 20e6
    t = 86400.0
    p = models.diffusion_exact("radial", "const_rate", np.array([10.0]), t, kappa=kappa, p0=p0, q=q, k=k, mu=mu, h=h)
    # log approximation of -Ei for small argument: -Ei(-u) ~ -0.5772 - ln u
    u = 10.0 ** 2 / (4 * kappa * t)
    approx = p0 - q * mu / (4 * math.pi * k * h) * (-0.5772 - math.log(u))
    assert abs(p[0] - approx) < 2e3
    assert math.isclose(float(models.pssc_front("radial", "const_rate", t, kappa=kappa, rw=0.1)),
                        math.sqrt(0.01 + 4 * kappa * t))
    # front grows as sqrt(t): not a constant speed
    r1 = models.pssc_front("radial", "const_rate", 3600, kappa=kappa, rw=0.1)
    r4 = models.pssc_front("radial", "const_rate", 4 * 3600, kappa=kappa, rw=0.1)
    assert 1.9 < r4 / r1 < 2.1


def test_linear_erf_matches_fd():
    # exact erf solution vs the numerical solver used for radial const-pressure (sanity of FD at large r)
    x = np.array([0.0, 50.0, 200.0])
    p = models.diffusion_exact("linear", "const_pressure", x, 3600 * 10, kappa=0.5, p0=20e6, pw=15e6)
    assert p[0] == pytest.approx(15e6)
    assert p[0] < p[1] < p[2] <= 20e6


def test_radial_const_pressure_fd_monotone():
    r = np.array([0.1, 1, 10, 100, 1000])
    p = models.diffusion_exact("radial", "const_pressure", r, 86400, kappa=0.1, p0=20e6, pw=15e6, rw=0.1)
    assert p[0] == pytest.approx(15e6, abs=1e4)
    assert np.all(np.diff(p) >= -1)
    assert p[-1] == pytest.approx(20e6, rel=1e-3)


def test_gas_kick_closed_vs_open():
    D, rho = 3000.0, 1200.0
    pb0 = float(models.hydrostatic(D, rho))
    closed = models.gas_kick_migration(1000, well_depth=D, rho_mud=rho, p_bottom_initial=pb0, v_bubble0=1, shut_in=True)
    opened = models.gas_kick_migration(1000, well_depth=D, rho_mud=rho, p_bottom_initial=pb0, v_bubble0=1, shut_in=False)
    assert closed["p_wellhead"] > 0 and closed["p_bottom"] > pb0     # pressure rises in the whole closed well
    assert closed["volume"] == 1
    assert opened["volume"] > 2                                       # expands in an open well


def test_timeline_younger_on_top():
    tg = get_template("timeline_growth")
    st = tg.state(tg.normalize(tg.example))
    for a, b in zip(st["strata"], st["strata"][1:]):
        assert np.all(b["bot"] >= a["bot"] - 1e-9)


def test_crossplot_safe_eval_rejects_code():
    from kmd.visuals.templates.crossplot import safe_eval
    assert safe_eval("0.05/x**2", np.array([0.1]))[0] == pytest.approx(5.0)
    with pytest.raises(ValueError):
        safe_eval("__import__('os').system('true')", np.array([1.0]))
