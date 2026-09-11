# CLAUDE.md

Context for working in this repo. Read fully before writing code.

## What this is

An electricity market clearing engine, built from scratch. It answers: given generator offers, a load forecast, and a transmission network with limits, who runs, at what output, and what is a MWh worth at each bus.

Scope: nodal energy market, DC approximation, 24-hour day-ahead solve. No AC power flow, no reactive power, no financial transmission rights.

The repo has two halves. The **engine** (M0-M4, done) is the formulation,
built by hand. The **web build** (W0-W4, next) puts that engine behind a
browser so a visitor can rewire the network and watch prices move. The engine
does not change to suit the web build; the web build is a caller, and a caller
that finds the engine too brittle to survive arbitrary input is reporting a
real defect in the engine, not asking for a special case.

## Purpose (read this before "helping")

This is a learning project. The author is a mechanical engineer transitioning into power markets. The point is to build the formulations by hand and understand where prices come from.

Therefore:

- **Do not reach for PyPSA, GenX, or pandapower to solve the problem.** They are reference implementations to check answers against, not starting points. Using them defeats the exercise.
- **Do not hand over a finished module** when the author is on a milestone they haven't attempted. Explain the formulation, then let them write it.
- Do write scaffolding, data ingestion, tests, and plotting code — that's not the part worth learning by hand.
- When explaining a new concept, include a diagram or visual, not just prose.

**The web build is not subject to the hand-build rule.** HTTP handlers, the
frontend, the editor, the charts, and the deploy are scaffolding: write them
outright. The line falls where power-systems reasoning starts.

Detecting an island is already done (`topology.py:59`) and is not the
interesting part. The formulation questions the author has to answer are the
ones with more than one defensible answer:

- **What does an island mean?** Today `ptdf.py:48` refuses to price a
  disconnected network at all. A real ISO would price each island separately,
  with its own λ. Refusing is a choice, and it is the wrong one the moment a
  visitor's first act is to cut a line.
- **What does the engine say when load cannot be served?** Refuse, or admit a
  scarcity price and let λ rise to it. Both are real market designs.
- **What happens when the slack is deleted?** Any bus works and prices do not
  depend on it, so picking one silently is defensible — and silently changing
  a thing the UI displays is not.

Explain those and let the author write them. Anything that would be the same
code in a to-do app, just write.

## How to talk to me

I have ADHD, and I want every response in this repo shaped for it. **Invoke the
`i-have-adhd` skill at the start of a session and stay in it** — I should not
have to type `/i-have-adhd` each time. In short: lead with the action, number
multi-step work, restate where we are every turn, give concrete time estimates,
no preamble and no closing pleasantries.

The skill's own exceptions still apply, and two of them matter constantly here:
**"explain" means explain in full** — a formulation walkthrough runs as long as
the concept needs — and a **destructive action gets confirmed before it runs**,
brevity notwithstanding.

## Core mechanics a contributor must understand

**Prices are dual variables.** The dual on the energy balance constraint is the marginal cost of serving one more MW. That is the price. It is not computed by a pricing rule; it falls out of the optimization.

**The two-pass structure is mandatory.** Unit commitment is a MILP. A MILP has no meaningful duals, so it cannot produce a price. The sequence is:

1. Solve UC as a MILP → binary on/off schedule
2. Fix the binaries at those values
3. Re-solve dispatch as an LP → dispatch levels AND valid duals
4. Assemble prices from the duals

Real ISOs do exactly this. Never try to read prices off the MILP.

**LMP assembly:**

```
LMP[i] = lambda + sum_over_lines( PTDF[line, i] * mu[line] )  [+ loss term]
```

- `lambda` = dual on system energy balance. Same at every bus. The energy component.
- `mu[line]` = dual on that line's flow limit. Zero unless binding. Its sign carries which direction the line binds in — positive at the lower limit, negative at the upper — so never read it as a magnitude.
- The sum is the congestion component.

Sign convention depends on how the flow constraint was written. Verify against a case with a published answer rather than trusting the formula.

**The settlement identity is the primary correctness test:**

```
sum(load payments) - sum(generator revenue) == -sum_over_lines( mu[line] * f[line] )
```

Must hold to floating-point tolerance. If it doesn't, the bug is in PTDF construction, a sign convention, or dual extraction. Run this check on every solve.

