#!/usr/bin/env bash
# =============================================================================
# discover_stig_vars.sh
#
# Run on an already-configured Ubuntu 24.04 server to extract the site-specific
# values needed for the ansible-ncs-clean STIG role defaults/group_vars.
#
# Usage:  sudo bash discover_stig_vars.sh [--yaml]
#   --yaml   Output as a ready-to-paste YAML vars snippet
#
# Requires: root or sudo, standard coreutils, apt, systemd
# =============================================================================
set -euo pipefail

YAML_MODE=false
[[ "${1:-}" == "--yaml" ]] && YAML_MODE=true

# ---------- helpers ----------------------------------------------------------
warn()  { echo "[WARN]  $*" >&2; }
info()  { echo "[INFO]  $*" >&2; }
sep()   { echo "# -----------------------------------------------------------------------------"; }

quote_yaml() {
  # Wrap value in double quotes, escaping inner doubles
  local v="$1"
  v="${v//\\/\\\\}"
  v="${v//\"/\\\"}"
  echo "\"${v}\""
}

collect() {
  local key="$1" val="$2" comment="${3:-}"
  if $YAML_MODE; then
    [[ -n "$comment" ]] && echo "# ${comment}"
    echo "${key}: $(quote_yaml "$val")"
  else
    printf "%-55s = %s\n" "$key" "$val"
  fi
}

