"""Verificação do pacote instalado: `screen-toolbox --self-test [arquivo]`.

Usada no CI do Windows para garantir que o bundle tem tudo que o app precisa
(bibliotecas GI, plugins do GStreamer, captura de tela e D-Bus). Não abre janelas.
O relatório vai para o arquivo indicado (o executável sem console não tem stdout).
"""

import shutil
import sys
import tempfile
import threading
import traceback

from . import IS_WINDOWS, VERSION

WINDOWS_ELEMENTS = ["d3d11screencapturesrc", "d3d11download", "wasapi2src"]
LINUX_ELEMENTS = ["pipewiresrc", "pulsesrc"]
COMMON_ELEMENTS = ["videocrop", "videorate", "videoconvert", "cairooverlay", "queue", "filesink",
                   "audioconvert", "audioresample", "audiomixer", "mp4mux"]


def run(report_path=None):
    lines = [f"Screen Toolbox {VERSION} — autoteste ({sys.platform})"]
    failures = []

    def check(name, func, required=True):
        try:
            detail = func()
            lines.append(f"OK    {name}{f': {detail}' if detail else ''}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"{'FALHA' if required else 'AVISO'} {name}: {e}")
            if required:
                failures.append(name)
                lines.append(traceback.format_exc())

    def gi_libraries():
        import gi

        gi.require_foreign("cairo")
        from gi.repository import Adw, Gdk, GdkPixbuf, Gst, Gtk, Pango, PangoCairo  # noqa: F401

        Gst.init(None)
        return f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}, {Gst.version_string()}"

    def elements():
        from gi.repository import Gst

        wanted = COMMON_ELEMENTS + (WINDOWS_ELEMENTS if IS_WINDOWS else LINUX_ELEMENTS)
        missing = [e for e in wanted if Gst.ElementFactory.find(e) is None]
        if missing:
            raise RuntimeError(f"elementos ausentes: {', '.join(missing)}")
        return f"{len(wanted)} elementos"

    def video_format():
        from .record.pipeline import choose_format

        ext, venc, _mux, aenc = choose_format("auto")
        if ext != "mp4" or not aenc:
            raise RuntimeError(f"esperado MP4 com áudio, obtido {ext} (áudio: {aenc})")
        return f"{ext}: {venc.split('!')[1].split()[0]} + {aenc.split()[0]}"

    def pipeline():
        from gi.repository import Gst

        from .record.pipeline import Recorder

        folder = tempfile.mkdtemp(prefix="screen-toolbox-test-")
        options = {"video_dir": folder, "video_format": "auto", "fps": 30,
                   "record_mic": True, "record_system_audio": True}
        try:
            recorder = Recorder("videotestsrc name=screen is-live=true", options)
            recorder.pipeline.set_state(Gst.State.NULL)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        return "montado"

    def screenshot():
        from .win32.screenshot import capture_virtual_screen, monitors

        surface = capture_virtual_screen()
        return f"{surface.get_width()}x{surface.get_height()}, {len(monitors())} monitor(es)"

    def session_bus():
        from gi.repository import Gio

        result = []
        thread = threading.Thread(target=lambda: result.append(Gio.bus_get_sync(Gio.BusType.SESSION, None)),
                                  daemon=True)
        thread.start()
        thread.join(15)
        if not result:
            raise RuntimeError("sem resposta em 15 s")
        return "conectado (instância única disponível)"

    check("bibliotecas GI", gi_libraries)
    check("elementos do GStreamer", elements)
    check("formato de vídeo", video_format)
    check("pipeline de gravação", pipeline)
    if IS_WINDOWS:
        # o runner do CI roda sem sessão interativa: a captura pode falhar lá
        check("print da tela (GDI)", screenshot, required=False)
        check("D-Bus de sessão", session_bus, required=False)

    lines.append("RESULTADO: " + ("falhou: " + ", ".join(failures) if failures else "ok"))
    report = "\n".join(lines) + "\n"
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
    if sys.stdout is not None:
        sys.stdout.write(report)
    return 1 if failures else 0
