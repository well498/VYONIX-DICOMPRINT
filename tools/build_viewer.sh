#!/usr/bin/env bash
# Compila o VYONIX VIEWER: OHIF oficial (MIT) na etiqueta $OHIF_TAG, sem alterações no código, com a
# configuração viewer/vyonix.js. Saída em viewer/dist (sem mapas de código-fonte).
# Uso: OHIF_TAG=v3.13.13 tools/build_viewer.sh   (precisa de Node 24 e rede para o registro npm)
set -euo pipefail
: "${OHIF_TAG:?defina OHIF_TAG}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${RUNNER_TEMP:-/tmp}/ohif-$OHIF_TAG"
rm -rf "$WORK"
git clone -q --depth 1 --branch "$OHIF_TAG" https://github.com/OHIF/Viewers.git "$WORK"
cd "$WORK"
echo "::notice title=OHIF::$(git rev-parse HEAD) ($OHIF_TAG); licença: $(head -1 LICENSE)"
cp "$ROOT/viewer/vyonix.js" platform/app/public/config/vyonix.js
corepack enable
pnpm install --frozen-lockfile
cd platform/app
NODE_ENV=production APP_CONFIG=config/vyonix.js PUBLIC_URL=/viewer/ QUICK_BUILD=false \
  NODE_OPTIONS=--max-old-space-size=12288 npx cross-env rspack build --config .webpack/webpack.pwa.js
rm -rf "$ROOT/viewer/dist"
mkdir -p "$ROOT/viewer/dist"
cp -r dist/. "$ROOT/viewer/dist/"
find "$ROOT/viewer/dist" -name "*.map" -delete
cp "$WORK/LICENSE" "$ROOT/viewer/dist/LICENSE-OHIF.txt"
printf 'OHIF Viewer %s (MIT), commit %s, sem alterações; configuração VYONIX: viewer/vyonix.js\n' \
  "$OHIF_TAG" "$(git -C "$WORK" rev-parse HEAD)" > "$ROOT/viewer/dist/ORIGEM.txt"
echo "::notice title=Viewer::$(du -sh "$ROOT/viewer/dist" | cut -f1), $(find "$ROOT/viewer/dist" -type f | wc -l) arquivos (sem .map)"
