// Quotation: a deal's quotation takes its prices from the deal's P&L
frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (frm.doc.eye_superseded && frm.doc.docstatus === 0) {
			frm.dashboard.set_headline_alert(
				__("A newer quotation replaced this one."),
				"gray"
			);
		}
		if (frm.doc.eye_pl && frm.doc.opportunity) {
			frm.add_custom_button(__("Open the Deal"), () =>
				frappe.set_route("Form", "Opportunity", frm.doc.opportunity)
			);
		}
	},
});
