from __future__ import annotations

import httpx


async def test_image_check(client, monkeypatch):
    from app.core.config import settings
    from app.services import image_service

    assert (await image_service.check())["ok"] is False
    settings.update({"image_gen_url": "http://127.0.0.1:7860"})

    def handler(req):
        if req.url.path.endswith("/options"):
            return httpx.Response(200, json={"sd_model_checkpoint": "sdxl"})
        return httpx.Response(200, json=[{"model_name": "sdxl"}, {"model_name": "sd15"}])

    real = httpx.AsyncClient

    class C(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr(image_service.httpx, "AsyncClient", C)
    r = await image_service.check()
    assert r == {"ok": True, "model": "sdxl", "models": ["sdxl", "sd15"]}
    settings.update({"image_gen_url": ""})
