"""A deal's documents: its services, its Cost Sheet and its P&L.

The deal is an Opportunity. Its services are the Opportunity's Items, each with a service number
that never changes. The Cost Sheet holds what each service costs, the P&L what each one sells for.
Before the project opens there is one draft of each. Once it opens they are submitted, and a
financial change makes a new revision of both, which applies when it is approved.
"""

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from eye_crm.eye import pricing


def settings():
	return frappe.get_cached_doc("Eye CRM Settings")


def is_opened(deal) -> bool:
	"""The project opened: the deal has an approved, submitted P&L."""
	return bool(approved_pl_name(deal.name))


def approved_pl_name(deal_name):
	return frappe.db.get_value(
		"Deal PL",
		{"opportunity": deal_name, "docstatus": 1, "superseded": 0},
		"name",
		order_by="revision desc",
	)


def approved_cost_sheet_name(deal_name):
	return frappe.db.get_value(
		"Cost Sheet",
		{"opportunity": deal_name, "docstatus": 1, "superseded": 0},
		"name",
		order_by="revision desc",
	)


# services


def number_services(deal):
	"""Give each new service the next number. A number is never used twice once a P&L knows it."""
	used = [cint(r.eye_service_no) for r in deal.get("items") if cint(r.eye_service_no)]
	known = 0
	if not deal.is_new():
		known = cint(
			frappe.db.sql(
				"""select max(l.service_no) from `tabPL Line` l join `tabDeal PL` p on p.name = l.parent
				where p.opportunity = %s and l.parenttype = 'Deal PL'""",
				deal.name,
			)[0][0]
		)
	last = max([known, *used]) if used or known else 0
	seen = set()
	for row in deal.get("items"):
		no = cint(row.eye_service_no)
		if not no or no in seen:
			last += 1
			row.eye_service_no = last
		seen.add(cint(row.eye_service_no))


FINANCIAL_SERVICE_FIELDS = ("item_code", "qty", "uom")


def services_snapshot(deal, financial_only=False):
	fields = (
		FINANCIAL_SERVICE_FIELDS
		if financial_only
		else (*FINANCIAL_SERVICE_FIELDS, "description", "eye_notes", "eye_attachment", "eye_hide_in_pdf")
	)
	return {
		cint(r.eye_service_no): tuple(flt(r.get(f)) if f == "qty" else (r.get(f) or "") for f in fields)
		for r in deal.get("items")
	}


# the Cost Sheet


def get_cost_sheet(deal, create=False):
	"""The deal's working Cost Sheet: its draft, or (before any change) the submitted one."""
	name = deal.get("eye_cost_sheet")
	if name and frappe.db.exists("Cost Sheet", name):
		return frappe.get_doc("Cost Sheet", name)
	if not create:
		return None
	company_currency = frappe.get_cached_value("Company", deal.company, "default_currency")
	sheet = frappe.get_doc(
		{
			"doctype": "Cost Sheet",
			"opportunity": deal.name,
			"company": deal.company,
			"currency": company_currency,
			"deal_currency": deal.currency or company_currency,
			"deal_exchange_rate": exchange_rate(company_currency, deal.currency or company_currency),
		}
	)
	sheet.flags.ignore_permissions = True
	sheet.insert()
	deal.db_set("eye_cost_sheet", sheet.name, update_modified=False)
	return sheet


def exchange_rate(from_currency, to_currency, date=None):
	if not from_currency or not to_currency or from_currency == to_currency:
		return 1.0
	from erpnext.setup.utils import get_exchange_rate

	return flt(get_exchange_rate(from_currency, to_currency, date), 9) or 1.0


def service_costs(sheet) -> dict[int, float]:
	"""What each service costs, in the deal currency."""
	if not sheet:
		return {}
	precision = 2
	by_service = {}
	for line in sheet.get("lines"):
		by_service.setdefault(cint(line.service_no), 0.0)
		by_service[cint(line.service_no)] += flt(line.base_amount)
	rate = flt(sheet.deal_exchange_rate) or 1.0
	return {no: flt(total * rate, precision) for no, total in by_service.items()}


# the P&L


def get_pl(deal, create=False):
	"""The deal's working P&L: its draft, or (before any change) the submitted one."""
	name = deal.get("eye_pl")
	if name and frappe.db.exists("Deal PL", name):
		return frappe.get_doc("Deal PL", name)
	if not create:
		return None
	pl = frappe.get_doc(
		{
			"doctype": "Deal PL",
			"opportunity": deal.name,
			"company": deal.company,
			"currency": deal.currency,
			"conversion_rate": flt(deal.conversion_rate) or 1.0,
			"cost_sheet": deal.get("eye_cost_sheet"),
		}
	)
	sync_pl(pl, deal, get_cost_sheet(deal))
	pl.flags.ignore_permissions = True
	pl.flags.eye_system = True
	pl.insert()
	deal.db_set("eye_pl", pl.name, update_modified=False)
	return pl


