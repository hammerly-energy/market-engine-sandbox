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

## How to write a comment in this repo

The prose in `src/`, `web/` and this file is read by people who did not write
it, including the author six months later. It carries the decisions, because
the code carries only the outcome. What follows is the register for that
prose, and it applies to comments, docstrings, captions, on-screen notes and
to edits to this file.

**A comment states a fact, a measurement, or a decision and its reason.**
Anything else is padding. The test: delete the sentence and ask what the
reader no longer knows. If the answer is "nothing", it was decoration.

**Do not shout.** No all-caps sentences, no all-caps phrases for emphasis.
Caps are for identifiers that are literally capitalised — `MW`, `PTDF`,
`INK_MUTED`, `SUPERSEDED`. Emphasis comes from position: put the load-bearing
sentence first in the block. A comment that shouts three times has told the
reader nothing about which of the three matters.

**Sentence case in prose.** Title Case belongs to titles and headings only —
figure panel titles, section headings, the HTML `<title>`, control-group
headings. A sentence inside a comment is a sentence.

**No rhetorical scaffolding.** These are the tells, and they had colonised
eight files before anyone counted them:

- *"...which is the failure this module exists to prevent"* — name the
  failure, then stop.
- *"...and that is the whole point / the whole design / the entire
  difference"* — if it is the point, it is already the first sentence.
- *"X is not a Y, it is a Z"* — say what it is. The antithesis is only worth
  the words when someone actually believes X is a Y, and then the belief is
  worth naming.
- *"the most important line in that file"*, *"the single most honest thing
  this site can show"* — superlatives about your own work. Cut, or replace
  with the measurement that earned them.
- *"a deliberate limit rather than an oversight"* — defending the code
  against an accusation nobody made.

**Claims about what a reader would think are weak; claims about what was
measured are strong.** "A reader would find this confusing" is untestable.
"`#8a8880` on `#fcfcfb` is 3.46:1, under AA's 4.5" is a fact, and it is the
sentence that actually justifies the change.

**Give an equation room to breathe.** A formula belongs on its own line,
indented, with the symbols defined around it — never buried mid-sentence:

```
    left = (v - min) / (max - min)      of the inset rail

A range input's travel is the track minus the thumb, so the thumb centre
never reaches either end.
```

**Comments go stale, and a stale comment is worse than none.** When a number
in a comment is measured, date it to the milestone that measured it, so a
later contradiction is visible as a contradiction rather than read as truth.
`controls.js` still called the slack-invariant LMPs "bit-identical" for a
whole phase after trap 2 was corrected to say they are equal to ~1e-13.

**Length is earned by content, not by importance.** A formulation decision
with three measurements and a rejected alternative can run thirty lines. A
CSS rule cannot, however important the rule is.

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
- **Titles and subtitles are Title Case. Everything else is sentence case.**
  The split is by *role*, not by size: a title names the thing, and the extra
  capitals are what make it read as a name rather than as the first sentence of
  the caption. A label is read against an axis or a column and wants as little
  ink as the meaning allows.

  **Title Case** — figure panel titles, page and section headings, the HTML
  `<title>`, control-group headings. The rules, and they are the ordinary
  English ones:

  - **Always capitalize the first and last word** of a title and of a
    subtitle, whatever part of speech they are.
  - **Capitalize major words:** nouns, pronouns, verbs including linking
    verbs, adjectives, adverbs. And prepositions of four letters or more —
    `Against`, `Across`, `From`, `With`.
  - **Lowercase minor words:** articles (`a`, `an`, `the`), coordinating
    conjunctions (`and`, `but`, `or`, `nor`), and short prepositions (`in`,
    `on`, `at`, `to`, `by`, `of`).
  - **Capitalize the first word after a colon, an em dash, or end
    punctuation**, even if it is a minor word.

  **Sentence case, with a capital first letter** — axis labels, legend
  entries, annotations, table column headers, inset tables, captions, notes
  and every other piece of display text. A column header is an axis label for
  a table and follows the axis rule, not the title rule.

  **Identifiers beat both.** Anything that comes from the data keeps its
  literal form wherever it appears, first or last word included: `g1`, bus
  names, `λ`, and the units, which keep their real capitalization (`MW`,
  `MWh`, `$/MWh`) because case is meaning there. `Sensitivity of DE` is
  correct and `Sensitivity of De` is not.
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
  `$/MWh`, Title Case for titles and sentence case for labels, units on the
  axis label once. A web figure is not licensed to be sloppier than a printed
  one.
- **Hover may carry precision the figure does not.** A tooltip is allowed to
  give four decimals where the mark is rounded. It may not carry an argument
  or a sentence the figure needed to make itself.
- **Motion is for continuity, not for decoration.** When a lever moves, marks
  transition so the eye can follow which bus went where. Nothing pulses,
  bounces, or animates on load. A price that changes instantly is a price the
  reader cannot track to its new value.

Colour is assigned by identity in a fixed order and never cycled. In
`src/viz/` that holds for every mark, and the shared palette is why a figure
in the PDF and a view on screen agree.

**The network map is where the two parted, at W3.2.** A printed figure has no
live price to carry, so it can spend colour on identity; the map has one, and
spends it there. A bus on screen is a neutral disc with its name inside and a
price ring around it. Names carry identity on screen. A view that does encode
a generator by hue — the merit-order stack — takes it from the shared
palette, in the same order.

