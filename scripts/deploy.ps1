param(
    [string]$TargetHost = "",
    [string]$User = "root",
    [string]$RemoteDir = "/opt/lucky-ticket",
    [int]$Port = 22,
    [string]$SshKey = "",
    [string]$NginxServerName = "",
    [string]$PublicWebUrl = "",
    [string]$DeployFile = "deploy.txt"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$deployPath = Join-Path $root $DeployFile
$tar = (Get-Command tar -ErrorAction SilentlyContinue).Source
if (-not $tar -and (Test-Path "C:\Windows\System32\tar.exe")) {
    $tar = "C:\Windows\System32\tar.exe"
}
if (-not $tar) {
    throw "tar is required and was not found."
}

if (Test-Path $deployPath) {
    Get-Content $deployPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $key, $value = $line.Split("=", 2)
        $key = $key.Trim().ToUpperInvariant()
        $value = $value.Trim()
        switch ($key) {
            "HOST" { $TargetHost = $value }
            "USER" { $User = $value }
            "REMOTE_DIR" { $RemoteDir = $value }
            "PORT" { $Port = [int]$value }
            "SSH_KEY" { $SshKey = $value }
            "NGINX_SERVER_NAME" { $NginxServerName = $value }
            "PUBLIC_WEB_URL" { $PublicWebUrl = $value.TrimEnd("/") }
            "TG_BOT_TOKEN" {
                if (-not $env:TG_BOT_TOKEN) {
                    $env:TG_BOT_TOKEN = $value
                }
            }
            "VK_BOT_TOKEN" {
                if (-not $env:VK_BOT_TOKEN) {
                    $env:VK_BOT_TOKEN = $value
                }
            }
            "VK_GROUP_ID" {
                if (-not $env:VK_GROUP_ID) {
                    $env:VK_GROUP_ID = $value
                }
            }
            "TICKET_CHECK_INTERVAL_SECONDS" {
                if (-not $env:TICKET_CHECK_INTERVAL_SECONDS) {
                    $env:TICKET_CHECK_INTERVAL_SECONDS = $value
                }
            }
            default {
                if ($key.StartsWith("TICKET_MAIL_") -and -not [Environment]::GetEnvironmentVariable($key)) {
                    [Environment]::SetEnvironmentVariable($key, $value, "Process")
                }
            }
        }
    }
}
$ssh = (Get-Command ssh -ErrorAction SilentlyContinue).Source
$scp = (Get-Command scp -ErrorAction SilentlyContinue).Source
if (-not $ssh -and (Test-Path "C:\Windows\System32\OpenSSH\ssh.exe")) {
    $ssh = "C:\Windows\System32\OpenSSH\ssh.exe"
}
if (-not $scp -and (Test-Path "C:\Windows\System32\OpenSSH\scp.exe")) {
    $scp = "C:\Windows\System32\OpenSSH\scp.exe"
}
if (-not $ssh -or -not $scp) {
    throw "OpenSSH client is required: ssh and scp were not found."
}

$localEnv = Join-Path $root ".env"
if (((-not $env:TG_BOT_TOKEN) -or (-not $env:VK_BOT_TOKEN) -or (-not $env:VK_GROUP_ID) -or (-not $env:TICKET_CHECK_INTERVAL_SECONDS)) -and (Test-Path $localEnv)) {
    Get-Content $localEnv | ForEach-Object {
        $line = $_.Trim()
        if ($line -and (-not $line.StartsWith("#")) -and $line.Contains("=")) {
            $key, $value = $line.Split("=", 2)
            switch ($key.Trim()) {
                "TG_BOT_TOKEN" {
                    if (-not $env:TG_BOT_TOKEN) {
                        $env:TG_BOT_TOKEN = $value.Trim()
                    }
                }
                "VK_BOT_TOKEN" {
                    if (-not $env:VK_BOT_TOKEN) {
                        $env:VK_BOT_TOKEN = $value.Trim()
                    }
                }
                "VK_GROUP_ID" {
                    if (-not $env:VK_GROUP_ID) {
                        $env:VK_GROUP_ID = $value.Trim()
                    }
                }
                "TICKET_CHECK_INTERVAL_SECONDS" {
                    if (-not $env:TICKET_CHECK_INTERVAL_SECONDS) {
                        $env:TICKET_CHECK_INTERVAL_SECONDS = $value.Trim()
                    }
                }
                default {
                    $normalizedKey = $key.Trim().ToUpperInvariant()
                    if ($normalizedKey.StartsWith("TICKET_MAIL_") -and -not [Environment]::GetEnvironmentVariable($normalizedKey)) {
                        [Environment]::SetEnvironmentVariable($normalizedKey, $value.Trim(), "Process")
                    }
                }
            }
        }
    }
}

