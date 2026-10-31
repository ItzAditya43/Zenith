from app.services import agent_service as a

OLD = "".join(f"line {i}\n" for i in range(30))
NEW = OLD.replace("line 2\n", "LINE TWO\n").replace("line 25\n", "LINE 25\n")


def test_preview_has_one_hunk_per_change_group(tmp_path):
    (tmp_path / "f.txt").write_text(OLD)
    diff, prev, _ = a._preview_diff("write_file", {"path": "f.txt", "content": NEW}, str(tmp_path))
    assert prev == OLD
    assert sum(line.startswith("@@") for line in diff.splitlines()) == 2


def test_apply_hunks_keeps_only_accepted():
    assert a._apply_hunks(OLD, NEW, set()) == NEW
    only_second = a._apply_hunks(OLD, NEW, {0})
    assert "line 2\n" in only_second and "LINE 25\n" in only_second
    assert a._apply_hunks(OLD, NEW, {0, 1}) == OLD


def test_partial_args_for_edit_file_and_all_rejected():
    args = {"path": "f.txt", "old_string": "line 2\n", "new_string": "LINE TWO\n"}
    assert a._partial_args("edit_file", args, OLD, {0}) is None
    out = a._partial_args("write_file", {"path": "f.txt", "content": NEW}, OLD, {1})
    assert out == {"path": "f.txt", "content": OLD.replace("line 2\n", "LINE TWO\n")}


def test_approve_records_rejections_only_when_approved():
    import asyncio

    async def go():
        fut = asyncio.get_running_loop().create_future()
        a._pending["c1"] = fut
        assert a.approve_tool_call("c1", True, [1])
        a._pending.pop("c1")
        return await fut

    assert asyncio.run(go()) is True
    assert a._rejected_hunks.pop("c1") == {1}
