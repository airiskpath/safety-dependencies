# Safety dependencies

**What still blocks attacks carried out with AI, who holds it, and since when.**

What stops an AI agent from doing damage is often not in your code: a provider closing an account, a lab keeping a model under lock, a human reviewing code before accepting it. These defenses belong to others, and nobody warns you when they give way. This repository lists them, dated, with their sources.

- **The list**, as of 26 September 2026: [`list/`](list/). One file per family of defenses, every entry with its primary source, its date, who holds the lever and what would lift it.
- **The trend**: [`trend/`](trend/). One command reproduces the figures we publish on how fast attack techniques move from idea to lab to the real world, in MITRE ATLAS.

**Read first:** the article, [in English](https://airiskpath.org/article) or [in French](https://airiskpath.org/fr/article). Site: [airiskpath.org](https://airiskpath.org).

## What this is not

No probabilities, no forecasts, no clock. We publish what has already been observed, and what still holds.

**We never publish a way through a defense.** An entry names what blocks, never how to get around it.

## Contribute

Know of a defense that holds, or one that has just given way? [Open an issue](../../issues/new/choose) with its source. Rules: [CONTRIBUTING.md](CONTRIBUTING.md). We answer within 48 hours during the first month.

## Method

How the list and the figures were built, including a pre-registered negative result: method note, [doi:10.5281/zenodo.22893444](https://doi.org/10.5281/zenodo.22893444).

## Licences

- The list (`list/`): [CC BY 4.0](list/LICENSE.md).
- The code (`trend/`): [MIT](LICENSE).

Author: [Franck Bardol](https://bardol.org), with the help of AI agents. Contact: contact@airiskpath.org
