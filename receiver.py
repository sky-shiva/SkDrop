
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOST = "0.0.0.0"
PORT = 8000

# Save incoming files inside the project folder
BASE_DIR = Path(__file__).resolve().parent
SAVE_DIR = BASE_DIR / "received_files"
SAVE_DIR.mkdir(exist_ok=True)


class SkDropHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        page = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>SkDrop</title>
        </head>
        <body style="font-family: Arial; text-align: center; padding: 40px;">
            <h1>🚀 SkDrop</h1>
            <p>Your local file-sharing server is running!</p>
            <p>Android file upload is coming next.</p>
        </body>
        </html>
        """

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))


server = HTTPServer((HOST, PORT), SkDropHandler)

print("=" * 32)
print("        SkDrop RECEIVER")
print("=" * 32)
print(f"Server running on port {PORT}")
print("Laptop test: http://127.0.0.1:8000")
print("Press Ctrl+C to stop.")

try:
    server.serve_forever()
except KeyboardInterrupt:
    print("\nSkDrop server stopped.")
finally:
    server.server_close()
