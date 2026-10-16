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


# ---------------------------------------------------------------- billing

BILLING_STAGE_TYPES = [
	("Draft", "Sales is preparing the request: Finance doesn't have it yet."),
	("Requested", "Sent to Finance, to issue the invoice."),
	("Invoiced", "The invoice is issued: its number and date are on the request."),
	("Collected", "The customer paid: the amount collected is on the request."),
]

# title, type, order, color, a request can start here, default, roles that move requests in and out
BILLING_STAGES = [
	("To be invoiced", "Draft", 10, "#94A3B8", 1, 1, []),
	("Finance, please issue", "Requested", 20, "#F97316", 1, 0, []),
	("Invoiced", "Invoiced", 30, "#3B82F6", 0, 0, ["Accounts User", "Accounts Manager"]),
	("Collected", "Collected", 40, "#22C55E", 0, 0, ["Accounts User", "Accounts Manager"]),
]


def make_billing():
	for title, description in BILLING_STAGE_TYPES:
		if not frappe.db.exists("Eye Billing Stage Type", title):
			_insert({"doctype": "Eye Billing Stage Type", "title": title, "description": description})
	for title, stage_type, order, color, can_start, default, roles in BILLING_STAGES:
		if frappe.db.exists("Billing Stage", title):
			continue
		_insert(
			{
				"doctype": "Billing Stage",
				"title": title,
				"stage_type": stage_type,
				"sequence": order,
				"color": color,
				"can_start_here": can_start,
				"is_default": default,
				"roles": [{"role": r} for r in roles if frappe.db.exists("Role", r)],
			}
		)


# ---------------------------------------------------------------- boards


def make_boards():
	from eye_crm.eye.board import make_board

	make_board(
		"Opportunity",
		"Deals",
		"title",
		["customer_name", "opportunity_amount", "expected_closing"],
		"Eye Deals",
	)
	make_board(
		"Billing Request",
		"Billing",
		"title",
		["customer_name", "total", "expected_date", "invoice_number"],
		"Eye Billing",
	)


# ---------------------------------------------------------------- notifications

ACCOUNTS = [{"receiver_by_role": "Accounts Manager"}, {"receiver_by_role": "Accounts User"}]

# in the bell (System Notification); each can be changed, sent by email too, or turned off from the
# desk (Notification). A billing request's notifications follow its stage's type: the request
# announces each stage it enters (Event: Method, eye_stage_changed), its first one included.
NOTIFICATIONS = [
	{
		"name": "Deal Needs Approval",
		"module": "Eye Deals",
		"document_type": "Opportunity",
		"event": "Value Change",
		"value_changed": "eye_approval_status",
		"condition": 'doc.eye_approval_status == "Pending"',
		"subject": "{{ doc.title }} needs approval",
		"message": "Deal {{ doc.name }} for {{ doc.customer_name }} is waiting for your decision.",
		"recipients": ACCOUNTS,
	},
	{
		"name": "Deal Approval Decided",
		"module": "Eye Deals",
		"document_type": "Opportunity",
		"event": "Value Change",
		"value_changed": "eye_approval_status",
		"condition": 'doc.eye_approval_status in ("Approved", "Rejected")',
		"subject": "{{ doc.title }}: {{ doc.eye_approval_status }}",
		"message": "Deal {{ doc.name }} for {{ doc.customer_name }} is now in {{ doc.sales_stage }}.",
		"recipients": [{"receiver_by_document_field": "opportunity_owner"}],
	},
	{
		"name": "Invoice Requested",
		"module": "Eye Billing",
		"document_type": "Billing Request",
		"event": "Method",
		"method": "eye_stage_changed",
		"condition": 'doc.stage_type == "Requested"',
		"subject": "Invoice requested: {{ doc.customer_name }} · {{ doc.get_formatted('total') }}",
		"message": "{{ doc.title }}: expected on {{ doc.get_formatted('expected_date') }}.",
		"recipients": ACCOUNTS,
	},
	{
		"name": "Invoice Issued",
		"module": "Eye Billing",
		"document_type": "Billing Request",
		"event": "Method",
		"method": "eye_stage_changed",
		"condition": 'doc.stage_type == "Invoiced"',
		"subject": "Invoiced: {{ doc.title }} · {{ doc.invoice_number }}",
		"message": "{{ doc.customer_name }} · {{ doc.get_formatted('total') }}",
		"recipients": [{"receiver_by_document_field": "salesperson"}],
	},
	{
		"name": "Payment Collected",
		"module": "Eye Billing",
		"document_type": "Billing Request",
		"event": "Method",
		"method": "eye_stage_changed",
		"condition": 'doc.stage_type == "Collected"',
		"subject": "Collected: {{ doc.title }} · {{ doc.get_formatted('collected_amount') }}",
		"message": "{{ doc.customer_name }}, invoice {{ doc.invoice_number }}.",
		"recipients": [{"receiver_by_document_field": "salesperson"}],
	},
]


