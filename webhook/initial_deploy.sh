#!/bin/bash
# initial_deploy.sh — One-time server setup for ramboq prod and/or dev environment
#
# Usage:
#   sudo bash /opt/ramboq/webhook/initial_deploy.sh [OPTIONS]
#
# Options:
#   --env           prod | dev | both    Which environment(s) to set up (default: both)
#   --ssh-key-prod  /path/to/key        SSH private key for prod git (optional — skips SSH if omitted)
#   --ssh-key-dev   /path/to/key        SSH private key for dev git (optional — skips SSH if omitted)
#   --branch-dev    <branch>            Dev branch to checkout (default: dev)
#
# What this script sets up:
#   - System packages (nginx, python3, webhook)
#   - SSH keys and config for git (if provided)
#   - Git clone and branch checkout for each environment
#   - Python venv and requirements install
#   - Log directories with correct ownership
#   - ramboq_deploy.yaml templates (fill in secrets.yaml manually after)
#   - systemd service files installed and started
#   - nginx site configs copied, default site removed
#   - sudoers entry for www-data
#
# Manual steps after this script:
#   1. Fill in secrets.yaml with real credentials
#   2. Set Cloudflare DNS records to grey cloud for webhook and dev subdomains
#   3. Run certbot for SSL certs
#   4. Add GitHub webhook pointing to https://webhook.ramboq.com/hooks/update

set -euo pipefail

# --- Defaults ---
ENV="both"
SSH_KEY_PROD=""
SSH_KEY_DEV=""
BRANCH_PROD="main"
BRANCH_DEV="dev"
REPO_HTTPS="https://github.com/RamanaAmbore/ramboq.git"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)          ENV="$2";          shift 2 ;;
        --ssh-key-prod) SSH_KEY_PROD="$2"; shift 2 ;;
        --ssh-key-dev)  SSH_KEY_DEV="$2";  shift 2 ;;
        --branch-dev)   BRANCH_DEV="$2";   shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Helpers ---
log_step() { echo ""; echo -e "${BOLD}${GREEN}=== $1 ===${NC}"; }
log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
log_err()  { echo -e "  ${RED}✗${NC} $1"; }

# --- Must run as root ---
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Run as root: sudo bash initial_deploy.sh${NC}"
    exit 1
fi

# --- Validate ENV ---
if [[ "$ENV" != "prod" && "$ENV" != "dev" && "$ENV" != "both" ]]; then
    echo "Invalid --env value: $ENV (must be prod, dev, or both)"
    exit 1
fi

echo ""
echo -e "${BOLD}RamboQuant Initial Deployment Setup${NC}"
echo -e "  Environment : $ENV"
echo -e "  Dev branch  : $BRANCH_DEV"
echo -e "  SSH prod key: ${SSH_KEY_PROD:-none (will use HTTPS)}"
echo -e "  SSH dev key : ${SSH_KEY_DEV:-none (will use HTTPS)}"

# ============================================================
# STEP 1: System prerequisites
# ============================================================
log_step "1. System Prerequisites"

apt-get update -qq

for pkg in nginx python3 python3-venv python3-pip git certbot python3-certbot-nginx; do
    if dpkg -l "$pkg" &>/dev/null; then
        log_ok "$pkg already installed"
    else
        apt-get install -y "$pkg" > /dev/null
        log_ok "Installed $pkg"
    fi
done

# webhook binary
if ! command -v webhook &>/dev/null; then
    apt-get install -y webhook > /dev/null
    log_ok "Installed webhook"
else
    log_ok "webhook already installed ($(webhook --version 2>&1 | head -1))"
fi

# ============================================================
# STEP 2: SSH setup (optional)
# ============================================================
setup_ssh() {
    local key_src="$1"
    local key_label="$2"   # prod or dev
    local ssh_dir="/var/www/.ssh"

    log_step "2. SSH Setup ($key_label)"

    if [ ! -f "$key_src" ]; then
        log_err "SSH key not found: $key_src"
        exit 1
    fi

    mkdir -p "$ssh_dir"
    chmod 700 "$ssh_dir"

    local key_dest="$ssh_dir/id_github_${key_label}"
    cp "$key_src" "$key_dest"
    chmod 600 "$key_dest"
    log_ok "Copied SSH key to $key_dest"

    # Add SSH config entry
    local config_file="$ssh_dir/config"
    local host_alias="github-${key_label}"
    if ! grep -q "Host $host_alias" "$config_file" 2>/dev/null; then
        cat >> "$config_file" << EOF

Host $host_alias
    HostName github.com
    User git
    IdentityFile $key_dest
    StrictHostKeyChecking no
EOF
        chmod 600 "$config_file"
        log_ok "Added SSH config entry for $host_alias"
    else
        log_ok "SSH config entry for $host_alias already exists"
    fi

    chown -R www-data:www-data "$ssh_dir"

    # Test connection
    if sudo -u www-data ssh -o BatchMode=yes -i "$key_dest" -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
        log_ok "SSH connection to GitHub verified"
    else
        log_warn "SSH connection test inconclusive — verify manually: ssh -T git@github.com -i $key_dest"
    fi

    # Return the clone URL to use
    echo "git@${host_alias}:RamanaAmbore/ramboq.git"
}