**The generator square is the exception, from W3.4, and it is a reversal.**
W3.2 left the square plain `--ink-2` on the grounds that a unit is dispatched
rather than priced. That was correct while no view coloured a unit. The merit
stack does, and it is the one view that prints a generator's name, so the
square takes that unit's hue and a reader can carry `E1` from the named block
to a mark the map has no room to label. `genInk()` in `web/js/scales.js`
is the single definition both views read.

The hue fills the square and `--ink-2` keeps the edge. Outlining in the hue
was measured and dropped: `--hue-4` `#56b4e9` on `--surface` is **2.2:1** and
`--hue-1` `#e69f00` is **2.1:1**, both under the 3:1 a non-text mark is held
to, and a thin outline is all edge. Filled, the shape is carried at 7.73:1 by
the edge and the hue only has to be told from four others.

Two things this does not reopen. The bus ring still carries no hue, for the
deuteranopia measurement below. And the square survives W3.6's line ramp
because **hue on this map is now split by mark shape, not by scale** — a blue
square and a blue wire are told apart by their outline before their colour.
Re-check it against the rendered ramp rather than trusting that sentence.

### Colour on the network map: settled at W3.2

**A bus is a neutral disc with its name inside it, and the ring around it is
its LMP.** There is no bus identity colour anywhere on the page any more —
not on the map, not on the price table's swatch, not on the lever rows.

That reverses what this section said while the question was open. The old
text held that identity "is not disposable" because it makes a bus
recognisable across the views sitting next to it. What it missed is that a
bus already carries its name, and a name is the stronger identifier; the hue
was a second channel spent on a question the reader was not asking. Spending
it on price instead is what a map of prices is for.

**The ring takes no hue at all, and that is a measurement rather than a
taste.** The line ramp runs blue to vermillion. Under deuteranopia every warm
hue collapses toward that vermillion and every cool hue toward that blue, so
there is no third hue free on this map. The channels therefore split by mark:

```
    lines   carry hue         and carry direction with it
    buses   carry lightness   and carry level with it
```

Nothing collides under any colour vision, and the map is literally rather
than approximately grayscale-safe, which is what the print register asks for.

**The ramp, measured against `--surface #fcfcfb`:**

```
    cheap   #919191   3.07:1      every stop clears the 3:1 a non-text
            #7d7d7d   4.01:1      mark is held to, so "every state is
            #6a6a6a   5.27:1      visible" is measured and not hoped
            #575757   7.04:1
            #454545   9.34:1
    dear    #242424  15.12:1
```

Interpolated in CIE L\*, 60 down to 14, not in sRGB — the sRGB midpoint of
those two greys sits four L\* units light of centre. The lightest stop is
close to the wire grey `#8a8880` that paints an idle line at 3.46:1. They are
a thick ring and a thin line and never touch, but it is the one place on the
map where two scales come near each other.

**The price is carried twice, in lightness and in width** — 2.5 to 7 user
units of stroke. Redundant on purpose: a double encoding survives a grayscale
print, a cheap monitor and every colour vision type, and the two channels
cannot drift apart because both read the same position on the domain. Width
also gives the eye an edge-to-edge comparison that lightness alone does not.

**The domain is fixed across the day and printed.** Across the day, because a
scale that rescaled when the hour moved would make the colour change when
only the scale changed, and a visitor scrubbing the day would read that as a
price change. Not across the session: a new solve is a different market whose
prices can leave the old domain entirely, and clamping them would hide the
most interesting thing a lever can do. The bounds are printed instead, so a
domain that moved is visible as a domain that moved.

A legend is mandatory the moment colour stops meaning identity, because an
unlabelled ramp is a picture of a number the reader cannot read off. It is
drawn as a **wedge** — thin and pale at the cheap end, thick and dark at the
dear one — since a flat bar would key only half the encoding. Its gradient is
built from the same function that inks the rings, so the key cannot drift
from the marks it explains.

Three smaller decisions that fell out:

- **Unpriced is thin and dashed, never pale.** A pale ring is the cheap end
  of the ramp and would assert a price of zero for a bus that is one round
  trip old.
- **The buses go stale, the wires do not.** The disc group carries
  `data-results`, so a refused solve dims the prices and leaves the topology
  at full strength. It is the answer that is out of date, not the picture of
  the network.
- **The slack ring sits at r = 26.** The price ring reaches r + 3.5 = 20.5 at
  its heaviest, and at 24 the two read as one thick mark on bus D.

#### What this fixes for the line ramp at W3.6

Two things about the line scale were settled here and are recorded so W3.6
does not re-decide them.

The ramp's neutral is `#8a8880`, **not** the `#f0efea` it was first drawn
with: `#f0efea` on `#fcfcfb` is **1.12:1**, so an idle line painted the
midpoint would be invisible. Diverging ramps assume a mid-lightness ground
and this page has none. `#8a8880` is already what an idle line is painted, so
nothing changes on screen until the ramp lands.

And the variable is **`f / limit`, signed, on `[−1, 1]`** — not percent of
rating. Percent of rating runs 0 to 100 and is natively sequential; a
diverging ramp needs a signed quantity, and the signed one carries direction
and loading in a single number. Blue and vermillion are then the two flow
directions, neutral is an idle line, and **70% is a saturation threshold, not
the midpoint** — the legend has to say that in those words, or a reader takes
the hue for magnitude. An unrated line is `f / ∞ = 0` and paints neutral
forever, which is correct and also belongs on the legend.

