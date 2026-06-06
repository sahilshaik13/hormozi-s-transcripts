#!/bin/sh
# Install vault + index into /app during Docker build.
# Source (first match wins):
#   1) hormozi-brain/ + hormozi-index/ in build context (git push)
#   2) render-data.zip in build context
#   3) BUILD_DATA_URL env (curl download at build time — set in Render Docker build args)

set -e
CTX="${1:-/buildctx}"
DEST="${2:-/app}"

install_dirs() {
  src_brain="$1"
  src_index="$2"
  echo "Installing vault from $src_brain"
  echo "Installing index from $src_index"
  cp -r "$src_brain" "$DEST/hormozi-brain"
  cp -r "$src_index" "$DEST/hormozi-index"
}

if [ -d "$CTX/hormozi-brain" ] && [ -d "$CTX/hormozi-index" ]; then
  install_dirs "$CTX/hormozi-brain" "$CTX/hormozi-index"
  exit 0
fi

if [ -f "$CTX/render-data.zip" ]; then
  echo "Extracting render-data.zip..."
  unzip -q "$CTX/render-data.zip" -d "$DEST"
  if [ -d "$DEST/hormozi-brain" ] && [ -d "$DEST/hormozi-index" ]; then
    exit 0
  fi
  echo "ERROR: render-data.zip must contain hormozi-brain/ and hormozi-index/ at zip root"
  exit 1
fi

if [ -n "$BUILD_DATA_URL" ]; then
  echo "Downloading data bundle from BUILD_DATA_URL..."
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends curl unzip ca-certificates
  curl -fsSL "$BUILD_DATA_URL" -o /tmp/render-data.zip
  unzip -q /tmp/render-data.zip -d "$DEST"
  rm -f /tmp/render-data.zip
  if [ -d "$DEST/hormozi-brain" ] && [ -d "$DEST/hormozi-index" ]; then
    exit 0
  fi
  echo "ERROR: downloaded zip must contain hormozi-brain/ and hormozi-index/"
  exit 1
fi

echo ""
echo "ERROR: No vault/index data for Docker build."
echo ""
echo "Pick one:"
echo "  A) Git (private repo):  scripts\\stage_for_render.bat  then commit + push"
echo "  B) Zip in repo:         scripts\\pack_render_data.bat  then git add render-data.zip + push"
echo "  C) URL at build time:   set Docker build arg BUILD_DATA_URL to a public zip URL"
echo ""
exit 1
