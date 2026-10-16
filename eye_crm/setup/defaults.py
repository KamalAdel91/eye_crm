"""The records Eye CRM starts a site with. Made once; after that they belong to the site."""

import frappe

LISTS = {
	"Eye Yes No": ("value", ["Yes", "No"]),
	"Eye PO Status": ("title", ["Purchase Order (PO)", "To receive the PO this month"]),
	"Eye Approval Status": ("title", ["Not Required", "Pending", "Approved", "Rejected"]),
	"Eye Quotation Type": ("title", ["Full", "Changes Only"]),
}

# the types the app's code knows; a Sales Stage takes one
STAGE_TYPES = [
	("Pipeline", 0, "A deal being worked on: its services, costs and prices are drafts."),
	("Quotation", 0, "A deal entering it gets its quotation from the P&L (see Eye CRM Settings)."),
	("In Hand", 0, "The customer agreed, and the PO arrived or is on its way."),
	(
		"Opening",
		0,
		"Opens the project: checks the deal, then opens it or asks for approval. A deal never stays in it.",
	),
	("Approval", 1, "Waiting for approval to open the project."),
	(
		"Opened",
		1,
		"The project is open: the Cost Sheet, P&L and quotation are submitted and the Sales Order is made.",
	),
	("Change Approval", 1, "A financial change after the project opened, waiting for approval."),
]

# title, key the code knows, message when it fails
CHECKS = [
	("Services Added", "services", "Add at least one service to the deal."),
	(
		"Costs Entered",
		"costs",
		"Every service needs its costs in the Cost Sheet, or No Cost ticked in the P&L.",
	),
	("Prices Set", "prices", "Every service needs a selling price in the P&L."),
	("Quotation Made", "quotation", "Make the quotation first."),
	(
		"Quotation Matches the P&L",
		"quotation_matches",
		"The P&L changed after the last quotation: update the quotation.",
	),
	("Customer Set", "customer", "The deal must be for a customer, not a lead."),
]

# name, type, order, color, checks before a deal enters
STAGES = [
	("Estimation", "Pipeline", 10, "#94A3B8", []),
	("Quotation", "Quotation", 20, "#1DA7DF", ["Services Added", "Prices Set"]),
	("Deals in Hand", "In Hand", 30, "#F59E0B", ["Quotation Made"]),
	(
		"Open Project",
		"Opening",
		40,
		"#8B5CF6",
		["Services Added", "Costs Entered", "Prices Set", "Quotation Matches the P&L", "Customer Set"],
	),
	("Needs Approval", "Approval", 50, "#EF4444", []),
	("Project Opened", "Opened", 60, "#22C55E", []),
	("Change Approval", "Change Approval", 70, "#F97316", []),
]

# what ERPNext's setup wizard adds; Eye's stages replace them
ERPNEXT_STAGES = [
	"Prospecting",
	"Qualification",
	"Needs Analysis",
	"Value Proposition",
	"Identifying Decision Makers",
	"Perception Analysis",
	"Proposal/Price Quote",
	"Negotiation/Review",
]


def _insert(doc):
	doc = frappe.get_doc(doc)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def make_lists():
	for doctype, (field, values) in LISTS.items():
		for value in values:
			if not frappe.db.exists(doctype, value):
				_insert({"doctype": doctype, field: value})
	for title, system_only, description in STAGE_TYPES:
		if not frappe.db.exists("Eye Stage Type", title):
			_insert(
				{
					"doctype": "Eye Stage Type",
					"title": title,
					"system_only": system_only,
					"description": description,
				}
			)
	for title, key, message in CHECKS:
		if not frappe.db.exists("Eye Check", {"check_key": key}):
			_insert({"doctype": "Eye Check", "title": title, "check_key": key, "message": message})


def make_stages():
	for name, stage_type, order, color, checks in STAGES:
		if frappe.db.exists("Sales Stage", name):
			continue
		_insert(
			{
				"doctype": "Sales Stage",
				"stage_name": name,
				"eye_stage_type": stage_type,
				"eye_stage_order": order,
				"eye_color": color,
				"eye_checks": [{"check": c} for c in checks if frappe.db.exists("Eye Check", c)],
			}
		)


def remove_erpnext_stages():
	"""ERPNext's default stages, when no deal uses them."""
	for name in ERPNEXT_STAGES:
		if frappe.db.exists("Sales Stage", name) and not frappe.db.exists(
			"Opportunity", {"sales_stage": name}
		):
			frappe.delete_doc("Sales Stage", name, ignore_permissions=True, force=True)


def make_settings():
	settings = frappe.get_single("Eye CRM Settings")
	if not settings.reject_stage and frappe.db.exists("Sales Stage", "Deals in Hand"):
		settings.reject_stage = "Deals in Hand"
	settings.flags.ignore_permissions = True
	settings.save()
