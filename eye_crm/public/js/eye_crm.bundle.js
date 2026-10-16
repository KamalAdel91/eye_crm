// Eye CRM: what every desk page needs. The deal form, the billing request form and the boards
// share these: the dialog that asks what a stage needs, Open Project and Request Invoice.
frappe.provide("eye_crm");
frappe.provide("eye_crm.billing");

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

// What a document needs before it enters `stage`, asked from `method` (the server decides): a
// failed check shows as a message; missing fields are asked in a dialog, again until nothing is
// missing, as an answer can make another field needed (a received PO needs its number).
// Resolves to the typed values ({} when nothing was needed), or null when it can't enter.
eye_crm.ask_for_stage = async function ({ doctype, doc, stage, method, title }) {
	await frappe.model.with_doctype(doctype);
	const values = {};
	for (let round = 0; round < 6; round++) {
		const current = Object.assign({}, doc, values);
		const r = await frappe.call(method, { doc: current, stage });
		const { missing_fields, failed_checks } = r.message;
		if (failed_checks.length) {
			frappe.msgprint({
				title: title || __("Can't enter {0} yet", [__(stage)]),
				message: `<ul>${failed_checks.map((c) => `<li>${c.message}</li>`).join("")}</ul>`,
				indicator: "orange",
			});
			return null;
		}
		if (!missing_fields.length) return values;
		const typed = await eye_crm.ask_fields(doctype, doc.name, missing_fields, current, __("Needed for {0}", [__(stage)]));
		if (!typed) return null;
		Object.assign(values, typed);
	}
	return values;
};

// A dialog with `missing` fields as the DocType has them (labels, options); resolves to their values
eye_crm.ask_fields = function (doctype, name, missing, doc, title) {
	return new Promise((resolve) => {
		const fields = missing.map((f) => {
			const df = Object.assign(
				{},
				frappe.meta.get_docfield(doctype, f.fieldname, name) || {
					fieldname: f.fieldname,
					label: f.label,
					fieldtype: f.fieldtype,
				}
			);
			delete df.depends_on;
			delete df.mandatory_depends_on;
			return Object.assign(df, { reqd: 1, read_only: 0, hidden: 0, default: doc[f.fieldname] });
		});
		let done = false;
		const dialog = new frappe.ui.Dialog({
			title,
			fields,
			primary_action_label: __("Continue"),
			primary_action: (values) => {
				done = true;
				dialog.hide();
				resolve(values);
			},
		});
		dialog.onhide = () => !done && resolve(null);
		dialog.show();
	});
};

// Open Project: the deal enters the Opening stage, which decides where it goes (approval or opened)
eye_crm.open_project = async function (deal, on_done) {
	const stages = await frappe.db.get_list("Sales Stage", {
		filters: { eye_stage_type: "Opening" },
		order_by: "eye_stage_order asc",
		limit: 1,
		pluck: "name",
	});
	if (!stages.length) return frappe.msgprint(__("There is no Sales Stage of type Opening."));
	const doc = (await frappe.call("frappe.client.get", { doctype: "Opportunity", name: deal })).message;
	const values = await eye_crm.ask_for_stage({
		doctype: "Opportunity",
		doc,
		stage: stages[0],
		method: "eye_crm.eye.api.what_is_missing",
		title: __("The deal can't enter {0} yet", [stages[0]]),
	});
	if (values === null) return;
	await frappe.call({ method: "eye_crm.eye.api.open_project", args: { deal, values }, freeze: true });
	on_done && on_done();
};

// ---------------------------------------------------------------- billing

