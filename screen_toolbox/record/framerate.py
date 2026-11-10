"""Taxas de quadros da gravação, limitadas pela taxa de atualização da tela gravada."""

from .. import log

logger = log.get(__name__)

FPS_OPTIONS = (30, 60, 90, 120)
UNKNOWN_LIMIT = 60  # sem saber a taxa da tela, não oferece mais que isso


def allowed(refresh_hz):
    """Opções que não passam da taxa da tela (119,88 Hz conta como 120). Sempre inclui 30."""
    limit = round(refresh_hz) if refresh_hz and refresh_hz > 0 else UNKNOWN_LIMIT
    return [fps for fps in FPS_OPTIONS if fps <= limit] or [FPS_OPTIONS[0]]


def clamp(fps, refresh_hz):
    """Maior opção permitida que não passa de `fps` (nem da taxa da tela)."""
    options = [o for o in allowed(refresh_hz) if o <= fps]
    return options[-1] if options else FPS_OPTIONS[0]


def monitor_refresh(monitor):
    """Taxa de atualização em Hz de um Gdk.Monitor (0 se desconhecida)."""
    return monitor.get_refresh_rate() / 1000  # o GDK devolve mHz


def _monitors(display):
    items = display.get_monitors()
    return [items.get_item(i) for i in range(items.get_n_items())]


def max_refresh(display):
    """Maior taxa entre os monitores conectados (0 se nenhuma for conhecida)."""
    return max((monitor_refresh(m) for m in _monitors(display)), default=0)


def refresh_at(display, position):
    """Taxa do monitor que começa em `position` (x, y lógicos, como o portal informa).

    Sem posição ou sem monitor nela: a menor taxa entre os monitores, para nunca passar da tela."""
    monitors = _monitors(display)
    if position is not None:
        for monitor in monitors:
            geo = monitor.get_geometry()
            if (geo.x, geo.y) == tuple(position):
                return monitor_refresh(monitor)
    if len(monitors) > 1:
        logger.warning("Não foi possível identificar o monitor gravado (posição %s); usando a menor taxa", position)
    return min((monitor_refresh(m) for m in monitors), default=0)


def refresh_of_index(display, rects, index):
    """Windows: taxa do monitor `rects[index]` (itens de win32.screenshot.monitors()).

    Os monitores do GDK são casados com os do Windows pela ordem de posição, como em
    capture/region.py."""
    monitors = sorted(_monitors(display), key=lambda m: (m.get_geometry().x, m.get_geometry().y))
    if len(monitors) != len(rects) or not 0 <= index < len(rects):
        return min((monitor_refresh(m) for m in monitors), default=0)
    ordered = sorted(range(len(rects)), key=lambda i: (rects[i]["x"], rects[i]["y"]))
    return monitor_refresh(monitors[ordered.index(index)])