if (-not $env:TG_BOT_TOKEN) {
    throw "Set TG_BOT_TOKEN in the current shell before deploy."
}
if (-not $TargetHost) {
    throw "Set HOST in deploy.txt or pass -TargetHost."
}
if (-not $NginxServerName) {
    $NginxServerName = $TargetHost
}
if (-not $PublicWebUrl) {
    $PublicWebUrl = "http://$NginxServerName"
}
if (-not $env:TICKET_CHECK_INTERVAL_SECONDS) {
    $env:TICKET_CHECK_INTERVAL_SECONDS = "900"
}
$TlsServerName = ($NginxServerName -split "\s+")[0]
if (-not $env:TICKET_MAIL_ENABLED) {
    $env:TICKET_MAIL_ENABLED = "false"
}
if (-not $env:TICKET_MAIL_IMAP_PORT) {
    $env:TICKET_MAIL_IMAP_PORT = "993"
}
if (-not $env:TICKET_MAIL_IMAP_FOLDER) {
    $env:TICKET_MAIL_IMAP_FOLDER = "INBOX"
}
if (-not $env:TICKET_MAIL_POLL_INTERVAL_SECONDS) {
    $env:TICKET_MAIL_POLL_INTERVAL_SECONDS = "300"
}
if (-not $env:TICKET_MAIL_AUTO_CONFIRM_ENABLED) {
    $env:TICKET_MAIL_AUTO_CONFIRM_ENABLED = "true"
}
if (-not $env:TICKET_MAIL_MARK_SEEN) {
    $env:TICKET_MAIL_MARK_SEEN = "true"
}
if (-not $env:TICKET_MAIL_PUBLIC_ADDRESS_TEMPLATE) {
    $env:TICKET_MAIL_PUBLIC_ADDRESS_TEMPLATE = "tickets+{code}@$TlsServerName"
}

$sshArgs = @("-p", "$Port", "-o", "StrictHostKeyChecking=accept-new")
$scpArgs = @("-P", "$Port", "-o", "StrictHostKeyChecking=accept-new")
if ($SshKey) {
    $resolvedKey = Resolve-Path $SshKey
    $sshArgs += @("-i", $resolvedKey.Path)
    $scpArgs += @("-i", $resolvedKey.Path)
}

$archive = Join-Path $env:TEMP "lucky-ticket-deploy.tar.gz"
if (Test-Path $archive) {
    Remove-Item -LiteralPath $archive -Force
}

& $tar `
    --exclude ".git" `
    --exclude ".env" `
    --exclude "deploy.txt" `
    --exclude ".venv" `
    --exclude "node_modules" `
    --exclude "dist" `
    --exclude "lucky_ticket.db" `
    --exclude "*.db" `
    --exclude "ticket_example" `
    --exclude "tickets_example" `
    --exclude "docs/ticket-batch-9-28-results.json" `
    --exclude "__pycache__" `
    --exclude ".pytest_cache" `
    -czf $archive -C $root .
if ($LASTEXITCODE -ne 0) {
    throw "tar failed with exit code $LASTEXITCODE"
}

& $ssh @sshArgs "$User@$TargetHost" "install -d -m 0755 '$RemoteDir/releases' '$RemoteDir/shared'"
if ($LASTEXITCODE -ne 0) {
    throw "ssh prepare failed with exit code $LASTEXITCODE"
}
& $scp @scpArgs $archive "$User@$TargetHost`:$RemoteDir/app.tar.gz"
if ($LASTEXITCODE -ne 0) {
    throw "scp failed with exit code $LASTEXITCODE"
}

$releaseName = (Get-Date -Format "yyyyMMddHHmmss")
$remoteScript = @"
set -euo pipefail

