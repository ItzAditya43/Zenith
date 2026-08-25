"""Focused, deterministic tests for batch_service — no Ollama/model calls."""
from app.services import batch_service


async def test_path_escape_rejected():
    """A folder_path containing a literal '..' traversal segment must be
    rejected up front, before any file listing happens."""
    results = [item async for item in batch_service.run_batch(
        "/tmp/somewhere/../../etc", "summarize", "llama3"
    )]
    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert "escape" in results[0]["error"].lower()


async def test_nonexistent_folder_rejected():
    results = [item async for item in batch_service.run_batch(
        "/this/path/does/not/exist/zenith-batch-test", "summarize", "llama3"
    )]
    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert "not a directory" in results[0]["error"].lower() or "visible" in results[0]["error"].lower()


async def test_empty_folder_yields_no_matching_files(tmp_path):
    (tmp_path / "notes.bin").write_bytes(b"\x00\x01")  # not a readable ext

    results = [item async for item in batch_service.run_batch(
        str(tmp_path), "summarize", "llama3"
    )]
    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert "no matching files" in results[0]["error"].lower()
