#!/usr/bin/env python3
"""Expose only Codex quota percentages and reset times to a local ESP32.

The Codex CLI keeps account credentials on the host VM. They are never sent to the
ESP32 or returned by this HTTP server.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import select
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TOKEN_FILE = PROJECT_DIR / ".codex-bridge" / "token"


def read_or_create_token(path: Path) -> str:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.exists():
        token = secrets.token_urlsafe(32)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(token)
    path.chmod(0o600)
    return path.read_text().strip()


def codex_usage(codex_binary: str) -> dict:
    process = subprocess.Popen(
        [codex_binary, "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    def send(message: dict) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def receive(request_id: int, timeout: float = 12.0) -> dict:
        assert process.stdout is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select(
                [process.stdout], [], [], max(0.0, deadline - time.monotonic())
            )
            if not ready:
                break
            line = process.stdout.readline()
            if not line:
                break
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") == request_id:
                if "error" in response:
                    raise RuntimeError("Codex a refusé la lecture des quotas")
                return response["result"]
        raise TimeoutError("Codex n'a pas répondu à temps")

    try:
        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "esp32_codex_clock",
                        "title": "ESP32 Codex Clock",
                        "version": "1.0.0",
                    }
                },
            }
        )
        receive(1)
        send({"method": "initialized"})
        send(
            {
                "id": 2,
                "method": "account/rateLimits/read",
                "params": {"excludeResetCreditDetails": True},
            }
        )
        snapshot = receive(2)
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    limits = (snapshot.get("rateLimitsByLimitId") or {}).get("codex")
    if not limits:
        limits = snapshot.get("rateLimits") or {}
    primary = limits.get("primary") or {}
    secondary = limits.get("secondary") or {}
    if not primary or not primary.get("resetsAt"):
        raise ValueError("La fenêtre Codex de 5 heures est indisponible")

    def remaining(window: dict) -> int | None:
        used = window.get("usedPercent")
        return max(0, min(100, 100 - int(used))) if used is not None else None

    return {
        "remaining_5h": remaining(primary),
        "reset_5h": int(primary["resetsAt"]),
        "remaining_week": remaining(secondary),
        "reset_week": int(secondary["resetsAt"]) if secondary.get("resetsAt") else None,
        "updated_at": int(time.time()),
    }


class QuotaCache:
    def __init__(self, codex_binary: str) -> None:
        self.codex_binary = codex_binary
        self.lock = threading.Lock()
        self.value: dict | None = None

    def get(self) -> dict:
        with self.lock:
            if self.value is None or time.time() - self.value["updated_at"] >= 60:
                self.value = codex_usage(self.codex_binary)
            return self.value


def handler_factory(token: str, cache: QuotaCache):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request = urlsplit(self.path)
            supplied = parse_qs(request.query).get("token", [""])[0]
            if request.path != "/quota" or not secrets.compare_digest(supplied, token):
                self.send_error(404)
                return
            try:
                data = json.dumps(cache.get(), separators=(",", ":")).encode()
            except Exception as error:
                print(f"Lecture Codex impossible : {type(error).__name__}", file=sys.stderr)
                self.send_error(503, "Quota temporairement indisponible")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format_string: str, *args) -> None:
            # A request URL contains the private bridge token.
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--codex", default=shutil.which("codex"))
    args = parser.parse_args()
    if not args.codex:
        parser.error("la commande codex est introuvable")
    token = read_or_create_token(args.token_file)
    server = ThreadingHTTPServer(
        (args.bind, args.port), handler_factory(token, QuotaCache(args.codex))
    )
    print(f"Bridge Codex prêt sur {args.bind}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
