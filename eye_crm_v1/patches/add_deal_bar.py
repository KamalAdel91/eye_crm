"""Add the "Eye Deal Bar" Client Script to a site that doesn't have it yet.

Only adds: a copy already on the site (edited or disabled from the desk) is left alone.
"""

import json

import frappe

NAME = "Eye Deal Bar"


def execute():
	if frappe.db.exists("Client Script", NAME):
		return
	path = frappe.get_app_path("eye_crm_v1", "setup_data", "client_script.json")
	with open(path) as f:
		row = next((d for d in json.load(f) if d["name"] == NAME), None)
	if not row:
		return
	doc = frappe.get_doc({k: v for k, v in row.items() if k not in ("modified", "docstatus")})
	doc.insert(ignore_permissions=True)
