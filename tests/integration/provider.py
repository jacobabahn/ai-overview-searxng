"""Stdlib-only fixture provider, isolated from live API credentials."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "data": [
                        {"id": "deepseek-v4-flash"},
                        {"id": "glm-5.2"},
                        {"id": "unknown-model"},
                    ]
                }
            ).encode()
        )

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        messages = body["messages"]
        planning = "Plan retrieval" in messages[0]["content"]
        text = (
            '{"query":"sunset colors"}'
            if planning
            else "The sky looks blue because air scatters blue light more strongly than red light. [1]\n\n"
            "At sunset, light travels through more atmosphere, leaving warmer colors. [2]"
        )
        if "fail-stream" in messages[-1]["content"]:
            self.send_error(429)
            return
        if "slow-stream" in messages[-1]["content"]:
            text *= 30
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            for start in range(0, len(text), 8):
                value = {
                    "choices": [
                        {"delta": {"content": text[start : start + 8]}, "finish_reason": None}
                    ]
                }
                self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
                self.wfile.flush()
                time.sleep(0.03)
            self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9876), Handler).serve_forever()
