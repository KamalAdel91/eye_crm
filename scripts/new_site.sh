#!/usr/bin/env bash
# A site for Eye CRM v2: ERPNext with the old site's company, the Nexlify apps the bench has,
# Eye CRM, and the old site's masters (customers, contacts, items, prices, users...). No deals.
# Run it from the bench folder:
#
#   bash apps/eye_crm/scripts/new_site.sh eye2.local eye.local
#
# It asks for the MariaDB root password once, for the new site's database (or set DB_ROOT_PASSWORD).
set -euo pipefail

SITE="${1:?usage: new_site.sh NEW_SITE [OLD_SITE]}"
OLD="${2:-}"
BENCH="$(pwd)"
PY="$BENCH/env/bin/python"
SCRIPTS="$BENCH/apps/eye_crm/scripts"

[ -f "$BENCH/sites/apps.txt" ] || { echo "Run this from the bench folder"; exit 1; }
[ -z "$OLD" ] || [ -d "$BENCH/sites/$OLD" ] || { echo "There is no site $OLD"; exit 1; }

installed() { bench --site "$SITE" list-apps 2>/dev/null | awk '{print $1}' | grep -qx "$1"; }

echo "1/5 site"
if [ ! -d "$BENCH/sites/$SITE" ]; then
	bench new-site "$SITE" --admin-password "${ADMIN_PASSWORD:-admin}" \
		${DB_ROOT_PASSWORD:+--mariadb-root-password "$DB_ROOT_PASSWORD"}
fi
installed erpnext || bench --site "$SITE" install-app erpnext

echo "2/5 company"
(cd "$BENCH/sites" && "$PY" "$SCRIPTS/setup_site.py" "$SITE" $OLD)

echo "3/5 apps"
for app in nexlify_core nexlify_board; do
	if [ -d "$BENCH/apps/$app" ] && ! installed "$app"; then
		bench --site "$SITE" install-app "$app" || echo "  $app did not install; Eye CRM doesn't need it"
	fi
done
installed eye_crm || bench --site "$SITE" install-app eye_crm

echo "4/5 masters"
if [ -n "$OLD" ]; then
	(cd "$BENCH/sites" && "$PY" "$SCRIPTS/copy_masters.py" "$OLD" "$SITE")
fi

echo "5/5 done"
bench --site "$SITE" clear-cache
bench --site "$SITE" list-apps
echo "Open http://$SITE:8000 (add $SITE next to the old site in your hosts file) and log in as Administrator."
