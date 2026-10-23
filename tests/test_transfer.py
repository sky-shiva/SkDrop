import io
import time
import pytest
from fastapi.testclient import TestClient
from receiver import app
from services import config, transfer_service

client = TestClient(app)


def test_upload_and_download_flow():
    unique_suffix = int(time.time() * 1000)
    test_content = b"Hello from SkDrop test transfer! Testing reliable upload."
    test_filename = f"test_doc_{unique_suffix}.txt"

    # Upload
    files = {"file": (test_filename, io.BytesIO(test_content), "text/plain")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    file_info = data["file"]
    assert "id" in file_info
    assert file_info["name"].startswith(f"test_doc_{unique_suffix}")
    assert file_info["size"] == len(test_content)
    file_id = file_info["id"]

    # Verify in files list
    list_res = client.get("/api/files")
    assert list_res.status_code == 200
    files_list = list_res.json()["files"]
    assert any(f["id"] == file_id for f in files_list)

    # Download by ID
    dl_res = client.get(f"/api/download/{file_id}")
    assert dl_res.status_code == 200
    assert dl_res.content == test_content


def test_collision_prevention():
    unique_suffix = int(time.time() * 1000)
    test_content = b"Collision test content"
    filename = f"collision_{unique_suffix}.txt"

    # Upload first
    f1 = {"file": (filename, io.BytesIO(test_content), "text/plain")}
    res1 = client.post("/api/upload", files=f1)
    assert res1.status_code == 200
    name1 = res1.json()["file"]["name"]
    assert name1 == filename

    # Upload second with identical filename
    f2 = {"file": (filename, io.BytesIO(test_content), "text/plain")}
    res2 = client.post("/api/upload", files=f2)
    assert res2.status_code == 200
    name2 = res2.json()["file"]["name"]

    assert name1 != name2
    assert "(1)" in name2


def test_path_traversal_sanitization():
    unique_suffix = int(time.time() * 1000)
    # Attempt filename with traversal sequences and illegal chars
    malicious_filename = f"../../../secret_data_{unique_suffix}.txt"
    files = {"file": (malicious_filename, io.BytesIO(b"safe content"), "text/plain")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 200
    saved_name = response.json()["file"]["name"]
    # Path components must be completely stripped
    assert "/" not in saved_name
    assert "\\" not in saved_name
    assert ".." not in saved_name
    assert f"secret_data_{unique_suffix}.txt" in saved_name


def test_download_invalid_file_id():
    response = client.get("/api/download/nonexistent-uuid-1234")
    assert response.status_code == 404
    assert response.json()["detail"] == "File not found"


def test_file_size_limit_enforcement(monkeypatch):
    # Temporarily set MAX_FILE_SIZE to 50 bytes for testing
    monkeypatch.setattr(config, "MAX_FILE_SIZE", 50)
    monkeypatch.setattr(transfer_service, "MAX_FILE_SIZE", 50)

    oversized_content = b"A" * 100
    files = {"file": ("bigfile.bin", io.BytesIO(oversized_content), "application/octet-stream")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 413
    assert "exceeds maximum allowed size" in response.json()["detail"]

    # Verify no temp files left in TEMP_DIR
    temp_files = list(config.TEMP_DIR.glob("upload_*_bigfile.bin"))
    assert len(temp_files) == 0
