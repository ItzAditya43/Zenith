"""Watched folder include/exclude patterns, preview, and symlinks that
lead outside the folder never being followed."""
from __future__ import annotations

import os

from app.services import folder_service as fs


def test_patterns_preview_and_symlink(client, tmp_path):
    root = tmp_path / "notes"
    (root / "drafts").mkdir(parents=True)
    (root / "a.md").write_text("alpha")
    (root / "drafts" / "b.md").write_text("beta")
    (root / "secret.md").write_text("pw")
    outside = tmp_path / "elsewhere.md"
    outside.write_text("outside")
    os.symlink(outside, root / "link.md")

    r = client.post("/api/folders", json={"path": str(root), "extensions": ".md", "exclude_patterns": "drafts/**, secret*"})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    prev = client.get(f"/api/folders/{fid}/preview").json()
    assert prev["files"] == ["a.md"]
    assert prev["counts"]["excluded"] == 2 and prev["counts"]["outside"] == 1 and prev["outside"] == ["link.md"]

    res = fs.scan_folder(fs.get_watched_folder(fid))
    assert res["indexed"] == 1 and res["skipped_outside"] == 1

    client.put(f"/api/folders/{fid}/patterns", json={"include_patterns": "drafts/*", "exclude_patterns": ""})
    prev = client.get(f"/api/folders/{fid}/preview").json()
    assert prev["files"] == ["drafts/b.md"] and prev["counts"]["not_included"] == 2
    res = fs.scan_folder(fs.get_watched_folder(fid))
    assert res["indexed"] == 1 and res["removed"] == 1  # a.md dropped from the index
