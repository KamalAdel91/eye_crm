"""What the deal form calls. Every action checks the Frappe permission it stands for:

costs                Write on Cost Sheet, and on the deal
prices               Write on Deal PL, and on the deal
approve / reject     Submit on Deal PL
quotation            Create on Quotation
moving the deal      Write on the deal, and the stage's roles
billing              Create on Billing Request, and Write on the deal (eye_crm.eye.billing)
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from eye_crm.eye import billing, changes, opening, stages
from eye_crm.eye import deal as deals
from eye_crm.eye.quotation import FULL, make_quotation


def _deal(name, ptype="read"):
	deal = frappe.get_doc("Opportunity", name)
	deal.check_permission(ptype)
	return deal


def _json(value):
	return json.loads(value) if isinstance(value, str) else value


def _list(doctype, **kwargs):
	"""frappe.get_list, or nothing for a user who can't read the DocType (the rest still shows)."""
	return frappe.get_list(doctype, **kwargs) if frappe.has_permission(doctype, "read") else []


@frappe.whitelist()
def deal_view(deal):
	"""Everything the deal's Cost Sheet, P&L and Quotations tabs show, with what the user may do."""
	deal = _deal(deal)
	sheet = deals.get_cost_sheet(deal)
	pl = deals.get_pl(deal)
	approved_name = deals.approved_pl_name(deal.name)
	quotations = _list(
		"Quotation",
		filters={"opportunity": deal.name},
		fields=[
			"name",
			"docstatus",
			"status",
			"transaction_date",
			"valid_till",
			"currency",
			"net_total",
			"grand_total",
			"eye_quotation_type",
			"eye_revision_of",
			"eye_superseded",
			"eye_pl_signature",
		],
		order_by="creation desc",
	)
	stage_type = deal.eye_stage_type
	edits_deal = bool(frappe.has_permission("Opportunity", "write", deal))
	return {
		"cost_sheet": sheet.as_dict() if sheet else None,
		"pl": pl.as_dict() if pl else None,
		"approved_pl": approved_name,
		"revisions": _list(
			"Deal PL",
			filters={"opportunity": deal.name},
			fields=[
				"name",
				"revision",
				"docstatus",
				"superseded",
				"approval_status",
				"total_selling",
				"margin",
			],
			order_by="revision desc",
		),
		"quotations": quotations,
		"stage_type": stage_type,
		"below_minimum_message": deals.settings().below_minimum_message,
		"locked": stage_type in stages.LOCKED_TYPES,
		"billing": billing.view(deal) if deal.get("eye_sales_order") else None,
		"can": {
			"costs": edits_deal
			and (
				bool(sheet and frappe.has_permission("Cost Sheet", "write", sheet))
				or (not sheet and bool(frappe.has_permission("Cost Sheet", "create")))
			),
			"prices": edits_deal and bool(pl and frappe.has_permission("Deal PL", "write", pl)),
			"decide": bool(pl and frappe.has_permission("Deal PL", "submit", pl)),
			"quote": bool(frappe.has_permission("Quotation", "create")),
			"move": edits_deal,
		},
	}


@frappe.whitelist()
def what_is_missing(doc, stage):
	"""What the deal (as it is in the form, unsaved) still needs to enter `stage`."""
	doc = frappe.get_doc(_json(doc))
	old = None
	if not doc.is_new():
		saved = frappe.get_doc("Opportunity", doc.name)
		saved.check_permission("read")
		old = stages.get_stage(saved.sales_stage)
	info = stages.get_stage(stage)
	if not info:
		return {"missing_fields": [], "failed_checks": []}
	blocked = stages.blocked_move(doc, old, info)
	if blocked:
		return {"missing_fields": [], "failed_checks": [{"check": "move", "message": blocked}]}
	return stages.what_is_missing(doc, info)


@frappe.whitelist()
def save_costs(deal, lines, currency=None, deal_exchange_rate=None):
	"""Replace the lines of the deal's working Cost Sheet (a new revision after the project opened)."""
	deal = _deal(deal, "write")
	if deal.eye_stage_type in stages.LOCKED_TYPES:
		frappe.throw(_("The deal is waiting for approval: its costs can't change now."))
	sheet = _working(deal)[0] or deals.get_cost_sheet(deal, create=True)
	sheet.check_permission("write")
	if currency:
		sheet.currency = currency
	if deal_exchange_rate is not None:
		sheet.deal_exchange_rate = flt(deal_exchange_rate)
	fields = (
		"service_no",
		"item_code",
		"description",
		"supplier",
		"qty",
		"uom",
		"rate",
		"line_currency",
		"exchange_rate",
	)
	sheet.set("lines", [{f: line.get(f) for f in fields} for line in _json(lines)])
	sheet.save()
	return deal_view(deal.name)


