#!/usr/bin/env bash
# Rename the old Eye CRM app (eye_crm) to eye_crm_v1, in this bench and on every site that has it,
# so that v2 can take the name eye_crm. Run it from the bench folder after switching the old app
# to the v1 branch, with `bench start` still running in its own terminal:
#
#   git -C apps/eye_crm fetch origin && git -C apps/eye_crm checkout -B v1 origin/v1
#   bash apps/eye_crm/scripts/rename_to_v1.sh
#
# Then restart `bench start`.
set -euo pipefail

BENCH="$(pwd)"
OLD="$BENCH/apps/eye_crm"
NEW="$BENCH/apps/eye_crm_v1"
PY="$BENCH/env/bin/python"

[ -f "$BENCH/sites/apps.txt" ] || { echo "Run this from the bench folder"; exit 1; }

echo "1/5 folder"
if [ -d "$OLD/eye_crm_v1" ] && [ ! -e "$NEW" ]; then
	if [ -n "$(git -C "$OLD" status --porcelain --untracked-files=no)" ]; then
		echo "apps/eye_crm has local changes; commit or discard them first:"
		git -C "$OLD" status --short --untracked-files=no
		exit 1
	fi
	# after the checkout only __pycache__ folders are left of the old package
	if [ -d "$OLD/eye_crm" ] && [ -z "$(git -C "$OLD" ls-files eye_crm)" ]; then rm -rf "$OLD/eye_crm"; fi
	mv "$OLD" "$NEW"
elif [ -d "$NEW/eye_crm_v1" ]; then
	echo "  apps/eye_crm_v1 is already there"
else
	echo "apps/eye_crm is not on the v1 branch yet:"
	echo "  git -C apps/eye_crm fetch origin && git -C apps/eye_crm checkout -B v1 origin/v1"
	exit 1
fi

echo "2/5 python package"
if command -v uv >/dev/null 2>&1; then PIP=(uv pip); PYARG=(--python "$PY"); else PIP=("$PY" -m pip); PYARG=(); fi
if [ ! -d "$OLD" ]; then
	"${PIP[@]}" uninstall "${PYARG[@]}" eye_crm $([ "${PIP[0]}" = uv ] || echo --yes) || true
fi
"${PIP[@]}" install --quiet "${PYARG[@]}" -e "$NEW"
if ! grep -qx eye_crm_v1 "$BENCH/sites/apps.txt"; then sed -i 's/^eye_crm$/eye_crm_v1/' "$BENCH/sites/apps.txt"; fi
"$PY" - "$BENCH/sites/apps.json" <<'PY'
import json, os, sys
path = sys.argv[1]
if os.path.exists(path):
	with open(path) as f:
		apps = json.load(f)
	if "eye_crm" in apps and "eye_crm_v1" not in apps:
		apps = {("eye_crm_v1" if k == "eye_crm" else k): v for k, v in apps.items()}
		with open(path, "w") as f:
			json.dump(apps, f, indent=4)
PY
# the old app's assets link; v2 makes its own when it is built
if [ -L "$BENCH/sites/assets/eye_crm" ] && [ ! -d "$OLD" ]; then rm -f "$BENCH/sites/assets/eye_crm"; fi

echo "3/5 sites"
cd "$BENCH/sites"
SITES=$("$PY" "$NEW/scripts/rename_db.py" | tee /dev/stderr | sed -n 's/^SITE //p')
cd "$BENCH"

echo "4/5 assets"
bench build --app eye_crm_v1

echo "5/5 migrate"
for SITE in $SITES; do
	bench --site "$SITE" migrate
	bench --site "$SITE" clear-cache
	bench --site "$SITE" list-apps
done
echo "Done: the old app is eye_crm_v1 now. Restart bench start."
