from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from unified_runtime.browser_escalation import PlaywrightBrowserBackend


HTML = b"""<!doctype html>
<html><body>
<h1>Example Company</h1>
<button onclick="document.getElementById('contact').hidden=false">Show contact details</button>
<div id="contact" hidden>
  <p>Email: purchasing@example.test</p>
  <p>Phone: +51 983 752 162</p>
  <a href="https://wa.me/51983752162">WhatsApp purchasing</a>
</div>
<div style="height:1800px"></div>
<a href="/team">Procurement Team</a>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = HTML if self.path == "/" else b"<html><body>Procurement Team</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


async def _run(port: int) -> None:
    async with PlaywrightBrowserBackend(
        navigation_timeout_ms=10_000,
        settle_ms=100,
        scroll_steps=2,
        click_budget=3,
    ) as browser:
        page = await browser.fetch(f"http://127.0.0.1:{port}/")
        assert page.success, page.error
        assert "purchasing@example.test" in page.text
        assert "+51 983 752 162" in page.text
        assert any(link.startswith("https://wa.me/51983752162") for link in page.links)
        assert any(label == "Procurement Team" for _, label in page.link_hints)
        assert browser.session_page_count == 1


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asyncio.run(_run(port))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    print("round2 Playwright live smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