// Request Invoice: how much of each service to invoice now, from the project's Sales Order
eye_crm.billing.request_invoice = async function (deal, on_done) {
	await frappe.model.with_doctype("Billing Request");
	const doc = (await frappe.call("eye_crm.eye.billing.get_new_request", { deal })).message;
	const L = (f) => __(frappe.meta.get_label("Billing Request Item", f));
	const H = (f) => __(frappe.meta.get_label("Billing Request", f));
	const rows = (doc.items || []).map((row) => ({
		service_no: row.service_no,
		item_name: row.item_name || row.item_code,
		so_amount: row.so_amount,
		requested_before: row.requested_before,
		available: row.available,
		percent: 0,
		amount: 0,
	}));
	const grid = () => dialog.fields_dict.items.grid;
	const show_total = () => {
		const data = grid().get_data();
		const total = data.reduce((a, row) => a + flt(row.amount), 0);
		const over = data.filter((row) => flt(row.amount) > flt(row.available) + 0.005);
		dialog.fields_dict.summary.$wrapper.html(
			`<div class="eye-cards"><div class="eye-card eye-strong"><div class="eye-card-label">${H("total")}</div>
			<div class="eye-card-value">${format_currency(total, doc.currency)}</div></div></div>` +
				(over.length
					? `<div class="eye-alert eye-alert-bad">${__("More than what is left to request")}: ${over
							.map((row) => `#${row.service_no}`)
							.join(", ")}</div>`
					: "")
		);
	};
	const refresh = () => {
		grid().refresh();
		show_total();
	};
	const dialog = new frappe.ui.Dialog({
		title: __("Request Invoice"),
		size: "extra-large",
		fields: [
			{
				fieldname: "billing_stage",
				fieldtype: "Link",
				options: "Billing Stage",
				label: H("billing_stage"),
				default: doc.billing_stage,
				reqd: 1,
				get_query: () => ({ filters: { can_start_here: 1 } }),
			},
			{ fieldtype: "Column Break" },
			{ fieldname: "expected_date", fieldtype: "Date", label: H("expected_date"), default: doc.expected_date, reqd: 1 },
			{ fieldtype: "Column Break" },
			{
				fieldname: "percent_for_all",
				fieldtype: "Percent",
				label: __("Percent for All"),
				description: __("Of each service, up to what is left of it."),
				onchange: () => {
					const p = dialog.get_value("percent_for_all");
					if (p === null || p === undefined || p === "") return;
					grid()
						.get_data()
						.forEach((row) => {
							row.amount = Math.max(Math.min(flt((flt(row.so_amount) * flt(p)) / 100, 2), flt(row.available)), 0);
							row.percent = row.so_amount ? flt((row.amount / row.so_amount) * 100, 2) : 0;
						});
					refresh();
				},
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "items",
				fieldtype: "Table",
				label: H("items"),
				cannot_add_rows: true,
				cannot_delete_rows: true,
				in_place_edit: true,
				data: rows,
				fields: [
					{ fieldname: "service_no", fieldtype: "Int", label: L("service_no"), read_only: 1, in_list_view: 1, columns: 1 },
					{ fieldname: "item_name", fieldtype: "Data", label: L("item_code"), read_only: 1, in_list_view: 1, columns: 2 },
					{ fieldname: "so_amount", fieldtype: "Float", precision: 2, label: L("so_amount"), read_only: 1, in_list_view: 1, columns: 2 },
					{ fieldname: "requested_before", fieldtype: "Float", precision: 2, label: L("requested_before"), read_only: 1 },
					{ fieldname: "available", fieldtype: "Float", precision: 2, label: L("available"), read_only: 1, in_list_view: 1, columns: 2 },
					{
						fieldname: "percent",
						fieldtype: "Percent",
						label: L("percent"),
						in_list_view: 1,
						columns: 1,
						onchange() {
							if (!this.doc) return;
							this.doc.amount = flt((flt(this.doc.so_amount) * flt(this.doc.percent)) / 100, 2);
							refresh();
						},
					},
					{
						fieldname: "amount",
						fieldtype: "Float",
						precision: 2,
						label: L("amount"),
						in_list_view: 1,
						columns: 2,
						onchange() {
							if (!this.doc) return;
							this.doc.percent = this.doc.so_amount ? flt((flt(this.doc.amount) / this.doc.so_amount) * 100, 2) : 0;
							refresh();
						},
					},
				],
			},
			{ fieldname: "summary", fieldtype: "HTML" },
			{ fieldname: "notes", fieldtype: "Small Text", label: H("notes") },
		],
		primary_action_label: __("Save"),
		primary_action: async (values) => {
			const lines = grid()
				.get_data()
				.filter((row) => flt(row.amount) > 0)
				.map((row) => ({ service_no: row.service_no, amount: flt(row.amount, 2) }));
			if (!lines.length) return frappe.msgprint(__("Type the amount to invoice for at least one service."));
			const r = await frappe.call({
				method: "eye_crm.eye.billing.make_request",
				args: {
					deal,
					lines,
					billing_stage: values.billing_stage,
					expected_date: values.expected_date,
					notes: values.notes,
				},
				freeze: true,
			});
			dialog.hide();
			frappe.show_alert({ message: __("Billing request {0} saved", [r.message]), indicator: "green" });
			on_done && on_done(r.message);
		},
	});
	dialog.show();
	show_total();
};

// a stage's color, as the nearest Frappe indicator (lists show stages in it)
eye_crm.billing.INDICATORS = {
	blue: "#2490EF",
	cyan: "#06B6D4",
	gray: "#94A3B8",
	green: "#22C55E",
	"light-blue": "#7DD3FC",
	orange: "#F97316",
	pink: "#EC4899",
	purple: "#8B5CF6",
	red: "#EF4444",
	yellow: "#F59E0B",
};

eye_crm.billing.indicator = function (color) {
	const rgb = (hex) => {
		hex = (hex || "").replace("#", "");
		if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
		if (!/^[0-9a-f]{6}$/i.test(hex)) return null;
		return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
	};
	const want = rgb(color);
	if (!want) return "gray";
	let best = "gray";
	let distance = Infinity;
	for (const [name, hex] of Object.entries(eye_crm.billing.INDICATORS)) {
		const d = rgb(hex).reduce((a, v, i) => a + (v - want[i]) ** 2, 0);
		if (d < distance) [best, distance] = [name, d];
	}
	return best;
};

// a stage's color in a page: a dot, then its name
eye_crm.billing.stage_pill = function (stage, color) {
	const safe = /^#[0-9a-f]{3,8}$/i.test(color || "") ? color : "var(--gray-400)";
	return `<span class="eye-stage"><span class="eye-dot" style="background:${safe}"></span>${frappe.utils.escape_html(
		__(stage || "")
	)}</span>`;
};

// Nexlify Board's card buttons (Board Card Layout actions); nothing needs Nexlify Board for them
window.nx_actions = window.nx_actions || {};
window.nx_actions.eye_request_invoice = (ctx) => eye_crm.billing.request_invoice(ctx.name, () => ctx.refresh && ctx.refresh());
window.nx_actions.eye_open_project = (ctx) => eye_crm.open_project(ctx.name, () => ctx.refresh && ctx.refresh());
