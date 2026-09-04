#!/bin/bash
# Run this once on the VPS to create the basic auth password file for dev.emotionflow.site
# Usage: sudo bash setup-htpasswd.sh <username> <password>

set -e

HTPASSWD_FILE="/etc/nginx/.htpasswd"
USERNAME="${1:-dev}"
PASSWORD="${2}"

if [[ -z "$PASSWORD" ]]; then
  echo "Usage: sudo bash setup-htpasswd.sh <username> <password>"
  exit 1
fi

if ! command -v htpasswd &>/dev/null; then
  echo "Installing apache2-utils for htpasswd..."
  apt-get install -y apache2-utils
fi

htpasswd -cb "$HTPASSWD_FILE" "$USERNAME" "$PASSWORD"
echo "Created $HTPASSWD_FILE for user '$USERNAME'"
echo "Reload nginx: docker compose -f docker-compose.prod.yml exec nginx nginx -s reload"
