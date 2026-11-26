"""Email triage into categories with user filters first, and reply drafts
that wait for review before sending. IMAP/SMTP are replaced with fakes."""
from __future__ import annotations

import pytest


@pytest.fixture
def mail(fake_ollama, monkeypatch):
    from app.core.config import settings
    from app.services import email_service as es

    settings.update({"email_enabled": True})
    inbox = [
        {"id": "1", "subject": "Contract to sign by Friday", "from": "Lee <lee@firm.com>", "date": 1, "snippet": "Please sign."},
        {"id": "2", "subject": "Weekly deals!", "from": "Shop <deals@shop.com>", "date": 2, "snippet": "50% off"},
        {"id": "3", "subject": "Lunch tomorrow?", "from": "Sam <sam@x.org>", "date": 3, "snippet": "Are you free?"},
    ]
    sent = []
    monkeypatch.setattr(es, "list_messages", lambda folder="INBOX", limit=None: [dict(m) for m in inbox])
    monkeypatch.setattr(es, "get_message", lambda mid, folder="INBOX": {**next(m for m in inbox if m["id"] == mid), "body": "Are you free for lunch?"})
    monkeypatch.setattr(es, "send_message", lambda to, subject, body, in_reply_to=None: sent.append((to, subject, body)))
    yield es, fake_ollama, sent
    settings.update({"email_enabled": False})


async def test_triage_with_filters_first(mail):
    # No TestClient here: starting the app also starts its background mail check.
    es, fake, _ = mail
    es.add_filter("Shops", "from", "deals@", "newsletter")
    with pytest.raises(es.EmailError):
        es.add_filter("", "from", "x", "spam")
    fake.queue("URGENT: needs a signature by Friday", "REPLY: Sam is asking about lunch")
    r = await es.triage()
    assert r == {"triaged": 3, "urgent": 1}
    assert len(fake.calls) == 2  # the filtered newsletter never reached the model
    by = {m["id"]: m for m in es.inbox()}
    assert by["1"]["category"] == "urgent" and by["2"]["category"] == "newsletter" and by["3"]["category"] == "reply"
    assert by["2"]["reason"] == "filter: Shops"
    assert (await es.triage())["triaged"] == 0  # once per message


async def test_drafts_wait_for_review(mail, client):
    es, fake, sent = mail
    fake.queue("Sure, 12:30 works for me.")
    d = await es.create_draft("3", "say yes")
    assert d["to_addr"] == "sam@x.org" and d["subject"] == "Re: Lunch tomorrow?" and d["status"] == "draft"
    assert sent == []  # drafting never sends
    assert es.inbox()[2]["has_draft"] is True
    client.patch(f"/api/email/drafts/{d['id']}", json={"body": "Sure, 1pm works."})
    r = client.post(f"/api/email/drafts/{d['id']}/send").json()
    assert r["status"] == "sent" and sent == [("sam@x.org", "Re: Lunch tomorrow?", "Sure, 1pm works.")]
    assert client.post(f"/api/email/drafts/{d['id']}/send").status_code == 400  # can't send twice
    assert client.get("/api/email/drafts").json() == []