collect_list() {
  local key="$1" comment="${2:-}"
  shift 2
  local items=("$@")
  if $YAML_MODE; then
    [[ -n "$comment" ]] && echo "${comment}"
    if [[ ${#items[@]} -eq 0 ]]; then
      echo "${key}: []"
    else
      echo "${key}:"
      for item in "${items[@]}"; do
        echo "  - $(quote_yaml "$item")"
      done
    fi
  else
    printf "%-55s = [%s]\n" "$key" "$(IFS=,; echo "${items[*]}")"
  fi
}

# ---------- pre-flight -------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Run as root or with sudo" >&2
  exit 1
fi

$YAML_MODE && echo "---"
$YAML_MODE && sep
$YAML_MODE && echo "# Auto-discovered STIG site-specific variables"
$YAML_MODE && echo "# Generated on $(hostname -f) at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
$YAML_MODE && sep
echo ""

# =============================================================================
# 1. audisp remote server  (SV-270658)
# =============================================================================
REMOTE_SERVER=""
if [[ -f /etc/audit/audisp-remote.conf ]]; then
  REMOTE_SERVER=$(awk -F'= *' '/^remote_server/ {print $2}' /etc/audit/audisp-remote.conf 2>/dev/null || true)
fi
if [[ -z "$REMOTE_SERVER" ]] && [[ -f /etc/audisp/audisp-remote.conf ]]; then
  REMOTE_SERVER=$(awk -F'= *' '/^remote_server/ {print $2}' /etc/audisp/audisp-remote.conf 2>/dev/null || true)
fi
[[ -z "$REMOTE_SERVER" ]] && warn "No audisp remote_server found — set manually"
collect "ubuntu2404STIG_stigrule_270658_remote_server" "${REMOTE_SERVER}" "audisp remote syslog/SIEM destination (SV-270658)"
echo ""

# =============================================================================
# 2. Chrony NTP server  (SV-270751)
# =============================================================================
CHRONY_SERVER=""
if [[ -f /etc/chrony/chrony.conf ]]; then
  # Grab the first 'server' line that isn't a pool
  CHRONY_SERVER=$(grep -E '^\s*server\s+' /etc/chrony/chrony.conf | head -1 | awk '{print $2}' || true)
fi
if [[ -z "$CHRONY_SERVER" ]] && command -v chronyc &>/dev/null; then
  CHRONY_SERVER=$(chronyc sources -n 2>/dev/null | awk '/^\^/ {print $2; exit}' || true)
fi
[[ -z "$CHRONY_SERVER" ]] && warn "No chrony server found — set manually"
collect "ubuntu2404STIG_stigrule_270751_chrony_server" "${CHRONY_SERVER}" "Authoritative NTP server (SV-270751)"
echo ""

# =============================================================================
# 3. Authorized sudo group members  (SV-270748)
# =============================================================================
SUDO_MEMBERS=()
if getent group sudo &>/dev/null; then
  IFS=',' read -ra SUDO_MEMBERS <<< "$(getent group sudo | cut -d: -f4)"
fi
# Filter out empty strings
SUDO_CLEAN=()
for m in "${SUDO_MEMBERS[@]}"; do
  [[ -n "$m" ]] && SUDO_CLEAN+=("$m")
done
collect_list "ubuntu2404STIG_stigrule_270748_authorized_sudo_members" \
  "# Accounts authorized in sudo group (SV-270748)" \
  "${SUDO_CLEAN[@]}"
echo ""

# =============================================================================
# 4. SSSD / LDAP  (SV-270734, SV-270735, SV-270736)
# =============================================================================
SSSD_DOMAIN=""
SSSD_LDAP_URI=""
SSSD_SEARCH_BASE=""

if [[ -f /etc/sssd/sssd.conf ]]; then
  # Get first domain from [sssd] domains = line
  SSSD_DOMAIN=$(awk -F'= *' '/^domains/ {print $2}' /etc/sssd/sssd.conf | cut -d',' -f1 | tr -d '[:space:]' || true)

  # Try to find ldap_uri in the domain section
  if [[ -n "$SSSD_DOMAIN" ]]; then
    SSSD_LDAP_URI=$(awk "/^\[domain\/${SSSD_DOMAIN}\]/,/^\[/" /etc/sssd/sssd.conf \
      | awk -F'= *' '/^ldap_uri/ {print $2}' | head -1 || true)
    SSSD_SEARCH_BASE=$(awk "/^\[domain\/${SSSD_DOMAIN}\]/,/^\[/" /etc/sssd/sssd.conf \
      | awk -F'= *' '/^ldap_search_base/ {print $2}' | head -1 || true)
  fi
fi

# Fallback: try realm/domain from hostname
if [[ -z "$SSSD_DOMAIN" ]]; then
  SSSD_DOMAIN=$(dnsdomainname 2>/dev/null || hostname -d 2>/dev/null || true)
fi

# Fallback: try resolving LDAP SRV records
if [[ -z "$SSSD_LDAP_URI" ]] && [[ -n "$SSSD_DOMAIN" ]]; then
  SRV_HOST=$(host -t SRV "_ldap._tcp.${SSSD_DOMAIN}" 2>/dev/null \
    | awk '/has SRV record/ {print $NF; exit}' | sed 's/\.$//' || true)
  [[ -n "$SRV_HOST" ]] && SSSD_LDAP_URI="ldap://${SRV_HOST}"
fi

# Fallback: derive search base from domain
if [[ -z "$SSSD_SEARCH_BASE" ]] && [[ -n "$SSSD_DOMAIN" ]]; then
  SSSD_SEARCH_BASE=$(echo "$SSSD_DOMAIN" | sed 's/\./,DC=/g; s/^/DC=/')
fi

[[ -z "$SSSD_DOMAIN" ]]      && warn "Could not determine SSSD domain — set manually"
[[ -z "$SSSD_LDAP_URI" ]]    && warn "Could not determine LDAP URI — set manually"
[[ -z "$SSSD_SEARCH_BASE" ]] && warn "Could not determine LDAP search base — set manually"

collect "ubuntu2404STIG_sssd_domain"          "${SSSD_DOMAIN}"      "SSSD domain name (SV-270734/735/736)"
collect "ubuntu2404STIG_sssd_ldap_uri"        "${SSSD_LDAP_URI}"    "LDAP server URI"
collect "ubuntu2404STIG_sssd_ldap_search_base" "${SSSD_SEARCH_BASE}" "LDAP search base DN"
echo ""

# =============================================================================
# 5. DoD Root CA  (SV-270745)
# =============================================================================
DOD_CA_FILE=""
DOD_CA_FILENAME=""
if ls /usr/local/share/ca-certificates/*[Dd][Oo][Dd]* 2>/dev/null | head -1 | read -r f; then
  DOD_CA_FILE="$f"
  DOD_CA_FILENAME="$(basename "$f")"
elif ls /etc/ssl/certs/*[Dd][Oo][Dd]* 2>/dev/null | head -1 | read -r f; then
  DOD_CA_FILE="$f"
  DOD_CA_FILENAME="$(basename "$f")"
fi

if [[ -n "$DOD_CA_FILE" ]]; then
  collect "ubuntu2404STIG_stigrule_270745_dod_ca_filename" "$DOD_CA_FILENAME" "DoD Root CA (SV-270745)"
  if $YAML_MODE; then
    echo "ubuntu2404STIG_stigrule_270745_dod_ca_content: |"
    sed 's/^/  /' "$DOD_CA_FILE"
  else
    echo "# DoD CA content found at: ${DOD_CA_FILE}"
    echo "# Use: ubuntu2404STIG_stigrule_270745_dod_ca_content: <contents of ${DOD_CA_FILE}>"
  fi
else
  warn "No DoD CA certificate found in /usr/local/share/ca-certificates or /etc/ssl/certs"
  collect "ubuntu2404STIG_stigrule_270745_dod_ca_filename" "dod-root-ca.crt" "DoD Root CA (SV-270745) — NOT FOUND, set manually"
  collect "ubuntu2404STIG_stigrule_270745_dod_ca_content" "" ""
fi
echo ""

# =============================================================================
# 6. Ubuntu Pro / FIPS  (SV-270744)
# =============================================================================
PRO_STATUS=""
PRO_TOKEN=""
if command -v pro &>/dev/null; then
  PRO_STATUS=$(pro status 2>/dev/null | grep -i fips || true)
  # Token can't be extracted from the host — just note the status
  info "Ubuntu Pro FIPS status: ${PRO_STATUS:-unknown}"
fi
collect "ubuntu2404STIG_stigrule_270744_pro_token" "" "Ubuntu Pro token (SV-270744) — must be set from Canonical account"
echo ""

# =============================================================================
# 7. GRUB PBKDF2 hash  (SV-270675)
# =============================================================================
GRUB_HASH=""
if [[ -f /etc/grub.d/40_custom ]]; then
  GRUB_HASH=$(grep -oP 'password_pbkdf2\s+root\s+\K\S+' /etc/grub.d/40_custom 2>/dev/null || true)
fi
if [[ -z "$GRUB_HASH" ]] && [[ -f /boot/grub/grub.cfg ]]; then
  GRUB_HASH=$(grep -oP 'password_pbkdf2\s+root\s+\K\S+' /boot/grub/grub.cfg 2>/dev/null || true)
fi
[[ -z "$GRUB_HASH" ]] && warn "No GRUB PBKDF2 hash found — generate with: grub-mkpasswd-pbkdf2"
collect "ubuntu2404STIG_stigrule_270675_grub_pbkdf2_hash" "${GRUB_HASH}" "GRUB password hash (SV-270675)"
echo ""

# =============================================================================
# 8. Encrypted partitions / crypttab  (SV-270747)
# =============================================================================
CRYPT_ENTRIES=()
if [[ -f /etc/crypttab ]]; then
  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "$line" ]] && continue
    CRYPT_ENTRIES+=("$line")
  done < /etc/crypttab
fi
collect_list "ubuntu2404STIG_stigrule_270747_crypttab_entries" \
  "# LUKS/crypttab entries (SV-270747)" \
  "${CRYPT_ENTRIES[@]}"
echo ""

# =============================================================================
# 9. Audit log mountpoint  (SV-270816)
# =============================================================================
AUDIT_LOG="/var/log/audit/audit.log"
if [[ -f /etc/audit/auditd.conf ]]; then
  AUDIT_LOG=$(awk -F'= *' '/^log_file/ {print $2}' /etc/audit/auditd.conf | tail -1)
fi
AUDIT_DIR=$(dirname "$AUDIT_LOG")
AUDIT_MOUNT=$(df -P "$AUDIT_DIR" 2>/dev/null | awk 'NR==2 {print $6}' || echo "")
AUDIT_FREE_KB=$(df -Pk "$AUDIT_DIR" 2>/dev/null | awk 'NR==2 {print $4}' || echo "0")

collect "ubuntu2404STIG_stigrule_270816_audit_log_mountpoint" "${AUDIT_DIR}" "Audit log directory (SV-270816)"
collect "ubuntu2404STIG_stigrule_270816_min_free_kb" "${AUDIT_FREE_KB}" "Current free space in KB (informational)"
info "Audit logs on mount: ${AUDIT_MOUNT}, free: ${AUDIT_FREE_KB} KB"
echo ""

# =============================================================================
# 10. Audit offload destination  (SV-270817)
# =============================================================================
OFFLOAD_DEST=""
if [[ -f /etc/cron.weekly/audit-offload ]]; then
  OFFLOAD_DEST=$(grep -oP 'rsync\s+.*\s+\K\S+/$' /etc/cron.weekly/audit-offload 2>/dev/null || true)
fi
[[ -z "$OFFLOAD_DEST" ]] && warn "No audit offload destination found — set manually"
collect "ubuntu2404STIG_stigrule_270817_audit_offload_destination" "${OFFLOAD_DEST}" "Weekly audit offload rsync target (SV-270817)"
echo ""

# =============================================================================
# 11. UFW rate-limited services  (SV-270754)
# =============================================================================
LIMITED=()
if command -v ufw &>/dev/null; then
  while IFS= read -r line; do
    port=$(echo "$line" | awk '{print $1}' | cut -d/ -f1)
    proto=$(echo "$line" | awk '{print $1}' | cut -d/ -f2)
    [[ "$proto" == "$port" ]] && proto=""
    if [[ -n "$port" ]]; then
      if $YAML_MODE; then
        LIMITED+=("{ port: \"${port}\", proto: \"${proto:-tcp}\" }")
      else
        LIMITED+=("${port}/${proto:-tcp}")
      fi
    fi
  done < <(ufw status 2>/dev/null | grep 'LIMIT' | grep -v '(v6)' || true)
fi
if $YAML_MODE; then
  echo "# UFW rate-limited services (SV-270754)"
  if [[ ${#LIMITED[@]} -eq 0 ]]; then
    echo "ubuntu2404STIG_stigrule_270754_limited_services: []"
  else
    echo "ubuntu2404STIG_stigrule_270754_limited_services:"
    for entry in "${LIMITED[@]}"; do
      echo "  - ${entry}"
    done
  fi
else
  printf "%-55s = [%s]\n" "ubuntu2404STIG_stigrule_270754_limited_services" "$(IFS=,; echo "${LIMITED[*]}")"
fi
echo ""

# =============================================================================
# 12. UFW allowed rules  (SV-270719)
# =============================================================================
ALLOWED=()
if command -v ufw &>/dev/null; then
  while IFS= read -r line; do
    port=$(echo "$line" | awk '{print $1}' | cut -d/ -f1)
    proto=$(echo "$line" | awk '{print $1}' | cut -d/ -f2)
    action=$(echo "$line" | awk '{print $2}')
    [[ "$proto" == "$port" ]] && proto=""
    if [[ -n "$port" ]] && [[ "$action" == "ALLOW" ]]; then
      if $YAML_MODE; then
        ALLOWED+=("{ rule: \"allow\", port: \"${port}\", proto: \"${proto:-tcp}\" }")
      else
        ALLOWED+=("allow:${port}/${proto:-tcp}")
      fi
    fi
  done < <(ufw status 2>/dev/null | grep 'ALLOW' | grep -v '(v6)' || true)
fi
if $YAML_MODE; then
  echo "# UFW allowed rules (SV-270719)"
  if [[ ${#ALLOWED[@]} -eq 0 ]]; then
    echo "ubuntu2404STIG_stigrule_270719_allowed_ufw_rules: []"
  else
    echo "ubuntu2404STIG_stigrule_270719_allowed_ufw_rules:"
    for entry in "${ALLOWED[@]}"; do
      echo "  - ${entry}"
    done
  fi
else
  printf "%-55s = [%s]\n" "ubuntu2404STIG_stigrule_270719_allowed_ufw_rules" "$(IFS=,; echo "${ALLOWED[*]}")"
fi
echo ""

# =============================================================================
# Summary
# =============================================================================
echo ""
sep
info "Discovery complete. Review output above and populate your group_vars/host_vars."
info "Items marked [WARN] need manual configuration."
sep