SSH_CLONE_PROD=""
SSH_CLONE_DEV=""

if [ -n "$SSH_KEY_PROD" ]; then
    SSH_CLONE_PROD=$(setup_ssh "$SSH_KEY_PROD" "prod")
fi
if [ -n "$SSH_KEY_DEV" ]; then
    SSH_CLONE_DEV=$(setup_ssh "$SSH_KEY_DEV" "dev")
fi

# ============================================================
# STEP 3: Clone and configure each environment
# ============================================================
setup_environment() {
    local app_root="$1"
    local branch="$2"
    local ssh_clone_url="$3"  # empty = use HTTPS

    local clone_url="${ssh_clone_url:-$REPO_HTTPS}"
    local capabilities="True"
    local notify_on_deploy="False"
    if [ "$branch" != "main" ]; then
        notify_on_deploy="True"
    fi

    log_step "3. Setting up $app_root (branch: $branch)"

    # Create directory
    mkdir -p "$app_root"
    chown www-data:www-data "$app_root"

    # Clone repo
    if [ ! -d "$app_root/.git" ]; then
        sudo -u www-data git clone "$clone_url" "$app_root"
        log_ok "Cloned repo to $app_root"
    else
        log_ok "$app_root already exists — skipping clone"
    fi

    # Configure safe.directory and checkout branch
    sudo -u www-data git -C "$app_root" config --add safe.directory "$app_root"
    sudo -u www-data git -C "$app_root" fetch origin "$branch"
    sudo -u www-data git -C "$app_root" checkout -B "$branch" "origin/$branch"
    log_ok "Checked out branch: $branch"

    # Python venv
    if [ ! -f "$app_root/venv/bin/activate" ]; then
        sudo -u www-data python3 -m venv "$app_root/venv"
        log_ok "Created Python virtualenv"
    else
        log_ok "Virtualenv already exists"
    fi

    # Install requirements
    log_ok "Installing Python requirements (this may take a minute)..."
    sudo -u www-data "$app_root/venv/bin/pip" install --no-cache-dir -q -r "$app_root/requirements.txt"
    log_ok "Requirements installed"

    # Log directory
    mkdir -p "$app_root/.log"
    chown -R www-data:www-data "$app_root/.log"
    # Create empty log files so tail -f works immediately
    for f in hook_debug.log error_file short_error_file log_file short_log_file; do
        touch "$app_root/.log/$f"
    done
    chown -R www-data:www-data "$app_root/.log"
    log_ok "Created $app_root/.log with empty log files"

    # backend_config.yaml template (connection settings + deploy flags + log paths)
    local yaml_dir="$app_root/backend/config"
    mkdir -p "$yaml_dir"

    if [ ! -f "$yaml_dir/backend_config.yaml" ]; then
        cat > "$yaml_dir/backend_config.yaml" << EOF
# Connection settings
retry_count: 3
conn_reset_hours: 23

# Log file paths (relative to app working directory — works uniformly for prod and dev)
file_log_file: .log/log_file
error_log_file: .log/error_file
short_file_log_file: .log/short_log_file
short_error_log_file: .log/short_error_file

# Log levels (Python logging: 10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR)
file_log_level: 10
error_log_level: 40
console_log_level: 40

# App flags — override on server after initial deploy (preserved across deploys by deploy scripts)
enforce_password_standard: False

# cap_in_dev: per-capability toggles for the DEV environment.
# IGNORED on prod (deploy_branch == 'main') where every capability is always on.
cap_in_dev:
  genai: True
  telegram: True
  mail: True
  notify_on_deploy: $notify_on_deploy
  market_feed: True

# Gemini 2.5 Flash allocates part of max_output_tokens to internal "thinking". Cap
# it so the full market-report response fits within the budget.
genai_thinking_budget: 512

# Set by deploy script — current git branch; used to prefix Telegram/email messages on non-main branches
deploy_branch: main

# Loss alert thresholds — checked after every background performance refresh (during market hours)
alert_loss_abs: 10000
alert_loss_pct: 2.0
alert_cooldown_minutes: 30

# Background refresh settings (all times in India IST)
background_refresh: True
performance_refresh_interval: 5
market_refresh_time: "08:30"
open_summary_offset_minutes: 15
close_summary_offset_minutes: 15

# Market segments
market_segments:
  equity:
    hours_start: "09:15"
    hours_end: "15:30"
    holiday_exchange: "NSE"
    exchanges: ["NSE", "BSE", "NFO", "CDS"]
  commodity:
    hours_start: "09:00"
    hours_end: "23:30"
    holiday_exchange: "MCX"
    exchanges: ["MCX"]
EOF
        chown www-data:www-data "$yaml_dir/backend_config.yaml"
        log_ok "Created backend_config.yaml"
    else
        log_ok "backend_config.yaml already exists — not overwriting"
    fi

    # secrets.yaml template
    if [ ! -f "$yaml_dir/secrets.yaml" ]; then
        cat > "$yaml_dir/secrets.yaml" << 'EOF'
# FILL IN REAL VALUES before starting the service
smtp_server: smtp.hostinger.com
smtp_port: 587
smtp_user_name: RamboQuant Team
smtp_user: <your-email>
smtp_pass: <your-smtp-password>
kite_accounts:
    <USER_ID>:
        password: <password>
        totp_token: <totp>
        api_key: <api_key>
        api_secret: <api_secret>
cookie_secret: <random-strong-string>
kite_login_url: https://kite.zerodha.com/api/login
kite_twofa_url: https://kite.zerodha.com/api/twofa
gemini_api_key: <gemini-api-key>
EOF
        chown www-data:www-data "$yaml_dir/secrets.yaml"
        log_warn "Created secrets.yaml TEMPLATE — fill in real values at $yaml_dir/secrets.yaml"
    else
        log_ok "secrets.yaml already exists — not overwriting"
    fi

    chown -R www-data:www-data "$yaml_dir"
}

