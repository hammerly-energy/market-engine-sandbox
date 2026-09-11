"""Power transfer distribution factors (shift factors), defined relative to a slack bus.

Changing the slack shifts every LMP by a constant. Price differences are invariant."""

import numpy as np

def ptdf(buses, branches, slack):
    """Power transfer distribution factors (shift factors) for a network.

    PTDFs are the linear sensitivities of line flows to bus injections:
    PTDF[l, i] is the MW that appears on line l when 1 MW is injected at bus i
    AND withdrawn at the slack. It is always a pair of actions -- a lone
    injection has nowhere to come from.

    The slack does two jobs, and both are needed here. It is the angle
    reference, theta_slack = 0, which resolves the singularity b_bus carries
    by construction. And it is the assumed withdrawal point, which is what
    makes a column mean something. Its own column is therefore exactly zero:
    inject at the slack, withdraw at the slack, nothing moves.

    Changing the slack shifts every LMP by a constant. Dispatch, congestion
    rent, and price DIFFERENCES are invariant; only the level of lambda moves
    (CLAUDE.md trap 2). One slack per connected component -- case5 is one.

    Args:
        buses: list of bus names. Fixes the column order.
        branches: list of Branch objects. Fixes the row order.
        slack: name of the slack bus

    Returns:
        (L, N) array. Rows ordered as branches, columns as buses.
    """
    from .topology import b_bus, b_flow, components

    # PTDF = (b @ A) @ (A.T @ b @ A)^-1
    #      = b_flow @ b_bus^-1

    # Connectivity is checked here, in front of the inverse, because this is
    # the line that fails when it is missing. A disconnected network makes
    # B_bus block diagonal, and each block carries its own zero eigenvalue --
    # so the matrix has two, the rank-1 fix below removes one, and numpy
    # reports "Singular matrix" without naming a bus. Duplicate bus names land
    # on the identical message from an unrelated cause. Neither is something a
    # caller can act on.
    #
    # One slack per connected component; this function prices one component.
    islands = components(buses, branches)
    if len(islands) > 1:
        home = next(g for g in islands if slack in g)
        stranded = sorted(b for g in islands if g is not home for b in g)
        raise ValueError(
            f"network is disconnected: {stranded} cannot reach slack "
            f"{slack!r}; components are {islands}"
        )

    # b_bus is singular by construction: adding a constant to every angle
    # changes no flow, so the all-ones vector is its null space. Adding 1 to
    # the slack column sends M @ ones = ones instead of 0, which kills that
    # null space and leaves a matrix that inverts.
    slack_index = buses.index(slack)
    e_slack = np.zeros(len(buses))
    e_slack[slack_index] = 1
    # np.outer(ones, e_slack) is all zeros except a column of 1s at the slack.
    B_bus = b_bus(buses, branches) + np.outer(np.ones(len(buses)), e_slack)

    # Compute the PTDFs.
    B_flow = b_flow(buses, branches)
    PTDF = B_flow @ np.linalg.inv(B_bus)

    # The inverse alone answers "inject 1 MW at bus i" with no counterparty,
    # which is not a physical question, and every row comes back floating by
    # an offset. Subtracting the slack column pairs each injection with a
    # withdrawal at the slack -- the actual PTDF definition -- and zeros the
    # slack column for free. Column DIFFERENCES were already correct; this
    # line only sets the anchor.
    PTDF = PTDF - PTDF[:, slack_index][:, None]

    return PTDF


def island_slacks(buses, branches, slack):
    """One slack per connected component. {slack bus: [buses in its island]}.

    A PTDF is defined relative to a slack, and a slack anchors exactly one
    component -- so a network in two pieces needs two. The user names one; the
    rest have to come from somewhere, and where they come from is a design
    decision rather than a detail:

        THE USER'S SLACK KEEPS ITS ISLAND. Whichever component contains it is
        keyed by it. Cutting a line must not move the slack the UI is
        displaying.

        EVERY OTHER ISLAND TAKES ITS FIRST BUS in the caller's bus order.
        Deterministic, so the same cut network gives the same answer twice,
        and reproducible from the config alone without running anything.

    The choice is pure accounting -- trap 2 -- and no LMP, flow, dispatch or
    settlement figure depends on it. What DOES depend on it is the level of
    lambda in that island, because lambda is the LMP at the slack. Which is
    why this returns the slacks rather than choosing them privately: a number
    the UI displays may not be picked silently.

    Ordered by the caller's bus order, so the island containing the first bus
    comes first whether or not it is the user's.
    """
    from .topology import components

    islands = components(buses, branches)
    out = {}
    for group in islands:
        home = slack if slack in group else group[0]
        out[home] = list(group)
    return out


def ptdf_blocks(buses, branches, slack):
    """PTDF for a network that may be in more than one piece.

    Returns (PTDF, islands): an (L, N) array in the caller's row and column
    order, and the {slack: [buses]} mapping island_slacks() chose.

    BLOCK DIAGONAL, and that is physics rather than a convenience. PTDF[l, i]
    is the flow appearing on line l when 1 MW is injected at bus i and
    withdrawn at that island's slack. If l and i are in different components
    there is no path between them, so the answer is zero:

        A ---- B ---- C        E          PTDF rows for AB, BC have zeros in
                              /|\         column E. The row for any line at E
        (the DE line is cut) / | \        has zeros in columns A, B, C.

    Which means every downstream expression is unchanged. The flow of a line
    is still sum_i PTDF[l, i] * inj[i]; the terms from other islands are
    simply zero. src/model/dispatch.py needs no change to m.inj, m.f, or
    either flow limit -- only the ENERGY BALANCE has to become one row per
    island, because that is the constraint that would otherwise let a
    generator in one island serve load in another through a line that does
    not exist.

    Each block is built by calling ptdf() on that component alone, so there is
    no second implementation of the linear algebra and no new way for a sign
    to be wrong. ptdf() keeps refusing a disconnected network, because a PTDF
    relative to one slack IS a single-component object; this function is the
    thing that knows there can be several.
    """
    islands = island_slacks(buses, branches, slack)
    col = {b: j for j, b in enumerate(buses)}
    row = {br.name: k for k, br in enumerate(branches)}

    PTDF = np.zeros((len(branches), len(buses)))
    for home, group in islands.items():
        inside = set(group)
        local_branches = [br for br in branches if br.from_bus in inside]
        if not local_branches:
            # A lone bus. No lines, so no rows to fill, and its own column is
            # zero everywhere -- which is correct: an injection there can
            # reach nothing. It still gets a slack and its own balance row.
            continue
        block = ptdf(group, local_branches, home)
        for k, br in enumerate(local_branches):
            for j, bus in enumerate(group):
                PTDF[row[br.name], col[bus]] = block[k, j]

    return PTDF, islands
