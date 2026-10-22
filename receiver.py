
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
import uvicorn

app = FastAPI(title="SkDrop")

# Folder where received files are stored
SAVE_DIR = Path(__file__).parent / "received_files"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
CHUNK_SIZE = 1024 * 1024  # 1 MB


@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>SkDrop</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 500px;
                margin: 60px auto;
                padding: 20px;
                text-align: center;
                background: #f4f6f8;
            }
            .card {
                background: white;
                padding: 25px;
                border-radius: 16px;
                box-shadow: 0 4px 15px #0001;
            }
            input, button {
                margin-top: 18px;
                width: 100%;
                padding: 12px;
                box-sizing: border-box;
            }
            button {
                background: #2563eb;
                color: white;
                border: none;
                border-radius: 8px;
                cursor: pointer;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>SkDrop</h1>
            <p>Send files to your laptop</p>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <input type="file" name="file" required>
                <button type="submit">Send File</button>
            </form>
        </div>
    </body>
    </html>
    """


@app.post("/upload", response_class=HTMLResponse)
async def upload_file(file: UploadFile = File(...)):
    # Keep only the filename, not any directory path
    filename = (file.filename or "upload.bin").replace("\\", "/").split("/")[-1]

    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")

    destination = SAVE_DIR / filename
    stem, suffix = destination.stem, destination.suffix

    # Avoid overwriting an existing file
    counter = 1
    while destination.exists():
        destination = SAVE_DIR / f"{stem}_{counter}{suffix}"
        counter += 1

    total_size = 0

    try:
        with destination.open("wb") as output:
            while True:
                chunk = await file.read(CHUNK_SIZE)

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > MAX_FILE_SIZE:
                    output.close()
                    destination.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail="File exceeds the 100 MB limit"
                    )

                output.write(chunk)

    except HTTPException:
        raise
    except Exception:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Upload failed")
    finally:
        await file.close()

    return f"""
    <html>
      <head><meta name="viewport" content="width=device-width, initial-scale=1"></head>
      <body style="font-family:Arial;text-align:center;margin-top:60px">
        <h2>File received successfully!</h2>
        <p>Saved as: {destination.name}</p>
        <p>Size: {total_size / (1024 * 1024):.2f} MB</p>
        <a href="/">Send another file</a>
      </body>
    </html>
    """


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
