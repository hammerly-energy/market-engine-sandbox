"""Settlement and the primary correctness test.

    sum(load payments) - sum(generator revenue) == -sum_over_lines( mu[l] * f[l] )

Must hold to floating-point tolerance. Run on every solve. A failure points at
PTDF construction, a sign convention, or dual extraction.

The identity says the market does not create or destroy money. Load pays the
LMP at its own bus, generators are paid the LMP at theirs, and when those two
numbers differ the gap is exactly what the binding lines are worth:

      load pays                                       gen is paid
    at bus E, $10                                   at bus A, $14
         |                                                |
         +------------ the gap is congestion rent --------+
                       and it equals -sum(mu * f)

With no congestion every mu is zero, the two sides are equal, and the identity
still holds -- with both halves at zero. That is why the M0 test survives M3
rather than being replaced.

-- why flows and not limits --------------------------------------------------

Rent used to be written sum(mu[l] * limit[l]), which is the form CLAUDE.md
states and the form most write-ups use. It is correct only for a line binding
in ONE direction, and case5's DE happens to bind that way:

    DE, case5                        the other direction
    f = -limit                       f = +limit
    mu_dn active, mu > 0             mu_up active, mu < 0
    mu * limit = +|mu| * limit       mu * limit = -|mu| * limit
                 correct                          SIGN INVERTED

mu is mu_up - mu_dn and the raw dual on an active <= row is negative, so the
sign of mu carries the direction the line binds in. Rent does not: it is money,
and it is positive whichever way the power flows.

The flow form needs no case analysis because it is not a result about binding
lines at all -- it is algebra on the price definition. Substitute
LMP[i] = lambda + sum_l PTDF[l,i] * mu[l] into payments - revenue, use
sum_i inj[i] = 0 and f[l] = sum_i PTDF[l,i] * inj[i], and the lambda term
vanishes with the injections:

    payments - revenue = -sum_i LMP[i] * inj[i]
                       = -lambda * 0 - sum_l mu[l] * f[l]

No complementary slackness, no assumption that a priced line sits at its
rating. That assumption is still true and still worth testing -- but as its
own statement, not folded into the arithmetic here.

The limit does not appear, which also removes the inf * 0 hazard the old form
had to guard: an unlimited line contributes 0 * f, and f is finite.
"""


def settle(lmp, load_mw, gen_mw, mu, flows):
    """Money flows for one hour, and the residual that must be zero.

    Args:
        lmp:     {bus: $/MWh}
        load_mw: {bus: MW} demand served
        gen_mw:  {bus: MW} generation dispatched, SUMMED TO THE BUS. Callers
                 holding {generator: MW} must aggregate first -- a generator
                 is paid the price at its bus, so the bus is the only level at
                 which this arithmetic is meaningful.
        mu:      {line: $/MWh} signed congestion price, mu_up - mu_dn
        flows:   {line: MW} the solved flow on each line, in the same sign
                 convention as mu. Keyed identically to mu; a line in one and
                 not the other is a caller mixing two solves.

    Returns:
        {payments, revenue, congestion_rent, rent_from_duals, residual}, $/h.
    """
    missing = set(mu) ^ set(flows)
    if missing:
        # Silently iterating over mu alone would drop a line and report a
        # residual that looks like a pricing bug rather than a caller bug.
        raise ValueError(f"mu and flows disagree on the lines: {sorted(missing)}")

    payments = sum(mw * lmp[b] for b, mw in load_mw.items())
    revenue = sum(mw * lmp[b] for b, mw in gen_mw.items())
    rent = -sum(mu[l] * flows[l] for l in mu)
    return {
        "payments": payments,
        "revenue": revenue,
        # What load paid over what generation collected. Measured from the
        # money side.
        "congestion_rent": payments - revenue,
        # The same quantity derived from the duals instead. Two independent
        # routes to one number; the identity is the claim that they agree.
        "rent_from_duals": rent,
        "residual": payments - revenue - rent,
    }
