"""Diálogo para nomear um arquivo antes de salvar (nome obrigatório, sem sugestão)."""

from pathlib import Path

from gi.repository import Adw, Gtk

from . import log

logger = log.get(__name__)


def _validate(text, folder, extension):
    """Retorna (caminho, None) se válido ou (None, mensagem de erro)."""
    name = text.strip()
    if name.lower().endswith(extension.lower()):
        name = name[: -len(extension)].rstrip()  # evita "teste.png.png"
    if not name:
        return None, ""
    if "/" in name or "\0" in name:
        return None, "O nome não pode conter “/”."
    if name in (".", ".."):
        return None, "Nome inválido."
    path = Path(folder) / f"{name}{extension}"
    if path.exists():
        return None, "Já existe um arquivo com esse nome."
    return path, None


def ask_filename(parent, heading, folder, extension, on_done, body=None):
    """Pede o nome do arquivo. on_done(Path) ao salvar ou on_done(None) ao cancelar."""
    dialog = Adw.AlertDialog(heading=heading, body=body or f"Será salvo em {folder}")
    dialog.add_response("cancel", "Cancelar")
    dialog.add_response("save", "Salvar")
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("save")
    dialog.set_close_response("cancel")
    dialog.set_response_enabled("save", False)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    entry = Gtk.Entry(placeholder_text="Nome do arquivo", activates_default=True)
    suffix = Gtk.Label(label=extension, css_classes=["dim-label"])
    row = Gtk.Box(spacing=6)
    entry.set_hexpand(True)
    row.append(entry)
    row.append(suffix)
    error = Gtk.Label(xalign=0, wrap=True, css_classes=["error", "caption"], visible=False)
    box.append(row)
    box.append(error)
    dialog.set_extra_child(box)

    state = {"path": None}

    def on_changed(*_):
        path, message = _validate(entry.get_text(), folder, extension)
        state["path"] = path
        dialog.set_response_enabled("save", path is not None)
        error.set_label(message or "")
        error.set_visible(bool(message))

    def on_response(_dialog, response):
        if response == "save" and state["path"] is not None:
            logger.info("Nome escolhido: %s", state["path"].name)
            on_done(state["path"])
        else:
            logger.info("Diálogo de nome cancelado (%s)", heading)
            on_done(None)

    entry.connect("changed", on_changed)
    dialog.connect("response", on_response)
    dialog.present(parent)
    entry.grab_focus()
    return dialog
