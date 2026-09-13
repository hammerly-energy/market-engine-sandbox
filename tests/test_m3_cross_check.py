r"""M3's prices, derived a second time by a formulation that shares no code.

tests/test_m3_network.py asserts five LMPs that were derived by hand from one
PTDF row before the LP existed. That is the engine's own arithmetic checked
against itself: same shift factors, same two dual families, same assembly
step. A sign convention that was wrong in `ptdf.py` would be wrong in the
hand derivation too, because the hand derivation read `ptdf.py`'s row.

case5.m carries no price column, so there is no published LMP to import. What
there is, is a second way to compute one.

    PTDF form, what src/ models          B-theta form, what this file builds
    ---------------------------          -----------------------------------
    one balance row for the system       one balance row per bus
    flows from PTDF * injection          flows from voltage angles
    lambda  + sum_l PTDF[l,i]*mu[l]      the dual on bus i's own row IS the
    assembled from two dual families     LMP, with nothing to assemble

The second form needs no PTDF, no slack-relative shift factors, no congestion
component and no assembly step. It solves

    min  sum_g c[g]*p[g]

    s.t. f[l]   == (theta[from] - theta[to]) / x[l]        for every branch
         -F[l]  <= f[l] <= F[l]
         theta[ref] == 0
         sum_{g at i} p[g] - D[i] - sum_{l out of i} f[l]
                            + sum_{l into i} f[l] == 0     for every bus

and reads LMP[i] off the dual of that last row. If the two agree, the PTDF
machinery and the LMP assembly are both right, because a shared error would
have to appear independently in two formulations that have no line of code in
common. Nothing above this point imports src.network or src.model; the
comparison at the bottom of the file is the only place the engine is called.

Measured, case5 at its single hour:

    bus   B-theta dual      engine LMP        difference
     A   16.9773588230   16.9773588230      -3.197e-14
     B   26.3844595190   26.3844595190       1.421e-14
     C   30.0000000000   30.0000000000       0.000e+00
     D   39.9427363228   39.9427363228       7.105e-15
     E   10.0000000000   10.0000000000      -3.553e-15

    worst flow 2.416e-12, worst dispatch 3.979e-13, cost equal to 10 decimals

ONE TRAP, and it cost a sign. Write the balance row as `inj == out - inn` and
bus B comes back at -26.3844595190 while the other four come back positive.
B is the only bus in case5 with load and no generator, so its left-hand side
is the bare constant -300 and Pyomo canonicalises that row in the opposite
direction from the four that carry variables on both sides. Written uniformly
as `expr == 0`, every row is canonicalised the same way and every dual has the
same sign. The magnitude was right throughout, which is what makes it a trap:
it looks like a price of the wrong sign at one bus rather than like a bug in
the harness.
"""

import pyomo.environ as pyo
import pytest
import yaml

from src.ingest.scenario import build_scenario
from src.model.clearing import clear

CONFIG = "configs/m3.yaml"

# The five LMPs as tests/test_m3_network.py asserts them, at the precision the
# hand derivation was written to. Repeated rather than imported: a cross-check
# that reads its expectation from the file it is checking has checked nothing.
HAND_DERIVED = {"A": 16.98, "B": 26.38, "C": 30.00, "D": 39.94, "E": 10.00}


def dc_opf(config=CONFIG, ref=None):
    """A DC OPF in B-theta form. Returns (dispatch, flows, lmp, cost).

    Deliberately unshared with src/. It re-reads the YAML rather than taking a
    Scenario, because Scenario construction is src.model.inputs and half of
    what this file exists to cross-check is that the network was read into the
    solver correctly.
    """
    cfg = yaml.safe_load(open(config))
    net = cfg["network"]
    buses = net["buses"]
    ref = ref or net["slack"]
    br = {
        n: (s["from"], s["to"], float(s["reactance_pu"]), float(s["limit_mw"]))
        for n, s in net["branches"].items()
    }
    gens = {
        g: (s["bus"], float(s["cost_usd_per_mwh"]), float(s["pmax_mw"]))
        for g, s in cfg["fleet"].items()
    }
    load = {b: float(cfg["load"]["mw"].get(b, 0.0)) for b in buses}

    m = pyo.ConcreteModel()
    m.B = pyo.Set(initialize=buses, ordered=True)
    m.L = pyo.Set(initialize=list(br), ordered=True)
    m.G = pyo.Set(initialize=list(gens), ordered=True)

    m.p = pyo.Var(m.G, bounds=lambda m, g: (0.0, gens[g][2]))
    m.theta = pyo.Var(m.B)
    m.f = pyo.Var(m.L)

    # The angle reference. An origin for theta and nothing else -- the test
    # below walks all five and no price moves.
    m.ref = pyo.Constraint(expr=m.theta[ref] == 0.0)

    # DC flow: power along a branch is the angle difference over its
    # reactance. This is the line src/network/ptdf.py builds its shift factors
    # from; here it stays as a constraint and no matrix is ever formed.
    def _flow(m, l):
        fr, to, x, _ = br[l]
        return m.f[l] == (m.theta[fr] - m.theta[to]) / x

    m.flow = pyo.Constraint(m.L, rule=_flow)
    m.cap_up = pyo.Constraint(m.L, rule=lambda m, l: m.f[l] <= br[l][3])
    m.cap_dn = pyo.Constraint(m.L, rule=lambda m, l: m.f[l] >= -br[l][3])

    # One row per bus, and its dual is that bus's LMP with no assembly.
    # `expr == 0` rather than `inj == out - inn`: see the trap in the module
    # docstring. B has no generator, so the second spelling leaves a bare
    # constant on the left and its dual comes back negated.
    def _balance(m, b):
        inj = sum(m.p[g] for g in m.G if gens[g][0] == b) - load[b]
        out = sum(m.f[l] for l in m.L if br[l][0] == b)
        inn = sum(m.f[l] for l in m.L if br[l][1] == b)
        return inj - out + inn == 0.0

    m.balance = pyo.Constraint(m.B, rule=_balance)
    m.obj = pyo.Objective(expr=sum(gens[g][1] * m.p[g] for g in m.G))
    m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)

    result = pyo.SolverFactory("appsi_highs").solve(m)
    assert str(result.solver.termination_condition) == "optimal"

    return (
        {g: pyo.value(m.p[g]) for g in m.G},
        {l: pyo.value(m.f[l]) for l in m.L},
        {b: m.dual[m.balance[b]] for b in buses},
        pyo.value(m.obj),
    )