**Write it with the flow, not the limit.** Most write-ups state the right-hand
side as `sum( mu[line] * limit[line] )`, and this file did too until a line
binding the other way proved it wrong. `mu` is `mu_up - mu_dn`, so its sign
carries the direction a line binds in — `mu > 0` at the lower limit, `mu < 0`
at the upper. Rent is money and is positive either way, so an expression that
tracks the sign of `mu` is correct in one direction and inverted in the other.
case5's DE binds at its lower limit, which is why the error survived M3 and M4.

The flow form needs no case analysis because it is not a claim about binding
lines at all. Substitute the LMP definition into `payments - revenue`, use
`sum_i inj[i] = 0` and `f[l] = sum_i PTDF[l,i] * inj[i]`, and the `lambda`
term vanishes with the injections:

```
payments - revenue = -sum_i LMP[i] * inj[i]
                   = -lambda * 0 - sum_l mu[l] * f[l]
```

No complementary slackness, no assumption that a priced line sits at its
rating. That assumption is still true and still tested — as its own statement,
in `test_a_priced_line_sits_at_its_rating`, not folded into the rent. The
limit never enters the arithmetic, which also removes the `inf * 0` hazard the
old form had to guard.

## Repo layout

```
market-engine-sandbox/
├── data/
│   ├── raw/                 exactly as downloaded, never edited, gitignored
│   ├── interim/             parsed, not yet aligned
│   └── processed/           canonical parquet, one schema, UTC index
├── src/
│   ├── ingest/              one module per source
│   │   ├── eia930.py
│   │   ├── eia_fuels.py
│   │   ├── nrel_profiles.py
│   │   ├── rts_gmlc.py
│   │   └── actuals.py       gridstatus pulls, HELD OUT from model inputs
│   ├── network/
│   │   ├── topology.py      buses, branches, susceptance matrix
│   │   └── ptdf.py          shift factors
│   ├── model/
│   │   ├── inputs.py        Generator, Bus, Branch, DemandBid, Scenario
│   │   ├── unit_commitment.py
│   │   ├── dispatch.py
│   │   └── pricing.py
│   ├── settle/settlement.py
│   ├── validate/compare.py
│   ├── api/                 FastAPI over clear(). transport only, no maths
│   └── viz/                 matplotlib, publication figures
├── web/                     the browser build. no toolchain, no build step
│   ├── index.html
│   ├── js/                  editor state, fetch, the seven views
│   └── css/
├── configs/                 yaml, one file per scenario, fully declarative
├── runs/                    one dir per solve, config snapshot copied in
├── tests/                   test_<milestone>_<context>.py
└── notebooks/               exploration only, nothing importable
```

## Conventions

- **The model layer must not know where data came from.** Ingest produces a `Scenario` object; the solver consumes it. Never call a data source from inside `src/model/`.
- **Everything is UTC internally.** Convert at the ingest boundary only.
- Units: MW for power, MWh for energy, $/MWh for prices, $/MMBtu for fuel.
- Every run writes its config into `runs/<timestamp>/` so results are reproducible.
- `data/raw/` is append-only. Never edit a downloaded file.
- Actuals in `src/ingest/actuals.py` are a held-out answer key. Never let them reach a `Scenario`.
- **Never commit automatically.** Make the changes, run the tests, report what
  changed, and stop. The author decides what gets committed and when, and writes
  the commit. Do not run `git commit`, `git push`, or `git add` unless explicitly
  asked in that message.
- **Test files are named `test_<milestone>_<context>.py`** — e.g. `test_m0_single_bus.py`, `test_m3_network.py`. The milestone says *when* a test was written and ties it to the table below; the context says *what physical setup it covers*, which is what still means something at M8. A milestone alone (`test_m0.py`) ages into a date stamp. A context alone loses the spine of the repo.
  Inside the file, group tests by lifespan, not by milestone: invariants that hold forever (energy balance, capacity bounds, cost consistency) belong in their own class, separate from the special cases a later milestone supersedes. The settlement identity at M0 is the example — it holds with congestion pinned at zero, and M3 replaces that zero with a real congestion term rather than deleting the test.

## Visualization

**Every plot is a publication figure.** Assume it will be printed in a journal
article, at column width, in grayscale, next to a caption. Nothing in this repo
gets a default-styled throwaway chart.

### Register

A figure labels; it does not narrate. The argument lives in the caption and in
prose — the image carries the evidence.

- **Titles are nominal phrases, not claims.** "Clearing price against demand" —
  not "Price is a staircase; the risers are where the dual breaks down." If a
  sentence is worth saying, say it in the caption.
