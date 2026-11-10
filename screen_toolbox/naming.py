"""Nome automático de prints e vídeos a partir de um padrão com campos, ex.: "Captura {data} {hora}"."""

import re
import time
from pathlib import Path

from . import IS_WINDOWS, log
from .config import DEFAULTS, config

logger = log.get(__name__)

WINDOWS_INVALID = set('\\/:*?"<>|')
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}

# (campo, descrição, só para vídeos)
FIELDS = [
    ("data", "Data (2026-11-10)", False),
    ("hora", "Hora (14-32-05)", False),
    ("ano", "Ano (2026)", False),
    ("mes", "Mês (11)", False),
    ("dia", "Dia (10)", False),
    ("h", "Hora do dia (14)", False),
    ("min", "Minuto (32)", False),
    ("seg", "Segundo (05)", False),
    ("contador", "Número sequencial (001)", False),
    ("duracao", "Duração do vídeo (01m23s)", True),
]

_FIELD_RE = re.compile(r"\{([a-z]+)\}")
_EXAMPLE_TIME = time.struct_time((2026, 11, 10, 14, 32, 5, 1, 314, -1))
_EXAMPLE_DURATION = 83


def fields_for(kind):
    """Campos disponíveis para kind ("screenshot" ou "video"), como (campo, descrição)."""
    return [(name, text) for name, text, video_only in FIELDS if kind == "video" or not video_only]


def _format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes:02d}m{secs:02d}s"


def _sanitize(name):
    """Troca o que não pode aparecer num nome de arquivo e apara as pontas."""
    name = name.replace("/", "-").replace("\0", "")
    if IS_WINDOWS:
        name = "".join("-" if c in WINDOWS_INVALID or ord(c) < 32 else c for c in name)
        name = name.strip().rstrip(".")
        if name.split(".")[0].upper() in WINDOWS_RESERVED:
            name = f"_{name}"
    name = name.strip()
    return "" if name in (".", "..") else name


def render(pattern, kind, when, counter, duration=None):
    """Monta o nome (sem extensão). Campos desconhecidos ficam como texto. Pode devolver ""."""
    values = {
        "data": time.strftime("%Y-%m-%d", when),
        "hora": time.strftime("%H-%M-%S", when),
        "ano": time.strftime("%Y", when),
        "mes": time.strftime("%m", when),
        "dia": time.strftime("%d", when),
        "h": time.strftime("%H", when),
        "min": time.strftime("%M", when),
        "seg": time.strftime("%S", when),
        "contador": f"{counter:03d}",
    }
    if kind == "video":
        values["duracao"] = _format_duration(duration or 0)
    return _sanitize(_FIELD_RE.sub(lambda m: values.get(m.group(1), m.group(0)), pattern))


def uses_counter(pattern):
    return "{contador}" in pattern


def preview(kind, pattern, extension):
    """Nome de exemplo para a tela de preferências ("" se o padrão não gera nome)."""
    name = render(pattern, kind, _EXAMPLE_TIME, config.get(f"{kind}_counter") + 1, _EXAMPLE_DURATION)
    return f"{name}{extension}" if name else ""


def auto_path(kind, folder, extension, duration=None):
    """Caminho livre em folder para o próximo arquivo, conforme o padrão configurado."""
    pattern = config.get(f"{kind}_name_pattern")
    counter = config.get(f"{kind}_counter") + 1
    when = time.localtime()
    name = render(pattern, kind, when, counter, duration)
    if not name:
        logger.warning("Padrão de nome vazio ou inválido para %s; usando o padrão de fábrica", kind)
        pattern = DEFAULTS[f"{kind}_name_pattern"]
        name = render(pattern, kind, when, counter, duration)
    if uses_counter(pattern):
        config.set(f"{kind}_counter", counter)
    folder = Path(folder)
    path = folder / f"{name}{extension}"
    n = 2
    while path.exists():
        path = folder / f"{name} ({n}){extension}"
        n += 1
    logger.info("Nome automático: %s", path.name)
    return path
