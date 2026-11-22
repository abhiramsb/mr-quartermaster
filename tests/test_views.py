"""Role-picker status text."""
import sys, types
from types import SimpleNamespace

import pytest

pytest.importorskip("discord")

from qm import views  # noqa: E402
from qm.layout import ROLE_CLUB, ROLE_EVENTS  # noqa: E402


def test_roles_status_marks_owned_roles(monkeypatch):
    roles = {name: SimpleNamespace(name=name) for name, *_ in views.PICKER_ROLES}
    monkeypatch.setattr(views, "get_role", lambda bot, guild, name: roles.get(name))
    member = SimpleNamespace(roles=[roles[ROLE_CLUB]])
    lines = views.roles_status(None, None, member).splitlines()
    assert len(lines) == len(views.PICKER_ROLES)
    assert lines[0].startswith("\u2705") and "Football Club" in lines[0]
    assert all(line.startswith("\u2b1c") for line in lines[1:])


def test_roles_status_handles_missing_role(monkeypatch):
    monkeypatch.setattr(views, "get_role", lambda bot, guild, name: None)
    out = views.roles_status(None, None, SimpleNamespace(roles=[]))
    assert out.count("\u2b1c") == len(views.PICKER_ROLES)




def test_welcome_button_custom_id_roundtrip():
    import re
    from qm.views import WelcomeButton, welcome_label
    item = WelcomeButton(123456789012345678, 3)
    assert item.item.custom_id == "qm:welcome:123456789012345678"
    assert re.fullmatch(WelcomeButton.__discord_ui_compiled_template__.pattern, item.item.custom_id)
    assert welcome_label(0) == "Welcome" and welcome_label(3) == "Welcome (3)"
