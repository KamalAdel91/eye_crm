"""The checks a stage can ask for before a deal enters it (Eye Check).

Each check record names a key below; its title and message are edited on the desk, and a stage
turns it on from the Sales Stage form. A check returns the services (or other things) that fail
it: empty means it passes.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from eye_crm.eye import deal as deals


def _services(deal):
	return [] if deal.get("items") else [_("no services")]


def _costs(deal):
	sheet = deals.get_cost_sheet(deal)
	costs = deals.service_costs(sheet)
	pl = deals.get_pl(deal)
	no_cost = {cint(line.service_no) for line in (pl.get("lines") if pl else []) if cint(line.no_cost)}
	return [
		_service_label(row)
		for row in deal.get("items")
		if flt(costs.get(cint(row.eye_service_no))) <= 0 and cint(row.eye_service_no) not in no_cost
	]


def _prices(deal):
	pl = deals.get_pl(deal)
	rates = {cint(line.service_no): flt(line.rate) for line in (pl.get("lines") if pl else [])}
	return [_service_label(row) for row in deal.get("items") if rates.get(cint(row.eye_service_no), 0) <= 0]


def _quotation(deal):
	from eye_crm.eye.quotation import latest_quotation

	return [] if latest_quotation(deal.name) else [_("no quotation")]


def _quotation_matches(deal):
	from eye_crm.eye.quotation import latest_quotation

	quotation = latest_quotation(deal.name)
	if not quotation:
		return []
	pl = deals.get_pl(deal)
	if pl and quotation.eye_pl_signature != deals.signature(pl):
		return [quotation.name]
	return []


def _customer(deal):
	if deal.opportunity_from == "Customer" and deal.party_name:
		return []
	return [deal.party_name or _("no party")]


CHECKS = {
	"services": _services,
	"costs": _costs,
	"prices": _prices,
	"quotation": _quotation,
	"quotation_matches": _quotation_matches,
	"customer": _customer,
}


def _service_label(row):
	return f"#{cint(row.eye_service_no)} {row.item_name or row.item_code}"


def run_checks(deal, check_names):
	"""The checks (Eye Check names) that fail, with their messages."""
	failed = []
	for name in check_names:
		check = frappe.get_cached_doc("Eye Check", name)
		fn = CHECKS.get(check.check_key)
		if not fn:
			continue
		problems = fn(deal)
		if problems:
			message = check.message or check.title
			failed.append(
				{
					"check": check.name,
					"key": check.check_key,
					"message": f"{message} ({', '.join(str(p) for p in problems)})",
				}
			)
	return failed
