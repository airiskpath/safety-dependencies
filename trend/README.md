# How fast do ATLAS techniques move up a grade?

This repository holds **one measurement and the code that produces it**. Clone it, run one
command, get the same numbers we publish. If you don't, that is a result too — tell us.

## What is measured

MITRE ATLAS grades each technique it catalogues: *Feasible*, *Demonstrated*, *Realized*. That
makes two gates. We measure whether crossing them is getting faster, and whether any speed-up
is simply the pace of the team that maintains the catalogue.

Both gates are being crossed faster than they used to be: **about 1.5 and 2.2 times faster per
year of entry**, after controlling for editorial activity.

**The uncontrolled figures are higher** — about 1.7 and 2.5. We publish the lower ones.

## What this does not establish

**It is difficult to tell a domain that is accelerating from a catalogue that is better kept.
Our hypothesis is that both effects are present, and this measurement cannot separate them.**

The editorial control removes only 5 to 11% of the trend — but it has almost no detection power
before 2025, because ATLAS rewrote 30 of its 37 published versions in a single commit on
27 May 2026, and the rebuilt older versions record almost no editorial change. So "the trend
survives the control" holds for the recent period, and is untested before it.

Two further biases push the same way and are corrected by nothing here: 24% of techniques appear
directly at the highest grade, and the dates of older entries come from that rebuilt history.

## Exact output

The rounded figures above are what we publish in prose. The exact values are what `make tendance`
prints, and they are the ones to cite in technical contexts:

| Gate | Year alone | + editorial volume | + per-technique edits |
|---|---|---|---|
| feasible → demonstrated | 1.662 | 1.529 | **1.546** [1.28 ; 1.89] |
| demonstrated → realized | 2.519 | 2.384 | **2.228** [1.55 ; 3.49] |

Intervals are 95% profile-likelihood. Run the command and compare: a difference is a finding,
not a bug on your side.

## Run it

    make tendance      # clones the pinned ATLAS sources if needed, then computes
    make check         # runs the tests, including solver validation

Requires Python 3.11+, `pip install -r requirements.txt`.

## Why you can trust the numbers — or catch us out

**The sources are pinned and re-verified on every run.** The 37 published ATLAS versions are
listed with their SHA-256 in `data/tendance-versions.json`, and the upstream repository by its
commit. **The program refuses to compute if any of them differs.** This is not decoration: ATLAS
rewrites its own history, and a silent mismatch would compare two different reconstructions
without anyone noticing.

**The solver is validated before it is believed.** Cox proportional hazards with Efron's
correction for ties is implemented here rather than imported, so the tests check it against
cases where the answer is known:

- a case solved by hand — two tied subjects with covariates 1 and 0, where the likelihood has its
  maximum at exactly β = 0;
- a test that **fails if anyone swaps Efron for Breslow**, by comparing the log-likelihood to its
  closed form;
- a simulation with a known coefficient, where the estimate recovers it and the profile-likelihood
  interval covers it.

**Confidence intervals come from the profile likelihood, never from Wald.** With 45 events on the
second gate, asymptotic normality is not available, and the profile does not assume it.

**Controls are time-varying**, in (start, stop] form. A fixed value per technique would control
nothing: a technique that entered in 2022 passes through quiet and busy editorial periods.
`maturity` and `employs` relations are excluded from the controls by construction — including them
would control the effect with itself.

**One trap worth knowing about.** MITRE often rewrites a technique's description in the same
version that raises its grade. A control counting "edited during this period" therefore measures a
*consequence* of the grade, not a confounder: using it removes the very effect being measured. All
controls here are lagged by one version. A test enforces this.

## Survival curves

`make tendance` also writes Kaplan-Meier curves for both gates. On the second gate the median is
**55 months**, but **its confidence interval has no upper bound** on the data available
[35 months ; not reached]: at five years, a little over a third of techniques have crossed it
(S = 0.38 at 64 months). The median does not travel without that interval.

## Licence and provenance

Code: see `LICENSE`. ATLAS data is MITRE's, under Apache 2.0, and is not redistributed here —
only its SHA-256 fingerprints, so you can verify you are computing on the same bytes we did.
