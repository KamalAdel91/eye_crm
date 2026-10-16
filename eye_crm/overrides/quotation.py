"""Quotation, as Eye CRM extends it: a deal's quotation sells at the deal's P&L prices."""

import frappe
from frappe import _
from frappe.utils import cint, flt


class EyeQuotation:
	def validate(self):
		super().validate()
		self.eye_validate_prices()

	def eye_validate_prices(self):
		if not self.get("eye_pl") or self.flags.get("eye_system"):
			return
		pl = frappe.get_doc("Deal PL", self.eye_pl)
		lines = {cint(line.service_no): line for line in pl.lines}
		for row in self.items:
			line = lines.get(cint(row.eye_service_no))
			if not line:
				frappe.throw(
					_("Row #{0}: {1} isn't one of the deal's services. Add services on the deal.").format(
						row.idx, frappe.bold(row.item_code)
					)
				)
			if flt(row.rate, 2) != flt(line.rate, 2) or flt(row.qty) != flt(line.qty):
				frappe.throw(
					_(
						"Row #{0}: prices and quantities come from the deal's P&L. Change them there (Edit Prices), then Update Quotation."
					).format(row.idx),
					title=_("Prices Come From the P&L"),
				)

	def on_trash(self):
		if getattr(super(), "on_trash", None):
			super().on_trash()
		# the quotation it replaced is current again
		if self.get("eye_revision_of"):
			frappe.db.set_value(
				"Quotation", {"name": self.eye_revision_of, "docstatus": 0}, "eye_superseded", 0
			)
		if self.get("opportunity"):
			if frappe.db.get_value("Opportunity", self.opportunity, "eye_quotation") == self.name:
				frappe.db.set_value(
					"Opportunity", self.opportunity, "eye_quotation", None, update_modified=False
				)
				frappe.flags.eye_relink_quotation = self.opportunity

	def after_delete(self):
		if getattr(super(), "after_delete", None):
			super().after_delete()
		deal = frappe.flags.pop("eye_relink_quotation", None)
		if deal:
			from eye_crm.eye.quotation import latest_quotation

			latest = latest_quotation(deal)
			frappe.db.set_value(
				"Opportunity", deal, "eye_quotation", latest.name if latest else None, update_modified=False
			)
