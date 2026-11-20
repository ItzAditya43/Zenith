"""Desktop control: tools only when enabled, approvals, and the action helpers with system commands faked."""
from __future__ import annotations

import json

import pytest

from app.services import desktop_control as dc


@pytest.fixture
def fake_cmds(monkeypatch, temp_data_dir):
    """Record every command; answer hyprctl/tesseract/ydotool/wtype like the real tools."""
    calls: list[tuple] = []
    state = {"active_class": "firefox"}
    clients = [
        {"address": "0x1", "class": "firefox", "title": "Docs - Mozilla Firefox", "workspace": {"name": "1"}, "mapped": True},
        {"address": "0x2", "class": "kitty", "title": "~/code", "workspace": {"name": "2"}, "mapped": True},
    ]
    tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n" \
          "5\t1\t1\t1\t1\t1\t100\t200\t40\t20\t96\tSave\n" \
          "5\t1\t1\t1\t1\t2\t150\t200\t60\t20\t95\tchanges\n" \
          "5\t1\t2\t1\t1\t1\t400\t500\t50\t20\t30\tblurry\n"

    async def run(*argv, timeout=15, stdin=None):
        calls.append(argv)
        if argv[0] == "hyprctl":
            if argv[1:] == ("-j", "clients"):
                return 0, json.dumps(clients), ""
            if argv[1:] == ("-j", "activewindow"):
                return 0, json.dumps({"address": "0x1", "class": state["active_class"]}), ""
            if argv[1:] == ("-j", "monitors"):
                return 0, json.dumps([{"name": "eDP-1", "x": 1920, "y": 0, "focused": True}]), ""
            return 0, "ok", ""
        if argv[0] == "tesseract":
            return 0, tsv, ""
        if argv[0].endswith("python3"):
            return 0, "[]", ""  # no accessibility tree: falls back to OCR
        return 0, "", ""

    async def png(focused_monitor_only=True):
        return b"\x89PNG fake"

    monkeypatch.setattr(dc, "_run", run)
    monkeypatch.setattr(dc, "screenshot_png", png)
    monkeypatch.setattr(dc, "status", lambda: {"hyprland": True, "pointer": True, "enabled": True})
    monkeypatch.setattr(dc, "_have", lambda c: True)
    return calls, state


def test_tools_are_offered_only_when_enabled(temp_data_dir):
    from app.core.config import settings
    from app.services.agent_service import _active_tools, _build_system_prompt

    settings.update({"desktop_control_enabled": False})
    assert not any(t.startswith("desktop_") for t in _active_tools())
    assert "desktop_click" not in _build_system_prompt([])
    settings.update({"desktop_control_enabled": True})
    try:
        assert "desktop_click" in _active_tools() and "desktop_click" in _build_system_prompt([])
    finally:
        settings.update({"desktop_control_enabled": False})


def test_looking_is_safe_and_acting_asks():
    from app.services.agent_service import classify_risk

    for t in ("desktop_windows", "desktop_screen", "desktop_find"):
        assert classify_risk(t, {}) == "safe"
    for t in ("desktop_open", "desktop_type", "desktop_keys", "desktop_click", "desktop_focus"):
        assert classify_risk(t, {}) == "risky"


async def test_windows_focus_and_move(fake_cmds):
    calls, _ = fake_cmds
    wins = await dc.windows()
    assert [w["class"] for w in wins] == ["firefox", "kitty"] and wins[0]["focused"]
    assert "kitty" in await dc.focus("kitty")
    assert ("hyprctl", "dispatch", "focuswindow", "address:0x2") in calls
    await dc.move_window("code", "3")
    assert ("hyprctl", "dispatch", "movetoworkspacesilent", "3,address:0x2") in calls
    with pytest.raises(dc.DesktopError):
        await dc.focus("spotify")


async def test_keys_and_typing(fake_cmds):
    calls, _ = fake_cmds
    await dc.press_keys("ctrl+shift+t")
    assert calls[-1] == ("wtype", "-M", "ctrl", "-M", "shift", "-k", "t", "-m", "shift", "-m", "ctrl")
    await dc.press_keys("enter")
    assert calls[-1] == ("wtype", "-k", "Return")
    await dc.type_text("hello world")
    assert calls[-1] == ("wtype", "--", "hello world")
    with pytest.raises(dc.DesktopError):
        await dc.press_keys("hyper+x")


async def test_password_managers_never_get_input(fake_cmds):
    _, state = fake_cmds
    state["active_class"] = "org.keepassxc.KeePassXC"
    for coro in (dc.type_text("secret"), dc.press_keys("ctrl+v")):
        with pytest.raises(dc.DesktopError, match="password manager"):
            await coro


async def test_find_by_ocr_then_click_by_number(fake_cmds):
    calls, _ = fake_cmds
    out = await dc.find("conv1", "save changes")
    assert "[1] text on screen: Save changes" in out and "blurry" not in out
    msg = await dc.click("conv1", 1)
    # Box spans both words, offset by the focused monitor at x=1920: centre (1920+100+55, 200+10).
    assert ("hyprctl", "dispatch", "movecursor", "2075 210") in calls
    assert calls[-1] == ("ydotool", "click", "0xC0") and "2075,210" in msg
    with pytest.raises(dc.DesktopError):
        await dc.click("conv1", 9)
    with pytest.raises(dc.DesktopError, match="desktop_find first"):
        await dc.click("other-conversation", 1)


async def test_open_prefers_urls_and_desktop_entries(fake_cmds, monkeypatch):
    calls, _ = fake_cmds
    await dc.open_thing("https://example.com")
    assert calls[-1] == ("xdg-open", "https://example.com")
    monkeypatch.setattr(dc, "_desktop_entries", lambda: [("Firefox", "firefox --new-window", "firefox"),
                                                         ("Files", "nautilus --new-window", "org.gnome.Nautilus")])
    assert await dc.open_thing("files") == "Started Files"
    assert calls[-1] == ("hyprctl", "dispatch", "exec", "nautilus --new-window")


async def test_agent_reports_disabled(temp_data_dir):
    from app.services.agent_service import _run_desktop

    assert (await _run_desktop("desktop_windows", {}, "c", 1000)).startswith("Error: desktop control is off")