- **Multi-panel figures use `(a)`, `(b)` labels**, set left, in the panel title.
  No figure-level suptitle and no subtitle sentence.
- **Annotations are terse.** `λ = 35`, `λ ∈ [20, 35]`. Not `λ = $35/MWh — the
  dual on energy balance`, not `no unique price`.
- **Units appear once, on the axis label.** Never repeated on every mark.
- **Capitalize every piece of display text.** Titles, panel labels, axis labels,
  legend entries, annotations, and inset tables all begin with a capital letter.
  Sentence case, not Title Case. Identifiers that come from the data (`g1`, bus
  names, `λ`) keep their literal form.
- **No bold, restrained type scale.** Roughly 8.5–10.5 pt. Emphasis comes from
  position and whitespace, not weight. This holds for text sitting on a shaded
  fill too — fix its legibility with font *color*, never with weight.
- **One typographic hierarchy, strictly ordered.** Panel title (10.5 pt) >
  axis label (9.5 pt) > annotation (8.5–9 pt) > tick label (8.5 pt). There is
  no tier above panel title, because there is no figure-level title.
- **Text over a shaded area takes a contrasting ink.** Surface-white on a deep
  fill, dark ink on a light one. Check it against the *rendered* fill, which is
  the color times its alpha over the surface, not the nominal hex.
- **Units keep their real capitalization.** `MW`, `MWh`, `$/MWh`, `$/MMBtu` —
  never `mw`, `mwh`. Case is meaning: `m` is milli and `M` is mega.
- **Identifiers match the prose and the equations.** If the text says `g1` and
  `λ`, the figure says `g1` and `λ` — not `G1`, not `Lambda`.
- **No arrow annotations.** Arrows collide with the labels they point at and
  almost always mean the text is in the wrong place. Put the text on empty
  ground adjacent to what it describes.
- **Resolve collisions by moving text, not by shrinking it.** If nothing fits,
  the figure has too much in it — cut content or split the panel.

### Construction

- **Axes are labeled with units, in parentheses, at the end.** `Dispatch (MW)`,
  `Clearing price λ ($/MWh)`, UTC timestamps. Always.
- **Colorblind-safe palette, validated, not eyeballed.** Assign hues by identity
  in a fixed order; never cycle. Sequential data gets one hue light-to-dark;
  diverging data gets two hues with a neutral midpoint. Never a rainbow.
- **Direct-label series** wherever they can be placed without collision. A legend
  is present for two or more series; direct labels supplement it, not replace it.
- **One y-axis.** Never a dual-axis chart. Two measures of different scale get
  two panels or an indexed common base.
- **Recessive grid and axes.** No top or right spine, no heavy gridlines, no
  chartjunk, no 3-D, no drop shadows.
- **Gridlines earn their place by helping the eye reach an axis.** A 24-hour
  series carries ticks and vertical gridlines every 6 hours, so the day has a
  visible rhythm and a reader can find the evening ramp without counting.
- **Annotations over a gridline or a data line get a bbox.**
  `bbox=dict(facecolor=SURFACE, alpha=0.75, edgecolor="none", pad=1.5)` — a
  line struck through a label is a silent failure, and moving the text is not
  always possible. Anchor a set of related annotations the same way relative to
  the feature each describes; do not alternate above and below to dodge.
- **Overlapping marks get a thin surface-colored edge** so a cluster reads as
  several points rather than one blob. Scatter, stacked fills, and adjacent
  bars alike.
- **Let a layout manager do the spacing.** `constrained_layout=True` or
  `tight_layout()`, never hand-tuned margins. A colorbar is allocated its own
  width and padding; it must not squeeze the panel it belongs to.
- **Curves are computed, not drawn.** A price-vs-demand staircase is many solves,
  not a hand-placed polyline. If the figure asserts something about the model,
  the model has to produce it.
- **300 dpi raster plus a vector copy** (PDF or SVG). Raster alone is not
  publishable.

### Before accepting a figure

**Render it and look at it. Every time.** Silent failures are the norm in
matplotlib: an unescaped `$` swallows the rest of the string into mathtext,
labels overlap, text overflows the axes. None of these raise, and no test
catches them. Open the file and inspect it.

Expect to iterate. Moving one label routinely creates a collision somewhere
else, so re-render and re-inspect after every adjustment.

### Placement

Figures are written into `runs/<timestamp>/` alongside the config snapshot that
produced them, so any figure can be traced back to the exact solve behind it.

Plotting code lives in `src/viz/` and is importable: a function returns a
`Figure`, and only `__main__` writes files. Never bury a `savefig` inside model
or ingest code.