APP_DIR="$RemoteDir"
RELEASE_DIR="`$APP_DIR/releases/$releaseName"
SHARED_DIR="`$APP_DIR/shared"
NGINX_SERVER_NAME="$NginxServerName"
TLS_SERVER_NAME="$TlsServerName"
install -d -m 0755 "`$RELEASE_DIR" "`$SHARED_DIR"
tar -xzf "`$APP_DIR/app.tar.gz" -C "`$RELEASE_DIR"

if [ -d "`$APP_DIR/current" ] && [ ! -L "`$APP_DIR/current" ]; then
  if [ -f "`$APP_DIR/current/lucky_ticket.db" ] && [ ! -f "`$SHARED_DIR/lucky_ticket.db" ]; then
    cp "`$APP_DIR/current/lucky_ticket.db" "`$SHARED_DIR/lucky_ticket.db"
  fi
  mv "`$APP_DIR/current" "`$APP_DIR/legacy-current-$releaseName"
fi

if [ -f "`$SHARED_DIR/.env" ] && grep -q '^INTERNAL_API_TOKEN=' "`$SHARED_DIR/.env"; then
  INTERNAL_API_TOKEN_VALUE="`$(grep '^INTERNAL_API_TOKEN=' "`$SHARED_DIR/.env" | tail -n 1 | cut -d= -f2-)"
else
  INTERNAL_API_TOKEN_VALUE="`$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
fi

cat > "`$SHARED_DIR/.env" <<'EOF'
APP_VERSION=0.1.0
DATABASE_URL=sqlite:////data/lucky_ticket.db
EKARTA_FISCAL_BASE_URL=https://f.ekarta-ek.ru/fiscal/
TICKET_CHECK_INTERVAL_SECONDS=$env:TICKET_CHECK_INTERVAL_SECONDS
BACKEND_URL=http://127.0.0.1:8000
PUBLIC_WEB_URL=$PublicWebUrl
TG_BOT_TOKEN=$env:TG_BOT_TOKEN
VK_BOT_TOKEN=$env:VK_BOT_TOKEN
VK_GROUP_ID=$env:VK_GROUP_ID
MESSENGER_NOTIFICATIONS_ENABLED=true
INTERNAL_API_TOKEN=__INTERNAL_API_TOKEN__
DAILY_SUMMARY_TIME=23:00
DAILY_SUMMARY_TZ=Asia/Yekaterinburg
TICKET_MAIL_ENABLED=$env:TICKET_MAIL_ENABLED
TICKET_MAIL_IMAP_HOST=$env:TICKET_MAIL_IMAP_HOST
TICKET_MAIL_IMAP_PORT=$env:TICKET_MAIL_IMAP_PORT
TICKET_MAIL_IMAP_USERNAME=$env:TICKET_MAIL_IMAP_USERNAME
TICKET_MAIL_IMAP_PASSWORD=$env:TICKET_MAIL_IMAP_PASSWORD
TICKET_MAIL_IMAP_FOLDER=$env:TICKET_MAIL_IMAP_FOLDER
TICKET_MAIL_POLL_INTERVAL_SECONDS=$env:TICKET_MAIL_POLL_INTERVAL_SECONDS
TICKET_MAIL_AUTO_CONFIRM_ENABLED=$env:TICKET_MAIL_AUTO_CONFIRM_ENABLED
TICKET_MAIL_MARK_SEEN=$env:TICKET_MAIL_MARK_SEEN
TICKET_MAIL_TARGET_USER_ID=$env:TICKET_MAIL_TARGET_USER_ID
TICKET_MAIL_TARGET_USER_TOKEN=$env:TICKET_MAIL_TARGET_USER_TOKEN
TICKET_MAIL_PUBLIC_ADDRESS_TEMPLATE=$env:TICKET_MAIL_PUBLIC_ADDRESS_TEMPLATE
EOF
sed -i "s|__INTERNAL_API_TOKEN__|`$INTERNAL_API_TOKEN_VALUE|" "`$SHARED_DIR/.env"
chmod 0600 "`$SHARED_DIR/.env"

cd "`$RELEASE_DIR"
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required on this server for счастливый билетик deploy." >&2
  exit 1
fi

docker build -t "lucky-ticket:$releaseName" .
docker run --rm --env-file "`$SHARED_DIR/.env" -e INTERNAL_API_TOKEN= -e MESSENGER_NOTIFICATIONS_ENABLED=false -v "`$SHARED_DIR:/data" "lucky-ticket:$releaseName" python -m pytest backend/tests -q

