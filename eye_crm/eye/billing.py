"""Billing: Sales asks Finance to invoice part of an open project; Finance issues the invoice and
records the payment.

A Billing Request is for the project's Sales Order: an amount per service, before taxes, never more
than what the deal's other requests leave of that service. Its stage (Billing Stage) says where it
is. The app knows a stage by its type (Eye Billing Stage Type), never by its name:

	Draft       Sales is preparing it
	Requested   sent to Finance
	Invoiced    the invoice is issued: its number and date are on the request
	Collected   the customer paid: the amount collected is on the request

Who may move a request into or out of a stage is set on the Billing Stage. What a request needs in
a stage comes from its fields' Mandatory Depends On (by doc.stage_type), as for deals, and it holds
on every save. Once its invoice is issued, a request's amounts are fixed and it can't be deleted.

The deal keeps the totals: Requested, Invoiced, Collected and Left to Request. A change after the
project opened can't take a service below what its requests already ask for.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, fmt_money, nowdate

from eye_crm.eye import stages
from eye_crm.eye.stages import StageError

DRAFT = "Draft"
REQUESTED = "Requested"
INVOICED = "Invoiced"
COLLECTED = "Collected"

# a request starts before its invoice exists
START_TYPES = (DRAFT, REQUESTED)
# Finance has it
SENT_TYPES = (REQUESTED, INVOICED, COLLECTED)
# its invoice exists: the amounts are fixed and the request stays
ISSUED_TYPES = (INVOICED, COLLECTED)

TOLERANCE = 0.005


# ---------------------------------------------------------------- stages


def get_stage(name):
	if not name:
		return None
	stage = frappe.get_cached_doc("Billing Stage", name)
	return frappe._dict(
		name=stage.name,
		type=stage.stage_type,
		order=cint(stage.sequence),
		can_start=cint(stage.can_start_here),
		is_default=cint(stage.is_default),
		roles=[r.role for r in stage.get("roles") or []],
	)


def start_stages():
	return frappe.get_all(
		"Billing Stage", filters={"can_start_here": 1}, pluck="name", order_by="sequence asc"
	)


def default_stage():
	"""Where a new request starts: the default stage, else the first one a request can start in."""
	name = frappe.db.get_value("Billing Stage", {"is_default": 1, "can_start_here": 1}, "name")
	name = name or next(iter(start_stages()), None)
	if not name:
		frappe.throw(
			_("No Billing Stage can start a request: tick A Request Can Start Here on one."),
			title=_("Missing Stage"),
		)
	return name


def _names(values):
	return ", ".join(frappe.bold(_(v)) for v in values)


def blocked_move(request, old, new, user=None):
	"""Why the user can't move the request from stage `old` into `new` (None: they can)."""
	if request.flags.get("eye_system_move") or not new:
		return None
	if not old and not new.can_start:
		return _("A billing request starts in {0}.").format(_names(start_stages()))
	roles = set(frappe.get_roles(user))
	if old and old.name != new.name and old.roles and not set(old.roles) & roles:
		return _("Only {0} can move requests out of {1}.").format(_names(old.roles), frappe.bold(old.name))
	if new.roles and not set(new.roles) & roles:
		return _("Only {0} can move requests into {1}.").format(_names(new.roles), frappe.bold(new.name))
	return None


def missing_fields(request):
	"""What the request's stage asks for and it doesn't have; an amount of 0 is no amount."""
	return stages.missing_fields(request, zero_is_empty=True)


def what_is_missing(request, stage):
	"""The fields and checks the request still needs for `stage`, as if it were in it."""
	before = (request.billing_stage, request.stage_type)
	request.billing_stage, request.stage_type = stage.name, stage.type
	try:
		# Nexlify Board tries the save before its popup asks for the fields
		missing = [] if request.flags.get("nx_skip_required") else missing_fields(request)
	finally:
		request.billing_stage, request.stage_type = before
	failed = []
	if stage.type != DRAFT and flt(request.total) <= 0:
		failed.append({"check": "amounts", "message": _("Type the amount to invoice for a service first.")})
	return {"missing_fields": missing, "failed_checks": failed}


