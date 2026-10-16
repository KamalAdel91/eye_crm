"""The deal (Opportunity), as Eye CRM extends it (hooks: extend_doctype_class)."""

import frappe
from frappe import _
from frappe.utils import cint, flt

from eye_crm.eye import deal as deals
from eye_crm.eye import stages


class EyeOpportunity:
	def validate(self):
		super().validate()
		if self.flags.get("eye_discarding"):
			stages.apply_stage_fields(self)
			return
		deals.fill_services(self)
		deals.number_services(self)
		self.eye_validate_stage()
		self.eye_validate_services()

	def eye_validate_stage(self):
		before = self.get_doc_before_save()
		old_stage = before.sales_stage if before else None
		if old_stage == self.sales_stage and not self.is_new():
			stages.apply_stage_fields(self)
			return

		stage = stages.apply_stage_fields(self)
		if self.flags.get("eye_system_move") or not stage:
			return
		stages.check_move(self, old_stage)
		if stage.type == stages.OPENING:
			from eye_crm.eye.opening import resolve_opening

			resolve_opening(self)
		elif stage.type == stages.QUOTATION and cint(deals.settings().auto_quotation):
			self.flags.eye_after_save = ("quotation", None)

	def eye_validate_services(self):
		"""After the project opened, a financial change to the services goes into a revision; while
		the deal waits for an approval, they can't change at all."""
		if self.is_new():
			return
		pl = deals.get_pl(self)
		if not pl:
			return
		approved = {
			cint(line.service_no): (line.item_code or "", flt(line.qty), line.uom or "") for line in pl.lines
		}
		current = deals.services_snapshot(self, financial_only=True)
		same_money = pl.currency == self.currency and flt(pl.conversion_rate) == flt(self.conversion_rate)
		if approved == current and same_money:
			self.eye_note_free_change(pl)
			return
		if self.eye_stage_type in stages.LOCKED_TYPES and not self.flags.get("eye_system_move"):
			frappe.throw(
				_("The deal is waiting for approval: its services can't change until it is decided."),
				title=_("Waiting for Approval"),
			)
		if pl.docstatus == 1:
			self.flags.eye_needs_revision = True
			self.eye_change_pending = 1
			frappe.msgprint(
				_("A financial change: it applies once it is approved (Deal > Send Change for Approval)."),
				alert=True,
				indicator="orange",
			)

	def eye_note_free_change(self, pl):
		"""After the project opened, words change without an approval: say so when they do."""
		before = self.get_doc_before_save()
		if pl.docstatus != 1 or not before:
			return
		if deals.services_snapshot(before) != deals.services_snapshot(self):
			frappe.msgprint(
				_("Saved. Descriptions, notes and attachments need no approval."),
				alert=True,
				indicator="green",
			)

	def on_update(self):
		super().on_update()
		self.eye_share_with_salesperson()
		if self.flags.get("eye_discarding"):
			return
		if self.flags.get("eye_needs_revision"):
			from eye_crm.eye.changes import working_revision

			working_revision(self)
		deals.sync_deal(self)
		action, arg = self.flags.get("eye_after_save") or (None, None)
		self.flags.eye_after_save = None
		self.flags.eye_system_move = False
		if action == "quotation":
			from eye_crm.eye.quotation import latest_quotation, make_quotation

			if not latest_quotation(self.name):
				make_quotation(self, system=True)
		elif action == "request_approval":
			from eye_crm.eye.opening import request_approval

			request_approval(self, arg)
		elif action == "open":
			from eye_crm.eye.opening import open_project

			open_project(self)

	def on_trash(self):
		if getattr(super(), "on_trash", None):
			super().on_trash()
		# its draft Cost Sheet and P&L are part of it; a submitted one keeps the deal (Frappe's links)
		for doctype in ("Deal PL", "Cost Sheet"):
			for name in frappe.get_all(
				doctype, filters={"opportunity": self.name, "docstatus": 0}, pluck="name"
			):
				frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)

	def eye_share_with_salesperson(self):
		"""Sales Users see their own deals and the ones shared with them: the Salesperson gets it."""
		before = self.get_doc_before_save()
		old = before.opportunity_owner if before else None
		new = self.opportunity_owner
		flags = {"ignore_share_permission": True, "ignore_permissions": True}
		if new and new != old and new != self.owner:
			frappe.share.add_docshare(self.doctype, self.name, new, write=1, flags=flags)
		if old and old not in (new, self.owner):
			frappe.share.remove(self.doctype, self.name, old, flags=flags)
