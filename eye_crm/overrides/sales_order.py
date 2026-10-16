"""Sales Order, as Eye CRM extends it: a project's Sales Order follows the deal's approved P&L."""

import frappe
from frappe import _
from frappe.utils import cint, flt


class EyeSalesOrder:
	def before_update_after_submit(self):
		if getattr(super(), "before_update_after_submit", None):
			super().before_update_after_submit()
		if not self.get("eye_opportunity") or frappe.flags.get("eye_sales_order_update"):
			return
		before = self.get_doc_before_save()
		if before and _lines(before) != _lines(self):
			frappe.throw(
				_(
					"This Sales Order follows the P&L of deal {0}. Change the deal: an approved change updates it."
				).format(frappe.bold(self.eye_opportunity)),
				title=_("Change It From the Deal"),
			)


def _lines(doc):
	return sorted((r.item_code, flt(r.qty), flt(r.rate), cint(r.get("eye_service_no"))) for r in doc.items)