if [[ "$ENV" == "prod" || "$ENV" == "both" ]]; then
    setup_environment "/opt/ramboq" "$BRANCH_PROD" "$SSH_CLONE_PROD"
fi
if [[ "$ENV" == "dev" || "$ENV" == "both" ]]; then
    setup_environment "/opt/ramboq_dev" "$BRANCH_DEV" "$SSH_CLONE_DEV"
fi

# ============================================================
# STEP 4: systemd service files
# ============================================================
log_step "4. Installing systemd service files"

# Source dir — always read service files from prod repo since webhook is shared
SRC="/opt/ramboq/webhook"
[ ! -d "$SRC" ] && SRC="/opt/ramboq_dev/webhook"

if [[ "$ENV" == "prod" || "$ENV" == "both" ]]; then
    cp "$SRC/ramboq.service" /etc/systemd/system/ramboq.service
    cp "$SRC/ramboq_hook.service" /etc/systemd/system/ramboq_hook.service
    chmod +x "$SRC/deploy.sh" "$SRC/log-request.sh" "$SRC/dispatch.sh" 2>/dev/null || true
    mkdir -p /etc/webhook
    cp "$SRC/hooks.json" /etc/webhook/hooks.json
    cp "$SRC/dispatch.sh" /etc/webhook/dispatch.sh
    chmod +x /etc/webhook/dispatch.sh
    log_ok "Installed ramboq.service, ramboq_hook.service, hooks.json, dispatch.sh"
fi
if [[ "$ENV" == "dev" || "$ENV" == "both" ]]; then
    cp "$SRC/ramboq_dev.service" /etc/systemd/system/ramboq_dev.service
    log_ok "Installed ramboq_dev.service"
fi

systemctl daemon-reload
log_ok "systemd daemon reloaded"

# ============================================================
# STEP 5: sudoers for www-data
# ============================================================
log_step "5. Configuring sudoers for www-data"

SUDOERS_FILE="/etc/sudoers.d/ramboq"

tee "$SUDOERS_FILE" > /dev/null <<'EOF'
www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart ramboq_api.service
www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart ramboq_dev_api.service
www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart ramboq_hook.service
www-data ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx
www-data ALL=(ALL) NOPASSWD: /usr/sbin/nginx
www-data ALL=(ALL) NOPASSWD: /bin/cp -r /opt/ramboq/etc/nginx/sites-available/. /etc/nginx/sites-available/
www-data ALL=(ALL) NOPASSWD: /bin/cp -r /opt/ramboq/var/www/html/. /var/www/html/
EOF
chmod 440 "$SUDOERS_FILE"
visudo -c > /dev/null && log_ok "Configured sudoers at $SUDOERS_FILE" || log_err "sudoers syntax error — check $SUDOERS_FILE manually"

# ============================================================
# STEP 6: nginx
# ============================================================
log_step "6. Configuring nginx"

