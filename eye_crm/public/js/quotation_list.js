// Quotation list: a quotation a newer one replaced shows as Superseded
(() => {
	const settings = (frappe.listview_settings["Quotation"] = frappe.listview_settings["Quotation"] || {});
	const base = settings.get_indicator;
	settings.add_fields = [...(settings.add_fields || []), "eye_superseded"];
	settings.get_indicator = function (doc) {
		if (doc.eye_superseded && doc.docstatus === 0) {
			return [__("Superseded"), "gray", "eye_superseded,=,1"];
		}
		return base ? base.call(this, doc) : null;
	};
})();
