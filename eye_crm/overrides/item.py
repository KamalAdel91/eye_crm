"""Item, as Eye CRM extends it: its Eye fields' conditions (Mandatory Depends On) hold on the
server too, so an import or an API call can't skip them."""

import frappe
from frappe import _


class EyeItem:
	def validate(self):
		super().validate()
		from eye_crm.eye.stages import missing_fields

		missing = missing_fields(self, prefix="eye_")
		if missing:
			frappe.throw(
				_("{0} is needed for {1}.").format(
					", ".join(frappe.bold(_(f["label"])) for f in missing),
					frappe.bold(self.name or self.item_code),
				),
				frappe.MandatoryError,
			)
