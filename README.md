# Screen Toolbox

Prints com anotações e gravação de tela mostrando teclas e cliques — tudo em um app só.
Feito com Python + GTK4/libadwaita + GStreamer + xdg-desktop-portal, então funciona em
Wayland e X11 (GNOME, KDE, Hyprland, Sway…) no Debian/Ubuntu, Fedora e Arch, e também no
Windows 10/11.

## Recursos

- **Print com edição no lugar** (estilo Flameshot): arraste para selecionar a área e edite
  direto sobre a tela — caneta, marca-texto, linha, seta, retângulo, elipse, texto, marcador
  numerado, desfocar e pixelar. A seleção continua ajustável pelas alças e pode ser movida
  (ferramenta Mover, `V`) sem perder as anotações. `Enter`/`Ctrl+C` copia e fecha, `Ctrl+S`
  salva, `Esc` cancela.
- **Nome automático** (ligado por padrão): salva direto, sem perguntar, com um padrão personalizável
  em Preferências. De fábrica: `Print-{contador}-{data}-{h}:{min}` e
  `Recording-{contador}-{data}-{h}:{min}`. Campos: `{data}`, `{hora}`, `{ano}`, `{mes}`, `{dia}`,
  `{h}`, `{min}`, `{seg}`, `{contador}` e, nos vídeos, `{duracao}`. No Windows o `:` vira `-`.
- **Nome manual**: com o nome automático desligado, todo print e todo vídeo pede um nome antes de
  salvar (cancelar o nome de um vídeo pergunta se quer descartá-lo).
- **Preferências com busca** (`Ctrl+,`): opções em abas por tarefa (Prints, Gravação, Teclas e
  cliques, Aplicativo) e um campo de busca que ignora acentos e entende sinônimos ("fps", "bandeja").
- **Ícone na barra superior**: Capturar área, Gravar/Parar (com o tempo), Abrir janela,
  Preferências e Sair. KDE suporta nativamente; no GNOME requer a extensão AppIndicator
  (já ativa no Ubuntu; em Fedora/Arch instale `gnome-shell-extension-appindicator`).
- **Segundo plano**: fechar a janela não encerra o app (atalhos respondem na hora); para
  encerrar use **Sair** no menu (`Ctrl+Q`). Dá para desligar em Preferências → Aplicativo.
- **Gravação** (sempre da tela inteira): MP4 (H.264/AAC) ou WebM (VP9/Opus), microfone e áudio do sistema
  (ambos desligados por padrão), teclas e cliques desenhados no vídeo.
  30, 60, 90 ou 120 quadros por segundo, sem nunca passar da taxa de atualização da tela gravada.

## Windows

Baixe o `ScreenToolbox-<versão>-setup.exe` na página de
[Releases](https://github.com/nicolas-tavaress/screen-toolbox/releases) e instale (não pede
administrador). O instalador ainda não é assinado: se o SmartScreen avisar, clique em
**Mais informações → Executar assim mesmo**.

- **Atalhos globais**: `Ctrl+Alt+S` captura uma área e `Ctrl+Alt+R` inicia/para a gravação,
  em qualquer programa, enquanto o app estiver aberto (inclusive só na bandeja).
- **Bandeja**: o ícone fica sempre ativo; clique para abrir a janela e use o botão direito
  para o menu. As notificações aparecem como balões do ícone.
- **Gravação**: escolha o monitor em Preferências → Gravação → Tela a gravar. Teclas e cliques
  aparecem no vídeo sem nenhuma configuração extra.
- **Iniciar com o Windows**: opção no instalador (abre direto na bandeja).
- Logs em `%LOCALAPPDATA%\screen-toolbox\screen-toolbox.log`.

### Gerar o instalador

O workflow `.github/workflows/windows-release.yml` gera o instalador no GitHub Actions
(manual ou a cada tag `v*`, que também publica a release). Para gerar localmente, no shell
**UCRT64** do [MSYS2](https://www.msys2.org/):

```sh
bash packaging/windows/build.sh --install   # instala as dependências e gera build/windows/dist/
build/windows/dist/screen-toolbox/screen-toolbox.exe --self-test teste.txt   # confere o pacote
iscc /DAppVersion=0.1.0 packaging/windows/screen-toolbox.iss                  # gera o setup.exe
```

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
a gravação**. Seu usuário precisa estar no grupo `input`. O botão **Permitir** em
Menu → Permissões (`Ctrl+H`) faz isso (pede a senha); ou, pelo terminal:

```sh
sudo usermod -aG input $USER   # depois saia e entre na sessão
```

### Permissões

Na primeira execução o app abre a **configuração inicial**, e a mesma tela fica em
Menu → Permissões (`Ctrl+H`) para conferir a situação depois:

- **Captura de tela**: o sistema pergunta uma vez se o app pode tirar prints. Essa permissão não
  aparece nas Configurações do GNOME (lá só entram apps Flatpak); se você negou, use
  **Pedir de novo** nessa tela.
- **Teclas e cliques no vídeo** (opcional): grupo `input`, como acima.
- **Gravação de tela**: o sistema pergunta qual tela gravar a cada gravação, ou lembra a escolha.

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

Para instalar o `.deb` **com as dependências**, use o `apt` (o `./` é obrigatório):

```sh
sudo apt install ./build/screen-toolbox_0.1.0_all.deb
```

O `dpkg -i` não baixa dependências: se usou ele, complete com `sudo apt -f install`.
