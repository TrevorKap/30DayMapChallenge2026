import http.server
import os
import socketserver


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()


port = int(os.environ.get("PORT", 8731))
with socketserver.TCPServer(("", port), NoCacheHandler) as httpd:
    print(f"Serving on port {port} (caching disabled)")
    httpd.serve_forever()
