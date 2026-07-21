from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


_PROMPT_DIR = Path(__file__).parent / "prompt_templates"
_ENV = Environment(loader=FileSystemLoader(_PROMPT_DIR), undefined=StrictUndefined, autoescape=False)


def render_prompt(name: str, **context: object) -> str:
    return _ENV.get_template(f"{name}.j2").render(**context).strip() + "\n"
