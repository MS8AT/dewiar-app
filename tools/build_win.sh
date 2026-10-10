#!/bin/bash
# Сборка установщика Windows:
#   tools/build_win.sh            → dist/Dewiar-Setup-X.Y.Z.exe          полный (~150 МБ), при установке ничего не качает
#   tools/build_win.sh --online   → dist/Dewiar-Setup-X.Y.Z-online.exe   компактный (<30 МБ): Python и программа внутри,
#                                   библиотеки (~100 МБ) скачиваются с PyPI при установке по requirements-win.lock
# Нужно: makensis (apt install nsis), uv, ImageMagick не обязателен (иконка лежит готовой).
# Python для Windows — python-build-standalone (скачивается один раз в кэш), библиотеки — колёса win_amd64.
set -euo pipefail
ONLINE=0; [ "${1:-}" = "--online" ] && ONLINE=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$ROOT/core/version.py")
CACHE=${DEWIAR_WIN_CACHE:-$HOME/wincache}
PYREL=${DEWIAR_WIN_PYREL:-20260929}
PYVER=${DEWIAR_WIN_PYVER:-3.12.14}
TAR="cpython-${PYVER}+${PYREL}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
UV=$(command -v uv || echo /opt/dewiar/bin/uv)
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$CACHE" "$ROOT/dist"

if [ ! -f "$CACHE/$TAR" ]; then
  echo "Скачиваю Python для Windows…"
  curl -fL -o "$CACHE/$TAR.part" "https://github.com/astral-sh/python-build-standalone/releases/download/$PYREL/$TAR"
  mv "$CACHE/$TAR.part" "$CACHE/$TAR"
fi
VOSK="$ROOT/data/vosk-model-small-ru-0.22.zip"             # модель имён — внутрь установщика (архив исходников её не везёт)
VOSK_SHA=961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4
if [ "$ONLINE" = 0 ] && [ ! -f "$VOSK" ]; then
  if [ ! -f "$CACHE/${VOSK##*/}" ]; then
    echo "Скачиваю модель имён Vosk (45 МБ)…"
    curl -fL -o "$CACHE/${VOSK##*/}.part" "https://alphacephei.com/vosk/models/${VOSK##*/}"
    echo "$VOSK_SHA  $CACHE/${VOSK##*/}.part" | sha256sum -c --quiet
    mv "$CACHE/${VOSK##*/}.part" "$CACHE/${VOSK##*/}"
  fi
  cp "$CACHE/${VOSK##*/}" "$VOSK"
fi
tar -xzf "$CACHE/$TAR" -C "$STAGE"                         # → $STAGE/python
# msvcp140*.dll для onnxruntime — рядом с python.exe: на Windows 10 без Visual C++ Redistributable их нет
cp "$ROOT/packaging/windows/vcruntime/"*.dll "$STAGE/python/"
if [ "$ONLINE" = 0 ]; then
  echo "Библиотеки (колёса win_amd64)…"
  "$UV" pip install -q --target "$STAGE/python/Lib/site-packages" --python-platform x86_64-pc-windows-msvc \
        --python-version "${PYVER%.*}" -r "$ROOT/requirements-win.lock"
fi

mkdir -p "$STAGE/app"
cp -r "$ROOT/core" "$ROOT/ui" "$ROOT/data" "$ROOT/icons" "$STAGE/app/"
find "$STAGE" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -rf "$STAGE/python/Lib/test" "$STAGE/python/Lib/idlelib" "$STAGE/python/Lib/tkinter" "$STAGE/python/tcl" 2>/dev/null || true
cp "$ROOT/packaging/windows/dewiar.ico" "$ROOT/packaging/windows/welcome.bmp" "$ROOT/packaging/windows/header.bmp" "$STAGE/"
cp "$ROOT/requirements-win.lock" "$STAGE/app/"

if [ "$ONLINE" = 1 ]; then
  rm -f "$STAGE/app/data/"*.zip                            # модель имён программа скачает сама при первом запуске
  # на PyPI у двух крошечных библиотек нет готовых колёс (только исходники) — везём колёса с собой,
  # чтобы установка ничего не собирала (packaging/windows/wheels, сделаны `uv build --wheel`)
  cp -r "$ROOT/packaging/windows/wheels" "$STAGE/app/wheels"
  OUT="$ROOT/dist/Dewiar-Setup-$VERSION-online.exe"
  makensis -V2 -DVERSION="$VERSION" -DSTAGE="$STAGE" -DOUT="$OUT" -DONLINE=1 "$ROOT/packaging/windows/dewiar.nsi"
else
  OUT="$ROOT/dist/Dewiar-Setup-$VERSION.exe"
  makensis -V2 -DVERSION="$VERSION" -DSTAGE="$STAGE" -DOUT="$OUT" "$ROOT/packaging/windows/dewiar.nsi"
fi
ls -la "$OUT"
