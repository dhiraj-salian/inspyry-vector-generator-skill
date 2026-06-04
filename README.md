# Inspyry Vector Generator — Claude skill

A [Claude](https://claude.com/claude-code) skill that generates clean, **flat-color
vector (SVG)** artwork from a text prompt using the [Inspyry](https://inspyry.com)
public API. Output is editable, scalable SVG — ideal for logos, icons, mascots,
badges, and wordmarks.

It ships with a dependency-free Python client ([`scripts/generate.py`](scripts/generate.py))
that drives the asynchronous *create → poll → save* flow, retries transient
failures with exponential backoff, and exits with meaningful status codes.

## Install

Copy this directory into your Claude skills folder:

```bash
git clone git@github.com:dhiraj-salian/inspyry-vector-generator-skill.git \
  ~/.claude/skills/inspyry-vector-generator
```

Claude Code discovers it automatically. The skill is described in
[`SKILL.md`](SKILL.md), which Claude reads to decide when and how to use it.

## Prerequisites

1. **API token** — create one at `inspyry.com → account menu → API access →
   Request token`. It looks like `insp_…`. Provide it via the
   `INSPYRY_API_TOKEN` environment variable (or `--token`).
2. **Credits** — each successful generation costs 1 credit (failed ones are
   auto-refunded). Check the balance with `--credits`.

## Usage

```bash
export INSPYRY_API_TOKEN=insp_xxx

# generate and save
python3 scripts/generate.py "a minimalist flat-design fox icon, 3 solid colors" fox.svg

# check remaining credits
python3 scripts/generate.py --credits

# machine-readable result
python3 scripts/generate.py "bold lightning bolt icon, flat vector" -o out/bolt.svg --json
```

### Options

| Flag | Purpose |
| --- | --- |
| `-o, --output PATH` | output path (also accepted as the 2nd positional arg) |
| `--token TOKEN` | API token (overrides `$INSPYRY_API_TOKEN`) |
| `--base-url URL` | API base URL (default `https://inspyry.com/api`) |
| `--credits` | print the credit balance and exit |
| `--timeout N` | seconds to wait for the generation (default 180) |
| `--poll-interval N` | seconds between status polls (default 2) |
| `--max-retries N` | retries for transient errors (default 4) |
| `--json` | emit a JSON result object on stdout |
| `-q, --quiet` | suppress progress messages on stderr |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 2 | usage error (bad arguments / prompt too short) |
| 3 | authentication error (missing or invalid token) |
| 4 | insufficient credits |
| 5 | generation failed (engine returned `failed`) |
| 6 | timed out waiting for the generation |
| 7 | network error reaching the API |
| 1 | any other error |

## Prompting tips

The engine produces **flat-color vector art** — lead with a single, centered
subject, name exact bold colors, and quote any text verbatim. Omit
`photorealistic`, `3D`, and `gradient` (they're stripped). See
[`SKILL.md`](SKILL.md) for the full prompting guide and API reference.

## Development

The client uses only the Python standard library (3.8+). Tests are fully mocked
and never hit the network:

```bash
python3 -m unittest discover -s tests
```

CI runs the suite on every push (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## License

[MIT](LICENSE) © Dhiraj Salian
