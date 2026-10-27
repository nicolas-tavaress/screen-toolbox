"""Pipeline GStreamer: PipeWire (tela) + áudio opcional + overlay de teclas -> arquivo."""

import time
from pathlib import Path

from gi.repository import GLib, Gst

from .. import log

logger = log.get(__name__)

Gst.init(None)

FIRST_FRAME_TIMEOUT = 8  # segundos
# MP4 fragmentado (fragmentos de 1 s): se a gravação for interrompida à força, o que já foi
# gravado continua reproduzível, ao contrário do MP4 comum que só escreve o índice no final.
MP4_MUX = "mp4mux fragment-duration=1000"
TEMP_PREFIX = ".screen-toolbox-"


def _has(name):
    return Gst.ElementFactory.find(name) is not None


def choose_format(preference="auto"):
    """Retorna (extensão, encoder de vídeo, muxer, encoder de áudio) conforme os plugins instalados."""
    h264 = None
    if _has("x264enc"):
        h264 = "x264enc speed-preset=veryfast tune=zerolatency pass=quant quantizer=21 key-int-max=120 " \
               "! video/x-h264,profile=high"
    elif _has("openh264enc"):
        h264 = "openh264enc bitrate=12000000 complexity=low"
    if h264 and _has("h264parse"):
        h264 += " ! h264parse"

    mp4_audio = "avenc_aac bitrate=192000" if _has("avenc_aac") else (
        "fdkaacenc bitrate=192000" if _has("fdkaacenc") else (
            "opusenc bitrate=160000" if _has("opusenc") else None))
    webm_audio = "opusenc bitrate=160000" if _has("opusenc") else (
        "vorbisenc" if _has("vorbisenc") else None)

    if _has("vp9enc"):
        vpx = "vp9enc deadline=1 cpu-used=8 row-mt=true threads=4 target-bitrate=10000000 keyframe-max-dist=120"
    elif _has("vp8enc"):
        vpx = "vp8enc deadline=1 cpu-used=8 threads=4 target-bitrate=10000000 keyframe-max-dist=120"
    else:
        vpx = None

    logger.debug("Codificadores: h264=%s vpx=%s áudio mp4=%s áudio webm=%s",
                 bool(h264), bool(vpx), mp4_audio and mp4_audio.split()[0], webm_audio and webm_audio.split()[0])
    if preference == "mp4" and not h264:
        logger.warning("MP4 solicitado mas nenhum encoder H.264 está instalado; tentando WebM")
    if preference in ("auto", "mp4") and h264 and _has("mp4mux"):
        return "mp4", f"video/x-raw,format=I420 ! {h264}", MP4_MUX, mp4_audio
    if vpx and _has("webmmux"):
        return "webm", f"video/x-raw,format=I420 ! {vpx}", "webmmux", webm_audio
    if h264 and _has("mp4mux"):
        return "mp4", f"video/x-raw,format=I420 ! {h264}", MP4_MUX, mp4_audio
    raise RuntimeError(
        "Nenhum codificador de vídeo encontrado. Instale o GStreamer 'plugins-ugly' (x264) ou 'plugins-good' (vpx)."
    )


