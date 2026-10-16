"""Billing, the Deals and Billing boards and the notifications, on a site that had the app before
them. A new site gets the same from eye_crm.setup.install."""

import frappe

from eye_crm.setup import custom_fields, defaults, install


def execute():
	# the new fields only: a field that is already there stays as the site has it
	custom_fields.make_custom_fields()
	frappe.clear_cache(doctype="Opportunity")
	defaults.approval_status_from_pls()
	install.make_billing_and_boards()
	# Accounts and Management read deals: in the Report view and in print too
	for doctype, roles in install.READERS.items():
		for role in roles:
			frappe.db.set_value(
				"Custom DocPerm",
				{"parent": doctype, "role": role, "permlevel": 0},
				{"report": 1, "print": 1},
			)
	install.add_readers()
	# what is left to request, for the projects already open
	from eye_crm.eye.billing import update_deal

	for name in frappe.get_all("Opportunity", filters={"eye_sales_order": ["is", "set"]}, pluck="name"):
		update_deal(name)
