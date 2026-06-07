# Inspyry Vector Generator — agent skill

A portable **agent skill** that generates clean, **flat-color vector (SVG)**
artwork from a text prompt using the [Inspyry](https://inspyry.com) public API.
Output is editable, scalable SVG — ideal for logos, icons, mascots, badges, and
wordmarks.

It's designed to plug into **any AI agent or LLM tool-calling setup**, not just
one vendor. The core is a dependency-free Python CLI
([`scripts/generate.py`](scripts/generate.py)) that drives the asynchronous
*create → poll → save* flow, retries transient failures with exponential
backoff, and exits with meaningful status codes — so any agent that can run a
shell command (or call the underlying [HTTP API](#use-from-any-agent)) can use
it. [`SKILL.md`](SKILL.md) is the model-readable manifest describing when and how
to invoke it.

## Use with any agent

The skill is intentionally vendor-neutral. Pick whichever integration fits your
agent:

- **[Claude Code](https://claude.com/claude-code) / Claude Agent SDK** — clone
  into the skills folder and it's discovered automatically:
  ```bash
  git clone git@github.com:dhiraj-salian/inspyry-vector-generator-skill.git \
    ~/.claude/skills/inspyry-vector-generator
  ```
- **Any other agent (Cursor, Cline, LangChain/LlamaIndex tools, OpenAI/Gemini
  function calling, custom loops)** — register the CLI as a tool. Give the model
  the contents of [`SKILL.md`](SKILL.md) as the tool description/system context,
  and have it shell out to:
  ```bash
  python3 scripts/generate.py "<prompt>" <output>.svg
  ```
  The `--json` flag returns a structured result (`{id,status,path,bytes,tags}`)
  for easy parsing, and the [exit codes](#exit-codes) let the agent branch on
  failures (auth, credits, timeout, …) without scraping text.
- **No wrapper at all** — call the [HTTP API directly](#use-from-any-agent);
  the CLI is just a convenience over a handful of REST endpoints.

Whatever the host, behavior, prompting guidance, and the API are identical —
[`SKILL.md`](SKILL.md) is the single source of truth.

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

## Use from any agent

The CLI is a thin convenience over a small REST API, so an agent can skip it
entirely and call the endpoints directly. Auth is a bearer token; generation is
asynchronous (create, then poll until `status` is `succeeded`):

```bash
# create
ID=$(curl -s -X POST "https://inspyry.com/api/v1/generations" \
  -H "Authorization: Bearer $INSPYRY_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"a bold lightning bolt icon, flat vector"}' | jq -r .id)

# poll until succeeded, then save the SVG
curl -s "https://inspyry.com/api/v1/generations/$ID" \
  -H "Authorization: Bearer $INSPYRY_API_TOKEN" | jq -r .svg > out.svg
```

A machine-readable OpenAPI spec is available at `GET
https://inspyry.com/api/v1/openapi.json`. See [`SKILL.md`](SKILL.md) for the full
endpoint and error reference.

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
