---
name: inspyry-vector-generator
description: Generate flat-color vector graphics (SVG) from a text prompt via the Inspyry API. Use when the user wants to create a logo, icon, mascot, character, badge, emblem, sticker, or wordmark as a scalable SVG (not a photo or raster). Handles auth, the async create→poll flow, and saving the SVG.
---

# Inspyry Vector Generator

Generate clean, **flat-color vector (SVG)** artwork from a text prompt using the
Inspyry public API. Output is editable, scalable SVG — ideal for logos, icons,
mascots, badges, and wordmarks.

## When to use this skill

Use it when the user asks to **create/generate/make** a vector, SVG, logo, icon,
mascot, character, emblem, badge, sticker, or wordmark. Produce an `.svg` file.

Do **not** use it for: photos, 3D renders, paintings, raster images (PNG/JPG),
UI screenshots, or multi-paragraph text layouts — the engine only produces
flat-color vector art.

## Prerequisites

1. **API token** (required). The user creates one at
   `https://inspyry.com` → account menu → **API access** → *Request token*.
   It looks like `insp_…`. Provide it via the `INSPYRY_API_TOKEN` env var.
2. **Credits.** Each successful generation costs 1 credit (failed ones are
   auto-refunded). Check the balance with `GET /v1/credits`.

The API base URL is always `https://inspyry.com/api`.

If `INSPYRY_API_TOKEN` is not set, ask the user for their token before calling
the API. Never hard-code or echo the token.

## Quick start

The bundled helper does create → poll → save in one step (stdlib only, no pip;
Python 3.8+). It retries transient errors (429/5xx/network) with backoff:

```bash
export INSPYRY_API_TOKEN=insp_xxx
python3 scripts/generate.py "a minimalist flat-design fox icon, 3 solid colors" fox.svg
```

It prints the saved path on success, or a clear error (insufficient credits,
invalid token, etc.) on stderr. Useful flags:

| Flag | Purpose |
| --- | --- |
| `-o, --output PATH` | output path (also the 2nd positional arg) |
| `--credits` | print the credit balance and exit (no generation) |
| `--json` | emit a JSON result (`{id,status,path,bytes,tags}`) on stdout |
| `--token TOKEN` | token override (else `$INSPYRY_API_TOKEN`) |
| `--timeout N` / `--poll-interval N` | poll deadline / cadence (default 180 / 2) |
| `-q, --quiet` | suppress progress messages on stderr |

Exit codes: `0` ok · `2` usage · `3` auth (401) · `4` credits (402) · `5`
generation failed · `6` timed out · `7` network · `1` other. Read
`scripts/generate.py` if you need to adapt the flow.

## What it can generate

**Great for:** logos & brand marks · UI/app icons & glyphs · character & mascot
illustrations · badges, crests, emblems · stickers & poster-style art · bold
lettering / wordmarks.

**Not supported:** photorealism / 3D · smooth gradients (flattened to solid
colors) · busy scenes with full backgrounds · photographic texture · long text.

## How to prompt (this strongly affects quality)

- **Lead with the subject.** One clear, centered subject first, then its most
  distinctive traits. Avoid scenes/crowds/landscapes.
- **Specify exact colors**, bold and saturated: "deep maroon and gold",
  "orange, white, dark brown".
- **For text, quote it exactly** and keep it short:
  `the word "INSPYRY" in a bold sans-serif font`.
- **Ornate detail is fine** (embroidery, filigree, jewellery) — the engine
  auto-detects complexity and renders richer output.
- **Don't fight the medium.** Omit "photorealistic", "3D", "gradient",
  "realistic lighting" — they're stripped automatically. You may add a style
  anchor like "flat vector design", "vector illustration", or "flat icon design".

Good example prompts:
- `a minimalist flat-design fox icon, simple geometric shapes, orange white and dark brown, no gradients`
- `a coffee cup with steam, bold outlines, flat colors, modern logo style`
- `elegant north indian bride, deep maroon and gold bridal lehenga, intricate zardozi embroidery, vector illustration`
- `the word "INSPYRY" in a clean bold sans-serif font, solid black`
- `a steampunk octopus mascot, brass goggles, bold shapes, flat vector design`

## API reference

Base URL: `https://inspyry.com/api` · Auth header: `Authorization: Bearer insp_…`
· Machine-readable spec: `GET {base}/v1/openapi.json`.

Generation is **asynchronous**: create, then poll until `status` is `succeeded`.

### POST /v1/generations — create
Body `{"prompt": "..."}` (prompt ≥ 5 chars). Returns `202`:
```json
{ "id": "generation_…", "status": "queued", "prompt": "…" }
```

### GET /v1/generations/{id} — poll
Poll every ~2s (typical completion 10–60s). When done:
```json
{ "id": "…", "status": "succeeded", "svg": "<svg …>…</svg>", "tags": ["icon"] }
```
`status` is one of `queued | running | succeeded | failed`. On `failed`, an
`error` field explains why.

### GET /v1/credits — balance & usage
```json
{ "balance": 42, "recentUsage": [ { "delta": -1, "reason": "generate", "ref": "…", "createdAt": "…" } ] }
```

### Errors
Envelope: `{ "error": "message" }`.

| Status | Meaning |
| --- | --- |
| 400 | Invalid body or prompt < 5 chars |
| 401 | Missing/invalid API token |
| 402 | Insufficient credits (top up at inspyry.com) |
| 404 | Generation not found / not owned by your token |
| 429 | Rate limited — back off and retry |

### Raw curl (if not using the helper)

```bash
# create
ID=$(curl -s -X POST "https://inspyry.com/api/v1/generations" \
  -H "Authorization: Bearer $INSPYRY_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"a bold lightning bolt icon, flat vector"}' | jq -r .id)

# poll
curl -s "https://inspyry.com/api/v1/generations/$ID" \
  -H "Authorization: Bearer $INSPYRY_API_TOKEN" | jq -r .svg > out.svg
```

## Workflow for the agent

1. Confirm a token is available (`INSPYRY_API_TOKEN`); if not, ask for it.
2. Refine the user's idea into a single-subject, flat-color prompt using the
   guidance above (keep their intent; add colors + a style anchor).
3. Run `scripts/generate.py "<prompt>" <output>.svg` (or the curl flow).
4. On success, report the saved `.svg` path. On `402`, tell the user to top up
   credits. On `failed`, surface the `error` and suggest a simpler prompt.
