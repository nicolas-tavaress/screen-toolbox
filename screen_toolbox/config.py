"""Configuração persistida em ~/.config/screen-toolbox/config.json."""

import json
import os
from pathlib import Path

from gi.repository import GLib

from . import log

logger = log.get(__name__)

SECRET_KEYS = {"restore_token"}


def _special_dir(kind, fallback):
    path = GLib.get_user_special_dir(kind)
    return path or str(Path.home() / fallback)


CONFIG_DIR = Path(GLib.get_user_config_dir()) / "screen-toolbox"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    # Prints
    "screenshot_dir": str(Path(_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES, "Pictures")) / "Screenshots"),
    "screenshot_delay": 0,
    "copy_on_save": False,
    # App
    "run_in_background": True,
    "show_tray": True,
    "background_notice_shown": False,
    # Vídeo
    "video_dir": str(Path(_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS, "Videos")) / "Screencasts"),
    "video_format": "auto",  # auto | mp4 | webm
    "fps": 30,
    "record_cursor": True,
    "record_mic": False,
    "record_system_audio": False,
    "minimize_on_record": True,
    "remember_source": True,
    "restore_token": "",
    # Teclas / cliques no vídeo
    "show_keys": True,
    "show_clicks": True,
    "overlay_position": "bottom-center",  # bottom-center | bottom-left | bottom-right | top-center | top-left | top-right
    "overlay_scale": 1.0,
    "overlay_duration": 2.0,
    # Editor
    "editor_color": "#e01b24",
    "editor_width": 4,
}


class Config:
    def __init__(self):
        self._data = dict(DEFAULTS)
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                stored = json.load(f)
        except FileNotFoundError:
            logger.info("Sem arquivo de configuração; usando padrões (%s)", CONFIG_FILE)
            return
        except (OSError, ValueError) as e:
            logger.warning("Configuração inválida em %s, usando padrões: %s", CONFIG_FILE, e)
            return
        if not isinstance(stored, dict):
            logger.warning("Configuração em %s não é um objeto JSON; ignorando", CONFIG_FILE)
            return
        unknown = sorted(set(stored) - set(DEFAULTS))
        if unknown:
            logger.debug("Ignorando chaves desconhecidas na configuração: %s", unknown)
        self._data.update({k: v for k, v in stored.items() if k in DEFAULTS})
        logger.debug("Configuração carregada de %s", CONFIG_FILE)

    def items(self):
        return dict(self._data).items()

    def get(self, key):
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        if self._data.get(key) == value:
            return
        shown = "<oculto>" if key in SECRET_KEYS else repr(value)
        logger.info("Configuração: %s = %s", key, shown)
        self._data[key] = value
        self.save()

    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, CONFIG_FILE)
        except OSError as e:
            logger.error("Não foi possível salvar a configuração em %s: %s", CONFIG_FILE, e)


config = Config()