def check_move(request, old_stage_name, user=None):
	"""Raise StageError when the request can't be in its stage (coming from `old_stage_name`)."""
	new = get_stage(request.billing_stage)
	blocked = blocked_move(request, get_stage(old_stage_name), new, user)
	if blocked:
		raise StageError(blocked)
	problems = what_is_missing(request, new)
	if problems["missing_fields"] or problems["failed_checks"]:
		lines = [
			_("{0} is needed").format(frappe.bold(_(f["label"]))) for f in problems["missing_fields"]
		] + [c["message"] for c in problems["failed_checks"]]
		raise StageError(
			_("The request can't be in {0} yet:").format(frappe.bold(new.name))
			+ "<ul>"
			+ "".join(f"<li>{line}</li>" for line in lines)
			+ "</ul>",
			missing_fields=problems["missing_fields"],
			failed_checks=problems["failed_checks"],
		)


# ---------------------------------------------------------------- the request


def sales_order_of(deal):
	"""The project's Sales Order (submitted), or an error: billing starts when the project opens."""
	so_name = deal.get("eye_sales_order")
	if not so_name or frappe.db.get_value("Sales Order", so_name, "docstatus") != 1:
		frappe.throw(
			_("Deal {0}'s project isn't open yet: billing starts with its Sales Order.").format(
				frappe.bold(deal.name)
			),
			title=_("Project Not Open"),
		)
	return frappe.get_doc("Sales Order", so_name)


def requested_by_service(deal_name, exclude=None):
	"""What the deal's billing requests ask for, per service number (all stages)."""
	rows = frappe.db.sql(
		"""select i.service_no, sum(i.amount) from `tabBilling Request Item` i
		join `tabBilling Request` r on r.name = i.parent and i.parenttype = 'Billing Request'
		where r.opportunity = %(deal)s and r.name != %(exclude)s
		group by i.service_no""",
		{"deal": deal_name, "exclude": exclude or ""},
	)
	return {cint(no): flt(amount) for no, amount in rows}


def fill(request):
	"""What a request takes from its deal and the deal's Sales Order, and its amounts."""
	deal = frappe.get_doc("Opportunity", request.opportunity)
	so = sales_order_of(deal)
	request.customer = so.customer
	request.customer_name = deal.customer_name or so.customer_name
	request.title = deal.title
	request.salesperson = deal.opportunity_owner or deal.owner
	request.company = so.company
	request.currency = so.currency
	request.sales_order = so.name
	stage = get_stage(request.billing_stage)
	request.stage_type = stage.type if stage else None

	services = {cint(r.eye_service_no): r for r in so.items if cint(r.eye_service_no)}
	others = requested_by_service(deal.name, exclude=None if request.is_new() else request.name)
	for row in request.items:
		no = cint(row.service_no)
		line = services.get(no)
		if not line:
			frappe.throw(
				_("Row #{0}: the project's Sales Order has no service #{1}.").format(row.idx, no),
				title=_("Unknown Service"),
			)
		row.so_detail = line.name
		row.item_code = line.item_code
		row.item_name = line.item_name
		row.description = line.description
		row.so_amount = flt(line.amount, 2)
		row.requested_before = flt(others.get(no), 2)
		row.available = flt(row.so_amount - row.requested_before, 2)
		row.amount = flt(row.amount, 2)
		row.percent = flt(row.amount / row.so_amount * 100, 2) if row.so_amount else 0
	request.total = flt(sum(flt(r.amount) for r in request.items), 2)


def _amounts(doc):
	return sorted((cint(r.service_no), flt(r.amount, 2)) for r in doc.get("items") or [])