@frappe.whitelist()
def save_prices(deal, lines, currency=None, conversion_rate=None):
	"""Margins, typed prices and No Cost, per service; and the deal's currency."""
	deal = _deal(deal, "write")
	if deal.eye_stage_type in stages.LOCKED_TYPES:
		frappe.throw(_("The deal is waiting for approval: its prices can't change now."))
	if currency and (currency != deal.currency or flt(conversion_rate) != flt(deal.conversion_rate)):
		deal.currency = currency
		deal.conversion_rate = flt(conversion_rate) or deal.conversion_rate
		deal.save()
		deal.reload()
	sheet, pl = _working(deal)
	if sheet and sheet.docstatus == 0 and sheet.deal_currency != deal.currency:
		sheet.deal_currency = deal.currency
		sheet.deal_exchange_rate = deals.exchange_rate(sheet.currency, deal.currency)
		sheet.save()
		pl.reload()
	pl.check_permission("write")
	given = {cint(line.get("service_no")): line for line in _json(lines)}
	for line in pl.lines:
		new = given.get(cint(line.service_no))
		if not new:
			continue
		line.no_cost = cint(new.get("no_cost"))
		line.fixed_price = cint(new.get("fixed_price"))
		line.margin = flt(new.get("margin"))
		line.rate = flt(new.get("rate"))
	pl.currency = deal.currency
	pl.conversion_rate = deal.conversion_rate
	pl.save()
	return deal_view(deal.name)


def _working(deal):
	"""The drafts to change: before the project opens, its drafts; after, a revision."""
	if deals.is_opened(deal):
		return changes.working_revision(deal)
	return deals.get_cost_sheet(deal, create=True), deals.get_pl(deal, create=True)


@frappe.whitelist()
def update_quotation(deal, quotation_type=FULL):
	deal = _deal(deal)
	if not frappe.has_permission("Quotation", "create"):
		frappe.throw(_("Making a quotation needs Create permission on Quotation."), frappe.PermissionError)
	quotation = make_quotation(deal, quotation_type or FULL)
	return quotation.name


@frappe.whitelist()
def open_project(deal, values=None):
	"""The Open Project button: the deal enters the Opening stage, which decides where it goes.
	`values`: the fields the stage asked for, typed in its dialog (from a board)."""
	deal = _deal(deal, "write")
	stage = stages.stage_of_type(stages.OPENING)
	typed, info = _json(values) or {}, stages.get_stage(stage)
	# only what the stage asks for; an answer can ask for another field (a PO needs its number)
	for _i in range(5):
		asked = {f["fieldname"] for f in stages.what_is_missing(deal, info)["missing_fields"]}
		answers = {k: v for k, v in typed.items() if k in asked}
		if not answers:
			break
		deal.update(answers)
	deal.sales_stage = stage
	deal.save()
	return deal.sales_stage


@frappe.whitelist()
def approve(deal):
	deal = _deal(deal)
	if deal.eye_stage_type == stages.CHANGE_APPROVAL:
		changes.approve(deal.name)
	else:
		opening.approve(deal.name)
	return frappe.db.get_value("Opportunity", deal.name, "sales_stage")


@frappe.whitelist()
def reject(deal, reason):
	deal = _deal(deal)
	if deal.eye_stage_type == stages.CHANGE_APPROVAL:
		changes.reject(deal.name, reason)
	else:
		opening.reject(deal.name, reason)
	return frappe.db.get_value("Opportunity", deal.name, "sales_stage")


@frappe.whitelist()
def send_change(deal, reason):
	deal = _deal(deal)
	changes.send_for_approval(deal.name, reason)
	return frappe.db.get_value("Opportunity", deal.name, "sales_stage")


@frappe.whitelist()
def discard_change(deal):
	deal = _deal(deal)
	changes.discard(deal.name)
	return True
