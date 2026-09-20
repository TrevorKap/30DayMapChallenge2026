import http.server
import os
import socketserver


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


port = int(os.environ.get("PORT", 8731))
with ThreadingHTTPServer(("", port), NoCacheHandler) as httpd:
    print(f"Serving on port {port} (caching disabled, handles concurrent requests)")
    print("Tip (Windows): don't click/select text in this console window while the")
    print("server needs to stay up — QuickEdit Mode pauses the whole process until")
    print("you press Enter or Esc. If pages stop loading, click here and hit Enter.")
    httpd.serve_forever()