class Recorder:
    """Grava a tela em arquivo. on_finished(caminho, erro) é chamado no loop principal."""

    def __init__(self, fd, node_id, options, overlay=None, on_finished=None):
        self.options = options
        self.overlay = overlay
        self.on_finished = on_finished
        self.started_at = None
        self._finished = False
        self._stop_timeout = 0
        self._frame_watchdog = 0
        self.frames = 0  # atualizado na thread de streaming

        ext, venc, mux, aenc = choose_format(options.get("video_format", "auto"))
        logger.info("Formato: %s | vídeo: %s | áudio: %s", ext, venc.split("!")[1].split()[0],
                    aenc.split()[0] if aenc else "nenhum encoder")
        folder = Path(options["video_dir"])
        folder.mkdir(parents=True, exist_ok=True)
        # Grava num arquivo temporário oculto na própria pasta; o usuário escolhe o nome ao final
        # e o arquivo é renomeado (os.replace, atômico por estar no mesmo sistema de arquivos).
        self.extension = f".{ext}"
        self.path = folder / time.strftime(f"{TEMP_PREFIX}%Y-%m-%d_%H-%M-%S.part.{ext}")

        fps = int(options.get("fps", 30))
        overlay_part = "videoconvert ! cairooverlay name=overlay ! " if overlay else ""
        location = str(self.path).replace("\\", "\\\\").replace('"', '\\"')
        parts = [
            # `path` recebe o node id devolvido pelo portal; `target-object` espera nome/serial
            # e, com o node id, o PipeWire liga ao objeto errado e nenhum quadro chega.
            f"pipewiresrc name=screen fd={fd} path={node_id} do-timestamp=true keepalive-time=1000 always-copy=true "
            f"! videocrop name=evencrop ! videorate ! video/x-raw,framerate={fps}/1 "
            f"! {overlay_part}videoconvert ! queue max-size-buffers=8 leaky=downstream "
            f"! {venc} ! queue ! mux.",
            f'{mux} name=mux ! filesink buffer-mode=unbuffered location="{location}"',
        ]

        sources = []
        if options.get("record_mic"):
            sources.append("pulsesrc do-timestamp=true")
        if options.get("record_system_audio"):
            sources.append("pulsesrc device=@DEFAULT_MONITOR@ do-timestamp=true")
        if sources and not aenc:
            logger.warning("Áudio solicitado, mas nenhum encoder de áudio disponível: gravando sem áudio")
        logger.info("Áudio: microfone=%s, sistema=%s", bool(options.get("record_mic")),
                    bool(options.get("record_system_audio")))
        if sources and aenc:
            audio_caps = "audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! queue"
            if len(sources) == 1:
                parts.append(f"{sources[0]} ! {audio_caps} ! audioconvert ! audio/x-raw,channels=2 ! {aenc} ! queue ! mux.")
            else:
                parts.append(f"audiomixer name=amix ! audioconvert ! audio/x-raw,channels=2 ! {aenc} ! queue ! mux.")
                for src in sources:
                    parts.append(f"{src} ! {audio_caps} ! amix.")

        self.description = "  ".join(parts)
        logger.debug("Pipeline: %s", self.description)
        self.pipeline = Gst.parse_launch(self.description)

        # x264/I420 exigem largura e altura pares (janelas podem ter tamanho ímpar)
        crop = self.pipeline.get_by_name("evencrop")
        crop.get_static_pad("sink").add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM, self._on_caps_probe, crop)

        screen_pad = self.pipeline.get_by_name("screen").get_static_pad("src")
        screen_pad.add_probe(Gst.PadProbeType.BUFFER, self._on_frame_probe)

        if overlay:
            element = self.pipeline.get_by_name("overlay")
            element.connect("caps-changed", overlay.on_caps_changed)
            element.connect("draw", overlay.on_draw)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", self._on_eos)
        bus.connect("message::error", self._on_error)
        bus.connect("message::warning", self._on_warning)
        bus.connect("message::state-changed", self._on_state_changed)

    @staticmethod
    def _on_caps_probe(_pad, info, crop):
        event = info.get_event()
        if event.type == Gst.EventType.CAPS:
            structure = event.parse_caps().get_structure(0)
            ok_w, width = structure.get_int("width")
            ok_h, height = structure.get_int("height")
            if ok_w and ok_h:
                logger.info("Formato do vídeo da tela: %dx%d%s", width, height,
                            " (cortando 1px para dimensões pares)" if width % 2 or height % 2 else "")
                crop.set_property("right", width % 2)
                crop.set_property("bottom", height % 2)
        return Gst.PadProbeReturn.OK

    def _on_frame_probe(self, _pad, _info):
        # thread de streaming: só conta; o log vai para o loop principal
        self.frames += 1
        if self.frames == 1:
            GLib.idle_add(self._on_first_frame)
        return Gst.PadProbeReturn.OK

    def _on_first_frame(self):
        logger.info("Primeiro quadro recebido após %.1f s", self.elapsed())
        if self._frame_watchdog:
            GLib.source_remove(self._frame_watchdog)
            self._frame_watchdog = 0
        return False

    def _on_no_frames(self):
        self._frame_watchdog = 0
        if self.frames == 0:
            logger.error("Nenhum quadro da tela em %d s: o PipeWire não entregou imagens", FIRST_FRAME_TIMEOUT)
            self._finish("A tela compartilhada não enviou imagens (falha na conexão com o PipeWire).")
        return False

    def start(self):
        result = self.pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            logger.error("Pipeline recusou o estado PLAYING")
            raise RuntimeError("Não foi possível iniciar a gravação.")
        self.started_at = time.monotonic()
        self._frame_watchdog = GLib.timeout_add_seconds(FIRST_FRAME_TIMEOUT, self._on_no_frames)

    def elapsed(self):
        return 0 if self.started_at is None else time.monotonic() - self.started_at

    def stop(self):
        """Envia EOS para fechar o arquivo corretamente."""
        if self._finished or self._stop_timeout:
            return
        # O EOS é injetado logo após cada fonte, em vez de pedir que a fonte o envie: se a
        # sessão do PipeWire já foi encerrada (ex.: parar pelo ícone do GNOME), o pipewiresrc
        # fica bloqueado esperando quadros e nunca emitiria o EOS, deixando o MP4 sem índice.
        iterator = self.pipeline.iterate_sources()
        count = 0
        while True:
            ok, source = iterator.next()
            if ok != Gst.IteratorResult.OK:
                break
            peer = source.get_static_pad("src").get_peer()
            if peer is not None:
                peer.send_event(Gst.Event.new_eos())
                count += 1
        logger.debug("EOS injetado após %d fonte(s)", count)
        # se o EOS não chegar (fonte travada), força o término
        self._stop_timeout = GLib.timeout_add_seconds(6, self._force_stop)

    def _force_stop(self):
        self._stop_timeout = 0
        logger.warning("EOS não chegou em 6 s; forçando a parada do pipeline")
        self._finish("A gravação não finalizou a tempo; o arquivo pode estar incompleto.")
        return False

    def _on_eos(self, _bus, _msg):
        logger.debug("EOS recebido: arquivo finalizado")
        self._finish(None)

    def _on_error(self, _bus, msg):
        err, debug = msg.parse_error()
        logger.error("Erro no GStreamer (%s): %s", msg.src.get_name() if msg.src else "?", err.message)
        logger.debug("Detalhes do erro: %s", debug)
        self._finish(err.message)

    def _on_warning(self, _bus, msg):
        warn, debug = msg.parse_warning()
        logger.warning("Aviso do GStreamer (%s): %s", msg.src.get_name() if msg.src else "?", warn.message)
        logger.debug("Detalhes do aviso: %s", debug)

    def _on_state_changed(self, _bus, msg):
        if msg.src is self.pipeline:
            old, new, _pending = msg.parse_state_changed()
            logger.debug("Pipeline: %s -> %s", old.value_nick, new.value_nick)

    def _finish(self, error):
        if self._finished:
            return
        self._finished = True
        logger.info("Gravação encerrada: %d quadros da tela em %.1f s", self.frames, self.elapsed())
        for attr in ("_stop_timeout", "_frame_watchdog"):
            if getattr(self, attr):
                GLib.source_remove(getattr(self, attr))
                setattr(self, attr, 0)
        self.pipeline.get_bus().remove_signal_watch()
        self.pipeline.set_state(Gst.State.NULL)
        try:
            if self.path.stat().st_size == 0:
                logger.warning("Arquivo vazio removido: %s", self.path)
                self.path.unlink()
        except OSError:
            pass
        if self.on_finished:
            self.on_finished(self.path, error)
