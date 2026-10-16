# Copyright (c) 2026, Kamal Adel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from eye_crm.eye import billing, board


class BillingStage(Document):
	def validate(self):
		if cint(self.can_start_here) and self.stage_type not in billing.START_TYPES:
			frappe.throw(
				_("A request starts before its invoice exists: only a {0} stage can start one.").format(
					" / ".join(frappe.bold(_(t)) for t in billing.START_TYPES)
				)
			)
		if cint(self.is_default) and not cint(self.can_start_here):
			self.can_start_here = 1

	def on_update(self):
		if cint(self.is_default):
			# one default
			frappe.db.set_value(
				"Billing Stage", {"is_default": 1, "name": ["!=", self.name]}, "is_default", 0
			)
			frappe.clear_document_cache("Billing Stage")
		if not self.is_new() and self.has_value_changed("stage_type"):
			# the requests in it keep their stage's type, for the fields' conditions
			frappe.db.set_value(
				"Billing Request",
				{"billing_stage": self.name},
				"stage_type",
				self.stage_type,
				update_modified=False,
			)
		if self.has_value_changed("sequence") or self.has_value_changed("color"):
			board.sync_columns(
				"Billing Request", recolor=self.name if self.has_value_changed("color") else None
			)

	def after_rename(self, old, new, merge=False):
		board.rename_column("Billing Request", old, new)

	def after_delete(self):
		board.sync_columns("Billing Request")
