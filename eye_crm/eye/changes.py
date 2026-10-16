"""Financial changes after the project opened.

The approved Cost Sheet and P&L stay as they are. A change (a service added, removed or its
quantity changed; a cost; a price) goes into a new revision of both, a Draft, and the deal shows
"A Change Is Waiting". Send for Approval moves the deal to the Change Approval stage (or applies the
change at once when Eye CRM Settings doesn't ask for approval). Approve submits the revision,
updates the Sales Order and brings the deal back to the Opened stage; Reject gives it back to Sales
with the reason; Discard drops the revision and puts the services back as they were approved.
Changes that aren't financial (descriptions, notes, attachments) are saved as they are.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from eye_crm.eye import deal as deals
from eye_crm.eye import stages
from eye_crm.eye.opening import APPROVED, PENDING, REJECTED, _save, _submit, _system_move


def working_revision(deal):
	"""The draft revision of the Cost Sheet and P&L, made from the approved ones when there is none."""
	sheet = deals.get_cost_sheet(deal)
	pl = deals.get_pl(deal)
	if sheet and sheet.docstatus == 1:
		sheet = _revise(sheet)
		deal.db_set("eye_cost_sheet", sheet.name, update_modified=False)
		deal.eye_cost_sheet = sheet.name
	if pl and pl.docstatus == 1:
		pl = _revise(pl, cost_sheet=sheet.name if sheet else None)
		deal.db_set("eye_pl", pl.name, update_modified=False)
		deal.eye_pl = pl.name
	if not cint(deal.get("eye_change_pending")):
		deal.db_set("eye_change_pending", 1, update_modified=False)
		deal.eye_change_pending = 1
	return sheet, pl


def _revise(doc, cost_sheet=None):
	new = frappe.copy_doc(doc)
	# copy_doc keeps the docstatus while tests run; a revision always starts as a draft
	new.docstatus = 0
	for row in new.get_all_children():
		row.docstatus = 0
	new.revision = cint(doc.revision) + 1
	new.previous_revision = doc.name
	new.superseded = 0
	new.amended_from = None
	if doc.doctype == "Deal PL":
		new.cost_sheet = cost_sheet or doc.cost_sheet
		for field in (
			"approval_status",
			"approval_reasons",
			"approved_by",
			"approved_on",
			"rejection_reason",
			"change_reason",
		):
			new.set(field, None)
	new.flags.ignore_permissions = True
	new.flags.eye_system = True
	new.insert()
	return new


def send_for_approval(deal_name, reason):
	deal = frappe.get_doc("Opportunity", deal_name)
	_check_change(deal, "write")
	if not (reason or "").strip():
		frappe.throw(_("Write the reason for the change."))
	pl = deals.get_pl(deal)
	pl.change_reason = reason
	if not cint(deals.settings().approve_changes):
		_save(pl)
		return apply_change(deal)
	pl.approval_status = PENDING
	pl.approval_reasons = _("A financial change after the project opened.")
	pl.rejection_reason = None
	_save(pl)
	_system_move(deal, stages.stage_of_type(stages.CHANGE_APPROVAL), None)
	return deal


def approve(deal_name):
	deal = frappe.get_doc("Opportunity", deal_name)
	if deal.eye_stage_type != stages.CHANGE_APPROVAL:
		frappe.throw(_("The deal has no change waiting for approval."))
	pl = deals.get_pl(deal)
	if not frappe.has_permission("Deal PL", "submit", pl):
		frappe.throw(_("Approving needs Submit permission on Deal PL."), frappe.PermissionError)
	pl.approval_status = APPROVED
	pl.approved_by = frappe.session.user
	pl.approved_on = now_datetime()
	_save(pl)
	return apply_change(deal)


def apply_change(deal):
	from eye_crm.eye.quotation import latest_quotation
	from eye_crm.eye.sales_order import update_sales_order

	sheet = deals.get_cost_sheet(deal)
	pl = deals.get_pl(deal)
	for doc in (sheet, pl):
		if doc and doc.docstatus == 0:
			previous = doc.previous_revision
			_submit(doc)
			if previous:
				frappe.db.set_value(doc.doctype, previous, "superseded", 1, update_modified=False)
	update_sales_order(deal, pl)
	quotation = latest_quotation(deal.name)
	if quotation and quotation.docstatus == 0:
		_submit(quotation)
	deal.reload()
	deal.eye_change_pending = 0
	_system_move(deal, stages.stage_of_type(stages.OPENED), None)
	deals.update_summary(deal.name, pl)
	return deal


def reject(deal_name, reason):
	deal = frappe.get_doc("Opportunity", deal_name)
	if deal.eye_stage_type != stages.CHANGE_APPROVAL:
		frappe.throw(_("The deal has no change waiting for approval."))
	if not (reason or "").strip():
		frappe.throw(_("Write why the change is rejected."))
	pl = deals.get_pl(deal)
	if not frappe.has_permission("Deal PL", "submit", pl):
		frappe.throw(_("Rejecting needs Submit permission on Deal PL."), frappe.PermissionError)
	pl.approval_status = REJECTED
	pl.rejection_reason = reason
	pl.approved_by = frappe.session.user
	pl.approved_on = now_datetime()
	_save(pl)
	_system_move(deal, stages.stage_of_type(stages.OPENED), None)
	return deal


def discard(deal_name):
	"""Drop the change: the revision goes, and the services are put back as they were approved."""
	deal = frappe.get_doc("Opportunity", deal_name)
	_check_change(deal, "write")
	sheet = deals.get_cost_sheet(deal)
	pl = deals.get_pl(deal)
	approved_pl = frappe.get_doc("Deal PL", pl.previous_revision) if pl and pl.previous_revision else None
	approved_sheet = (
		frappe.get_doc("Cost Sheet", sheet.previous_revision) if sheet and sheet.previous_revision else None
	)
	for doc in (pl, sheet):
		if doc and doc.docstatus == 0 and doc.previous_revision:
			frappe.delete_doc(doc.doctype, doc.name, ignore_permissions=True, force=True)
	for quotation in frappe.get_all(
		"Quotation",
		filters={"opportunity": deal.name, "docstatus": 0, "eye_pl": pl.name if pl else ""},
		pluck="name",
	):
		frappe.delete_doc("Quotation", quotation, ignore_permissions=True)

	deal.reload()
	if approved_pl:
		restore_services(deal, approved_pl)
		deal.currency = approved_pl.currency
		deal.conversion_rate = approved_pl.conversion_rate
	deal.eye_pl = approved_pl.name if approved_pl else deal.eye_pl
	deal.eye_cost_sheet = approved_sheet.name if approved_sheet else deal.eye_cost_sheet
	deal.eye_change_pending = 0
	deal.flags.eye_discarding = True
	deal.flags.ignore_permissions = True
	deal.save()
	return deal


def restore_services(deal, pl):
	"""The deal's services as `pl` has them; descriptions and notes changed since are kept."""
	current = {cint(r.eye_service_no): r for r in deal.items}
	rows = []
	for line in sorted(pl.lines, key=lambda line: cint(line.service_no)):
		row = current.get(cint(line.service_no))
		if row:
			row.item_code, row.qty, row.uom = line.item_code, line.qty, line.uom
		else:
			row = frappe._dict(
				eye_service_no=line.service_no,
				item_code=line.item_code,
				item_name=line.item_name,
				description=line.description,
				qty=line.qty,
				uom=line.uom,
				eye_notes=line.notes,
				eye_attachment=line.attachment,
				eye_hide_in_pdf=line.hide_in_pdf,
			)
		rows.append(row)
	deal.set("items", [r if hasattr(r, "doctype") else dict(r) for r in rows])


def _check_change(deal, ptype):
	if not cint(deal.get("eye_change_pending")):
		frappe.throw(_("The deal has no change."))
	if deal.eye_stage_type != stages.OPENED:
		frappe.throw(_("The change is already waiting for approval."))
	pl = deals.get_pl(deal)
	if not frappe.has_permission("Deal PL", ptype, pl):
		frappe.throw(_("Changing prices needs Write permission on Deal PL."), frappe.PermissionError)
