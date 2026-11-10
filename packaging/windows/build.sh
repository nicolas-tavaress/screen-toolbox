#!/usr/bin/env bash
# Gera o Screen Toolbox para Windows em build/windows/dist/screen-toolbox/.
# Rodar no shell UCRT64 do MSYS2 (localmente ou no GitHub Actions).
#
#   packaging/windows/build.sh            # usa os pacotes já instalados
#   packaging/windows/build.sh --install  # instala as dependências com o pacman antes
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/build/windows"
APP_ID="io.github.nicolas.ScreenToolbox"

PACKAGES=(
    python python-gobject python-cairo gtk4 libadwaita adwaita-icon-theme librsvg
    gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-libav
    pyinstaller imagemagick
)

if [[ "${1:-}" == "--install" ]]; then
    pacman -S --needed --noconfirm "${PACKAGES[@]/#/${MINGW_PACKAGE_PREFIX:-mingw-w64-ucrt-x86_64}-}"
fi

if [[ "${MSYSTEM:-}" != "UCRT64" ]]; then
    echo "Rode no shell UCRT64 do MSYS2 (MSYSTEM=${MSYSTEM:-indefinido})." >&2
    exit 1
fi

VERSION="$(cd "$ROOT" && python -c 'import screen_toolbox; print(screen_toolbox.VERSION)')"
echo "==> Screen Toolbox $VERSION"

echo "==> Ícones (.ico)"
mkdir -p "$OUT/icons" "$OUT/png"
for name in "$APP_ID" "$APP_ID-tray" "$APP_ID-tray-recording"; do
    pngs=()
    for size in 16 20 24 32 40 48 64 256; do
        png="$OUT/png/$name-$size.png"
        rsvg-convert -w "$size" -h "$size" -o "$png" "$ROOT/data/$name.svg"
        pngs+=("$png")
    done
    magick "${pngs[@]}" "$OUT/icons/$name.ico"
done

echo "==> PyInstaller"
cd "$ROOT"
python -m PyInstaller --noconfirm --clean \
    --distpath "$OUT/dist" --workpath "$OUT/work" \
    packaging/windows/screen-toolbox.spec

echo "$VERSION" > "$OUT/VERSION"
echo "==> Pronto: $OUT/dist/screen-toolbox/screen-toolbox.exe"
