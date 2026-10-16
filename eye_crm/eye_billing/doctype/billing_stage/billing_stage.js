// Copyright (c) 2026, Kamal Adel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Billing Stage", {
	setup(frm) {
		frm.set_query("role", "roles", () => ({ filters: { desk_access: 1 } }));
	},
});