cp /opt/ramboq/etc/nginx/sites-available/ramboq.com /etc/nginx/sites-available/ramboq.com 2>/dev/null \
    || cp /opt/ramboq_dev/etc/nginx/sites-available/ramboq.com /etc/nginx/sites-available/ramboq.com
cp /opt/ramboq/etc/nginx/sites-available/dev.ramboq.com /etc/nginx/sites-available/dev.ramboq.com 2>/dev/null \
    || cp /opt/ramboq_dev/etc/nginx/sites-available/dev.ramboq.com /etc/nginx/sites-available/dev.ramboq.com
log_ok "Copied nginx site configs"

# Remove default site — it intercepts all unmatched requests
rm -f /etc/nginx/sites-enabled/default
log_ok "Removed default nginx site"

if [[ "$ENV" == "prod" || "$ENV" == "both" ]]; then
    ln -sf /etc/nginx/sites-available/ramboq.com /etc/nginx/sites-enabled/ramboq.com
    log_ok "Enabled ramboq.com site"
fi
if [[ "$ENV" == "dev" || "$ENV" == "both" ]]; then
    ln -sf /etc/nginx/sites-available/dev.ramboq.com /etc/nginx/sites-enabled/dev.ramboq.com
    log_ok "Enabled dev.ramboq.com site"
fi

# Test nginx config — SSL certs likely missing at this point, so allow failure
if nginx -t > /dev/null 2>&1; then
    systemctl reload nginx
    log_ok "nginx reloaded"
else
    log_warn "nginx config test failed — likely missing SSL certs (run certbot after DNS setup)"
fi

# ============================================================
# STEP 7: Enable and start services
# ============================================================
log_step "7. Enabling and starting services"

start_service() {
    local svc="$1"
    systemctl enable "$svc" > /dev/null 2>&1
    if systemctl start "$svc" 2>/dev/null; then
        log_ok "$svc started"
    else
        log_warn "$svc failed to start — fill in secrets.yaml then: sudo systemctl start $svc"
    fi
}

if [[ "$ENV" == "prod" || "$ENV" == "both" ]]; then
    start_service ramboq.service
    start_service ramboq_hook.service
fi
if [[ "$ENV" == "dev" || "$ENV" == "both" ]]; then
    start_service ramboq_dev.service
fi

# ============================================================
# SUMMARY
# ============================================================
WEBHOOK_SECRET=$(grep -o '"secret": *"[^"]*"' /opt/ramboq/webhook/hooks.json 2>/dev/null | head -1 | grep -o '"[^"]*"$' | tr -d '"' || echo "check hooks.json")

echo ""
echo -e "${BOLD}${GREEN}============================================${NC}"
echo -e "${BOLD}${GREEN}  Setup complete!${NC}"
echo -e "${BOLD}${GREEN}============================================${NC}"
echo ""
echo -e "${BOLD}Verify services:${NC}"
echo "  sudo systemctl status ramboq.service ramboq_dev.service ramboq_hook.service"
echo "  sudo ss -tlnp | grep -E '8502|8503|9001'"
echo ""
echo -e "${BOLD}${YELLOW}Required manual steps:${NC}"
echo ""
echo "  1. Fill in secrets.yaml:"
[[ "$ENV" == "prod" || "$ENV" == "both" ]] && echo "       sudo nano /opt/ramboq/backend/config/secrets.yaml"
[[ "$ENV" == "dev"  || "$ENV" == "both" ]] && echo "       sudo nano /opt/ramboq_dev/backend/config/secrets.yaml"
echo ""
echo "  2. Set Cloudflare DNS to grey cloud (DNS only):"
echo "       webhook.ramboq.com → $(curl -s ifconfig.me 2>/dev/null || echo '<server-ip>')"
echo "       dev.ramboq.com     → $(curl -s ifconfig.me 2>/dev/null || echo '<server-ip>')"
echo ""
echo "  3. Run certbot after DNS propagates:"
echo "       sudo certbot --nginx -d ramboq.com -d www.ramboq.com -d webhook.ramboq.com -d dev.ramboq.com"
echo ""
echo "  4. Add GitHub webhook:"
echo "       URL:    https://webhook.ramboq.com/hooks/update"
echo "       Event:  push"
echo "       Secret: $WEBHOOK_SECRET"
echo ""
echo "  5. After filling secrets.yaml, restart app services:"
[[ "$ENV" == "prod" || "$ENV" == "both" ]] && echo "       sudo systemctl restart ramboq.service"
[[ "$ENV" == "dev"  || "$ENV" == "both" ]] && echo "       sudo systemctl restart ramboq_dev.service"
echo ""
