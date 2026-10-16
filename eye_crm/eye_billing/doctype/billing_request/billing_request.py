# Copyright (c) 2026, Kamal Adel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from eye_crm.eye import billing, stages


class BillingRequest(Document):
	def before_insert(self):
		if not self.billing_stage:
			self.billing_stage = billing.default_stage()

	def validate(self):
		billing.fill(self)
		self.eye_validate_stage()
		billing.validate_amounts(self)

	def eye_validate_stage(self):
		before = self.get_doc_before_save()
		old = before.billing_stage if before else None
		if self.is_new() or old != self.billing_stage:
			billing.check_move(self, old)
			if self.stage_type in billing.SENT_TYPES and not self.sent_on:
				self.sent_on = now_datetime()
			return
		# what its stage needs holds on every save, as the form asks for it
		missing = [] if self.flags.get("nx_skip_required") else billing.missing_fields(self)
		if missing:
			raise stages.StageError(
				_("{0} is needed in {1}.").format(
					", ".join(frappe.bold(_(f["label"])) for f in missing), frappe.bold(self.billing_stage)
				),
				missing_fields=missing,
			)

	def on_update(self):
		billing.update_deal(self.opportunity)
		if self.has_value_changed("billing_stage"):
			# for Notifications (Event: Method, eye_stage_changed) and other apps' doc_events; a new
			# request counts, as it enters its first stage
			self.run_method("eye_stage_changed")

	def on_trash(self):
		if self.stage_type in billing.ISSUED_TYPES and not self.flags.get("eye_system"):
			frappe.throw(
				_(
					"The invoice of {0} is issued, so the request stays. If it was cancelled, move the request back first."
				).format(frappe.bold(self.name)),
				title=_("Invoice Issued"),
			)

	def after_delete(self):
		billing.update_deal(self.opportunity)
