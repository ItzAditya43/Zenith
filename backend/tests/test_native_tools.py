import asyncio

from app.services import agent_service as a


def test_params_from_description_marks_optional():
    p = a._params_from_description(a.TOOLS["write_file"]["description"])
    assert set(p["properties"]) == {"path", "content", "mode"}
    assert p["required"] == ["path", "content"]
    assert a._params_from_description("No args here.")["properties"] == {}


def test_native_specs_cover_builtin_and_mcp():
    mcp = {"mcp_x": {"description": "x", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}}}
    specs = a._native_tool_specs(["read_file", "mcp_x"], mcp)
    assert specs[0]["function"]["parameters"]["required"] == ["path"]
    assert specs[1]["function"]["parameters"]["properties"] == {"q": {"type": "string"}}


class _Client:
    def __init__(self, msg):
        self.msg = msg
        self.used = None

    async def chat_tools(self, model, messages, tools):
        self.used = "native"
        return self.msg

    async def chat(self, model, messages, format=None):
        self.used = "json"
        return '{"final": "done"}'


def _step(msg, native=True):
    c = _Client(msg)
    step, _ = asyncio.run(a._next_step(c, "m", [], {}, [{"x": 1}] if native else None))
    return step, c.used


def test_native_tool_call_becomes_step():
    msg = {"content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "a.txt"}}}]}
    assert _step(msg) == ({"tool": "read_file", "args": {"path": "a.txt"}}, "native")


def test_native_string_arguments_and_text_fallbacks():
    msg = {"tool_calls": [{"function": {"name": "list_dir", "arguments": '{"path": "."}'}}]}
    assert _step(msg)[0] == {"tool": "list_dir", "args": {"path": "."}}
    assert _step({"content": '{"tool": "bash", "args": {"command": "ls"}}'})[0]["tool"] == "bash"
    assert _step({"content": "All finished."})[0] == {"final": "All finished."}


def test_models_without_tools_use_json_protocol():
    assert _step({}, native=False) == ({"final": "done"}, "json")
