from app.api.mcp import _registry_entry


def test_npm_package_maps_to_npx_with_env():
    e = _registry_entry({"server": {"name": "io.x/weather", "description": "d", "packages": [
        {"registryType": "npm", "identifier": "weather-mcp", "transport": {"type": "stdio"},
         "packageArguments": [{"type": "positional", "value": "--metric"}],
         "environmentVariables": [{"name": "API_KEY", "isRequired": True}]}]}})
    assert e["name"] == "weather" and e["command"] == "npx"
    assert e["args"] == ["-y", "weather-mcp", "--metric"]
    assert e["env"] == [{"name": "API_KEY", "required": True, "description": ""}]


def test_pypi_and_remote_only():
    assert _registry_entry({"server": {"name": "a/b", "packages": [{"registryType": "pypi", "identifier": "mcp-b"}]}})["args"] == ["mcp-b"]
    assert _registry_entry({"server": {"name": "a/c", "packages": [{"registryType": "oci", "identifier": "img"}]}}) is None
    assert _registry_entry({"server": {"name": "a/d", "remotes": [{"url": "https://x"}]}}) is None