`f / limit` is arithmetic, so `clear()` returns it and the browser does not
compute it — the same rule, and the same reason, as `headroom`.

#### What W3.6 landed

The ramp, and the panel it is keyed under. `clear()` grew `loading` —
`f / limit`, signed, clamped to `[−1, 1]` because the solver returns
`-240.00000000000003` for a line rated 240 and a ramp indexed past its own
domain is a colour nobody chose. `flowInk()` in `web/js/scales.js` is the one
definition the panel's bars and the map's wires both read.

Interpolated in CIE Lab from the neutral to each end, measured against
`--surface #fcfcfb`:

```
    toward blue                     toward vermillion
    0.00  #8a8880   3.46:1          0.00  #8a8880   3.46:1
    0.25  #737581   4.46:1          0.25  #987664   4.00:1
    0.50  #5b6381   5.77:1          0.50  #a06349   4.68:1
    0.70  #455681   7.05:1          0.70  #a55433   5.22:1
    1.00  #104281   9.66:1          1.00  #a8380f   6.32:1
```

Contrast rises monotonically from the neutral in both directions, so the idle
line is the minimum and every stop clears the 3:1 a non-text mark is held to.
Both ends are dark and the middle is light, which is what carries *magnitude*
through a grayscale print. **Direction does not survive that print**, and it
is carried by position in the flows panel — the bar sits on the side of zero
its flow is on — which is why direction is stated there and not on the map.

**No threshold is marked, and the 70% above is not one.** The domain is the
rating itself, so the track's ends *are* the limit and there is no
intermediate number for a reader to mistake for the midpoint. The sentence
this section used to require on the legend is therefore unnecessary rather
than omitted.

**An unrated line has no track at all**, and that is the panel's one real
design decision. `f / ∞ = 0` says it can never bind, so "how close is it to
its limit" has no answer; a bar drawn against the largest flow on the panel
would be a second scale in the same column, and a reader would compare two
lines that were never measured the same way. The flow is printed and the
track says `no rating`. Four of case5's six branches are unrated, so most of
the panel is that state, which is the honest picture of why the same two
lines carry every μ in the ledger.

**A full bar and a priced μ are the same fact reached twice** — once from the
primal, once from the dual — so the panel draws the bar from `loading` and
the binding mark from `mu`, and neither is derived from the other.

One thing the ramp broke and fixed. A branch label's stroke halo follows the
glyph outlines, so a wire showed through the gap between two letters: `DE`
was struck through the moment it was painted `#104281` at its rating.
Invisible while every wire was pale grey. The label now sits on an opaque
surface plate, which is CLAUDE.md's own bbox rule applied to the map.

### What the engine already refuses

Measured against the M3 case5 scenario, not assumed. This table exists so W1
does not spend a day rediscovering it, and so a new failure found later can
be checked against a list of what was already true.

| A visitor does this | What happens now | Verdict |
|---|---|---|
| Cuts a line, islanding a bus | ~~`ValueError: network is disconnected`~~ → prices each island separately, one λ each | **Was** clean, named and displayable. It was also the wrong answer — see below |
| Names a slack that is not a bus | `ValueError: slack 'Z' is not a bus in [...]` | Clean, and kept — `slack=` is an assertion by the caller |
| Deletes the bus the *config* names as slack | Falls back to the first bus, and reports it | New at W1 — see below |
| Adds a branch with zero reactance | `ValueError: reactance_pu must be > 0` at `Branch.__post_init__` | Clean, caught at construction |
| Duplicates a bus or branch name | `ValueError` at `Scenario.__post_init__` | Clean |
| Adds a bus with no generator and no load | Prices correctly. The bus gets a real LMP | **Not a bug.** Do not "fix" |
| Adds a second line between two buses | Solves correctly | **Not a bug.** Parallel lines are physical |
| Sets capacity below load, demand priced | Sheds the least valuable MW, λ rises to the highest bid | Fixed at W1 — a scarcity price, not an error |
| Sets capacity below load, demand inelastic | `RuntimeError: solve not optimal: infeasible` | The last refusal standing. Unreachable from the editor, which emits only `blocks` |
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
- **M0–M4 must not move.** With `v` above every offer the block is always
  served in full, so every existing number is unchanged. That equality is the
  acceptance test for the change, not a nice-to-have.

  How much of it is *bitwise* was measured at W2.6, m4.yaml against w1.yaml:
  **every LMP is exactly equal, and dispatch differs by 2.3e-13.** Adding a
  demand variable is a different LP, so the primal is free to land a few ulps
  away even where the prices do not — which is why the test asserts with
  `pytest.approx` and is right to. See trap 2 for the general statement.

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
`configs/m4.yaml` as priced bids and must clear to the same numbers — every
LMP bitwise, the primal to solver tolerance, as measured above — today
because the price is ignored and afterwards because a bid at the cap outbids
every generator.

### W1 decision: what an island means

**Two markets, not an error.** A cut network is priced component by
component: one energy balance row, one λ, one slack and one settlement
identity per island.

The insight that makes this a forty-line change rather than a rewrite is that
**an island is a balance constraint, not a PTDF.** `ptdf.py` refused because
a disconnected `B_bus` carries two zero eigenvalues and the rank-1 fix
removes one — a linear-algebra symptom. The market problem was one line away
in `dispatch.py`: a single system-wide balance row says total generation
equals total demand, which lets a generator in one island serve load in
another through a line that does not exist, and no flow limit objects because
the constraint set only contains lines that exist.

