from app.services import pairing_service


def test_pairing_reports_addresses_and_gates(client, monkeypatch):
    monkeypatch.setattr(pairing_service, "addresses", lambda: [{"kind": "lan", "host": "192.168.1.20", "ip": "192.168.1.20"}])
    monkeypatch.setattr(pairing_service, "listening_on", lambda ip, port: False)
    body = client.get("/api/pairing").json()
    assert body["addresses"][0]["backend_reachable"] is False
    assert body["gate"] is False and body["cors_allow_lan"] is False


def test_tailscale_absent_is_quiet(monkeypatch):
    monkeypatch.setattr(pairing_service.shutil, "which", lambda _: None)
    assert pairing_service._tailscale() == (None, None)