## The web build

### Why there is a server at all

The engine is Pyomo calling HiGHS. Neither runs in a browser, and there is no
scipy in this venv to fall back to. That settles it: **Python solves, the
browser draws.**

A precomputed sweep shipped as static JSON was the alternative and it is dead
on arrival, because the levers include adding a bus and connecting a line.
You cannot precompute a sweep over topologies that do not exist yet. The
moment the editor can change the network, the solve has to be live.

```
  browser                         server
  ───────                         ──────
  editor state                    src/api/        (W0, a transport)
  {buses, branches,   ──POST──>   scenario_from_config()
   fleet, load,                   clear(scenario, slack=, limits=)
   slack, hour}                        |
                                  src/model/      (M0-M4, unchanged)
                                       |
  seven views       <──JSON───     {dispatch, flows, mu, lmp,
  formatted only                    lmbda, settlement, PTDF}
```

### The boundary rule

**No market arithmetic in JavaScript.** The browser formats numbers, picks
colours, and positions marks. It does not add λ to a congestion component, it
does not multiply μ by a flow, and it does not compute a residual. Every
number on screen is a field of the `clear()` return or a direct formatting of
one.

This is the same rule as *"the model layer must not know where data came
from"*, pointed the other way. It exists because a second implementation of
the LMP assembly — in a second language, untested — would be a new place for
a sign convention to be wrong, and the whole repo is organised around having
exactly one such place. If a view needs a number the engine does not return,
the engine returns it. `clear()` grows; the frontend does not.

Corollary: the settlement residual is **displayed, not hidden**. It is the
repo's central claim. A site that computes prices and quietly drops the proof
they are consistent is doing the thing this repo exists to not do.

### Scope honesty

The site must not imply M5-M8 exist. No unit commitment, no storage, no
reserves, no comparison against published prices. The fleet is five synthetic
generators on a five-bus teaching case and the offers are cost-based.

State that on the page, in the reader's path, not in a footer. The honest
version is more impressive than the inflated one: a visitor who works in
markets will spot a missing UC in thirty seconds, and the difference between
"knows what is missing" and "does not" is the entire signal.

### Interactive figure register

The publication rules above still govern anything exported as a file. On
screen, they hold with three amendments:

- **Identifiers, capitalisation and units are unchanged.** `g1`, `λ`, `MW`,
  `$/MWh`, sentence case, units on the axis label once. A web figure is not
  licensed to be sloppier than a printed one.
- **Hover may carry precision the figure does not.** A tooltip is allowed to
  give four decimals where the mark is rounded. It may not carry an argument
  or a sentence the figure needed to make itself.
- **Motion is for continuity, not for decoration.** When a lever moves, marks
  transition so the eye can follow which bus went where. Nothing pulses,
  bounces, or animates on load. A price that changes instantly is a price the
  reader cannot track to its new value.

Colour is assigned by identity in a fixed order and shared between the static
figures and the web views, so a bus is the same hue in the PDF and on screen.

### What the engine already refuses

Measured against the M3 case5 scenario, not assumed. This table exists so W1
does not spend a day rediscovering it, and so a new failure found later can
be checked against a list of what was already true.

| A visitor does this | What happens now | Verdict |
|---|---|---|
| Cuts a line, islanding a bus | `ValueError: network is disconnected: ['E'] cannot reach slack 'D'` | Clean, named, displayable |
| Names a slack that is not a bus | `ValueError: slack 'Z' is not a bus in [...]` | Clean |
| Adds a branch with zero reactance | `ValueError: reactance_pu must be > 0` at `Branch.__post_init__` | Clean, caught at construction |
| Duplicates a bus or branch name | `ValueError` at `Scenario.__post_init__` | Clean |
| Adds a bus with no generator and no load | Prices correctly. The bus gets a real LMP | **Not a bug.** Do not "fix" |
| Adds a second line between two buses | Solves correctly | **Not a bug.** Parallel lines are physical |
| Sets capacity below load | `RuntimeError: solve not optimal: infeasible` from `dispatch.py:235` | **The one real gap.** W1, and the answer is *elastic demand* — see below |
| Sets all load to zero | Solves, `λ = -0.0` | Degenerate, not broken. Trap 3 |

The pattern: **topology was hardened at M3 and economics was not.** The
network guards were written when PTDF was written, because a singular matrix
is loud. An infeasible LP is quiet — it returns a status, and the status was
only ever read by a developer.