```
  one balance row, two islands              one row per island
  ────────────────────────────              ──────────────────
  Σ p  ==  Σ D                              Σ    p  ==  Σ    D      island 1
     ↑                                       g∈I₁         i∈I₁
  E1 at E serves B's load                   Σ    p  ==  Σ    D      island 2
  through a line that isn't there            g∈I₂         i∈I₂
```

So the PTDF goes **block diagonal** — an injection in one island moves no
line in another, which is physics and not bookkeeping — and `m.inj`, `m.f`
and both flow limits are untouched. Only the balance is re-indexed.
`ptdf_blocks()` assembles the blocks by calling `ptdf()` per component, so
there is no second implementation of the linear algebra. `ptdf()` itself
keeps refusing a disconnected network, because a PTDF relative to one slack
*is* a single-component object.

**Islands are named by their slack**, and λ is keyed `(island, hour)`. λ is
the LMP at the slack, so the name is the honest one; an index would mean
nothing to a reader and would renumber the moment another line is cut. The
wire carries `lmbda` as `{island: [per hour]}` always — never a bare array,
because a shape that changes with the topology is a shape the frontend
branches on, and it would branch wrong the first time someone cut a line.

**The user's slack keeps its island; every other island takes its first bus**
in config order. Deterministic, reproducible from the config alone, and
returned rather than chosen privately — a number the UI displays may not be
picked silently.

Two cases fall out and neither is a bug:

- **An island with load and no generation** sheds and prices at the cap. Only
  reachable because the elastic demand side landed first; before that the
  island was infeasible and took the whole solve down with it.
- **An island with generation and no load** is degenerate. `p = 0`, `d = 0`,
  and λ sits anywhere between zero and the cheapest offer. Trap 3, and the
  view must say so rather than print the number as though it meant something.

Settlement is now per island **and** per hour. Summing the islands would let
a positive residual in one cancel a negative one in the other — the per-hour
mistake, one dimension over.

### W1 decision: what happens when the slack is deleted

**Chosen when it came from the config, refused when the caller named it.**
Those are two different claims and they deserve two different answers:

| | | |
|---|---|---|
| `clear(scenario, slack="Z")` | **raises** | An assertion by this caller about this call. A typo that silently answered about a different bus is how a sweep reports a day of the wrong λ and nobody notices |
| `provenance["slack"]` names a deleted bus | **falls back to `buses[0]`** | A *record*, written at parse time and stale by the time the editor deleted that bus |

The editor holds the slack in its own state, so deleting a bus leaves the
config naming one that is gone. Refusing there would make deleting the slack
the one edit that breaks the site — and it would refuse for no physical
reason: the slack is an accounting origin (trap 2), any bus works, and no LMP,
dispatch, flow or settlement figure depends on which. Only the **level of λ**
moves, because λ is the LMP at the slack.

**Consequence for W2, decided: the editor keeps posting an explicit `slack`
and updates its own state when that bus goes.** It holds the bus list, so
deleting a bus and leaving the dropdown pointing at it is a client bug, and
the 422 is the engine telling it so. Dropping the field and relying on the
config's recorded slack was the alternative and is not taken — it would trade
the typo check away to paper over a bug the editor is in the best position to
prevent.

Which leaves the fallback as a safety net the editor should never trigger. It
still earns its place: a sweep, a notebook, or a hand-edited config can all
carry a recorded slack that no longer exists, and none of them has a dropdown
to keep in step.

**Silent in the sense that it does not raise. Not silent in the sense of
unreported.** The chosen slack comes back under `slack` and names its island
in `islands` and `lmbda`, so a caller that asked for a bus which is gone can
see which one it actually got. Same rule `island_slacks()` follows, and it is
the whole reason this is a fallback rather than a secret.

Three properties, all tested:

- **Reproducible.** First bus in config order, derivable without running
  anything.
- **It fires only when the named slack is actually gone.** Deleting an
  unrelated bus does not move it — a slack that wandered would make λ jump on
  screen for no reason a reader could see.
- **No price moves.** Only λ and the congestion split change, and they cancel.
  Not *bitwise*, though: the fallback lands on a different slack, so it is a
  different PTDF and a different LP, and the cancellation leaves float64
  debris of order 1e-13. Assert it with `pytest.approx`, and see trap 2 for
  the measurement and the tolerance.

### W1 deliverable: the topology fuzz

`tests/test_w1_fuzz_topology.py` builds random networks from the moves the
editor has — add a bus, connect a line, add a generator, price a bid, name a
slack — and asserts that each one returns **either a priced solve satisfying
every invariant, or one named reason from a closed list**. 120 seeds, no new
dependency; a failure names its seed and rerunning that seed reproduces it.

The second half of the file asserts **the corpus itself**, and that is what
stops the first half being theatre: a fuzz that happened to generate only
connected five-bus networks would satisfy every assertion and test none of
the cases W1 exists for. So it is asserted to actually contain disconnected
networks, three-or-more islands, isolated buses, empty buses, parallel
branches, curtailment, a binding line, and each named refusal.

It found a real bug on its first run. **An island containing no generator, no
priced bid and no inelastic load makes `0 == 0`** — a Python bool, not a
Pyomo expression — and Pyomo refuses to build the model with a message about
`Constraint.Feasible` that says nothing about a network. Two cases, two
meanings, both now resolved in `_balance` where the meaning is still visible:
vacuous is `Constraint.Feasible`, while inelastic load in an island with
nothing to serve it is `Constraint.Infeasible` and reaches the caller as the
named infeasibility.

