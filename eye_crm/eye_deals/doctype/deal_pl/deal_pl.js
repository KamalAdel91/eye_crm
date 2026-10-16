// Copyright (c) 2026, Kamal Adel and contributors
// For license information, please see license.txt

// A P&L is submitted by its deal's actions (Open Project, Approve), never from here.
frappe.ui.form.on("Deal PL", {
	refresh(frm) {
		eye_crm.hide_submit(frm);
		// the lines are the deal's services
		frm.set_df_property("lines", "cannot_add_rows", 1);
		frm.set_df_property("lines", "cannot_delete_rows", 1);
		if (frm.doc.opportunity) {
			frm.add_custom_button(__("Open the Deal"), () =>
				frappe.set_route("Form", "Opportunity", frm.doc.opportunity)
			);
		}
	},
});

frappe.ui.form.on("PL Line", {
	// a typed price stays when the cost changes; a margin makes the price follow the cost
	rate(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "fixed_price", 1);
	},
	margin(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "fixed_price", 0);
	},
});