def validate_amounts(request):
	before = request.get_doc_before_save()
	if (
		before
		and before.stage_type in ISSUED_TYPES
		and request.stage_type in ISSUED_TYPES
		and _amounts(before) != _amounts(request)
	):
		frappe.throw(
			_(
				"The invoice of {0} is issued, so its amounts can't change. If it was cancelled, move the request back first."
			).format(frappe.bold(request.name)),
			title=_("Invoice Issued"),
		)
	seen = set()
	for row in request.items:
		no = cint(row.service_no)
		if no in seen:
			frappe.throw(_("Service #{0} is twice in the request.").format(no))
		seen.add(no)
		if flt(row.amount) < 0:
			frappe.throw(_("Row #{0}: the amount to invoice can't be negative.").format(row.idx))
		if flt(row.amount) > flt(row.available) + TOLERANCE:
			frappe.throw(
				_("Service #{0} {1}: {2} is more than what is left to request ({3}).").format(
					no,
					row.item_name or row.item_code,
					fmt_money(row.amount, currency=request.currency),
					fmt_money(row.available, currency=request.currency),
				),
				title=_("More Than the Service"),
			)
	if flt(request.collected_amount) < 0:
		frappe.throw(_("The amount collected can't be negative."))
	if flt(request.collected_amount) > flt(request.total) + TOLERANCE:
		frappe.throw(
			_("Collected ({0}) can't be more than the request's amount ({1}).").format(
				fmt_money(request.collected_amount, currency=request.currency),
				fmt_money(request.total, currency=request.currency),
			)
		)


def new_request(deal):
	"""A new request for the deal, not saved: every service of its Sales Order, nothing asked yet."""
	so = sales_order_of(deal)
	request = frappe.new_doc("Billing Request")
	request.opportunity = deal.name
	request.billing_stage = default_stage()
	request.expected_date = nowdate()
	for row in sorted(so.items, key=lambda r: cint(r.eye_service_no)):
		if cint(row.eye_service_no):
			request.append("items", {"service_no": cint(row.eye_service_no), "amount": 0})
	fill(request)
	return request


# ---------------------------------------------------------------- the deal


def update_deal(deal_name):
	"""The deal's billing numbers, from its requests."""
	if not deal_name:
		return
	rows = frappe.db.sql(
		"""select stage_type, sum(total) as total, sum(collected_amount) as collected
		from `tabBilling Request` where opportunity = %s group by stage_type""",
		deal_name,
		as_dict=True,
	)
	requested = sum(flt(r.total) for r in rows)
	invoiced = sum(flt(r.total) for r in rows if r.stage_type in ISSUED_TYPES)
	collected = sum(flt(r.collected) for r in rows if r.stage_type == COLLECTED)
	selling = flt(frappe.db.get_value("Opportunity", deal_name, "opportunity_amount"))

	def percent(value):
		return flt(value / selling * 100, 2) if selling else 0

	frappe.db.set_value(
		"Opportunity",
		deal_name,
		{
			"eye_requested_amount": flt(requested, 2),
			"eye_left_to_request": flt(max(selling - requested, 0), 2),
			"eye_invoiced_amount": flt(invoiced, 2),
			"eye_invoiced_percent": percent(invoiced),
			"eye_collected_amount": flt(collected, 2),
			"eye_collected_percent": percent(collected),
		},
		update_modified=False,
	)


