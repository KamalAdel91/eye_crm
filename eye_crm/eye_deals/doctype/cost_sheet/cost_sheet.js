// Copyright (c) 2026, Kamal Adel and contributors
// For license information, please see license.txt

// A Cost Sheet is submitted by its deal's actions (Open Project, Approve), never from here.
frappe.ui.form.on("Cost Sheet", {
	setup(frm) {
		frm.set_query("item_code", "lines", () => ({ filters: { is_purchase_item: 1, disabled: 0 } }));
	},
	refresh(frm) {
		eye_crm.hide_submit(frm);
		if (frm.doc.opportunity) {
			frm.add_custom_button(__("Open the Deal"), () =>
				frappe.set_route("Form", "Opportunity", frm.doc.opportunity)
			);
		}
	},
});