def sync_pl(pl, deal, sheet):
	"""Bring the P&L's lines in line with the deal's services and the Cost Sheet's costs."""
	costs = service_costs(sheet)
	existing = {cint(line.service_no): line for line in pl.get("lines")}
	default_margin = flt(settings().default_margin)
	lines = []
	for row in sorted(deal.get("items"), key=lambda r: cint(r.eye_service_no)):
		no = cint(row.eye_service_no)
		line = existing.get(no)
		item = (
			frappe.get_cached_value(
				"Item", row.item_code, ["eye_requires_min_margin", "eye_min_margin"], as_dict=True
			)
			or {}
		)
		requires_min = item.get("eye_requires_min_margin") == "Yes"
		min_margin = flt(item.get("eye_min_margin")) if requires_min else 0
		if not line:
			line = frappe._dict(margin=max(default_margin, min_margin))
		line.update(
			{
				"service_no": no,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"description": row.description,
				"qty": flt(row.qty) or 1,
				"uom": row.uom,
				"notes": row.get("eye_notes"),
				"attachment": row.get("eye_attachment"),
				"hide_in_pdf": cint(row.get("eye_hide_in_pdf")),
				"cost": costs.get(no, 0.0),
				"requires_min_margin": cint(requires_min),
				"min_margin": min_margin,
			}
		)
		lines.append(line)
	pl.set("lines", [line if hasattr(line, "doctype") else dict(line) for line in lines])
	pl.cost_sheet = sheet.name if sheet else pl.cost_sheet
	pl.currency = deal.currency
	pl.conversion_rate = flt(deal.conversion_rate) or 1.0
	return pl


def price_pl(pl):
	"""Price every line and total the P&L. Called by the P&L's validate."""
	precision = 2
	for line in pl.get("lines"):
		if line.no_cost and flt(line.cost) > 0:
			frappe.throw(
				_("Service #{0} has costs in the Cost Sheet, so it can't be marked No Cost.").format(
					line.service_no
				)
			)
		if flt(line.cost) <= 0 and flt(line.rate) > 0:
			# a price typed for a service with no cost stays when costs come
			line.fixed_price = 1
		driver = "rate" if (cint(line.fixed_price) or flt(line.cost) <= 0) else "margin"
		priced = pricing.price_line(line.cost, line.qty, line.margin, line.rate, driver, precision)
		line.unit_cost = priced["unit_cost"]
		line.margin = priced["margin"]
		line.rate = priced["rate"]
		line.amount = priced["amount"]
		line.profit = priced["profit"]
		line.below_minimum = cint(
			cint(line.requires_min_margin)
			and pricing.is_below_minimum(priced["actual_margin"], line.min_margin)
		)
	total = pricing.totals([line.as_dict() for line in pl.get("lines")], precision)
	pl.update(total)
	pl.base_total_selling = flt(total["total_selling"] * (flt(pl.conversion_rate) or 1.0), precision)
	pl.below_minimum = cint(any(cint(line.below_minimum) for line in pl.get("lines")))


def signature(pl) -> str:
	"""What a quotation copied from the P&L: a quotation whose signature differs is out of date."""
	if not pl:
		return ""
	data = [pl.currency] + [
		[
			cint(line.service_no),
			line.item_code,
			flt(line.qty),
			line.uom or "",
			flt(line.rate),
			(line.description or "").strip(),
			cint(line.hide_in_pdf),
		]
		for line in sorted(pl.get("lines"), key=lambda line: cint(line.service_no))
	]
	return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def update_summary(deal_name, pl):
	"""The deal's own numbers (Selling, Cost, Profit, Margin) from the P&L that counts: the draft
	before the project opens, the approved one after."""
	frappe.db.set_value(
		"Opportunity",
		deal_name,
		{
			"opportunity_amount": pl.total_selling,
			"base_opportunity_amount": pl.base_total_selling,
			"eye_total_cost": pl.total_cost,
			"eye_total_profit": pl.total_profit,
			"eye_margin": pl.margin,
			"eye_below_minimum": pl.below_minimum,
		},
		update_modified=False,
	)


def sync_deal(deal):
	"""After a deal is saved: its draft P&L follows its services and costs."""
	if not deal.get("items"):
		return
	sheet = get_cost_sheet(deal, create=True)
	if sheet.docstatus == 0:
		sync_cost_sheet(sheet, deal)
	pl = get_pl(deal, create=True)
	if pl.docstatus == 0:
		sync_pl(pl, deal, sheet)
		pl.flags.ignore_permissions = True
		pl.flags.eye_system = True
		pl.save()


def sync_cost_sheet(sheet, deal):
	"""The Cost Sheet follows the deal: its currency, and its services (a removed service's costs go
	with it)."""
	numbers = {cint(r.eye_service_no): r.item_code for r in deal.get("items")}
	changed = False
	kept = []
	for line in sheet.get("lines"):
		if cint(line.service_no) in numbers:
			if line.service_item != numbers[cint(line.service_no)]:
				line.service_item = numbers[cint(line.service_no)]
				changed = True
			kept.append(line)
		else:
			changed = True
	if len(kept) != len(sheet.get("lines")):
		removed = len(sheet.get("lines")) - len(kept)
		sheet.set("lines", kept)
		frappe.msgprint(
			_("{0} cost line(s) of removed services were taken off the Cost Sheet.").format(removed),
			alert=True,
		)
	if sheet.deal_currency != deal.currency:
		sheet.deal_currency = deal.currency
		sheet.deal_exchange_rate = exchange_rate(sheet.currency, deal.currency)
		changed = True
	if changed:
		sheet.flags.ignore_permissions = True
		sheet.flags.eye_system = True
		sheet.save()
