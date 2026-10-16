"""Opening the project.

A deal entering an Opening stage (by the Open Project button, or dragged on the board) never stays
there. Its checks run first; then, if it needs approval (Eye CRM Settings), it moves to the
Approval stage and waits, otherwise the project opens straight away: the Cost Sheet, P&L and
quotation are submitted, the Sales Order is made and the deal moves to the Opened stage.
Approve finishes the opening; Reject sends the deal back, with its reason. The deal keeps the
last approval's status (Approval), which its notifications follow.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate

from eye_crm.eye import deal as deals
from eye_crm.eye import stages

NOT_REQUIRED = "Not Required"
PENDING = "Pending"
APPROVED = "Approved"
REJECTED = "Rejected"


def approval_reasons(pl):
	s = deals.settings()
	reasons = []
	if cint(s.approve_every_opening):
		reasons.append(_("Every project opening is approved (Eye CRM Settings)."))
	if cint(s.approve_below_minimum) and pl:
		below = [line for line in pl.lines if cint(line.below_minimum)]
		if below:
			details = "; ".join(
				_("#{0} {1}: margin {2}% (minimum {3}%)").format(
					line.service_no,
					line.item_name or line.item_code,
					round(flt(line.margin), 2),
					round(flt(line.min_margin), 2),
				)
				for line in below
			)
			reasons.append(f"{s.below_minimum_message or _('Below the minimum margin.')} {details}")
	return reasons


def resolve_opening(deal):
	"""Called while a deal that enters an Opening stage is validated: where it really goes."""
	pl = deals.get_pl(deal)
	reasons = approval_reasons(pl)
	deal.flags.eye_system_move = True
	if reasons:
		deal.sales_stage = stages.stage_of_type(stages.APPROVAL)
		deal.eye_approval_status = PENDING
		deal.flags.eye_after_save = ("request_approval", reasons)
	else:
		deal.sales_stage = stages.stage_of_type(stages.OPENED)
		deal.eye_approval_status = NOT_REQUIRED
		deal.flags.eye_after_save = ("open", None)
	stages.apply_stage_fields(deal)


def request_approval(deal, reasons):
	pl = deals.get_pl(deal)
	pl.approval_status = PENDING
	pl.approval_reasons = "\n".join(reasons)
	pl.approved_by = None
	pl.approved_on = None
	pl.rejection_reason = None
	_save(pl)


def open_project(deal):
	"""Submit everything and make the Sales Order. Runs after the deal moved to the Opened stage."""
	from eye_crm.eye.quotation import latest_quotation
	from eye_crm.eye.sales_order import make_sales_order

	sheet = deals.get_cost_sheet(deal, create=True)
	if sheet.docstatus == 0:
		_submit(sheet)
	pl = deals.get_pl(deal, create=True)
	if pl.docstatus == 0:
		if pl.approval_status != APPROVED:
			pl.approval_status = NOT_REQUIRED
		pl.cost_sheet = sheet.name
		_submit(pl)
	quotation = latest_quotation(deal.name)
	if quotation and quotation.docstatus == 0:
		_submit(quotation)
	so = make_sales_order(deal, pl, quotation)
	deal.db_set({"eye_sales_order": so.name, "eye_opened_on": nowdate()}, update_modified=False)
	deals.update_summary(deal.name, pl)
	return so


def approve(deal_name):
	deal = frappe.get_doc("Opportunity", deal_name)
	pl = _pl_for_decision(deal, stages.APPROVAL)
	pl.approval_status = APPROVED
	pl.approved_by = frappe.session.user
	pl.approved_on = now_datetime()
	_save(pl)
	deal.eye_approval_status = APPROVED
	_system_move(deal, stages.stage_of_type(stages.OPENED), ("open", None))
	return deal


def reject(deal_name, reason):
	if not (reason or "").strip():
		frappe.throw(_("Write why the opening is rejected."))
	deal = frappe.get_doc("Opportunity", deal_name)
	pl = _pl_for_decision(deal, stages.APPROVAL)
	pl.approval_status = REJECTED
	pl.rejection_reason = reason
	pl.approved_by = frappe.session.user
	pl.approved_on = now_datetime()
	_save(pl)
	deal.eye_approval_status = REJECTED
	back = deals.settings().reject_stage or stages.stage_of_type(stages.IN_HAND)
	_system_move(deal, back, None)
	return deal


def _pl_for_decision(deal, stage_type):
	if deal.eye_stage_type != stage_type:
		frappe.throw(_("The deal isn't waiting for approval."))
	pl = deals.get_pl(deal)
	if not pl or pl.docstatus != 0:
		frappe.throw(_("The deal has no P&L waiting for approval."))
	if not frappe.has_permission("Deal PL", "submit", pl):
		frappe.throw(_("Approving needs Submit permission on Deal PL."), frappe.PermissionError)
	return pl


def _system_move(deal, stage, after_save):
	deal.sales_stage = stage
	deal.flags.eye_system_move = True
	deal.flags.eye_after_save = after_save
	deal.flags.ignore_permissions = True
	deal.save()


def _save(doc):
	doc.flags.ignore_permissions = True
	doc.flags.eye_system = True
	doc.save()


def _submit(doc):
	doc.flags.ignore_permissions = True
	doc.flags.eye_system = True
	doc.submit()
