"""The deal's Connections: its Cost Sheets and P&Ls, its quotations and Sales Order, its billing."""

from frappe import _


def opportunity(data):
	data.setdefault("non_standard_fieldnames", {})["Sales Order"] = "eye_opportunity"
	rest = [i for t in data.get("transactions", []) for i in t.get("items", []) if i != "Quotation"]
	data["transactions"] = [
		{"label": _("Deal"), "items": ["Cost Sheet", "Deal PL"]},
		{"label": _("Selling"), "items": ["Quotation", "Sales Order"]},
		{"label": _("Billing"), "items": ["Billing Request"]},
	] + ([{"label": _("Buying"), "items": rest}] if rest else [])
	return data
