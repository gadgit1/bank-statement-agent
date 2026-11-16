#!/usr/bin/env bash
# Download the Russian trusted root CA using the official provider URL.
set -euo pipefail
mkdir -p certs
curl -fSL --connect-timeout 15 \
  'https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt' \
  -o certs/russian_trusted_root_ca_pem.crt
openssl x509 -in certs/russian_trusted_root_ca_pem.crt -noout -subject -issuer
printf '\nCA certificate downloaded. Check the official issuer before use.\n'
