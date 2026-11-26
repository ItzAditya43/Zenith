"""Safe sharing: detect sensitive text, redact it, share a snapshot."""
from __future__ import annotations


def test_detection():
    from app.services.share_service import find_sensitive

    text = ("mail me at jo.doe@example.com or +44 20 7946 0958, key sk-proj-abcdefghijklmnop1234 "
            "server 192.168.1.20 file /home/adityap10/notes.txt version 1.2.3")
    kinds = {k: t for k, t in find_sensitive(text)}
    assert kinds["email"] == "jo.doe@example.com"
    assert kinds["key"].startswith("sk-proj-")
    assert kinds["ip"] == "192.168.1.20"
    assert kinds["path"] == "/home/adityap10"
    assert "phone" in kinds
    assert all(t != "1.2.3" for _, t in find_sensitive(text))


def test_snapshot_share_redacts_and_freezes(client):
    from app.db import storage

    c = storage.create_conversation("Deploy help for jo@example.com")
    u = storage.add_message(c["id"], "user", "My token is ghp_abcdefghijklmnopqrstuvwx12 and mail jo@example.com")
    a = storage.add_message(c["id"], "assistant", "Rotate that token now.", parent_id=u["id"], model="llama3.2:3b")
    x = storage.add_message(c["id"], "user", "Private aside", parent_id=a["id"])
    prev = client.get(f"/api/conversations/{c['id']}/share/preview").json()
    found = {f["kind"]: f for f in prev["findings"]}
    assert found["key"]["message_ids"] == [u["id"]] and found["email"]["count"] == 1

    redact = [{"kind": f["kind"], "text": f["text"]} for f in prev["findings"]] + [{"text": "Rotate", "replacement": "Change"}]
    token = client.post(f"/api/conversations/{c['id']}/share",
                        json={"redact": redact, "exclude_message_ids": [x["id"]]}).json()["token"]
    storage.add_message(c["id"], "assistant", "Added after sharing", parent_id=x["id"])
    shared = client.get(f"/api/share/{token}").json()
    body = " ".join(m["content"] for m in shared["messages"])
    assert "ghp_" not in body and "jo@example.com" not in body and "[key or token]" in body
    assert "Change that token" in body and "Private aside" not in body and "Added after sharing" not in body
    assert "jo@example.com" not in shared["title"]

    md = client.post(f"/api/conversations/{c['id']}/share/export", json={"redact": redact}).text
    assert md.startswith("# Deploy help for [email address]") and "ghp_" not in md

    client.delete(f"/api/conversations/{c['id']}/share")
    assert client.get(f"/api/share/{token}").status_code == 404
    every = [m["id"] for m in storage.get_messages(c["id"])]
    assert client.post(f"/api/conversations/{c['id']}/share", json={"exclude_message_ids": every}).status_code == 400