**And it settled the open W2 question.** With every bid elastic, `d = 0` and
`p = 0` is feasible for any topology — zero injections, zero flows, every
limit satisfied — so a priced demand side cannot be infeasible on capacity.
That is now proved over 120 random networks rather than reasoned about:

| corpus | priced | infeasible |
|---|---|---|
| mixed elastic/inelastic | 59 / 120 | **31** |
| every bid priced | 90 / 120 | **0** |

So **the editor emits only `blocks` configs.** Inelastic demand on a random
topology is infeasible more often than not, and an editor that can build any
topology while insisting its load must be served is an editor whose most
ordinary move is an error message. The other refusals are untouched by this:
a one-bus network still has no network to price, and an empty fleet still has
nothing to dispatch. Those are statements about the scenario, not about
whether the market clears.

All three W1 formulation questions are answered and the deliverable is in.

### Degeneracy under a moving slider

Dragging a line limit walks the LP through thresholds where it is degenerate,
and there the price genuinely flickers between equally valid values on inputs
a pixel apart. Trap 3. **Do not smooth it, debounce it away, or average it.**

Show it. A price that is not unique is invisible in every commercial tool a
visitor has seen, and the engine already has the right instinct — M0 asserts
*bounds* at degenerate breakpoints rather than values, so a view that prints
one number there is claiming more than the market said.

That requires the engine to know it is degenerate, which it currently does
not. W2.9 settles the half of that which can be settled now.

#### W2.9 decision: the flag lands, the interval waits

**`clear()` returns a per-island, per-hour uniqueness flag. Whether the site
ever prints the interval is deferred to W4.**

They were one question all through W2 and they are not. The flag changes what
the page claims — from "the price is $15" to "$15 is one of several" — and it
is a count over fields `clear()` already returns, so it costs no extra solve.
About an hour in `pricing.py` and its tests, built at the top of W3.

The interval is a second optimization, and whether it earns its cost depends
on something that does not exist yet: whether W4's narrative walks a visitor
to a breakpoint deliberately, or whether a breakpoint is only ever stumbled
into mid-drag. If the first, the interval is the payload and a flag undersells
it. If the second, the flag is the whole job. Deciding that before the
narrative is written is guessing, so the cost is measured below and the choice
is left to W4.

The degenerate case is reachable from the editor in one move. Measured on
`configs/w1.yaml` with both line limits dragged to max, hour 8:

```
   A1   p =  40.0 /  40.0   at_max     rc =   1.0000
   A2   p = 170.0 / 170.0   at_max     rc =   0.0000
   C1   p =   0.0 / 520.0   off        rc = -15.0000
   D1   p =   0.0 / 200.0   off        rc = -25.0000
   E1   p = 600.0 / 600.0   at_max     rc =   5.0000

   λ = 15.0000
```

Load lands exactly on 40 + 170 + 600 = 810 MW, and A2 is full and indifferent
at once — the case `reduced_costs` already documents. The true
answer is `λ ∈ [15, 30]`, and the total cost curve is where that is visible:
sweeping the load at hour 8 gives a kink at 810, slope $15/MWh to its left and
$30/MWh to its right, with λ equal to the slope on each side. A convex kink
has no single slope, and the supporting slopes at it are the whole interval.

```
    load    served     cost $   λ        slope
     790     790.0     8810.0   15.00    15.0000
     809     809.0     9095.0   15.00    15.0000
     810     810.0     9110.0   15.00    15.0000    <- kink
     811     811.0     9140.0   30.00    30.0000
     830     830.0     9710.0   30.00    30.0000
```

λ tracks that slope only because nothing is congested here and every LMP
equals λ — measured, all five buses at $15.00 at that point. In general the
derivative of cost with respect to load at a bus is that bus's LMP, and λ is
the derivative at the slack, which is trap 2's statement in another form.

**Detection is a count, per island and per hour:**

```
    basic = # generators strictly inside their bounds
          + # bids strictly between 0 and their quantity

    rows  = 1  +  # lines with mu != 0
            ▲         ▲
     the island's   each binding limit
     balance row    is an active row
```

`basic < rows` means a row is held by a variable pinned at a bound, so the
dual has room to move and λ is an interval. Hour 8 above is `basic = 0,
rows = 1`. Every input is a field `clear()` already returns, which is what
makes detection a count rather than a second solve — the same count is
already written as `test_one_basic_unit_per_active_row`, where it is the
uniqueness precondition W2.8's slack assertion depends on.

Returning the interval is a second optimization and not a count: fix the
primal at its optimum, then maximize and minimize λ over the dual feasible
set. Two LPs per island-hour is 48 extra solves on case5, and the per-bus LMP
interval is a further two per bus per hour.

**The two directions are different sentences and must not collapse into one
`degenerate` bool.** `basic > rows` is the other degeneracy: the price is
unique and *who runs* is not. It is not a kink in the cost curve — it is a
straight stretch of it carrying two dispatches at the same cost — so the
curve above is a picture of the price ambiguity only, not of both.

