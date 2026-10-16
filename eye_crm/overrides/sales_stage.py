"""Sales Stage, as Eye CRM extends it: deals keep their stage's type and order with them, so field
conditions (doc.eye_stage_type, doc.eye_stage_order) stay right when a stage is changed."""

import frappe
from frappe import _
from frappe.utils import cint


class EyeSalesStage:
	def validate(self):
		if getattr(super(), "validate", None):
			super().validate()
		if (
			self.get("eye_stage_type")
			and cint(frappe.db.get_value("Eye Stage Type", self.eye_stage_type, "system_only"))
			and self.get("eye_roles")
		):
			frappe.msgprint(
				_("Only the system moves deals into a {0} stage, so its roles are not used.").format(
					frappe.bold(_(self.eye_stage_type))
				),
				alert=True,
			)

	def on_update(self):
		if getattr(super(), "on_update", None):
			super().on_update()
		if self.has_value_changed("eye_stage_type") or self.has_value_changed("eye_stage_order"):
			frappe.db.set_value(
				"Opportunity",
				{"sales_stage": self.name},
				{
					"eye_stage_type": self.get("eye_stage_type"),
					"eye_stage_order": cint(self.get("eye_stage_order")),
				},
				update_modified=False,
			)