### W1 decision: what the engine says when load cannot be served

**It admits a price.** Load stops being a constant on the right-hand side and
becomes a variable with a value:

```
  today                          with a demand block
  ─────                          ───────────────────
  Σ p[g,t] == Σ D[i,t]           Σ p[g,t] == Σ d[i,k,t]
                                              ▲
  min  Σ c[g]·p[g,t]             min  Σ c[g]·p[g,t] − Σ v[i,k]·d[i,k,t]
                                                        ▲
  D is data                              d is a variable, 0 ≤ d ≤ Dmax[i,k,t]
                                         v is what that MW is worth to the buyer
```

The objective stops being "minimise production cost" and becomes "maximise
welfare" — consumer benefit minus production cost. The cost-minimising model
is the special case, not a different model.

Why this and not a refusal. A visitor's most likely act is to drag capacity
down or load up, and a refusal makes the most interesting state in the whole
market unreachable: **scarcity pricing**. With a block priced at VOLL, λ rises
to VOLL in the short hour, and with a binding line the shortage — and the price
— is *local*. That is a real market design, not a fallback.

Three properties that make it safe to adopt:

- **It subsumes the refusal.** One block per bus, `Dmax` = the forecast, `v` =
  VOLL. Unserved MW is `Dmax − d`. A deploy that wants to refuse instead reports
  `d < Dmax` as a hard failure and loses nothing.
- **Nothing downstream changes.** `pricing.py` and `src/network/` are untouched;
  the LMP assembly does not know what an injection is made of.
- **M0–M4 must stay bit-identical.** With `v` above every offer the block is
  always served in full, so every existing number is unchanged. That equality
  is the acceptance test for the change, not a nice-to-have.

The one place it breaks quietly is settlement: `payments` must be computed on
**served** quantity `Σ_k d[i,k,t]`, not on declared load. Wrong, and the
residual goes non-zero in exactly the interesting hours and reads like a PTDF
sign error. Re-derive `payments − revenue = −Σ_l μ[l]·f[l]` with `d` in the
injection before writing the code — the benefit term drops out, but the
identity is only trustworthy because it was derived.

VOLL is a number one invents, so it lives in the config with provenance and is
never hardcoded. ERCOT's system-wide offer cap is the natural anchor; check the
current protocols rather than a remembered figure.

**Demand bids are named, not indexed.** `DemandBid(name, bus, mw, value)` is
deliberately the mirror of `Generator(name, bus, cost, pmax)`, because
economically it is one. The name is the load-bearing part: an anonymous block
indexed `(bus, k)` cannot later carry an owner or a constraint spanning hours
without renumbering every config and every test, and a named one can. Two bids
at one bus is a demand curve, not a collision, and the lower-valued one is
demand response — which is why M9(a) costs a line of YAML rather than an
engine change.

Firm load is valued at the **system-wide offer cap**, which lives in the
config with its provenance and never in the code. ERCOT's has moved — it was
$9000/MWh before the 2021 legislation — so a figure remembered from a
write-up is exactly how a stale constant ends up looking like data.

`value_usd_per_mwh = None` means inelastic and keeps demand on the right-hand
side, which is how the data model, the config path and the tests could land
green *before* the LP changes. `configs/w1.yaml` is the control: it restates
`configs/m4.yaml` as priced bids and must clear to the same numbers bit for
bit, today because the price is ignored and afterwards because a bid at the
cap outbids every generator.

The other two W1 questions — what an island means, and what happens when the
slack is deleted — are still open.

### Degeneracy under a moving slider

Dragging a line limit walks the LP through thresholds where it is degenerate,
and there the price genuinely flickers between equally valid values on inputs
a pixel apart. Trap 3. **Do not smooth it, debounce it away, or average it.**

Show it. A price that is not unique is the single most honest thing this site
can demonstrate, and it is invisible in every commercial tool a visitor has
seen. The engine already has the right instinct — M0 asserts *bounds* at
degenerate breakpoints rather than values — so the view should say `λ ∈ [20,
35]` where the repo's own tests would.

That requires the engine to know it is degenerate, which it currently does
not. Either detect it and return a flag, or accept that the site shows one
arbitrary member of the set without comment. The first is better and is not
free; decide before W3, not during.

### Frontend stack

Default: **no build step.** Plain ES modules, hand-written SVG, D3 for scales
and path generators only. The reason is lifespan — a portfolio piece is
judged years after it is written, and a toolchain that has rotted is worse
than no site.

