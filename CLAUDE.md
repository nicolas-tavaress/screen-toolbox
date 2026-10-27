# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projeto

Screen Toolbox: prints com anotação (estilo Flameshot) e gravação de tela com teclas/cliques
desenhados no vídeo. Python + GTK4/libadwaita + GStreamer + xdg-desktop-portal, para Wayland e X11.
Sem dependências pip: tudo vem dos pacotes PyGObject/GStreamer da distro (lista no README).
Código, comentários, logs e textos da interface são em português: mantenha assim.

## Comandos

```sh
./bin/screen-toolbox            # roda a partir do código (ajusta PYTHONPATH e chama python3 -m screen_toolbox)
make dev                        # modo dev: DEBUG colorido no terminal, GST_DEBUG=2, app ID ".Devel"
make logs                       # tail de ~/.local/state/screen-toolbox/screen-toolbox.log
./bin/screen-toolbox --screenshot | --record | --stop   # ações enviadas à instância em execução
make deb                        # gera build/screen-toolbox_<versão>_all.deb
make clean
```

Não há suíte de testes nem linter configurados. Para verificar mudanças de UI sem interação,
escreva um script avulso (fora do repositório) que crie um `Adw.Application`, instancie a janela
(ex.: `CaptureWindow(app, cairo_surface, None, callback)`), manipule o estado via `GLib.timeout_add`
e confira os resultados. Use uma surface com a proporção do monitor, porque o canvas estica a imagem
para a tela inteira.

`build/deb/` é uma cópia gerada pelo `make deb`. Não edite nem pesquise código ali.

A versão aparece em vários lugares: `screen_toolbox/__init__.py`, `Makefile`, `data/*.metainfo.xml`,
`packaging/rpm/*.spec`, `packaging/arch/PKGBUILD`.

## Arquitetura

- **Instância única via `Gio.Application`** (`app.py`, `HANDLES_COMMAND_LINE`): os atalhos globais
  do sistema chamam `screen-toolbox --screenshot` etc., e o comando é encaminhado para a instância já
  aberta em `do_command_line`. O app fica em segundo plano (`hold()`) após fechar a janela. Se os
  `.py` mudaram desde o início (ex.: `make install`), a instância remota se reinicia com `os.execv`
  (`restart_argv` em `__main__.py`). No modo dev o ID é diferente, para não cair na instância instalada.
- **Portais** (`portal.py`): helper genérico para o padrão Request/Response do xdg-desktop-portal
  via `Gio.DBus`. É usado pelo Screenshot (`capture/screenshot.py`) e pelo ScreenCast
  (`record/screencast.py`, que devolve fd + nó PipeWire e um `restore_token` salvo na config).
- **Fluxo de print** (`ScreenToolboxApp.capture`): esconde a janela principal, tira um print do
  desktop inteiro pelo portal, recorta um pedaço por monitor (`capture/region.monitor_crop`, que
  converte de coordenadas lógicas para físicas e reamostra conforme a escala) e abre uma
  `CaptureWindow` em tela cheia por monitor. Quando a seleção começa num monitor, as outras janelas
  fecham. Se o GNOME recusar o print, o app mostra a janela para pedir a permissão e tenta de novo.
- **Editor** (`editor/`):
  - `canvas.py` (`Canvas`, uma `Gtk.DrawingArea`) guarda a seleção (`crop`, em coordenadas da
    imagem), as formas e um undo/redo por snapshots.
  - `tools.py` define as formas vetoriais e a renderização Cairo.
  - `window.py` é a janela em tela cheia, com a barra de ferramentas num `Gtk.Overlay`, posicionada
    via `margin_start`/`margin_top`. Atenção: o `measure()` do GTK4 inclui as margens e devolve 0
    para widgets ocultos.
  - O canvas emite `changed`, `selection-dragging` e `selection-started`. A escala imagem↔tela vem
    de `Canvas.scale()`.
- **Gravação** (`record/`): a sessão ScreenCast entrega o fd e o nó para o `pipeline.Recorder`, que
  monta uma descrição `Gst.parse_launch`: `pipewiresrc`, `videocrop` (força dimensões pares),
  `cairooverlay` opcional, encoder e mux. `choose_format` escolhe MP4 (x264) ou WebM conforme os
  plugins disponíveis. O MP4 é fragmentado, então continua reproduzível se a gravação cair. Grava num
  arquivo temporário (`.screen-toolbox-*`) e depois pede um nome obrigatório (`name_dialog.py`).
- **Teclas/cliques**: `input_events.InputMonitor` é uma thread que lê `/dev/input/event*` (exige o
  grupo `input`) só durante a gravação. `KeystrokeModel` transforma os eventos em badges,
  `keymap.KeyLabeler` faz a tradução de layout e `overlay.KeyOverlay` desenha no `cairooverlay`.
  Teclas digitadas nunca podem ir para o log.
- **Bandeja** (`tray.py`): StatusNotifierItem + DBusMenu implementados direto em D-Bus, porque o
  GTK4 não tem API de bandeja.
- **Config** (`config.py`): singleton `config` com `DEFAULTS`, salvo em
  `~/.config/screen-toolbox/config.json`. As chaves em `SECRET_KEYS` (ex.: `restore_token`) não vão
  para o log.
- **Log** (`log.py`): use `log.get(__name__)`. O arquivo é rotativo; no terminal aparecem só avisos,
  ou tudo no modo dev.
