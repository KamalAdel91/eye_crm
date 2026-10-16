# Copyright (c) 2026, Kamal Adel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class EyeCRMSettings(Document):
	def validate(self):
		if self.reject_stage:
			stage_type = frappe.db.get_value("Sales Stage", self.reject_stage, "eye_stage_type")
			if stage_type and cint(frappe.db.get_value("Eye Stage Type", stage_type, "system_only")):
				frappe.throw(
					_("A rejected deal must go back to a stage Sales can work in, not {0}.").format(
						frappe.bold(self.reject_stage)
					)
				)
