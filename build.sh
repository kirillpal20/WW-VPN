#!/usr/bin/env bash
# Запускается Render'ом на этапе сборки (Build Command).
# Ставит python-зависимости и скачивает бинарник xray-core под Linux amd64.
set -euo pipefail

echo "==> Устанавливаю Python-зависимости"
pip install --no-cache-dir -r requirements.txt

echo "==> Скачиваю xray-core"
XRAY_VERSION="v26.7.28"   # можно обновить на актуальную с https://github.com/XTLS/Xray-core/releases
XRAY_URL="https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}/Xray-linux-64.zip"

curl -L -o xray.zip "$XRAY_URL"
unzip -o xray.zip xray -d .
chmod +x xray
rm -f xray.zip

echo "==> Готово. Бинарник xray лежит в $(pwd)/xray"
