import re

import pytest


@pytest.fixture
def stylesheet(client) -> str:
    return client.get("/static/ama.css").text


def _rules(css: str) -> list[tuple[str, str]]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def test_form_controls_inherit_the_page_font(stylesheet):
    inheriting = {
        name.strip()
        for selector, body in _rules(stylesheet)
        if re.search(r"(^|;)\s*font\s*:\s*inherit\s*(;|$)", body)
        for name in selector.split(",")
    }
    assert {"button", "input", "select", "textarea"} <= inheriting


def test_every_font_naming_archivo_falls_back_to_sans_serif(stylesheet):
    bare = [
        f"{selector}{{{decl}}}"
        for selector, body in _rules(stylesheet)
        if not selector.startswith("@font-face")
        for decl in body.split(";")
        if re.match(r"\s*font(-family)?\s*:", decl)
        and "Archivo" in decl
        and not decl.rstrip().endswith("sans-serif")
    ]
    assert bare == []
