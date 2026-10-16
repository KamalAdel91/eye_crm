# Copyright (c) 2026, Kamal Adel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from eye_crm.eye import deal as deals
from eye_crm.eye_deals.doctype.cost_sheet.cost_sheet import check_deal_unlocked, check_one_per_deal


class DealPL(Document):
	def before_insert(self):
		check_one_per_deal(self)

	def validate(self):
		if not self.flags.get("eye_system"):
			check_deal_unlocked(frappe.get_doc("Opportunity", self.opportunity), self)
		deals.price_pl(self)

	def before_submit(self):
		if not self.flags.get("eye_system"):
			frappe.throw(
				_(
					"A P&L is submitted when its project opens or its change is approved: use the deal's actions."
				)
			)

	def on_update(self):
		# before the project opens, the deal shows its draft P&L's numbers
		if self.docstatus == 0 and not self.previous_revision:
			deals.update_summary(self.opportunity, self)

	def on_submit(self):
		deals.update_summary(self.opportunity, self)
