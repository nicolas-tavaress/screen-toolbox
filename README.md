# Screen Toolbox

Prints com anotações e gravação de tela mostrando teclas e cliques — tudo em um app só.
Feito com Python + GTK4/libadwaita + GStreamer + xdg-desktop-portal, então funciona em
Wayland e X11 (GNOME, KDE, Hyprland, Sway…) no Debian/Ubuntu, Fedora e Arch.

## Recursos

- **Print com edição no lugar** (estilo Flameshot): arraste para selecionar a área e edite
  direto sobre a tela — caneta, marca-texto, linha, seta, retângulo, elipse, texto, marcador
  numerado, desfocar e pixelar. A seleção continua ajustável pelas alças e pode ser movida
  (ferramenta Mover, `V`) sem perder as anotações. `Enter`/`Ctrl+C` copia e fecha, `Ctrl+S`
  salva, `Esc` cancela.
- **Nome obrigatório**: todo print e todo vídeo pede um nome antes de salvar (cancelar o nome de um
  vídeo pergunta se quer descartá-lo).
- **Ícone na barra superior**: Capturar área, Gravar/Parar (com o tempo), Abrir janela,
  Preferências e Sair. KDE suporta nativamente; no GNOME requer a extensão AppIndicator
  (já ativa no Ubuntu; em Fedora/Arch instale `gnome-shell-extension-appindicator`).
- **Segundo plano**: fechar a janela não encerra o app (atalhos respondem na hora); para
  encerrar use **Sair** no menu (`Ctrl+Q`). Dá para desligar em Preferências → Geral.
- **Gravação** (sempre da tela inteira): MP4 (H.264/AAC) ou WebM (VP9/Opus), microfone e áudio do sistema
  (ambos desligados por padrão), teclas e cliques desenhados no vídeo.

## Rodar a partir do código

```sh
# Debian/Ubuntu
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0 \
    gstreamer1.0-pipewire gstreamer1.0-plugins-good gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    gstreamer1.0-pulseaudio
# Fedora (x264 vem do RPM Fusion; sem ele grava em WebM)
sudo dnf install python3-gobject python3-cairo gtk4 libadwaita gstreamer1-plugins-good \
    pipewire-gstreamer gstreamer1-plugins-ugly gstreamer1-plugin-libav
# Arch
sudo pacman -S python-gobject python-cairo gtk4 libadwaita gst-plugins-good gst-plugin-pipewire \
    gst-plugins-ugly gst-libav

./bin/screen-toolbox
```

### Modo dev e logs

```sh
make dev            # ou: ./bin/screen-toolbox --dev   (ou SCREEN_TOOLBOX_DEV=1)
make logs           # acompanha o arquivo de log
```

- **Modo dev**: tudo (DEBUG+) colorido no terminal, avisos do GStreamer ativados e um ID de
  app separado (`.Devel`), para não cair numa instância instalada que já esteja aberta.
- **Modo normal**: só avisos e erros no terminal.
- Sempre grava em `~/.local/state/screen-toolbox/screen-toolbox.log` (rotativo, 1 MB × 4).
- Teclas digitadas durante a gravação **nunca** são registradas no log.

### Teclas e cliques no vídeo

No Wayland não existe API para ler teclas globalmente; o app lê `/dev/input` **somente durante
a gravação**. Seu usuário precisa estar no grupo `input`:

```sh
sudo usermod -aG input $USER   # depois saia e entre na sessão
```

Limitações: cliques aparecem como etiqueta (“Mouse: esquerdo”), não como círculo no ponto
(o kernel não informa a posição do cursor); toque no touchpad (tap-to-click) não é detectado.

## Atalhos globais

Crie atalhos personalizados nas configurações de teclado do sistema:

| Ação | Comando |
|---|---|
| Capturar área | `screen-toolbox --screenshot` |
| Iniciar/parar gravação | `screen-toolbox --record` |
| Parar gravação | `screen-toolbox --stop` |

Atalhos na captura: `V P H L A R E T N B X` (ferramentas), `[` `]` (espessura), `Shift`
(restringe ângulo/proporção), `Ctrl+Z`/`Ctrl+Shift+Z`, `Enter`/`Ctrl+C` (copiar), `Ctrl+S`, `Del`, `Esc`.

## Instalar / empacotar

```sh
sudo make install PREFIX=/usr/local   # instalação direta
make deb                              # gera build/screen-toolbox_0.1.0_all.deb
# Fedora: packaging/rpm/screen-toolbox.spec   Arch: packaging/arch/PKGBUILD
# Flatpak: flatpak-builder build packaging/flatpak/io.github.nicolas.ScreenToolbox.yml
```
