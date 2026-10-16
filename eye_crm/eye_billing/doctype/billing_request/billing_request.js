// Copyright (c) 2026, Kamal Adel and contributors
// For license information, please see license.txt

// A billing request: the amounts come from the deal's Sales Order (eye_crm.eye.billing); a new
// stage asks for what it needs before the request is saved in it.

frappe.ui.form.on("Billing Request", {
	setup(frm) {
		frm.set_query("billing_stage", () => (frm.is_new() ? { filters: { can_start_here: 1 } } : {}));
		frm.set_query("opportunity", () => ({ filters: { eye_sales_order: ["is", "set"] } }));
	},

	refresh(frm) {
		frm.eye_stage_before = frm.doc.billing_stage;
		frm.set_df_property("items", "cannot_add_rows", 1);
		// once the invoice is issued, its amounts stay
		const issued = ["Invoiced", "Collected"].includes(frm.doc.stage_type);
		for (const f of ["amount", "percent"]) {
			frm.fields_dict.items.grid.update_docfield_property(f, "read_only", issued ? 1 : 0);
		}
		frm.set_df_property("items", "cannot_delete_rows", issued ? 1 : 0);
		if (frm.doc.opportunity && !frm.is_new()) {
			frm.add_custom_button(__("Deal"), () => frappe.set_route("Form", "Opportunity", frm.doc.opportunity));
		}
	},

	// a new request from the list: the deal's services, nothing asked yet
	async opportunity(frm) {
		if (!frm.is_new() || !frm.doc.opportunity) return;
		const doc = (await frappe.call("eye_crm.eye.billing.get_new_request", { deal: frm.doc.opportunity })).message;
		for (const f of ["title", "customer", "customer_name", "salesperson", "sales_order", "company", "currency"]) {
			frm.doc[f] = doc[f];
		}
		if (!frm.doc.billing_stage) frm.doc.billing_stage = doc.billing_stage;
		if (!frm.doc.expected_date) frm.doc.expected_date = doc.expected_date;
		frm.clear_table("items");
		for (const row of doc.items) {
			const fields = ["service_no", "item_code", "item_name", "description", "so_detail", "so_amount", "requested_before", "available", "amount", "percent"];
			frm.add_child("items", Object.fromEntries(fields.map((f) => [f, row[f]])));
		}
		frm.refresh_fields();
		eye_crm.billing.set_total(frm);
	},

	async billing_stage(frm) {
		const target = frm.doc.billing_stage;
		const before = frm.eye_stage_before;
		if (frm.is_new() || !target || target === before || frm.eye_moving) return;
		const revert = () => {
			frm.eye_moving = true;
			frm.set_value("billing_stage", before).then(() => (frm.eye_moving = false));
		};
		const values = await eye_crm.ask_for_stage({
			doctype: "Billing Request",
			doc: frm.doc,
			stage: target,
			method: "eye_crm.eye.billing.what_is_missing_for",
			title: __("The request can't enter {0} yet", [target]),
		});
		if (values === null) return revert();
		for (const [k, v] of Object.entries(values)) await frm.set_value(k, v);
		frm.save();
	},
});

frappe.ui.form.on("Billing Request Item", {
	async amount(frm, cdt, cdn) {
		if (frm.eye_syncing) return;
		const row = locals[cdt][cdn];
		frm.eye_syncing = true;
		await frappe.model.set_value(cdt, cdn, "percent", row.so_amount ? flt((flt(row.amount) / row.so_amount) * 100, 2) : 0);
		frm.eye_syncing = false;
		eye_crm.billing.set_total(frm);
	},

	async percent(frm, cdt, cdn) {
		if (frm.eye_syncing) return;
		const row = locals[cdt][cdn];
		frm.eye_syncing = true;
		await frappe.model.set_value(cdt, cdn, "amount", flt((flt(row.so_amount) * flt(row.percent)) / 100, 2));
		frm.eye_syncing = false;
		eye_crm.billing.set_total(frm);
	},

	items_remove(frm) {
		eye_crm.billing.set_total(frm);
	},
});

// the server totals it again when the request is saved
eye_crm.billing.set_total = function (frm) {
	frm.set_value("total", flt((frm.doc.items || []).reduce((a, row) => a + flt(row.amount), 0), 2));
};