def check_pl(pl):
	"""A change after the project opened can't take a service below what the deal's billing requests
	ask for, nor change the currency the requests are in. Called by the revision's validate."""
	currency = frappe.db.get_value("Billing Request", {"opportunity": pl.opportunity}, "currency")
	if not currency:
		return
	if pl.currency != currency:
		frappe.throw(
			_("The deal has billing requests in {0}, so its currency can't change.").format(currency),
			title=_("Billing Started"),
		)
	amounts = {cint(line.service_no): flt(line.amount) for line in pl.lines}
	names = {cint(line.service_no): line.item_name or line.item_code for line in pl.lines}
	short = [
		(no, asked)
		for no, asked in requested_by_service(pl.opportunity).items()
		if asked > amounts.get(no, 0) + TOLERANCE
	]
	if not short:
		return
	holders = {}
	for no, parent in frappe.db.sql(
		"""select i.service_no, i.parent from `tabBilling Request Item` i
		join `tabBilling Request` r on r.name = i.parent and i.parenttype = 'Billing Request'
		where r.opportunity = %s and i.amount > 0 order by r.creation""",
		pl.opportunity,
	):
		holders.setdefault(cint(no), [])
		if parent not in holders[cint(no)]:
			holders[cint(no)].append(parent)
	lines = [
		_("#{0} {1}: {2} is in billing requests ({3})").format(
			no,
			names.get(no) or _("a removed service"),
			fmt_money(asked, currency=pl.currency),
			", ".join(holders.get(no, [])),
		)
		for no, asked in sorted(short)
	]
	frappe.throw(
		_("A service can't go below what its billing requests ask for:")
		+ "<ul>"
		+ "".join(f"<li>{line}</li>" for line in lines)
		+ "</ul>"
		+ _("Lower or delete those requests first."),
		title=_("Billing Started"),
	)


# ---------------------------------------------------------------- what the forms call


def _json(value):
	return json.loads(value) if isinstance(value, str) else value


def view(deal):
	"""The deal's Billing tab: its requests, and whether the user can make one."""
	if not frappe.has_permission("Billing Request", "read"):
		return {"requests": [], "colors": {}, "can_request": False}
	requests = frappe.get_list(
		"Billing Request",
		filters={"opportunity": deal.name},
		fields=[
			"name",
			"billing_stage",
			"stage_type",
			"expected_date",
			"total",
			"currency",
			"invoice_number",
			"invoice_date",
			"collected_amount",
		],
		order_by="creation asc",
	)
	return {
		"requests": requests,
		"colors": {s.name: s.color for s in frappe.get_all("Billing Stage", fields=["name", "color"])},
		"can_request": bool(
			deal.get("eye_sales_order")
			and frappe.has_permission("Billing Request", "create")
			and frappe.has_permission("Opportunity", "write", deal)
		),
	}


@frappe.whitelist()
def get_new_request(deal):
	"""The Request Invoice dialog starts from this: the request as it would be, not saved."""
	deal = frappe.get_doc("Opportunity", deal)
	deal.check_permission("read")
	return new_request(deal).as_dict()


@frappe.whitelist()
def make_request(deal, lines, billing_stage=None, expected_date=None, notes=None):
	"""Request Invoice: a new request with the amounts typed per service (only those above zero)."""
	deal = frappe.get_doc("Opportunity", deal)
	deal.check_permission("read")
	request = new_request(deal)
	amounts = {cint(line.get("service_no")): flt(line.get("amount")) for line in _json(lines) or []}
	rows = [
		{"service_no": cint(r.service_no), "amount": amounts[cint(r.service_no)]}
		for r in request.items
		if flt(amounts.get(cint(r.service_no))) > 0
	]
	if not rows:
		frappe.throw(_("Type the amount to invoice for at least one service."))
	request.set("items", rows)
	request.billing_stage = billing_stage or request.billing_stage
	request.expected_date = expected_date or nowdate()
	request.notes = notes
	request.insert()
	return request.name


@frappe.whitelist()
def what_is_missing_for(doc, stage):
	"""What the request (as it is in the form, unsaved) still needs to enter `stage`."""
	request = frappe.get_doc(_json(doc))
	old = None
	if not request.is_new():
		saved = frappe.get_doc("Billing Request", request.name)
		saved.check_permission("read")
		old = get_stage(saved.billing_stage)
	new = get_stage(stage)
	if not new:
		return {"missing_fields": [], "failed_checks": []}
	blocked = blocked_move(request, old, new)
	if blocked:
		return {"missing_fields": [], "failed_checks": [{"check": "move", "message": blocked}]}
	return what_is_missing(request, new)
