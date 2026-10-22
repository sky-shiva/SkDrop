
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote
import html
import re

HOST = "0.0.0.0"
PORT = 8000

BASE_DIR = Path(__file__).resolve().parent
SAVE_DIR = BASE_DIR / "received_files"
SAVE_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


class SkDropHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        files = sorted(p.name for p in SAVE_DIR.iterdir() if p.is_file())

        file_list = "".join(
            f"<li>{html.escape(name)}</li>" for name in files
        ) or "<li>No files received yet</li>"

        page = f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>SkDrop</title>
</head>
<body style="font-family:Arial;max-width:600px;margin:40px auto;padding:16px">
    <h1>🚀 SkDrop</h1>
    <p>Send files from your Android phone to your Windows laptop.</p>
    <form action="/upload" method="post" enctype="multipart/form-data">
        <input type="file" name="file" required>
        <button type="submit">Send file</button>
    </form>
    <h3>Received files</h3>
    <ul>{file_list}</ul>
</body>
</html>"""

        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/upload":
            self.send_error(404)
            return

        content_type = self.headers.get("Content-Type", "")
        match = re.search(r'multipart/form-data;\s*boundary=(?:"([^"]+)"|([^;]+))',
                          content_type, re.I)

        if not match:
            self.send_error(400, "Expected a multipart file upload")
            return

        boundary = (match.group(1) or match.group(2)).encode("ascii", "strict")
        length_header = self.headers.get("Content-Length")

        if not length_header or not length_header.isdigit():
            self.send_error(411, "Content-Length required")
            return

        length = int(length_header)
        if length > MAX_FILE_SIZE + 1024 * 1024:
            self.send_error(413, "File is too large (maximum 100 MB)")
            return

        body = self.rfile.read(length)
        delimiter = b"--" + boundary

        for part in body.split(delimiter):
            if b"\r\n\r\n" not in part:
                continue

            headers, data = part.split(b"\r\n\r\n", 1)
            disposition = re.search(
                rb'Content-Disposition:\s*form-data;[^\r\n]*filename="([^"]*)"',
                headers, re.I
            )

            if not disposition:
                continue

            filename = unquote(
                disposition.group(1).decode("utf-8", "replace")
            ).replace("\\", "/").split("/")[-1].strip()

            if not filename or filename in {".", ".."}:
                self.send_error(400, "Invalid filename")
                return

            data = data.removesuffix(b"\r\n").removesuffix(b"--")
            if len(data) > MAX_FILE_SIZE:
                self.send_error(413, "File is too large")
                return

            # Avoid overwriting an existing file.
            destination = SAVE_DIR / filename
            stem, suffix = destination.stem, destination.suffix
            counter = 1
            while destination.exists():
                destination = SAVE_DIR / f"{stem}_{counter}{suffix}"
                counter += 1

            destination.write_bytes(data)

            print(f"Received: {destination.name} ({len(data)} bytes)")
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            return

        self.send_error(400, "No file found in upload")


server = HTTPServer((HOST, PORT), SkDropHandler)

print("=" * 32)
print("        SkDrop RECEIVER")
print("=" * 32)
print("Laptop: http://127.0.0.1:8000")
print("Keep this terminal open while transferring.")
print("Press Ctrl+C to stop.")

try:
    server.serve_forever()
except KeyboardInterrupt:
    print("\nSkDrop server stopped.")
finally:
    server.server_close()
