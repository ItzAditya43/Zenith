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


def test_native_call_rejected_by_ollama_falls_back_to_json_protocol():
    from app.services.ollama_client import OllamaError

    class _Broken(_Client):
        async def chat_tools(self, model, messages, tools):
            raise OllamaError("Ollama returned 500: XML syntax error on line 3")

    c = _Broken({})
    step, _ = asyncio.run(a._next_step(c, "m", [], {}, [{"x": 1}]))
    assert step == {"final": "done"} and c.used == "json"


def test_call_nested_inside_its_own_args_is_unwrapped():
    inner = {"path": "cart.py", "old_string": "a", "new_string": "b"}
    for key in ("args", "parameters"):
        msg = {"tool_calls": [{"function": {"name": "edit_file", "arguments": {"tool": "edit_file", key: inner}}}]}
        assert _step(msg)[0] == {"tool": "edit_file", "args": inner}
    raw = '{"tool": "read_file", "args": {"tool": "read_file", "args": {"path": "a"}}}'
    assert a._parse_step(raw) == {"tool": "read_file", "args": {"path": "a"}}
    # A tool that really takes an argument named "tool" is left alone.
    keep = {"tool": "x", "args": {"tool": "x", "other": 1}}
    assert a._unwrap_step(keep) == keep