**The example this section used to give does not reach it, and W3.1 measured
that rather than inheriting it.** Every offer set to $25 with both limits
removed gives λ = 25 under slack A and slack C alike, with A1 and A2 sitting
*off* at `rc = 0.0000` and able to swap in at no cost — the dispatch
table under trap 2. The count there is `basic 1, rows 1`, and the flag says
`unique`, correctly: it is a statement about the *price*, and the price was
never in doubt. Units sitting at a bound with a zero reduced cost are a
different test from the one the count performs, and the count does not claim
to run it.

Reaching `basic > rows` needs two units able to be part-loaded **at once**,
which equal offers alone do not arrange: with one capacity for all five the
solver loads them in order and exactly one lands interior. Found by sweeping
offers and ratings, and banked in
`tests/test_w2_degenerate_optimum.py`:

```
    three units at $25, AD rated 400 MW, DE rated 240, hours 20 and 21

    A1   interior   offer $25   rc 0.0000
    E1   interior   offer $25   rc 0.0000

    basic 2, rows 1        one uncongested row, two variables free
```

A MW moves between A1 and E1 at no cost, so the dispatch is one of many and
the price is still the one number.

The flag inherits the flicker rather than curing it. It reads `|mu| > 1e-9`
and the 1e-6 MW status tolerance in `generator_status`, so within a pixel of
the breakpoint the flag itself moves. That is trap 3 one level up, and the
rule above applies unchanged: do not smooth the flag either.

The pair of hours the flag has to get right is banked ahead of it in
`tests/test_w2_degenerate_optimum.py`: hour 8 with the limits off, and hour 7
of the same solve as its control. It also carries a negative result worth
having in one place. That fixture cannot flake W2.8's slack assertion, and
neither can any setting of w1.yaml's limits — swept over 1201 DE ratings and
all 24 hours, the only pattern this scenario reaches is `basic 0, rows 1`,
which is degenerate and uncongested. Measured there, all five slacks return
15.0000. So degeneracy and slack-sensitivity are independent on this network,
and the fixture that would show them together has still to be found.

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
| **W2** | The editor | The eight levers, against the live engine: line limit, peak load per bus, add/remove bus, connect/disconnect line, add/remove generator, edit generator capacity and marginal cost, hour 1–24, slack bus. | Every lever re-solves and redraws. **Deleting the slack bus moves the dropdown, it does not 422** — the editor posts an explicit `slack` and owns keeping it in step with the bus list, and the engine refusing a slack that is not a bus is the check that catches it failing to. The slack dropdown is the acceptance test, **on a fixture with a unique optimum**: moving it must rearrange the λ/congestion split while every LMP and every settlement figure stays put — to solver tolerance, not bitwise, because a different slack is a different LP; trap 2 has the measurement and the tolerance. A UI that shows prices moving with the slack has a bug in it. Run that assertion on a degenerate fixture and it will flake, correctly — see trap 2. | 1.5 weeks |
| **W3** | The views | **The page frame is decided first, before any view is coded** — the single 60ch column that carries four panels does not carry eleven, and a heatmap needs 24 columns of horizontal room a text measure will not give it. Retrofitting a grid under seven hand-coded views is the expensive order to do this in, and it is the same argument as settling colour at the top rather than mid-view. Then: network map with buses coloured by LMP — which is where W2.3's identity colouring is replaced, and the three questions under *Colour on the network map* are settled at the top of this milestone, not mid-view; LMP split into λ + congestion; merit-order stack; settlement ledger with the residual; line flows against limits; live generation by unit; 24-hour heatmap. Three of these need fields `clear()` does not yet return — **add them in W0, not mid-W3**: a per-bus `congestion[bus, hour]`, which `pricing.py` already computes and then discards; per-generator `cost` and `pmax`, without which no merit-order stack can be drawn; and per-generator **status** (`off` / `interior` / `at_max`) with its `headroom` and `reduced_cost`. Status, *not* "the marginal unit" — that field was written at W0 and replaced within the hour, because under congestion there is no single marginal unit and three of case5's five buses have an LMP equal to no offer at all. Bus *coordinates* are not an engine concern at all — they are editor state, and they belong to W2. | Every number on screen is traceable to a field of the `clear()` return. Nothing is recomputed in JavaScript — the browser formats and draws, it does not do market arithmetic. The residual is displayed, not hidden, because a visible `≈ 0` is the claim the whole repo rests on. Two views can be read against each other without scrolling between them, which is what the frame is for. | 1 w + 0.5 d |
| **W4** | The frame and the deploy | Narrative scroll, one section per engine milestone, each with its live figure and a link to the source that implements it. Equations rendered next to the code. Scope statement. Deployed. | A stranger can reach it at a URL, rewire the network, and leave understanding that λ is a dual variable. The scope statement is on the page, not in a footer. | 3 days |

#### W2, phase by phase

W2 is the one milestone big enough to need its own ladder, so it has one. Ten
phases summing to 9 days — half a day over the row's original 8.5, which is
what the keyboard path and the armed-state readout cost. A phase is done when
the page still loads and the suite still passes; report progress as *phase n
of 10*.