Be honest about what this costs: W2 *is* drag interaction — placing buses,
pulling lines between them, hit-testing, undo. Hand-writing that in SVG is
the most likely place this plan overruns, which is why W2 is sized at a week
and a half rather than a week. If it starts to quagmire, adopting a framework
for the editor alone is the correct retreat, and it is a retreat worth making
early rather than at day nine.

## Data sources

| Input | Source |
|---|---|
| Network + fleet + profiles | RTS-GMLC (NREL, GitHub) — primary test system |
| Small test networks | MATPOWER cases (case14, case118) |
| Hourly load | EIA-930 Hourly Grid Monitor, API v2 |
| Fuel prices | EIA API v2 (Henry Hub, SoCal Citygate, Waha) |
| Generator specs | EIA Form 860, Form 923, EPA CAMD |
| Wind/solar shapes | NREL NSRDB, PVWatts, WIND Toolkit |
| Real offer curves | ERCOT 60-Day SCED Disclosure |
| Validation LMPs | `gridstatus` Python library |

Offers start as a cost proxy: `fuel_price * heat_rate + VOM`. Upgrade to real ERCOT offer curves later.

## Tooling

- Pyomo + HiGHS (`pip install pyomo highspy`). Julia/JuMP is a valid alternative and is where NREL's Sienna stack lives.
- If UC solve time explodes, set a MIP gap of 0.1% rather than chasing optimality. Production systems do the same.

## Milestones

Start at M0. Each milestone adds exactly one new way to be wrong — one new
failure surface — so that when a result looks wrong there is only one place to
look. A milestone is done when its **Goal** column is demonstrably true, not
when the code runs.

| | Milestone | Description | Goal — done when this is true | Est. |
|---|---|---|---|---|
| **M0** ✓ | Single-bus clearing | 3 generators, 1 bus, 1 hour. LP dispatch, minimize offer cost subject to one energy-balance equality. Price read off the dual on that constraint. | λ equals the marginal unit's offer, verified by hand and asserted in tests. Degenerate breakpoints assert bounds, not values. Settlement identity holds with the congestion term at zero. | 45 min |
| **M1** ✓ | Time indexing | Same fleet, 24 hours, hardcoded synthetic load shape. `p[g,t]`, 24 balance constraints, 24 duals. No data source, no timezone, no ramp limits. | A joint 24-hour solve reproduces 24 independent single-hour solves *exactly*. Hours are provably separable, because nothing yet couples them. | an evening |
| **M2** ✓ | Real load data | Replace the synthetic shape with EIA-930 hourly demand, API v2. Establishes the ingest → `Scenario` boundary and the UTC discipline. | Row count asserted against hours requested; index is UTC with no gaps or duplicates; the scaling choice from system load to fleet capacity is written down and justified. | a weekend |
| **M3** ✓ | DC network and congestion | PJM 5-bus example. Susceptance matrix, PTDF relative to a slack, line flow limits. `LMP[i] = λ + Σ PTDF[l,i]·μ[l]`. | Published PJM 5-bus LMPs reproduced exactly and committed as a regression test. Price *differences* invariant to slack choice. | 1 week |
| **M4** ✓ | Hourly nodal clearing | The M3 network across a full day. case5's static hour becomes a 24-hour load shape on the same five buses, so `LMP[i,t]` is indexed by both. No new data source, no new topology — the cross product of M1's time index and M3's network, and nothing else. | Congestion appears in some hours and not others, and the settlement identity holds in **every** hour separately — a day-level sum would let a positive residual in one hour cancel a negative one in another. The 24-hour solve reproduces 24 independent single-hour network solves exactly, because nothing couples the hours yet. | an evening |
| **M5** | *Not pursued.* | Full DC OPF at scale — RTS-GMLC, 73 buses, 120 branches. | — | — |
| **M6** | *Not pursued.* | Unit commitment. Startup cost, min up/down, min stable output. | — | — |
| **M7** | *Not pursued.* | Storage and reserves, co-optimized. | — | — |
| **M8** | *Not pursued.* | Validation against published LMPs via `gridstatus`. | — | — |
| **M9** | Demand-side participation | The rest of the demand side, once W1's single VOLL block exists. Two halves, and they are not the same size. **(a) Multi-block bids:** a real willingness-to-pay curve per bus instead of one block, so the clearing price can be set by a *consumer* and the merit-order view becomes two staircases meeting. Config and a figure; the LP is already the right shape. **(b) Load shifting:** `Σ_t d[i,t] == E[i]` — the day's energy is fixed and only its timing moves. | For (a): a demand block is the marginal resource in at least one hour, λ equals its valuation there, and the settlement identity still holds per hour. For (b): **`test_separability` fails, deliberately** — the joint 24-hour solve stops reproducing 24 independent hourly solves, because this is the first constraint in the repo that spans `t`. The dual on the energy-conservation row is a price on *when* energy is used, and it is the same object as storage arbitrage value. Do not build (b) without accepting that it is M7's formulation arriving early under another name. | (a) a weekend, (b) 1 week |

