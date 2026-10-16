"""Quotations come from the deal's P&L: the same services, at the P&L's prices.

A deal entering a Quotation stage gets one (a Draft, Full), when Eye CRM Settings says so. After
that, Update Quotation makes the next one: Full, or Changes Only (just what changed since the last
quotation). The new one supersedes the last draft of its type; a submitted quotation is never
superseded, because it went to the customer.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, nowdate

from eye_crm.eye import deal as deals

FULL = "Full"
CHANGES_ONLY = "Changes Only"


def latest_quotation(deal_name, quotation_type=None):
	"""The deal's newest quotation that is still current (not cancelled, not superseded)."""
	filters = {"opportunity": deal_name, "docstatus": ["<", 2], "eye_superseded": 0}
	if quotation_type:
		filters["eye_quotation_type"] = quotation_type
	name = frappe.db.get_value("Quotation", filters, "name", order_by="creation desc")
	return frappe.get_doc("Quotation", name) if name else None


def make_quotation(deal, quotation_type=FULL, system=False):
	"""A new quotation for the deal, from its P&L."""
	if not system and not frappe.has_permission("Quotation", "create"):
		frappe.throw(_("You need permission to create a Quotation."), frappe.PermissionError)
	pl = deals.get_pl(deal)
	if not pl or not pl.get("lines"):
		frappe.throw(_("Add the deal's services first."))
	unpriced = [f"#{line.service_no}" for line in pl.lines if flt(line.rate) <= 0]
	if unpriced:
		frappe.throw(_("Set the prices of services {0} in the P&L first.").format(", ".join(unpriced)))

	previous = latest_quotation(deal.name)
	lines = {cint(line.service_no): line for line in pl.lines}
	if quotation_type == CHANGES_ONLY:
		if not previous:
			frappe.throw(_("There is no quotation yet to show changes against: make a Full one."))
		before = {cint(r.eye_service_no): r for r in previous.items}
		changed = [
			no
			for no, line in lines.items()
			if no not in before
			or flt(before[no].qty) != flt(line.qty)
			or flt(before[no].rate) != flt(line.rate)
			or (before[no].description or "").strip() != (line.description or "").strip()
			or before[no].item_code != line.item_code
		]
		if not changed:
			frappe.throw(_("Nothing changed since {0}.").format(previous.name))
		numbers = set(changed)
	else:
		numbers = set(lines)

	from erpnext.crm.doctype.opportunity.opportunity import make_quotation as erpnext_make_quotation

	quotation = erpnext_make_quotation(deal.name)
	# the mapper keeps the deal's order: each row is the service at the same place
	for row, service in zip(quotation.items, deal.items, strict=False):
		row.eye_service_no = cint(service.eye_service_no)
	quotation.set("items", [r for r in quotation.items if cint(r.eye_service_no) in numbers])
	quotation.ignore_pricing_rule = 1
	for row in quotation.items:
		line = lines[cint(row.eye_service_no)]
		row.qty = line.qty
		row.uom = line.uom
		row.description = line.description
		row.eye_hide_in_pdf = line.hide_in_pdf
		row.price_list_rate = line.rate
		row.discount_percentage = 0
		row.margin_rate_or_amount = 0
		row.rate = line.rate

	s = deals.settings()
	quotation.update(
		{
			"opportunity": deal.name,
			"title": deal.title or deal.customer_name,
			"transaction_date": nowdate(),
			"valid_till": add_days(nowdate(), cint(s.quotation_valid_days) or 30),
			"currency": deal.currency,
			"conversion_rate": deal.conversion_rate,
			"eye_quotation_type": quotation_type,
			"eye_revision_of": previous.name if previous else None,
			"eye_pl": pl.name,
			"eye_pl_signature": pl.signature,
			"eye_prepared_by": frappe.utils.get_fullname(deal.opportunity_owner)
			if deal.opportunity_owner
			else None,
		}
	)
	if s.default_terms and not quotation.tc_name:
		from erpnext.setup.doctype.terms_and_conditions.terms_and_conditions import (
			get_terms_and_conditions,
		)

		quotation.tc_name = s.default_terms
		quotation.terms = get_terms_and_conditions(s.default_terms, quotation.as_dict())
	quotation.flags.eye_system = True
	quotation.flags.ignore_permissions = system
	quotation.run_method("set_missing_values")
	quotation.run_method("calculate_taxes_and_totals")
	quotation.insert()

	if previous and previous.docstatus == 0 and (previous.eye_quotation_type or FULL) == quotation_type:
		previous.db_set("eye_superseded", 1)
	deal.db_set("eye_quotation", quotation.name, update_modified=False)
	return quotation