| | Phase | Est. | What lands, and the one thing that can go quietly wrong |
|---|---|---|---|
| **W2.0** ✓ | Serve the page | 0.5 d | `web/` skeleton, plain ES modules, no toolchain. `StaticFiles` mounted at `/` **registered last**, or the mount shadows `/clear` and the failure looks like a frontend bug for an afternoon |
| **W2.1** | Editor state | 1 d | The single source of truth the eight levers mutate; nothing else in the frontend holds state. `{buses: [{name, x, y}], branches, fleet, bids, shape, slack, hour, limits}`. **Coordinates are editor state and never cross the wire.** `toConfig()` emits w1.yaml's exact dict and **always `load.source: blocks`**. The **defaults policy** is written down, because a default is a market assumption wearing a UI detail's clothes. Client-side bound check against `/limits`, refusing before it posts — a courtesy, not the defence |
| **W2.2** | Transport | 0.5 d | `postClear(state)`, and **request coalescing**: a monotonic id per request, stale responses dropped. A drag fires many solves and they return out of order, so the last response is not the last request. This is *not* debouncing the price — the flicker at a degenerate breakpoint is kept and shown (trap 3). Error surface switches on the stable code and prints `detail` verbatim |
| **W2.3** | Minimal render | 1 d | Enough feedback to prove a lever worked, and no more: hand-written SVG buses and branches, a readout of LMP per bus, λ per island, and the settlement residual. Formatted only. Bus colour was identity here and was replaced at W3.2 by the price ring — see *Colour on the network map*. **The seven views are W3 — do not build them here** |
| **W2.4** | The five non-drag levers | 1 d | Line limit → the `limits` override, which is an argument to `clear()` and not a config edit. Peak load per bus, generator capacity, marginal cost. Hour 1–24 indexes the returned arrays and does **not** re-solve; the day comes back whole |
| **W2.5** | The editing grammar | 2.5 d | Add/remove bus, connect/cut line, add/remove generator. Drag a bus body to move it; every structural edit is an **armed mode** — press a button, then click the target. Hit-testing by hand in SVG. **This is where the plan overruns.** Checkpoint at the end of its second day: if drag is still fighting you, adopt a framework for the editor alone. That retreat is correct on day 2 and worthless on day 9. Three things ride along because they are the same hit-testing and the same state: the **armed-state readout**, the **keyboard path** (focus and activate, never a shortcut), and **undo**, pulled forward from W2.7 — see *W2 decision: the editing grammar* |
| **W2.6** | The slack lever | 0.5 d | A dropdown over the bus list, posted explicitly on every request. **Deleting the slack bus moves the dropdown; it does not 422.** The editor owns keeping slack in step with its bus list, and the engine's refusal of a non-bus slack is the check that catches it failing to |
| **W2.7** | The register fixes | 0.5 d | Three small things a usability review found, batched so the page is re-rendered and looked at once rather than three times. **Wire labels get their own screen token** — `--ink-muted` is 3.46:1 on the surface and branch names are load-bearing, not decorative; **the hour slider is visually distinct** from the four that re-solve, because that difference currently lives only in prose; **results sit above the levers**, so a moved slider does not land its answer below the fold. Half a day because CLAUDE.md requires rendering and inspecting each one, and moving one label routinely creates a collision somewhere else |
| **W2.8** ✓ | Acceptance tests | 1 d | The slack assertion, **on a fixture whose optimum is verified unique first**: moving the slack rearranges λ and the congestion split while every LMP, payment, revenue and rent stays put. **`pytest.approx(abs=1e-9)`, not equality** — a different slack is a different LP and the cancellation leaves ~1e-13 on prices and ~1e-10 on payments (trap 2). Assert the other half too, that λ *moved* by a margin outside that tolerance, or the test passes on a build where the lever does nothing. On a degenerate fixture it would flake, correctly — trap 2 against trap 3 — and that remains **untested**, because no such fixture exists here: W2.9 swept the DE limit over 1201 settings and all 24 hours and the only degeneracy w1.yaml reaches is uncongested, where trap 2 says λ does not move with the slack anyway. Proving the flake needs a scenario that is degenerate *and* congested, and finding one is open. Plus the delete-the-slack test, and `toConfig()` round-tripping to w1.yaml's numbers bit for bit. Two things the row did not anticipate, both measured: **λ moves only where a line binds** — see trap 2 — and uniqueness is checkable from fields `clear()` already returns, so it is a test rather than a remark. The emitter is JavaScript, so its half runs in `web/check-emit.html` |
| **W2.9** ✓ | The degeneracy decision | 0.5 d | **Decided: the flag lands, the interval waits.** `clear()` grows a per-island, per-hour uniqueness flag, read off fields it already returns at no extra solve — built at W3.1, returning `basic`, `rows` and one of `unique` / `price_is_an_interval` / `dispatch_is_not_unique`. Whether the site ever prints `λ ∈ [15, 30]` is deferred to W4, because it is a second optimization whose worth depends on a narrative that does not exist yet. The degenerate case is reachable from the editor in one move and was measured rather than assumed — see *W2.9 decision: the flag lands, the interval waits* |

Two things W2 does not touch: the seven views (W3), and market arithmetic in
JavaScript (never). If a lever needs a number `clear()` does not return,
`clear()` grows.

#### W2 decision: the editing grammar

**Drag moves a bus. Every other structural edit is an armed mode.** Press
*Add bus*, *Add line*, *Add generator* or *Remove*, then click the target.
No modifier keys, no right-click, no keyboard shortcuts — one grammar, and
the same one for adding and removing.

```
  idle  ──press a button──>  armed  ──click a target──>  edit applied, idle
   ▲                           │
   └──── Esc, or press the ────┘
         armed button again
```

The consequence that matters is not stylistic. With drag reserved for moving,
**a bus is never a drop target**, so hit-testing only has to answer *which
mark is under the pointer* — there is no drag-source/drop-target distinction
and no rubber-band line to hit-test against. That is most of what the ladder
flags as W2.5's overrun risk, removed by the grammar rather than by
cleverness.