M9 is not numbered after M8 because it comes after it in time — it comes after **W1**, which is what puts a demand variable in the LP at all. It is numbered as an engine milestone because that is where it changes code, and it sits below the not-pursued rows so the table stays in one order rather than two.

M5-M8 are **deliberately not being built in this repo.** The rows stay because
the reasoning in them is still correct and because the web build must not
imply they exist. Anything the site says about unit commitment, storage,
reserves, or validation against real prices is a claim about code that is not
here. See *Scope honesty* below.

The two-pass UC structure documented under **Core mechanics** is likewise
description, not implementation. It stays because it explains why the engine
is an LP and where prices come from; it is not a thing this repo does.

### Web milestones

Same discipline: one new failure surface each, done when the **Goal** column
is demonstrably true.

| | Milestone | Description | Goal — done when this is true | Est. |
|---|---|---|---|---|
| **W0** | Serve one solve | FastAPI in `src/api/`, wrapping `clear()`. One `POST /clear` taking a scenario config as JSON. Two things that are not transport and must land here: a **wire format** — `clear()` keys dispatch, flows, μ and lmp by `(name, hour)` tuples, which JSON cannot express — and **input bounds**, because a public URL means a hostile POST body and a live HiGHS solve behind one is a resource-exhaustion vector. Cap buses, branches, generators, hours and body size; reject, don't truncate. | The published case5 LMPs come back over HTTP and match the in-process `clear()` result field for field, asserted as a test. The API adds no arithmetic. An oversized or malformed body returns a named 4xx, never a traceback and never a solve. | 1 day |
| **W1** | Make the engine total | Less is missing here than it looks. Measured, not assumed: islanding, an isolated bus, a mistyped slack, a zero-reactance branch and duplicate names **already** raise clean named `ValueError`s — `ptdf.py:48` and `topology.py:59` were built for exactly this. A connected bus with no generator and no load prices correctly. Parallel branches solve correctly. The one real gap is **infeasibility**: too little capacity for the load returns a bare `RuntimeError: solve not optimal: infeasible` from `dispatch.py:235`, which is not a sentence anyone can show a visitor. | **Every input the editor can produce returns either a priced solve or one named, displayable reason.** The fuzz test over random topologies is the deliverable, not the `RuntimeError` fix — the fix is an hour and the fuzz test is what proves *What the engine already refuses* is complete rather than merely the cases someone thought of. The harder half is the three formulation questions under **Purpose**: what an island means, what the engine says when load cannot be served, and what happens when the slack is deleted. Each has more than one defensible answer. Pick one each and write down why — a refusal chosen deliberately is a design; a refusal inherited from `ptdf.py` is an accident. | 1.5 days |
| **W2** | The editor | The eight levers, against the live engine: line limit, peak load per bus, add/remove bus, connect/disconnect line, add/remove generator, edit generator capacity and marginal cost, hour 1–24, slack bus. | Every lever re-solves and redraws. The slack dropdown is the acceptance test, **on a fixture with a unique optimum**: moving it must rearrange the λ/congestion split while every LMP and every settlement figure stays bit-identical. A UI that shows prices moving with the slack has a bug in it. Run that assertion on a degenerate fixture and it will flake, correctly — see trap 2. | 1.5 weeks |
| **W3** | The views | Network map with buses coloured by LMP; LMP split into λ + congestion; merit-order stack; settlement ledger with the residual; line flows against limits; live generation by unit; 24-hour heatmap. Three of these need fields `clear()` does not yet return — **add them in W0, not mid-W3**: a per-bus `congestion[bus, hour]`, which `pricing.py` already computes and then discards; per-generator `cost` and `pmax`, without which no merit-order stack can be drawn; and per-generator **status** (`off` / `interior` / `at_max`) with its `headroom` and `reduced_cost`. Status, *not* "the marginal unit" — that field was written at W0 and replaced within the hour, because under congestion there is no single marginal unit and three of case5's five buses have an LMP equal to no offer at all. Bus *coordinates* are not an engine concern at all — they are editor state, and they belong to W2. | Every number on screen is traceable to a field of the `clear()` return. Nothing is recomputed in JavaScript — the browser formats and draws, it does not do market arithmetic. The residual is displayed, not hidden, because a visible `≈ 0` is the claim the whole repo rests on. | 1 week |
| **W4** | The frame and the deploy | Narrative scroll, one section per engine milestone, each with its live figure and a link to the source that implements it. Equations rendered next to the code. Scope statement. Deployed. | A stranger can reach it at a URL, rewire the network, and leave understanding that λ is a dual variable. The scope statement is on the page, not in a footer. | 3 days |

