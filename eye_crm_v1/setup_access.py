"""Who sees what in Eye: read access for Accounts and Management on the ERPNext documents Eye uses.

run() goes once, when the app is installed (eye_crm_v1.install), and is safe to run again by hand:
a permission taken away from the desk later stays taken away. It goes through
frappe.permissions.add_permission, which first copies a DocType's standard permissions into
Custom DocPerm when the site has none yet, so no role loses access.

before_fixtures() goes at install, ahead of Eye's Custom DocPerm rows (Production's rows on
Item, Customer...). A DocType with no custom permissions yet gets
its standard ones copied first; without that, Production's row would be the only one left.
"""

import json
import os

import frappe
from frappe.permissions import add_permission, setup_custom_perms

READ = {
	"Opportunity": ["Accounts User", "Accounts Manager", "Management"],
	"Quotation": ["Accounts User", "Accounts Manager", "Management"],
	"Sales Order": ["Management"],
	"Customer": ["Management"],
	"Item": ["Management"],
	"Pricing Request": ["Accounts User", "Accounts Manager", "Management"],
	"Billing Request": ["Management"],
}

# roles Eye adds rows for; a DocType whose custom permissions hold only these lost its standard ones
EYE_ROLES = {"Production", "Management", "Accounts User", "Accounts Manager"}


def fixture_doctypes():
	path = frappe.get_app_path("eye_crm_v1", "setup_data", "custom_docperm.json")
	if not os.path.exists(path):
		return []
	with open(path) as f:
		return sorted({r["parent"] for r in json.load(f)})


def before_fixtures():
	for doctype in fixture_doctypes():
		if frappe.db.exists("DocType", doctype):
			setup_custom_perms(doctype)
	frappe.db.commit()


def repair(doctype):
	roles = set(frappe.get_all("Custom DocPerm", filters={"parent": doctype}, pluck="role"))
	if not roles or not roles <= EYE_ROLES:
		return
	for d in frappe.get_all("DocPerm", fields="*", filters={"parent": doctype}):
		if d.role in roles:
			continue
		row = frappe.new_doc("Custom DocPerm")
		row.update({k: v for k, v in d.items() if k not in ("name", "creation", "modified")})
		row.insert(ignore_permissions=True)
	print(f"Eye CRM: standard permissions restored on {doctype}")


def run():
	for doctype in sorted(set(fixture_doctypes()) | set(READ)):
		if frappe.db.exists("DocType", doctype):
			repair(doctype)
	for doctype, roles in READ.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for role in roles:
			if not frappe.db.exists("Role", role):
				continue
			if has_read(doctype, role):
				continue
			add_permission(doctype, role, 0, "read")
			frappe.db.set_value(
				"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}, {"report": 1, "print": 1}
			)
	frappe.clear_cache()
	frappe.db.commit()


def has_read(doctype, role):
	custom = frappe.get_all("Custom DocPerm", filters={"parent": doctype, "role": role, "permlevel": 0, "read": 1}, limit=1)
	if custom:
		return True
	if frappe.db.exists("Custom DocPerm", {"parent": doctype}):
		return False  # the site's custom permissions replace the standard ones
	return bool(frappe.db.exists("DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "read": 1}))
