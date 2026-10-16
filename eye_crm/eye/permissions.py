"""Who sees what, on top of Frappe's own permissions (the Role Permission Manager decides).

A deal's documents follow the deal: a user whose deals are limited to their own (If Owner on the
Opportunity, in the Role Permission Manager) sees the Cost Sheets, P&Ls, Quotations, Sales Orders
and Billing Requests of those deals only. "Their own" is Frappe's: the deals they made and the ones
shared with them (the app shares a deal with its Salesperson; Frappe shares it with whoever it is
assigned to). A user who sees every deal is not limited here at all.
"""

import frappe

# doctype -> the field that names its deal
FOLLOWERS = {
	"Cost Sheet": "opportunity",
	"Deal PL": "opportunity",
	"Quotation": "opportunity",
	"Sales Order": "eye_opportunity",
	"Billing Request": "opportunity",
}


def limited_to_own_deals(user=None) -> bool:
	"""The user's read on Opportunity is If Owner only."""
	user = user or frappe.session.user
	if user == "Administrator":
		return False
	perms = frappe.permissions.get_role_permissions("Opportunity", user=user)
	return "read" in (perms.get("if_owner") or {})


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Frappe's has_permission hook: deny what belongs to a deal the user can't see."""
	user = user or frappe.session.user
	field = FOLLOWERS.get(doc.doctype)
	deal = doc.get(field) if field else None
	if not deal or not limited_to_own_deals(user):
		return True
	deal_ptype = (
		"read" if ptype in (None, "read", "select", "print", "email", "report", "export") else "write"
	)
	return bool(frappe.has_permission("Opportunity", deal_ptype, doc=deal, user=user))


def query_conditions(doctype, user=None):
	user = user or frappe.session.user
	field = FOLLOWERS.get(doctype)
	if not field or not limited_to_own_deals(user):
		return ""
	u = frappe.db.escape(user)
	return f"""(ifnull(`tab{doctype}`.`{field}`, '') = '' or `tab{doctype}`.`{field}` in (
		select o.name from `tabOpportunity` o where o.owner = {u}
		union select s.share_name from `tabDocShare` s where s.share_doctype = 'Opportunity'
			and s.`read` = 1 and (s.user = {u} or s.everyone = 1)))"""


def cost_sheet_query(user=None):
	return query_conditions("Cost Sheet", user)


def deal_pl_query(user=None):
	return query_conditions("Deal PL", user)


def quotation_query(user=None):
	return query_conditions("Quotation", user)


def sales_order_query(user=None):
	return query_conditions("Sales Order", user)


def billing_request_query(user=None):
	return query_conditions("Billing Request", user)


def has_app_permission():
	"""The Eye CRM tile on the apps screen."""
	return frappe.has_permission("Opportunity", "read")