Do not skip to a later milestone. Each one's test suite is the foundation for the
next, and the invariants established early are what catch the subtle failures
later.

## Known traps

1. **Time zones.** EIA-930 is UTC. ERCOT market time is Central Prevailing Time with DST — one 23-hour and one 25-hour day per year, including a duplicated hour. CAISO is Pacific Prevailing. Assert 8760 or 8784 rows in a year.
2. **PTDF slack bus.** PTDF is defined relative to a slack, and it is an
   accounting origin, not a modelling assumption. `PTDF[l, slack] = 0` by
   construction, so congestion at the slack is zero, so **λ is the LMP at the
   slack bus** — that is the whole content of the choice.

   Changing it moves λ and moves every PTDF column, and the two changes
   cancel exactly. Measured on case5, slack D → A → E:

   ```
   slack   λ         LMP:  A       B       C       D       E
   ──────────────────────────────────────────────────────────
     D    39.9427         16.9774 26.3845 30.0000 39.9427 10.0000
     A    16.9774         16.9774 26.3845 30.0000 39.9427 10.0000
     E    10.0000         16.9774 26.3845 30.0000 39.9427 10.0000
   ```

   λ moves $30. **No LMP moves at all**, and no payment, revenue or rent
   moves either. Earlier wording here said prices "shift by a constant"; the
   constant is zero, and saying it the loose way invites a UI that animates
   prices sliding when the slack changes. They do not slide.

   The mechanism: `f = PTDF·inj` and `Σ inj = 0`, so the reference term
   `PTDF[l, s']·Σ inj` vanishes. Different matrix, identical feasible set,
   identical dispatch and identical μ. The two matrices agree only *on* the
   balance hyperplane, so the Lagrangian splits the same total price
   differently between the balance row and the flow rows — λ absorbs the
   difference, and the sum is physics.

   Consequence for testing: a slack bug is **invisible in settlement**. Every
   bill is right whichever slack is wrong. It shows only if λ and the
   congestion component are asserted separately.

   **The precondition is a unique optimum, and it is not decorative.** What is
   slack-invariant is the *set* of optimal prices, because the shift identity
   maps each optimal dual under one slack onto an equal-LMP dual under
   another. Which member of that set the solver hands back is not guaranteed.
   Change the PTDF matrix and the simplex pivots differently, so under
   degeneracy it can land on a different vertex. Measured, case5 with every
   offer set to $25 and both limits removed:

   ```
   slack   alta  park_city  solitude  sundance  brighton
   ───────────────────────────────────────────────────────
     A       0        0        520       200      280
     C      40      170          0       200      590
   ```

   Same LP, same feasible set, different answer. LMPs held at $25 there only
   because nothing was congested and every μ was zero — with a binding line,
   the prices could have moved too. So: **slack choice is accounting. LP
   degeneracy is what moves the answer, and it moves it whatever the slack
   is.** That is trap 3, not this trap, and conflating them will send you
   hunting a PTDF sign error that is not there.
3. **LP degeneracy.** When multiple optimal bases exist, duals are arbitrary and prices flip between values on near-identical inputs. Not a bug.
4. **Min output without binaries.** A pure LP will run a 600 MW coal unit at 4 MW. Physically impossible. This is why UC exists.
5. **ERCOT has no loss component in its LMPs** — losses are socialized to load. A model with a loss term will not match ERCOT prices.

## Validation stance

Absolute price levels will be wrong; the fleet is synthetic and offers are cost-based. What should match published data is structure: when prices separate across the system, when the evening ramp bites, which hours go negative.

When the model says $40 and the market cleared at $180, the gap is usually a real market feature not yet modeled. Investigate it, don't tune it away.

## Reference

Kirschen & Strbac, *Fundamentals of Power System Economics*. Read chapters as the corresponding milestone comes up.
