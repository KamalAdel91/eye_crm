"""Point every site that has the old app (eye_crm) at its new name (eye_crm_v1).

Called by rename_to_v1.sh with the bench's python, from the sites folder. Only SQL is used, because
the old package is already gone and loading the site's hooks would fail until the rename is done.
"""

import json
import os

import frappe

OLD, NEW = "eye_crm", "eye_crm_v1"
# a dotted path (eye_crm.module.function) or an asset path (/assets/eye_crm/...); not a file name
# like eye_crm.css and not the module folder inside the package (eye_crm_v1.eye_crm.doctype)
DOTTED = r"(?<![[:alnum:]_./])eye_crm(?=\.(?!(css|js|json|html|py|png|svg|txt|md)\b)[a-z_])"
# history and logs are left as they were
SKIP = {
	"tabVersion", "tabDeleted Document", "tabComment", "tabCommunication", "tabEmail Queue",
	"tabEmail Queue Recipient", "tabRoute History", "tabPrepared Report", "tabConsole Log",
	"tabPatch Log",
}


V1_MODULES = ("Eye CRM", "Eye Home", "Eye Sales")


def v1_sites():
	"""Sites that have v1, by its modules: v2 is also called eye_crm but has other modules."""
	for site in sorted(os.listdir(".")):
		if not os.path.exists(os.path.join(site, "site_config.json")):
			continue
		frappe.init(site=site, sites_path=".")
		try:
			frappe.connect()
			apps = {
				r[0]
				for r in frappe.db.sql(
					"select app_name from `tabModule Def` where name in %s", (V1_MODULES,)
				)
			}
			if apps & {OLD, NEW}:
				yield site, OLD in apps
		except Exception as e:
			print(f"  {site}: skipped ({e})")
		finally:
			frappe.destroy()


def rename_site(site):
	frappe.init(site=site, sites_path=".")
	frappe.connect()
	db = frappe.db
	try:
		for name, value in db.sql("select name, defvalue from tabDefaultValue where defkey='installed_apps'"):
			apps = [NEW if a == OLD else a for a in json.loads(value or "[]")]
			db.sql("update tabDefaultValue set defvalue=%s where name=%s", (json.dumps(apps), name))
		db.sql("update `tabInstalled Application` set app_name=%s where app_name=%s", (NEW, OLD))
		db.sql("update `tabModule Def` set app_name=%s where app_name=%s", (NEW, OLD))
		# the app's own dock is named after the app
		if db.sql("select name from tabDock where name=%s", OLD):
			db.sql("update tabDock set name=%s where name=%s", (NEW, OLD))
			db.sql("update `tabDock Item` set parent=%s where parent=%s and parenttype='Dock'", (NEW, OLD))
		db.sql(
			"update `tabPatch Log` set patch=concat(%s, substring(patch, %s)) where patch like %s",
			(NEW + ".", len(OLD) + 2, OLD + ".%"),
		)

		columns = db.sql(
			"""select table_name, column_name, data_type from information_schema.columns
			where table_schema=database() and table_name like 'tab%%'
			and data_type in ('varchar', 'text', 'mediumtext', 'longtext', 'json')""",
			as_dict=True,
		)
		changed = 0
		for c in columns:
			table, col = c.table_name, c.column_name
			if table in SKIP or table.endswith(" Log"):
				continue
			if col in ("app", "app_name") and c.data_type == "varchar":
				changed += db.sql(f"update `{table}` set `{col}`=%s where `{col}`=%s", (NEW, OLD)) or 0
			hits = db.sql(
				f"select count(*) from `{table}` where `{col}` like %s or `{col}` like %s",
				("%eye_crm.%", "%/assets/eye_crm/%"),
			)[0][0]
			if not hits:
				continue
			db.sql(
				f"""update `{table}` set `{col}` = regexp_replace(replace(`{col}`, '/assets/eye_crm/',
				'/assets/eye_crm_v1/'), %s, %s) where `{col}` like %s or `{col}` like %s""",
				(DOTTED, NEW, "%eye_crm.%", "%/assets/eye_crm/%"),
			)
			print(f"  {site}: {table}.{col}: {hits} row(s)")
			changed += hits
		db.commit()
		frappe.cache.delete_keys("")
		print(f"  {site}: renamed")
	finally:
		frappe.destroy()


if __name__ == "__main__":
	sites = list(v1_sites())
	if not sites:
		print("No site has Eye CRM v1")
	for site, needs_rename in sites:
		if needs_rename:
			rename_site(site)
		else:
			print(f"  {site}: already renamed")
	for site, _ in sites:
		print(f"SITE {site}")
