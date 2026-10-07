# Contributing to the dated list of locks

This list is a **dated snapshot**, not an index. Every entry states what blocks a named harm today, who holds the lever, and **as of which date**. We do not forecast, we do not score, and we do not publish probabilities.

The most useful contribution is often the simplest: **a lock has fallen, here is the evidence and its date.**

## How to propose

Open an issue with one of the two templates:
- **New entry**: a defense that blocks a named harm, with its source.
- **State update**: an existing entry has changed (a lock has fallen, or a source confirms it still holds).

You can also open a pull request editing the YAML file of the family concerned in `list/`.

## What a proposal must provide

A proposal is **admissible** when it provides all of the following:

1. **The lock, quoted as its source names it.** Not your reading of it: the sentence itself. If the source does not name the lock, say so; the entry may still be published as `not-tested`.
2. **A primary source**, with its date. An article reporting an evaluation is not the source: link the evaluation. If the primary source is unreachable or paywalled, the entry can only be `not-tested`.
3. **One type**, from the closed list: capability, resource, identity, access, duration, tacit knowledge, installed control (`defensive-barrier` in the files), not tested. If two types seem to fit, propose `not-tested` and say why.
4. **The named harm** the lock currently prevents.
5. **The state, with its date** (`state_as_of`) and what establishes it (`state_source`). An old source does not establish today's state.
6. **Who holds the lever**, as a fact, not as blame. If the source is silent, write `unspecified`; never infer it.

Fields you cannot fill take one of two values, and they are not interchangeable: **`not-tested`** means nobody has checked; **`unspecified`** means the source is silent on that field. No field is left empty.

## What gets a proposal rejected

- **An inferred lock.** If we cannot quote a source naming it, it is not a lock in this list.
- **Any way through.** We publish what blocks, never a way around it: a permissive configuration, an unguarded provider, a working sequence. **Such contributions are neither accepted nor published, and they are not kept privately for later.** If your finding is real and dangerous, report it to the parties concerned, not here.
- **Forecasts, probabilities, timelines.** "Likely within two years" has no place in a snapshot. What we accept is what is missing and what would lift it.
- **Blame.** The lever holder is stated as a fact.
- **Self-interested material without flag.** A source with an interest in the lock is admissible, flagged `self-interested: yes`, and it cannot be the only source supporting an entry.

## How we handle proposals

- **We answer every proposal within 48 hours during the first month** after publication, and within a week afterwards.
- **Every decision is public and reasoned**, in the issue. Rejections say which criterion failed.
- **A lock that has fallen is not deleted.** It changes state, and the date is kept. That is what makes the series readable a year from now.
- **Contributions are credited** in the entry's history.

## What this list will never become

- **A score, a ranking, or a clock.** No aggregate number is derived from the entries.
- **A source of operational detail.** See "any way through" above.

## Licence

By contributing to `list/`, you agree that your contribution is published under CC BY 4.0. Contributions to `trend/` are published under the MIT licence.