@pytest.fixture(scope="module")
def theirs():
    return dc_opf()


@pytest.fixture(scope="module")
def ours():
    cleared = clear(build_scenario(CONFIG))
    return cleared, cleared["hours"][0]


class TestTheSecondDerivation:
    """B-theta on its own, before anything is compared."""

    def test_it_reaches_the_hand_derived_prices(self, theirs):
        """The claim M3's goal row makes, reached without a PTDF.

        This is the assertion that upgrades those five numbers from the
        engine's own arithmetic to a result two formulations agree on.
        """
        _, _, lmp, _ = theirs
        assert lmp == pytest.approx(HAND_DERIVED, abs=0.01)

    def test_it_reaches_matpower_s_dispatch(self, theirs):
        """case5.m's Pg column, which is the one published answer here.

        Asserted again in this file because a second formulation that got the
        prices right off a wrong dispatch would be agreeing by coincidence.
        """
        p, _, _, _ = theirs
        assert p == pytest.approx(
            {"A1": 40.0, "A2": 170.0, "C1": 323.49, "D1": 0.0, "E1": 466.51},
            abs=0.01,
        )

    def test_de_is_the_line_that_binds(self, theirs):
        """Each line against its OWN rating, which is the only comparison
        that means anything: AB carries 249.72 MW here and is rated 400."""
        _, f, _, _ = theirs
        limits = {
            n: float(s["limit_mw"])
            for n, s in yaml.safe_load(open(CONFIG))["network"]["branches"].items()
        }
        assert f["DE"] == pytest.approx(-limits["DE"], abs=1e-6)
        for l, v in f.items():
            if l != "DE":
                assert abs(v) < limits[l] - 1e-6

    @pytest.mark.parametrize("ref", ["A", "B", "C", "D", "E"])
    def test_no_price_depends_on_the_angle_reference(self, ref, theirs):
        """Trap 2, reached by a route that has no split to cancel.

        In PTDF form the invariance is arithmetic: lambda moves one way, the
        congestion sum moves the other, and they cancel to ~1e-13. Here there
        is no lambda and no congestion component -- the LMP is one dual on one
        row -- so the five prices do not move at all rather than moving and
        cancelling. Measured: identical to ten decimals under every reference.
        """
        _, _, base, _ = theirs
        _, _, lmp, _ = dc_opf(ref=ref)
        for bus, v in base.items():
            assert lmp[bus] == pytest.approx(v, abs=1e-9)


class TestTheTwoFormulationsAgree:
    """The cross-check itself, field by field."""

    def test_every_lmp(self, theirs, ours):
        _, _, lmp, _ = theirs
        cleared, t = ours
        for bus, v in lmp.items():
            assert v == pytest.approx(cleared["lmp"][bus, t], abs=1e-9)

    def test_every_flow(self, theirs, ours):
        _, f, _, _ = theirs
        cleared, t = ours
        for line, v in f.items():
            assert v == pytest.approx(cleared["flows"][line, t], abs=1e-9)

    def test_every_dispatch(self, theirs, ours):
        p, _, _, _ = theirs
        cleared, t = ours
        for g, v in p.items():
            assert v == pytest.approx(cleared["dispatch"][g, t], abs=1e-9)

    def test_the_total_cost(self, theirs, ours):
        _, _, _, cost = theirs
        cleared, _ = ours
        assert cost == pytest.approx(cleared["cost"], abs=1e-6)

    def test_the_agreement_is_tighter_than_the_tolerance(self, theirs, ours):
        """The margin, asserted so a loosening is visible as a loosening.

        Worst LMP difference measured at 3.197e-14, five orders inside the
        1e-9 the tests above use. A change that degraded agreement to 1e-10
        would still pass every assertion above and would be worth knowing
        about.
        """
        _, _, lmp, _ = theirs
        cleared, t = ours
        worst = max(abs(v - cleared["lmp"][bus, t]) for bus, v in lmp.items())
        assert worst < 1e-12
