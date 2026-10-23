import pytest
from fastapi.testclient import TestClient
from receiver import app

client = TestClient(app)


def test_discovery_status_and_manual_entry():
    # 1. Check discovery endpoint
    res = client.get("/api/devices")
    assert res.status_code == 200
    data = res.json()
    assert "discovery" in data
    assert "devices" in data

    # 2. Add manual device IP
    manual_payload = {
        "ip": "10.72.217.40",
        "port": 8000,
        "name": "Friend Laptop",
    }
    disc_res = client.post("/api/devices/discover", json=manual_payload)
    assert disc_res.status_code == 200
    disc_data = disc_res.json()
    assert disc_data["status"] == "registered"
    assert disc_data["ip"] == "10.72.217.40"

    # 3. Check that it appears in devices list
    res2 = client.get("/api/devices")
    devices = res2.json()["devices"]
    assert any(d["ip"] == "10.72.217.40" for d in devices)
