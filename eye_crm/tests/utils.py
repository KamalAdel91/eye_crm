"""Records the tests need, made the way a user would make them."""

import frappe
from frappe.utils import nowdate

PREFIX = "_Test Eye"


def company():
	return frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name")[0]


def currency():
	return frappe.get_cached_value("Company", company(), "default_currency")


def ensure(doctype, name, values, name_field=None):
	if frappe.db.exists(doctype, name):
		return frappe.get_doc(doctype, name)
	doc = frappe.get_doc({"doctype": doctype, **values})
	if name_field:
		doc.set(name_field, name)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def make_item(code, sales=True, min_margin=None, purchase=False):
	group = (
		"Services"
		if frappe.db.exists("Item Group", "Services")
		else frappe.db.get_value("Item Group", {"is_group": 0})
	)
	values = {
		"item_code": code,
		"item_name": code,
		"item_group": group,
		"stock_uom": "Nos",
		"is_stock_item": 0,
		"is_sales_item": int(sales),
		"is_purchase_item": int(purchase),
	}
	if sales:
		values["eye_requires_min_margin"] = "Yes" if min_margin else "No"
		if min_margin:
			values["eye_min_margin"] = min_margin
	return ensure("Item", code, values)


def make_customer(name=f"{PREFIX} Customer"):
	group = frappe.db.get_value("Customer Group", {"is_group": 0}) or "All Customer Groups"
	territory = frappe.db.get_value("Territory", {"is_group": 0}) or "All Territories"
	return ensure(
		"Customer",
		name,
		{"customer_name": name, "customer_group": group, "territory": territory, "customer_type": "Company"},
	)


def make_exchange_rates():
	local = currency()
	for frm, to, rate in (("USD", local, 50.0), (local, "USD", 0.02)):
		if frm == to:
			continue
		if not frappe.db.exists("Currency Exchange", {"from_currency": frm, "to_currency": to}):
			ensure(
				"Currency Exchange",
				f"{frm}-{to}",
				{
					"date": "2026-01-01",
					"from_currency": frm,
					"to_currency": to,
					"exchange_rate": rate,
					"for_buying": 1,
					"for_selling": 1,
				},
			)


def make_user(email, roles):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		)
		user.flags.ignore_permissions = True
		user.insert()
	user.add_roles(*roles)
	return user


def items():
	return {
		"booth": make_item(f"{PREFIX} Booth", min_margin=30),
		"print": make_item(f"{PREFIX} Printing"),
		"wood": make_item(f"{PREFIX} Wood", sales=False, purchase=True),
		"labor": make_item(f"{PREFIX} Labor", sales=False, purchase=True),
	}


def make_deal(services, currency_="USD", rate=50.0, party=None, **values):
	deal = frappe.get_doc(
		{
			"doctype": "Opportunity",
			"opportunity_from": "Customer",
			"party_name": party or make_customer().name,
			"company": company(),
			"currency": currency_,
			"conversion_rate": rate,
			"transaction_date": nowdate(),
			"title": f"{PREFIX} Deal",
			"items": [{"item_code": code, "qty": qty} for code, qty in services],
			**values,
		}
	)
	deal.insert()
	return deal


def add_costs(deal, lines, sheet_currency=None, deal_rate=None):
	"""lines: (service_no, item_code, qty, unit cost[, currency, exchange rate])"""
	deal.reload()
	sheet = frappe.get_doc("Cost Sheet", deal.eye_cost_sheet)
	if sheet_currency:
		sheet.currency = sheet_currency
	if deal_rate:
		sheet.deal_exchange_rate = deal_rate
	for line in lines:
		no, code, qty, rate, *rest = line
		row = {"service_no": no, "item_code": code, "qty": qty, "rate": rate}
		if rest:
			row["line_currency"] = rest[0]
			row["exchange_rate"] = rest[1] if len(rest) > 1 else 0
		sheet.append("lines", row)
	sheet.save()
	return sheet


def set_margins(deal, margins: dict, rates: dict | None = None):
	deal.reload()
	pl = frappe.get_doc("Deal PL", deal.eye_pl)
	for line in pl.lines:
		if line.service_no in margins:
			line.margin = margins[line.service_no]
			line.fixed_price = 0
		if rates and line.service_no in rates:
			line.rate = rates[line.service_no]
			line.fixed_price = 1
	pl.save()
	return pl


def move(deal, stage, **values):
	deal.reload()
	deal.update(values)
	deal.sales_stage = stage
	deal.save()
	deal.reload()
	return deal
