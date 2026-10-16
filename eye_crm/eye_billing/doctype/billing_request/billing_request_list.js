// Billing requests: each shows its stage, in the stage's color (Billing Stage)
frappe.listview_settings["Billing Request"] = {
	add_fields: ["billing_stage", "stage_type", "currency"],

	onload(listview) {
		frappe.db.get_list("Billing Stage", { fields: ["name", "color"], limit: 100 }).then((rows) => {
			eye_crm.billing.stage_colors = Object.fromEntries(rows.map((r) => [r.name, r.color]));
			listview.refresh();
		});
	},

	get_indicator(doc) {
		const colors = eye_crm.billing.stage_colors || {};
		return [__(doc.billing_stage), eye_crm.billing.indicator(colors[doc.billing_stage]), `billing_stage,=,${doc.billing_stage}`];
	},
};
