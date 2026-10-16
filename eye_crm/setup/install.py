"""What the app puts on a site, once, when it is installed.

After that the site owns it: a migrate never brings back what was changed or deleted from the desk.
A later change from the app comes as a patch that makes that one change.
"""

import frappe

from eye_crm.setup import custom_fields, defaults

ROLES = ["Management"]


def before_install():
	# the app's doctypes give this role permissions, so it must exist before they are synced
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def after_install():
	defaults.make_lists()
	custom_fields.make_custom_fields()
	frappe.clear_cache(doctype="Sales Stage")
	defaults.make_stages()
	defaults.remove_erpnext_stages()
	custom_fields.make_property_setters()
	defaults.make_settings()
	set_permissions()
	frappe.clear_cache()


def after_setup_wizard(args=None):
	# the wizard adds ERPNext's own sales stages; Eye's replace them
	if "eye_crm" in frappe.get_installed_apps():
		defaults.remove_erpnext_stages()


def set_permissions():
	"""Defaults for the Role Permission Manager, where they can be changed."""
	from frappe.permissions import add_permission, setup_custom_perms

	# Sales User: their own deals, and the ones shared with them. The app shares a deal with its
	# Salesperson; Frappe shares it with whoever it is assigned to.
	setup_custom_perms("Opportunity")
	frappe.db.set_value(
		"Custom DocPerm", {"parent": "Opportunity", "role": "Sales User", "permlevel": 0}, "if_owner", 1
	)
	# Accounts approve deals and bill them; Management reads everything
	readers = {
		"Opportunity": ["Accounts User", "Accounts Manager", "Management"],
		"Quotation": ["Management"],
		"Sales Order": ["Management"],
		"Customer": ["Management"],
	}
	for doctype, roles in readers.items():
		setup_custom_perms(doctype)
		for role in roles:
			if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
				add_permission(doctype, role, 0)


def before_uninstall():
	"""Undo what isn't removed with the app's modules (its fields and property setters are)."""
	frappe.db.set_value(
		"Custom DocPerm", {"parent": "Opportunity", "role": "Sales User", "permlevel": 0}, "if_owner", 0
	)