Three things follow, and they are in W2.5 rather than later because they are
the same hit-testing and the same state object:

- **An armed mode must be visible.** A pressed button state, a cursor, and a
  readout naming the mode. A visitor who arms *Add line*, gets distracted, and
  later clicks a bus must not silently connect two buses they had stopped
  thinking about.
- **Undo is pulled forward from W2.7**, and it is what makes *Remove* safe
  rather than a confirmation step. A confirm taxes the most exploratory act on
  the page, and the site's whole pitch is that rewiring is safe to try;
  editor state is plain data, so a snapshot stack is a `structuredClone` per
  mutation. Cheaper than the dialog it replaces, and it removes a class of
  question rather than answering one.
- **A keyboard path, which is focus and activate — not a shortcut.** Marks
  become focusable and Enter completes an armed mode. This does not reopen
  the no-shortcuts decision; it is the ordinary activation semantics a button
  already has, extended to the click half of the grammar. Without it W2.5
  ships a page where every slider is keyboard-operable and no structural edit
  is, which is a regression visible in the same session.

#### W2 decision: `--ink-muted` is a print token, and the screen needs its own

Measured, not eyeballed: `#8a8880` on `#fcfcfb` is **3.46:1**, under AA's 4.5
for normal-size text. It paints the branch labels on the network map, and a
branch name is load-bearing — the map is unreadable without knowing which
line is `DE`.

The trap is that this looks like a one-line CSS fix and is not. `#8a8880` is
`INK_MUTED` in five modules under `src/viz/`, so it is the shared screen-and-
print palette, and editing `style.css` alone would silently desync a grey
between the PDF and the page — the exact drift the shared palette exists to
prevent.

So: **wire labels get their own screen token near `--ink-2`** (7.73:1), and
the print figures are left alone. Recessive on paper at 300 dpi is a
different problem from recessive on a backlit monitor at 14 px, and the
register's demand is that text be recessive, not that it be the same hex
everywhere. `--ink-muted` keeps its meaning for what is genuinely decorative.


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
   identical dispatch and identical μ — identical in real arithmetic; see
   below for what that is worth in float64. The two matrices agree only *on*
   the balance hyperplane, so the Lagrangian splits the same total price
   differently between the balance row and the flow rows — λ absorbs the
   difference, and the sum is physics.

   Consequence for testing: a slack bug is **invisible in settlement**. Every
   bill is right whichever slack is wrong. It shows only if λ and the
   congestion component are asserted separately.

   **And only where a line binds.** With every μ zero the LMP is one number at
   every bus, so λ is that number under whichever slack and there is no split
   to rearrange. Measured on case5: λ moves at hours 07-22 and is identical
   across all five slacks at 00-06 and 23. A slack test written over the whole
   day asserts nothing in a third of it, and one written over the uncongested
   hours asserts the opposite of what it means to.

   **"Identical" here is a statement about real arithmetic. In float64 it is
   a tolerance, and this file said "bit-identical" until W2.6 measured it.**
   Changing the slack changes the LP's *coefficients* — a PTDF relative to a
   different origin is a different matrix, correctly so — and HiGHS then
   factorizes different bases and pivots on different numbers. The primal
   moves before any price is assembled. Measured, case5, slack A against
   slack D, worst over all 24 hours:

   ```
   dispatch   6.8e-13      the primal itself, not just the duals
   flows      2.2e-12
   mu         3.9e-13
   lmbda      22.97        <- the real move, and the only intended one
   LMP        1.7e-13
   payments   9.8e-11
   ```

   Two things to take from that. First, **the solver is deterministic and the
   input is what changed**: the same scenario at the same slack, solved twice,
   gives bitwise-equal LMPs. Second, the cancellation is *arithmetic*, not
   structural — λ moves +$23 and `Σ PTDF·μ` moves −$23, summed in a different
   order over different products at intermediate magnitudes around $30, where
   one ulp is ~7e-15. Debris of order 1e-13 is the expected size of that
   cancellation, not a symptom of anything.

   None of this is HTTP's doing: the same comparison in-process gives the identical
   figure to every digit, and the JSON round trip is exactly lossless — Python
   emits shortest-round-trip float reprs and `wire.encode` copies floats
   without touching them.

   So assert this invariance with `pytest.approx`, and pick the tolerance to
   sit far above the debris and far below any real move: `abs=1e-9` clears the
   measured 9.8e-11 by three orders and would still catch a price that
   actually moved. **And assert the other half too** — that λ *did* move, by a
   margin outside that tolerance. A test that only checks "no LMP moved"
   passes on a build where the slack lever does nothing at all. The repo's
   tests already work this way (`test_w1_islands.py:307`, `:323`); it was only
   the prose here that claimed bitwise.

   **The precondition is a unique optimum, and it is not decorative.** What is
   slack-invariant is the *set* of optimal prices, because the shift identity
   maps each optimal dual under one slack onto an equal-LMP dual under
   another. Which member of that set the solver hands back is not guaranteed.
   Change the PTDF matrix and the simplex pivots differently, so under
   degeneracy it can land on a different vertex. Measured, case5 with every
   offer set to $25 and both limits removed:

   ```
   slack     A1    A2    C1    D1    E1
   ───────────────────────────────────
     A        0     0   520   200   280
     C       40   170     0   200   590
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
