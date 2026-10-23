import pytest
from fastapi.testclient import TestClient
from receiver import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "SkDrop"
    assert "device" in data
    assert "discovery" in data
    assert data["device"]["is_online"] is True
    assert isinstance(data["device"]["pin"], str)


def test_index_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "SkDrop" in response.text
    assert "Nearby Devices" in response.text
    assert "/static/style.css" in response.text
    assert "/static/app.js" in response.text


def test_static_files():
    css_res = client.get("/static/style.css")
    assert css_res.status_code == 200
    assert "box-sizing" in css_res.text

    js_res = client.get("/static/app.js")
    assert js_res.status_code == 200
    assert "SkDrop Frontend Application" in js_res.text

    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "SkDrop"
    assert "device" in data
    assert "discovery" in data
    assert data["device"]["is_online"] is True
    assert isinstance(data["device"]["pin"], str)


def test_device_info_endpoint():
    response = client.get("/api/device")
    assert response.status_code == 200
    data = response.json()
    assert "device_id" in data
    assert "device_name" in data
    assert "pin" in data
    assert len(data["pin"]) == 6
