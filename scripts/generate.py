#!/usr/bin/env python3
"""Generate a flat-color vector SVG from a text prompt via the Inspyry API.

A single-file, dependency-free client for the Inspyry public API. It drives the
asynchronous create -> poll -> save flow, retries transient failures with
exponential backoff, and exits with meaningful status codes.

Examples
--------
    export INSPYRY_API_TOKEN=insp_xxx
    python3 generate.py "a minimalist flat-design fox icon, 3 solid colors" fox.svg
    python3 generate.py --credits            # just print the remaining balance
    python3 generate.py "bold lightning bolt icon" -o out/bolt.svg --json

Exit codes
----------
    0  success
    2  usage error (bad arguments / prompt too short)
    3  authentication error (missing or invalid token, HTTP 401)
    4  insufficient credits (HTTP 402)
    5  generation failed (engine returned status=failed)
    6  timed out waiting for the generation
    7  network error reaching the API
    1  any other error

Requires Python 3.8+ and only the standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

DEFAULT_BASE_URL = "https://inspyry.com/api"
USER_AGENT = "inspyry-vector-generator/1.0 (+https://inspyry.com)"
MIN_PROMPT_LEN = 5
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Exit codes (see module docstring).
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_CREDITS = 4
EXIT_FAILED = 5
EXIT_TIMEOUT = 6
EXIT_NETWORK = 7
EXIT_ERROR = 1


# ─── Errors ──────────────────────────────────────────────────────────────────


class SkillError(Exception):
    """Base error carrying an intended process exit code."""

    exit_code = EXIT_ERROR


class UsageError(SkillError):
    exit_code = EXIT_USAGE


class GenerationError(SkillError):
    exit_code = EXIT_FAILED


class TimeoutExceeded(SkillError):
    exit_code = EXIT_TIMEOUT


class NetworkError(SkillError):
    exit_code = EXIT_NETWORK


class ApiError(SkillError):
    """An HTTP-level error from the API. ``code`` is the HTTP status."""

    def __init__(self, code: int, message: str, retry_after: Optional[float] = None):
        super().__init__(message or f"HTTP {code}")
        self.code = code
        self.message = message or f"HTTP {code}"
        self.retry_after = retry_after

    @property
    def exit_code(self) -> int:  # type: ignore[override]
        return {401: EXIT_AUTH, 402: EXIT_CREDITS}.get(self.code, EXIT_ERROR)


# ─── Client ──────────────────────────────────────────────────────────────────


def _extract_error(body: bytes) -> str:
    try:
        return str(json.loads(body.decode()).get("error", "")).strip()
    except Exception:
        return ""


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


class InspyryClient:
    """Thin client over the Inspyry public API with retry + backoff."""

    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        poll_interval: float = 2.0,
        poll_timeout: float = 180.0,
        http_timeout: float = 60.0,
        max_retries: int = 4,
        log=lambda _msg: None,
    ):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.http_timeout = http_timeout
        self.max_retries = max_retries
        self._log = log

    # -- transport -----------------------------------------------------------

    def _http(self, req: urllib.request.Request) -> bytes:
        """Perform one HTTP call. Raises ApiError / NetworkError; returns body."""
        try:
            with urllib.request.urlopen(req, timeout=self.http_timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:
                pass
            retry_after = None
            if exc.headers is not None:
                retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
            raise ApiError(exc.code, _extract_error(body) or (exc.reason or ""), retry_after)
        except urllib.error.URLError as exc:
            raise NetworkError(f"could not reach {self.base_url}: {exc.reason}")
        except TimeoutError:
            raise NetworkError("the request timed out")

    def _backoff(self, attempt: int) -> float:
        # Exponential backoff with full jitter, capped at 30s.
        return min(30.0, (2 ** attempt)) * (0.5 + random.random() / 2)

    def _send(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = json.dumps(body).encode() if body is not None else None
        attempt = 0
        while True:
            req = urllib.request.Request(self.base_url + path, data=payload, method=method)
            req.add_header("Authorization", f"Bearer {self.token}")
            req.add_header("User-Agent", USER_AGENT)
            req.add_header("Accept", "application/json")
            if payload is not None:
                req.add_header("Content-Type", "application/json")
            try:
                raw = self._http(req)
            except ApiError as exc:
                if exc.code in RETRYABLE_STATUS and attempt < self.max_retries:
                    delay = exc.retry_after if exc.retry_after is not None else self._backoff(attempt)
                    self._log(f"API returned {exc.code}; retrying in {delay:.1f}s "
                              f"(attempt {attempt + 1}/{self.max_retries})")
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise
            except NetworkError as exc:
                if attempt < self.max_retries:
                    delay = self._backoff(attempt)
                    self._log(f"{exc}; retrying in {delay:.1f}s "
                              f"(attempt {attempt + 1}/{self.max_retries})")
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise
            if not raw:
                return {}
            try:
                return json.loads(raw.decode())
            except (ValueError, UnicodeDecodeError):
                raise ApiError(0, "the API returned a response that was not valid JSON")

    # -- endpoints -----------------------------------------------------------

    def credits(self) -> Dict[str, Any]:
        return self._send("GET", "/v1/credits")

    def generate(self, prompt: str) -> Dict[str, Any]:
        """Create a generation and poll until it succeeds. Returns the job dict."""
        created = self._send("POST", "/v1/generations", {"prompt": prompt})
        gen_id = created.get("id")
        if not gen_id:
            raise ApiError(0, "the API did not return a generation id")
        self._log(f"created {gen_id} (status={created.get('status', 'queued')}); polling …")

        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            job = self._send("GET", f"/v1/generations/{gen_id}")
            status = job.get("status")
            if status == "succeeded":
                svg = job.get("svg") or ""
                if "<svg" not in svg.lower():
                    raise GenerationError("the generation succeeded but returned no SVG payload")
                return job
            if status == "failed":
                raise GenerationError(job.get("error") or "the generation failed")
            self._log(f"  status={status} …")
            time.sleep(self.poll_interval)
        raise TimeoutExceeded(
            f"timed out after {self.poll_timeout:.0f}s waiting for {gen_id}; "
            "the job may still finish — re-poll or try again"
        )


# ─── CLI ─────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="generate.py",
        description="Generate a flat-color vector SVG from a text prompt via the Inspyry API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("prompt", nargs="?", help="the text prompt (>= %d chars)" % MIN_PROMPT_LEN)
    p.add_argument("output", nargs="?", help="output path (default: output.svg)")
    p.add_argument("-o", "--output", dest="output_flag", metavar="PATH",
                   help="output path (overrides the positional output)")
    p.add_argument("--token", help="API token (overrides $INSPYRY_API_TOKEN)")
    p.add_argument("--base-url", default=os.environ.get("INSPYRY_API_BASE", DEFAULT_BASE_URL),
                   help="API base URL (default: %(default)s)")
    p.add_argument("--credits", action="store_true",
                   help="print the remaining credit balance and exit (no generation)")
    p.add_argument("--timeout", type=float, default=180.0,
                   help="seconds to wait for the generation (default: %(default)s)")
    p.add_argument("--poll-interval", type=float, default=2.0,
                   help="seconds between status polls (default: %(default)s)")
    p.add_argument("--max-retries", type=int, default=4,
                   help="retries for transient errors (default: %(default)s)")
    p.add_argument("--json", action="store_true",
                   help="emit a JSON result object on stdout")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="suppress progress messages on stderr")
    return p


def _resolve_token(args: argparse.Namespace) -> str:
    token = (args.token or os.environ.get("INSPYRY_API_TOKEN", "")).strip()
    if not token:
        raise SkillError(
            "No API token. Set $INSPYRY_API_TOKEN or pass --token. "
            "Create one at inspyry.com → account menu → API access."
        )
    return token


def _write_svg(svg: str, out_path: str) -> str:
    if not out_path.lower().endswith(".svg"):
        out_path += ".svg"
    parent = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return out_path


def run(argv: Optional[list] = None) -> int:
    args = _build_parser().parse_args(argv)
    log = (lambda _m: None) if args.quiet else (lambda m: print(m, file=sys.stderr))

    token = _resolve_token(args)
    client = InspyryClient(
        token,
        base_url=args.base_url,
        poll_interval=args.poll_interval,
        poll_timeout=args.timeout,
        max_retries=args.max_retries,
        log=log,
    )

    if args.credits:
        data = client.credits()
        if args.json:
            print(json.dumps(data))
        else:
            print(f"balance: {data.get('balance', '?')} credits")
        return EXIT_OK

    prompt = (args.prompt or "").strip()
    if not prompt:
        raise UsageError('A prompt is required. Usage: generate.py "<prompt>" [output.svg]')
    if len(prompt) < MIN_PROMPT_LEN:
        raise UsageError(f"Prompt must be at least {MIN_PROMPT_LEN} characters.")

    out_path = args.output_flag or args.output or "output.svg"
    job = client.generate(prompt)
    saved = _write_svg(job["svg"], out_path)

    if args.json:
        print(json.dumps({
            "id": job.get("id"),
            "status": job.get("status"),
            "path": os.path.abspath(saved),
            "bytes": len(job["svg"].encode("utf-8")),
            "tags": job.get("tags", []),
        }))
    else:
        print(saved)
    return EXIT_OK


def main() -> None:
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
    except ApiError as exc:
        hint = {
            EXIT_AUTH: " — check your API token (inspyry.com → API access)",
            EXIT_CREDITS: " — top up at inspyry.com",
        }.get(exc.exit_code, "")
        print(f"error: API {exc.code}: {exc.message}{hint}", file=sys.stderr)
        sys.exit(exc.exit_code)
    except SkillError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)


if __name__ == "__main__":
    main()
