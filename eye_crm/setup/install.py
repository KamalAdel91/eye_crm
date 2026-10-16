"""What the app puts on a site, once, when it is installed.

After that the site owns it: a migrate never brings back what was changed or deleted from the desk.
A later change from the app comes as a patch that makes that one change (eye_crm/patches); a new
site gets it from here, as the patches are marked done when the app is installed.
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
	frappe.clear_cache(doctype="Opportunity")
	make_billing_and_boards()
	frappe.clear_cache()


def make_billing_and_boards():
	"""Billing stages, the Deals and Billing boards, the notifications, and Nexlify Board's settings
	when it is installed (eye_crm.patches.billing_boards_notifications, for sites that had the app)."""
	defaults.make_billing()
	defaults.make_boards()
	defaults.make_notifications()
	defaults.make_nexlify_settings()


def after_app_install(app_name):
	"""Nexlify Board installed after this app: its settings for the deals and requests, then."""
	if app_name == "nexlify_board" and "eye_crm" in frappe.get_installed_apps():
		defaults.make_nexlify_settings()


def after_setup_wizard(args=None):
	# the wizard adds ERPNext's own sales stages; Eye's replace them
	if "eye_crm" in frappe.get_installed_apps():
		defaults.remove_erpnext_stages()


# Accounts approve deals and bill them; Management reads everything
READERS = {
	"Opportunity": ["Accounts User", "Accounts Manager", "Management"],
	"Quotation": ["Accounts User", "Accounts Manager", "Management"],
	"Sales Order": ["Management"],
	"Customer": ["Management"],
}


def set_permissions():
	"""Defaults for the Role Permission Manager, where they can be changed."""
	from frappe.permissions import setup_custom_perms

	# Sales User: their own deals, and the ones shared with them. The app shares a deal with its
	# Salesperson; Frappe shares it with whoever it is assigned to.
	setup_custom_perms("Opportunity")
	frappe.db.set_value(
		"Custom DocPerm", {"parent": "Opportunity", "role": "Sales User", "permlevel": 0}, "if_owner", 1
	)
	add_readers()


def add_readers():
	from frappe.permissions import add_permission, setup_custom_perms

	for doctype, roles in READERS.items():
		setup_custom_perms(doctype)
		for role in roles:
			if not frappe.db.exists("Role", role):
				continue
			if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
				add_permission(doctype, role, 0)
				frappe.db.set_value(
					"Custom DocPerm",
					{"parent": doctype, "role": role, "permlevel": 0},
					{"report": 1, "print": 1},
				)
	frappe.clear_cache()


def before_uninstall():
	"""Undo what isn't removed with the app's modules (its fields, property setters, boards and
	notifications are)."""
	frappe.db.set_value(
		"Custom DocPerm", {"parent": "Opportunity", "role": "Sales User", "permlevel": 0}, "if_owner", 0
	)
	defaults.remove_nexlify_settings()
