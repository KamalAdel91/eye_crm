// Eye CRM: what every desk page needs
frappe.provide("eye_crm");

// Cost Sheets and P&Ls are submitted by their deal's actions: their forms keep Save, not Submit
eye_crm.hide_submit = function (frm) {
	if (frm.doc.docstatus !== 0 || frm.is_new()) return;
	if (!frm.is_dirty()) frm.page.clear_primary_action();
	frm.dashboard.clear_comment();
	frm.dashboard.add_comment(
		__("Submitted by the deal: when its project opens, or when its change is approved."),
		"blue",
		true
	);
};
