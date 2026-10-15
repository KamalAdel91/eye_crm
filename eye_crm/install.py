"""Eye's setup data: put on a site once, then the site owns it.

The Custom Fields, Property Setters, Client and Server Scripts, Reports, permissions and lists in
setup_data/ are loaded when the app is installed. They are not fixtures: a migrate never loads
them again, so what is changed or deleted from the desk (Customize Form, Client Script, Server
Script...) stays as it is. A later change from the app comes as a patch that makes that one change.

	bench --site SITE execute eye_crm.install.load_setup_data
		adds only the records the site doesn't have (nothing is overwritten); for a site that
		lost some of them, or one that had the app before setup_data existed
"""

import json
import os

import frappe

# lists first, then what links to them
ORDER = [
	"role.json",
	"deal_nature.json",
	"service_type.json",
	"po_status.json",
	"pricing_status.json",
	"sales_stage.json",
	"billing_stage.json",
	"eye_approval_status.json",
	"eye_books_mode.json",
	"eye_sync_status.json",
	"custom_field.json",
	"property_setter.json",
	"custom_docperm.json",
	"server_script.json",
	"client_script.json",
	"report.json",
]


def after_install():
	from eye_crm.setup_access import before_fixtures

	from eye_crm.setup_access import run as read_access

	before_fixtures()  # standard permissions are copied before Production's rows are added
	load_setup_data()
	read_access()


def load_setup_data():
	folder = frappe.get_app_path("eye_crm", "setup_data")
	added = 0
	for fname in ORDER:
		path = os.path.join(folder, fname)
		if not os.path.exists(path):
			continue
		with open(path) as f:
			docs = json.load(f)
		for data in docs:
			if frappe.db.exists(data["doctype"], data["name"]):
				continue
			doc = frappe.get_doc(data)
			doc.flags.ignore_links = True
			doc.flags.ignore_permissions = True
			doc.insert(set_name=data["name"])
			added += 1
	frappe.db.commit()
	frappe.clear_cache()
	print(f"Eye CRM: {added} setup record(s) added")
	return added
