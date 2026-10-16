# Copyright (c) 2026, Kamal Adel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class EyeCheck(Document):
	def validate(self):
		from eye_crm.eye.checks import CHECKS

		if self.check_key not in CHECKS:
			frappe.msgprint(
				_(
					"The app has no check called {0}, so this one does nothing. The app's checks are: {1}."
				).format(frappe.bold(self.check_key), ", ".join(CHECKS)),
				indicator="orange",
			)
