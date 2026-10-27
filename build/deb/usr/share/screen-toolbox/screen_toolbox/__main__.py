import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")


MISSING_CAIRO = """Screen Toolbox: falta a integração PyGObject <-> Cairo.
Instale o pacote da sua distribuição:
  Debian/Ubuntu: sudo apt install python3-gi-cairo
  Fedora:        sudo dnf install python3-gobject
  Arch:          sudo pacman -S python-gobject python-cairo"""


def show_startup_error(message):
    """Mostra o erro numa janela: aberto pelo menu, ninguém vê o terminal."""
    from gi.repository import Adw, Gtk

    app = Adw.Application(application_id="io.github.nicolas.ScreenToolbox.Error")

    def on_activate(app):
        window = Adw.ApplicationWindow(application=app, title="Screen Toolbox", default_width=480)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        label = Gtk.Label(label=message, selectable=True, wrap=True, xalign=0)
        button = Gtk.Button(label="Fechar", halign=Gtk.Align.END, css_classes=["suggested-action"])
        button.connect("clicked", lambda *_: window.close())
        box.append(label)
        box.append(button)
        window.set_content(box)
        window.present()

    app.connect("activate", on_activate)
    app.run(None)


def main():
    import os

    from . import log

    argv = list(sys.argv)
    dev = "--dev" in argv or os.environ.get("SCREEN_TOOLBOX_DEV") == "1"
    argv = [a for a in argv if a != "--dev"]
    if dev:
        # avisos do GStreamer no terminal (sem sobrescrever um GST_DEBUG já definido)
        os.environ.setdefault("GST_DEBUG", "2")
    logger = log.setup(dev)

    try:
        gi.require_foreign("cairo")
    except ImportError:
        logger.critical(MISSING_CAIRO)
        show_startup_error(MISSING_CAIRO)
        return 1

    from .app import ScreenToolboxApp

    app = ScreenToolboxApp(dev=dev)
    status = app.run(argv)
    if app.restart_argv is not None:
        args = [sys.executable, "-m", "screen_toolbox", *(["--dev"] if dev else []), *app.restart_argv]
        logger.info("Reiniciando: %s", " ".join(args[1:]))
        os.execv(sys.executable, args)
    return status


if __name__ == "__main__":
    sys.exit(main())