ln -sfn "`$RELEASE_DIR" "`$APP_DIR/current"

systemctl stop lucky-ticket-backend.service lucky-ticket-bot.service lucky-ticket-vk-bot.service 2>/dev/null || true
docker rm -f lucky-ticket-backend lucky-ticket-bot lucky-ticket-vk-bot 2>/dev/null || true
docker network create lucky-ticket-net 2>/dev/null || true

docker run -d \
  --name lucky-ticket-backend \
  --restart unless-stopped \
  --network lucky-ticket-net \
  --env-file "`$SHARED_DIR/.env" \
  -v "`$SHARED_DIR:/data" \
  -p 127.0.0.1:8000:8000 \
  "lucky-ticket:$releaseName" \
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

sleep 3
curl -fsS http://127.0.0.1:8000/api/health

docker run -d \
  --name lucky-ticket-bot \
  --restart unless-stopped \
  --env-file "`$SHARED_DIR/.env" \
  --network host \
  -v "`$SHARED_DIR:/data" \
  "lucky-ticket:$releaseName" \
  python apps/tg-bot/bot.py

if grep -Eq '^VK_BOT_TOKEN=.+$' "`$SHARED_DIR/.env"; then
  docker run -d \
    --name lucky-ticket-vk-bot \
    --restart unless-stopped \
    --env-file "`$SHARED_DIR/.env" \
    --network host \
    -v "`$SHARED_DIR:/data" \
    "lucky-ticket:$releaseName" \
    python apps/vk-bot/bot.py
fi

if command -v nginx >/dev/null 2>&1; then
  install -d -m 0755 /var/www/certbot
  if [ -f "/etc/letsencrypt/live/`$TLS_SERVER_NAME/fullchain.pem" ] && [ -f "/etc/letsencrypt/live/`$TLS_SERVER_NAME/privkey.pem" ]; then
    cat > /etc/nginx/sites-available/lucky-ticket.conf <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name `$NGINX_SERVER_NAME;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://`$TLS_SERVER_NAME\`$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name `$TLS_SERVER_NAME;

    ssl_certificate /etc/letsencrypt/live/`$TLS_SERVER_NAME/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/`$TLS_SERVER_NAME/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;

    access_log /var/log/nginx/lucky-ticket.access.log;
    error_log /var/log/nginx/lucky-ticket.error.log;

    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \`$host;
        proxy_set_header X-Real-IP \`$remote_addr;
        proxy_set_header X-Forwarded-For \`$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \`$scheme;
        proxy_set_header Upgrade \`$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
EOF
  else
  cat > /etc/nginx/sites-available/lucky-ticket.conf <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name `$NGINX_SERVER_NAME;

    access_log /var/log/nginx/lucky-ticket.access.log;
    error_log /var/log/nginx/lucky-ticket.error.log;

    client_max_body_size 10m;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \`$host;
        proxy_set_header X-Real-IP \`$remote_addr;
        proxy_set_header X-Forwarded-For \`$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \`$scheme;
        proxy_set_header Upgrade \`$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
EOF
  fi
  ln -sfn /etc/nginx/sites-available/lucky-ticket.conf /etc/nginx/sites-enabled/lucky-ticket.conf
  nginx -t
  systemctl reload nginx
fi

docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
  | awk -v keep="lucky-ticket:$releaseName" '`$1 ~ /^lucky-ticket:/ && `$1 != keep { print `$2 }' \
  | sort -u \
  | xargs -r docker rmi 2>/dev/null || true

APP_RELEASES="`$APP_DIR/releases" python3 -c 'import os, shutil; from pathlib import Path; releases_dir = Path(os.environ["APP_RELEASES"]); releases = sorted(path for path in releases_dir.iterdir() if path.is_dir()); [shutil.rmtree(path, ignore_errors=True) for path in releases[:-5]]'
"@

$remoteScript = $remoteScript.Replace("`r", "")
$remoteScript | & $ssh @sshArgs "$User@$TargetHost" "bash -s"
if ($LASTEXITCODE -ne 0) {
    throw "remote deploy failed with exit code $LASTEXITCODE"
}
Write-Host "Deployed to $TargetHost as $User. Managed Docker containers: lucky-ticket-backend, lucky-ticket-bot, lucky-ticket-vk-bot."
