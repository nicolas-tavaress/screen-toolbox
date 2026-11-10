"""Fonte de vídeo da tela no Windows (Direct3D 11), com a interface de ScreenCastSession.

No Windows não há portal nem seletor do sistema: o monitor vem da configuração
`record_monitor` (índice em win32.screenshot.monitors(), 0 = principal).
"""

from gi.repository import GLib

from .. import log
from .screenshot import monitors

logger = log.get(__name__)


class WinScreenSource:
    def __init__(self, monitor_index=0):
        self.monitor_index = monitor_index
        self.restore_token = ""
        self.not_monitor = False
        self.show_cursor = True
        self.monitor = None

    def start(self, on_ready, on_error, on_closed, show_cursor=True, restore_token="", persist=True):
        """Mesma assinatura de ScreenCastSession.start; on_ready é chamado no próximo ciclo."""
        self.show_cursor = show_cursor
        found = monitors()
        if not found:
            GLib.idle_add(lambda: on_error("Nenhum monitor encontrado.") and False)
            return
        if self.monitor_index >= len(found):
            logger.warning("Monitor %d não existe mais (%d monitores); gravando o principal",
                           self.monitor_index, len(found))
            self.monitor_index = 0
        self.monitor = found[self.monitor_index]
        m = self.monitor
        details = f"monitor {self.monitor_index} ({m['device']}, {m['width']}x{m['height']})"
        GLib.idle_add(lambda: on_ready(self.video_source(), details) and False)

    def video_source(self):
        """Elemento GStreamer da tela (precisa se chamar `screen`)."""
        cursor = "true" if self.show_cursor else "false"
        return (f"d3d11screencapturesrc name=screen monitor-handle={self.monitor['handle']} "
                f"show-cursor={cursor} ! d3d11download")

    def close(self):
        self.monitor = None