def make_notifications():
	for spec in NOTIFICATIONS:
		if frappe.db.exists("Notification", spec["name"]):
			continue
		recipients = [
			r
			for r in spec["recipients"]
			if not r.get("receiver_by_role") or frappe.db.exists("Role", r["receiver_by_role"])
		]
		doc = frappe.get_doc(
			{
				"doctype": "Notification",
				"enabled": 1,
				"is_standard": 0,
				"channel": "System Notification",
				"condition_type": "Python",
				**{k: v for k, v in spec.items() if k != "recipients"},
				"recipients": recipients,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert(set_name=spec["name"])


def approval_status_from_pls():
	"""A deal made before the deal kept its approval status takes its P&L's."""
	frappe.db.sql(
		"""update `tabOpportunity` o join `tabDeal PL` p on p.name = o.eye_pl
		set o.eye_approval_status = p.approval_status
		where ifnull(o.eye_approval_status, '') = '' and ifnull(p.approval_status, '') != ''"""
	)


# ---------------------------------------------------------------- Nexlify Board

FLOW_METHOD = "eye_crm.eye.board.flow"

# Nexlify Board's cards for the two boards; they read the stage types, never stage names
CARD_LAYOUTS = {
	"Opportunity": {
		"title_field": "title",
		"show_name": 1,
		"compact_numbers": 1,
		"show_stage_path": 1,
		"path_style": "Dots",
		"dedupe_actions": 1,
		"form_actions": 0,
		"hero_field": "opportunity_amount",
		"hero_note": "Cost {eye_total_cost} · Margin {eye_margin}%",
		"progress_value": "eye_invoiced_amount",
		"progress_target": "opportunity_amount",
		"progress_label": "invoiced",
		"progress_title": "Billing",
		"progress_secondary": "eye_collected_amount",
		"progress_secondary_label": "collected",
		"progress_condition": "eval:doc.eye_sales_order",
		"fields": [
			{"fieldname": "customer_name", "show_as": "Subtitle", "position": "Top"},
			{
				"fieldname": "expected_closing",
				"show_as": "Date",
				"position": "Bottom",
				"condition": "eval:!doc.eye_sales_order",
			},
			{
				"fieldname": "opportunity_owner",
				"label": "Salesperson",
				"show_as": "User",
				"position": "Bottom",
			},
		],
		"rules": [
			{
				"condition": "eval:doc.eye_below_minimum",
				"color": "#e03636",
				"badge": "Below minimum",
				"badge_theme": "red",
			},
			{
				"condition": 'eval:doc.eye_approval_status == "Pending"',
				"color": "#f59f00",
				"badge": "Waiting for approval",
				"badge_theme": "orange",
			},
			{
				"condition": 'eval:doc.eye_change_pending && doc.eye_approval_status != "Pending"',
				"color": "#f59f00",
				"badge": "Change not sent",
				"badge_theme": "orange",
			},
			{
				"condition": "eval:!doc.eye_sales_order && doc.expected_closing && doc.expected_closing < frappe.datetime.get_today()",
				"color": "#e03636",
				"badge": "Overdue",
				"badge_theme": "red",
			},
		],
		"next_steps": [
			{
				"condition": 'eval:["Pipeline", "Quotation"].includes(doc.eye_stage_type) && !doc.eye_quotation',
				"text": "Price the services and make the quotation",
				"button_label": "Open",
				"action": "form",
				"tone": "Info",
			},
			{
				"condition": 'eval:doc.eye_stage_type == "In Hand"',
				"text": "Open the project",
				"button_label": "Open Project",
				"action": "eye_open_project",
				"tone": "Warning",
			},
			{
				"condition": 'eval:["Approval", "Change Approval"].includes(doc.eye_stage_type)',
				"text": "Waiting for the approval",
				"button_label": "Review",
				"action": "form",
				"tone": "Pending",
			},
			{
				"condition": 'eval:doc.eye_stage_type == "Opened" && doc.eye_change_pending',
				"text": "Send the change for approval",
				"button_label": "Open",
				"action": "form",
				"tone": "Warning",
			},
			{
				"condition": 'eval:doc.eye_stage_type == "Opened" && !doc.eye_change_pending && flt(doc.eye_left_to_request) > 0',
				"text": "Request the next invoice",
				"button_label": "Request Invoice",
				"action": "eye_request_invoice",
				"tone": "Info",
			},
			{
				"condition": 'eval:doc.eye_stage_type == "Opened" && flt(doc.eye_left_to_request) <= 0',
				"text": "Everything is requested for invoicing",
				"tone": "Success",
			},
		],
		"checklist": [
			{"label": "Quotation", "done_when": "eval:doc.eye_quotation"},
			{"label": "Project opened", "done_when": "eval:doc.eye_sales_order"},
			{
				"label": "Invoiced {eye_invoiced_percent}%",
				"done_when": "eval:flt(doc.eye_invoiced_percent) >= 99.99",
				"only_when": "eval:doc.eye_sales_order",
			},
			{
				"label": "Collected {eye_collected_percent}%",
				"done_when": "eval:flt(doc.eye_collected_percent) >= 99.99",
				"only_when": "eval:doc.eye_sales_order",
			},
		],
		"actions": [
			{
				"label": "Request Invoice",
				"action": "eye_request_invoice",
				"condition": 'eval:doc.eye_stage_type == "Opened"',
				"style": "Primary",
			},
			{
				"label": "Open Project",
				"action": "eye_open_project",
				"condition": 'eval:["Pipeline", "Quotation", "In Hand"].includes(doc.eye_stage_type) && doc.status != "Lost"',
				"style": "Default",
			},
		],
	},
	"Billing Request": {
		"title_field": "title",
		"show_name": 1,
		"compact_numbers": 1,
		"show_stage_path": 1,
		"path_style": "Dots",
		"dedupe_actions": 1,
		"form_actions": 1,
		"hero_field": "total",
		"progress_value": "collected_amount",
		"progress_target": "total",
		"progress_label": "collected",
		"progress_title": "Payment",
		"progress_condition": 'eval:doc.stage_type == "Collected"',
		"fields": [
			{"fieldname": "customer_name", "show_as": "Subtitle", "position": "Top"},
			{
				"fieldname": "invoice_number",
				"label": "Invoice",
				"show_as": "Text",
				"position": "Top",
				"condition": "eval:doc.invoice_number",
			},
			{
				"fieldname": "expected_date",
				"label": "Expected",
				"show_as": "Date",
				"position": "Bottom",
				"condition": 'eval:["Draft", "Requested"].includes(doc.stage_type)',
			},
			{"fieldname": "salesperson", "show_as": "User", "position": "Bottom"},
		],
		"rules": [
			{
				"condition": 'eval:doc.expected_date && doc.expected_date < frappe.datetime.get_today() && ["Draft", "Requested"].includes(doc.stage_type)',
				"color": "#e03636",
				"badge": "Late",
				"badge_theme": "red",
			},
		],
		"next_steps": [
			{
				"condition": 'eval:doc.stage_type == "Draft"',
				"text": "Send it to Finance",
				"button_label": "Open",
				"action": "form",
				"tone": "Warning",
			},
			{
				"condition": 'eval:doc.stage_type == "Requested"',
				"text": "Waiting for the invoice",
				"tone": "Pending",
			},
			{
				"condition": 'eval:doc.stage_type == "Invoiced"',
				"text": "Waiting for the payment",
				"tone": "Pending",
			},
			{"condition": 'eval:doc.stage_type == "Collected"', "text": "Collected", "tone": "Success"},
		],
	},
}


def nexlify_installed():
	return "nexlify_board" in frappe.get_installed_apps() and frappe.db.exists(
		"DocType", "Nexlify Board Settings"
	)


def make_nexlify_settings():
	"""Nexlify Board, when it is installed: the move check and the Flow for the deals and requests,
	and their cards. Data on the site, made once; the app doesn't need Nexlify Board."""
	if not nexlify_installed():
		return
	settings = frappe.get_single("Nexlify Board Settings")
	have = {r.reference_doctype for r in settings.get("doctypes") or []}
	added = False
	for doctype in CARD_LAYOUTS:
		if doctype not in have:
			settings.append(
				"doctypes", {"reference_doctype": doctype, "check_moves": 1, "flow_method": FLOW_METHOD}
			)
			added = True
	if added:
		settings.flags.ignore_permissions = True
		settings.save()
	for doctype, layout in CARD_LAYOUTS.items():
		if frappe.db.exists("Board Card Layout", doctype):
			continue
		_insert(
			{
				"doctype": "Board Card Layout",
				"reference_doctype": doctype,
				"enabled": 1,
				"replace_card": 1,
				**layout,
			}
		)


def remove_nexlify_settings():
	"""Uninstalling: the app's rows in Nexlify Board Settings and its cards go with it."""
	if not nexlify_installed():
		return
	settings = frappe.get_single("Nexlify Board Settings")
	kept = [r for r in settings.get("doctypes") or [] if (r.flow_method or "").strip() != FLOW_METHOD]
	if len(kept) != len(settings.get("doctypes") or []):
		settings.set("doctypes", kept)
		settings.flags.ignore_permissions = True
		settings.save()
	for doctype in CARD_LAYOUTS:
		if not frappe.db.exists("Board Card Layout", doctype):
			continue
		# a layout made for another app's fields stays
		layout = frappe.get_doc("Board Card Layout", doctype)
		if doctype == "Billing Request" or "eye_" in frappe.as_json(layout.as_dict()):
			frappe.delete_doc("Board Card Layout", doctype, ignore_permissions=True, force=True)
