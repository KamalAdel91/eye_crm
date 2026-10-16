"""The project's Sales Order: made from the approved P&L when the project opens, and kept in line
with it after every approved change through ERPNext's Update Items (same Sales Order, its lines
matched to the services by service number)."""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, nowdate

from eye_crm.eye import deal as deals


def delivery_date():
	return add_days(nowdate(), cint(deals.settings().delivery_days) or 30)


def make_sales_order(deal, pl, quotation=None):
	"""Make and submit the Sales Order of a project that opens."""
	if quotation and quotation.docstatus == 1 and quotation.eye_pl_signature == pl.signature:
		from erpnext.selling.doctype.quotation.quotation import _make_sales_order

		so = _make_sales_order(quotation.name, ignore_permissions=True)
	else:
		so = frappe.new_doc("Sales Order")
		so.update(
			{
				"customer": deal.party_name,
				"company": deal.company,
				"currency": pl.currency,
				"conversion_rate": pl.conversion_rate,
				"ignore_pricing_rule": 1,
			}
		)
		for line in pl.lines:
			so.append("items", {"item_code": line.item_code, "eye_service_no": line.service_no})

	lines = {cint(line.service_no): line for line in pl.lines}
	date = delivery_date()
	so.transaction_date = nowdate()
	so.delivery_date = date
	so.po_no = deal.get("eye_po_no")
	so.po_date = deal.get("eye_po_date")
	so.eye_opportunity = deal.name
	so.eye_pl = pl.name
	so.ignore_pricing_rule = 1
	for row in so.items:
		line = lines.get(cint(row.eye_service_no))
		if not line:
			continue
		row.update(
			{
				"item_name": line.item_name,
				"description": line.description,
				"qty": line.qty,
				"uom": line.uom,
				"price_list_rate": line.rate,
				"discount_percentage": 0,
				"margin_rate_or_amount": 0,
				"rate": line.rate,
				"delivery_date": date,
			}
		)
	so.run_method("set_missing_values")
	so.run_method("calculate_taxes_and_totals")
	so.flags.ignore_permissions = True
	so.flags.eye_system = True
	so.insert()
	so.submit()
	return so


def has_billing(so_name) -> bool:
	"""Anything billed against the Sales Order, submitted or not, or asked for in a billing request."""
	billed = frappe.db.get_value("Sales Order", so_name, "per_billed")
	drafts = frappe.db.exists("Sales Invoice Item", {"sales_order": so_name, "docstatus": ["<", 2]})
	requested = frappe.db.exists("Billing Request", {"sales_order": so_name})
	return bool(flt(billed) or drafts or requested)


def update_sales_order(deal, pl):
	"""Bring the Sales Order in line with an approved P&L revision."""
	so_name = deal.get("eye_sales_order")
	if not so_name:
		return None
	so = frappe.get_doc("Sales Order", so_name)
	if so.docstatus != 1:
		return None

	if so.currency != pl.currency:
		if has_billing(so.name):
			frappe.throw(
				_("Sales Order {0} is already billed, so the deal's currency can't change.").format(so.name)
			)
		return remake_sales_order(deal, pl, so)

	rows = {cint(r.eye_service_no): r for r in so.items if cint(r.eye_service_no)}
	trans_items, new_numbers = [], []
	for line in sorted(pl.lines, key=lambda line: cint(line.service_no)):
		row = rows.get(cint(line.service_no))
		item = {
			"item_code": line.item_code,
			"qty": line.qty,
			"rate": line.rate,
			"uom": line.uom,
			"description": line.description,
			"delivery_date": str(row.delivery_date) if row and row.delivery_date else delivery_date(),
			"conversion_factor": row.conversion_factor if row else 1,
		}
		if row:
			item["docname"] = row.name
		else:
			new_numbers.append(cint(line.service_no))
		trans_items.append(item)

	from erpnext.controllers.accounts_controller import update_child_qty_rate

	# the approval is the permission for this; ERPNext checks the user's own
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		update_child_qty_rate("Sales Order", json.dumps(trans_items), so.name)
	finally:
		frappe.set_user(user)

	so.reload()
	unnumbered = [r for r in so.items if not cint(r.eye_service_no)]
	for row, number in zip(unnumbered, new_numbers, strict=False):
		row.db_set("eye_service_no", number, update_modified=False)
	so.db_set("eye_pl", pl.name, update_modified=False)
	return so


def remake_sales_order(deal, pl, so):
	"""A new currency: the old Sales Order is cancelled and the project gets a new one."""
	so.flags.ignore_permissions = True
	so.cancel()
	new = make_sales_order(deal, pl)
	deal.db_set("eye_sales_order", new.name, update_modified=False)
	return new
