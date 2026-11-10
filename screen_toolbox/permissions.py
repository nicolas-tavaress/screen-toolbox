"""Situação das permissões do sistema (Linux): print pelo portal, gravação e leitura de teclas.

A permissão de print sem diálogo fica no PermissionStore do xdg-desktop-portal (tabela
`screenshot`), com uma entrada por app. Para apps fora de sandbox ela não aparece nas
Configurações do GNOME, então o app consulta e redefine por conta própria.
"""

import getpass
import grp
import re
import shutil

from gi.repository import Gio, GLib

from . import log
from .config import config
from .portal import get_portal
from .record.input_events import input_access_ok

logger = log.get(__name__)

GRANTED, DENIED, NOT_ASKED, NEEDS_RELOGIN, UNKNOWN = "concedida", "negada", "não solicitada", "relogar", "desconhecida"

STORE_BUS = "org.freedesktop.impl.portal.PermissionStore"
STORE_PATH = "/org/freedesktop/impl/portal/PermissionStore"
SCREENSHOT_TABLE = SCREENSHOT_ID = "screenshot"
INPUT_GROUP = "input"

# Mesmas regras do xdg-desktop-portal para tirar o ID do app do nome da unidade systemd:
# app[-<lançador>]-<ID>-<aleatório>.scope|slice e app[-<lançador>]-<ID>[@<aleatório>].service
_UNIT_SCOPE = re.compile(r"^app-(?:[A-Za-z0-9]+-)?(.+?)(?:-[A-Za-z0-9]*)(?:-[A-Za-z0-9]*)?\.(?:scope|slice)$")
_UNIT_SERVICE = re.compile(r"^app-(?:[A-Za-z0-9]+-)?(.+?)(?:@[A-Za-z0-9]*)?\.service$")


def app_id_from_cgroup(text):
    """ID com que o portal enxerga o processo, a partir do conteúdo de /proc/<pid>/cgroup.
    Vazio quando o app não foi aberto pelo menu (ex.: terminal ou atalho de teclado)."""
    for line in text.splitlines():
        unit = line.rsplit("/", 1)[-1].strip()
        match = _UNIT_SCOPE.match(unit) or _UNIT_SERVICE.match(unit)
        if match:
            # o systemd escapa caracteres como "-" no nome da unidade (\x2d)
            return re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), match.group(1))
    return ""


def portal_app_id():
    try:
        with open("/proc/self/cgroup", encoding="utf-8") as f:
            return app_id_from_cgroup(f.read())
    except OSError as e:
        logger.debug("Não foi possível ler /proc/self/cgroup: %s", e)
        return ""


def _store_call(method, params, reply_type=None):
    return get_portal().bus.call_sync(
        STORE_BUS, STORE_PATH, STORE_BUS, method, params,
        GLib.VariantType(reply_type) if reply_type else None,
        Gio.DBusCallFlags.NONE, 3000, None,
    )


def screenshot_status():
    """Permissão para tirar prints sem o diálogo do sistema."""
    if get_portal().get_property("org.freedesktop.portal.Screenshot", "version") is None:
        return UNKNOWN
    try:
        permissions = _store_call("Lookup", GLib.Variant("(ss)", (SCREENSHOT_TABLE, SCREENSHOT_ID)),
                                  "(a{sas}v)").unpack()[0]
    except GLib.Error as e:
        if "NotFound" in (Gio.DBusError.get_remote_error(e) or ""):
            return NOT_ASKED  # tabela ainda vazia: nenhum app pediu
        logger.debug("PermissionStore indisponível: %s", e.message)
        return UNKNOWN
    values = permissions.get(portal_app_id())
    if not values:
        return NOT_ASKED
    return {"yes": GRANTED, "no": DENIED}.get(values[0], NOT_ASKED)


def reset_screenshot():
    """Apaga a resposta gravada, para o sistema voltar a perguntar. Devolve False se falhar."""
    app_id = portal_app_id()
    try:
        _store_call("DeletePermission", GLib.Variant("(sss)", (SCREENSHOT_TABLE, SCREENSHOT_ID, app_id)))
    except GLib.Error as e:
        logger.warning("Não foi possível redefinir a permissão de print: %s", e.message)
        return False
    logger.info("Permissão de print redefinida (app id do portal: %r)", app_id)
    return True


def input_status():
    """Leitura de /dev/input, usada para mostrar teclas e cliques no vídeo."""
    if input_access_ok():
        return GRANTED
    try:
        if getpass.getuser() in grp.getgrnam(INPUT_GROUP).gr_mem:
            return NEEDS_RELOGIN  # já está no grupo, mas a sessão atual é de antes disso
    except (KeyError, OSError):
        pass
    return DENIED


def input_group_command():
    return f"sudo usermod -aG {INPUT_GROUP} $USER"


def add_to_input_group(callback):
    """Adiciona o usuário ao grupo `input` pedindo a senha pelo polkit.
    callback(erro): None se deu certo, "" se o usuário cancelou, ou a mensagem de erro."""
    pkexec, usermod = shutil.which("pkexec"), shutil.which("usermod") or "/usr/sbin/usermod"
    if not pkexec:
        callback("O pkexec (polkit) não está instalado.")
        return
    user = getpass.getuser()
    logger.info("Adicionando o usuário ao grupo %s via pkexec", INPUT_GROUP)

    def done(process, result):
        try:
            process.wait_finish(result)
        except GLib.Error as e:
            callback(e.message)
            return
        status = process.get_exit_status()
        if status == 0:
            logger.info("Usuário adicionado ao grupo %s", INPUT_GROUP)
            callback(None)
        elif status in (126, 127):  # pkexec: autenticação cancelada ou negada
            logger.info("Autenticação do pkexec cancelada")
            callback("")
        else:
            logger.error("usermod terminou com código %d", status)
            callback(f"O usermod falhou (código {status}).")

    try:
        process = Gio.Subprocess.new([pkexec, usermod, "-aG", INPUT_GROUP, user], Gio.SubprocessFlags.NONE)
    except GLib.Error as e:
        callback(e.message)
        return
    process.wait_async(None, done)


def screencast_status():
    """(portal disponível, tela lembrada). Essa permissão é pedida pelo sistema ao gravar."""
    available = get_portal().get_property("org.freedesktop.portal.ScreenCast", "version") is not None
    return available, bool(config.get("remember_source") and config.get("restore_token"))
