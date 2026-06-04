"""Unit tests for the Inspyry generate.py client.

Network is fully mocked — these tests never touch the real API. Run with:

    python3 -m unittest discover -s tests
"""

import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

# Load scripts/generate.py as a module without requiring it to be a package.
_GEN_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "generate.py"
_spec = importlib.util.spec_from_file_location("generate", _GEN_PATH)
generate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate)


def _bytes(obj):
    return json.dumps(obj).encode()


class FakeHttp:
    """Returns/raises a scripted sequence of responses, ignoring the request."""

    def __init__(self, sequence):
        self._seq = list(sequence)
        self.calls = 0

    def __call__(self, _req):
        self.calls += 1
        item = self._seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(sequence, **kwargs):
    client = generate.InspyryClient("insp_test", **kwargs)
    client._http = FakeHttp(sequence)
    return client


class HelperTests(unittest.TestCase):
    def test_extract_error(self):
        self.assertEqual(generate._extract_error(_bytes({"error": "nope"})), "nope")
        self.assertEqual(generate._extract_error(b"not json"), "")

    def test_parse_retry_after(self):
        self.assertEqual(generate._parse_retry_after("3"), 3.0)
        self.assertIsNone(generate._parse_retry_after(None))
        self.assertIsNone(generate._parse_retry_after("soon"))

    def test_write_svg_adds_extension_and_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "nested", "logo")  # no extension
            saved = generate._write_svg("<svg></svg>", out)
            self.assertTrue(saved.endswith(".svg"))
            self.assertTrue(os.path.exists(saved))


class ApiErrorTests(unittest.TestCase):
    def test_exit_code_mapping(self):
        self.assertEqual(generate.ApiError(401, "x").exit_code, generate.EXIT_AUTH)
        self.assertEqual(generate.ApiError(402, "x").exit_code, generate.EXIT_CREDITS)
        self.assertEqual(generate.ApiError(500, "x").exit_code, generate.EXIT_ERROR)


class ClientTests(unittest.TestCase):
    def test_credits(self):
        client = make_client([_bytes({"balance": 7})])
        self.assertEqual(client.credits()["balance"], 7)

    def test_generate_success(self):
        client = make_client([
            _bytes({"id": "generation_1", "status": "queued"}),
            _bytes({"id": "generation_1", "status": "succeeded",
                    "svg": "<svg viewBox='0 0 1 1'></svg>", "tags": ["icon"]}),
        ])
        job = client.generate("a flat fox icon")
        self.assertEqual(job["status"], "succeeded")
        self.assertIn("<svg", job["svg"])

    def test_generate_polls_until_done(self):
        client = make_client([
            _bytes({"id": "g", "status": "queued"}),
            _bytes({"id": "g", "status": "running"}),
            _bytes({"id": "g", "status": "succeeded", "svg": "<svg></svg>"}),
        ], poll_interval=0)
        self.assertEqual(client.generate("prompt here")["status"], "succeeded")

    def test_generate_failed_raises(self):
        client = make_client([
            _bytes({"id": "g", "status": "queued"}),
            _bytes({"id": "g", "status": "failed", "error": "too complex"}),
        ], poll_interval=0)
        with self.assertRaises(generate.GenerationError):
            client.generate("prompt here")

    def test_succeeded_without_svg_raises(self):
        client = make_client([
            _bytes({"id": "g", "status": "queued"}),
            _bytes({"id": "g", "status": "succeeded", "svg": ""}),
        ], poll_interval=0)
        with self.assertRaises(generate.GenerationError):
            client.generate("prompt here")

    def test_retries_on_429_then_succeeds(self):
        client = make_client([
            generate.ApiError(429, "slow down", retry_after=0),
            _bytes({"balance": 1}),
        ])
        with mock.patch.object(generate.time, "sleep"):
            self.assertEqual(client.credits()["balance"], 1)
        self.assertEqual(client._http.calls, 2)

    def test_gives_up_after_max_retries(self):
        client = make_client(
            [generate.NetworkError("boom")] * 5, max_retries=2,
        )
        with mock.patch.object(generate.time, "sleep"):
            with self.assertRaises(generate.NetworkError):
                client.credits()

    def test_non_retryable_status_raises_immediately(self):
        client = make_client([generate.ApiError(402, "no credits")])
        with self.assertRaises(generate.ApiError) as ctx:
            client.credits()
        self.assertEqual(ctx.exception.code, 402)


class CliTests(unittest.TestCase):
    def test_prompt_too_short(self):
        with mock.patch.dict(os.environ, {"INSPYRY_API_TOKEN": "insp_test"}):
            with self.assertRaises(generate.UsageError):
                generate.run(["hi", "out.svg"])

    def test_missing_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(generate.SkillError):
                generate.run(["a valid prompt"])

    def test_run_generate_writes_file(self):
        seq = [
            _bytes({"id": "g", "status": "queued"}),
            _bytes({"id": "g", "status": "succeeded", "svg": "<svg></svg>"}),
        ]
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "icon.svg")
            with mock.patch.dict(os.environ, {"INSPYRY_API_TOKEN": "insp_test"}):
                with mock.patch.object(generate.InspyryClient, "_http", FakeHttp(seq)):
                    code = generate.run(["a flat fox icon", out, "--poll-interval", "0", "-q"])
            self.assertEqual(code, generate.EXIT_OK)
            self.assertTrue(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
