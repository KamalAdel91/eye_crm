// The deal form (Opportunity): its Cost Sheet, P&L, Quotations and Billing tabs, their dialogs,
// and the actions that move it: Open Project, Approve / Reject, changes after opening, and
// Request Invoice. Every number shown comes from a stored field; every label from that field's
// label.

frappe.provide("eye_crm.deal");

const API = "eye_crm.eye.api.";

frappe.ui.form.on("Opportunity", {
	setup(frm) {
		frm.set_query("sales_stage", () => ({
			filters: { eye_stage_type: ["not in", eye_crm.deal.system_types] },
		}));
	},

	onload(frm) {
		eye_crm.deal.load_system_types();
	},

	refresh(frm) {
		frm.eye_stage_before = frm.doc.sales_stage;
		eye_crm.deal.lock_stage(frm);
		if (frm.is_new()) return;
		// ERPNext's own "Create > Quotation" copies the deal without its prices: the deal's comes
		// from the P&L
		frm.remove_custom_button(__("Quotation"), __("Create"));
		eye_crm.deal.load(frm);
	},

	sales_stage(frm) {
		eye_crm.deal.on_stage_change(frm);
	},
});

Object.assign(eye_crm.deal, {
	system_types: [],

	load_system_types() {
		if (this._types_loading) return;
		this._types_loading = frappe.db
			.get_list("Eye Stage Type", { filters: { system_only: 1 }, pluck: "name" })
			.then((names) => (this.system_types = names));
	},

	lock_stage(frm) {
		// a deal in a stage only the system enters is moved by its actions
		const locked = eye_crm.deal.system_types.includes(frm.doc.eye_stage_type);
		frm.set_df_property("sales_stage", "read_only", locked ? 1 : 0);
	},

	async load(frm) {
		await Promise.all(
			["Cost Sheet", "Deal PL", "Quotation", "Billing Request"].map((dt) => frappe.model.with_doctype(dt))
		);
		const r = await frappe.call(API + "deal_view", { deal: frm.doc.name });
		frm.eye_view = r.message;
		this.render(frm);
	},

	render(frm) {
		const view = frm.eye_view;
		if (!view) return;
		this.render_costs(frm, view);
		this.render_pl(frm, view);
		this.render_quotations(frm, view);
		this.render_billing(frm, view);
		this.add_actions(frm, view);
	},

	// ---------------------------------------------------------------- helpers

	label(doctype, fieldname) {
		return __(frappe.meta.get_label(doctype, fieldname));
	},

	fmt(doctype, fieldname, value, doc) {
		const df = frappe.meta.get_docfield(doctype, fieldname);
		return df ? frappe.format(value, df, { inline: true }, doc) : frappe.utils.escape_html(value ?? "");
	},

	card(doctype, fieldname, doc, extra_class = "") {
		return `<div class="eye-card ${extra_class}">
			<div class="eye-card-label">${this.label(doctype, fieldname)}</div>
			<div class="eye-card-value">${this.fmt(doctype, fieldname, doc[fieldname], doc)}</div>
		</div>`;
	},

	table(doctype, fields, rows, parent) {
		const head = fields
			.map((f) => `<th class="${this.is_number(doctype, f) ? "eye-num" : ""}">${this.label(doctype, f)}</th>`)
			.join("");
		const body = rows
			.map(
				(row) =>
					`<tr class="${row.below_minimum ? "eye-below" : ""}">${fields
						.map(
							(f) =>
								`<td class="${this.cell_class(doctype, f)}">${this.fmt(
									doctype,
									f,
									row[f],
									Object.assign({}, parent, row)
								)}</td>`
						)
						.join("")}</tr>`
			)
			.join("");
		return `<div class="eye-table-wrap"><table class="eye-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
	},

	cell_class(doctype, fieldname) {
		const df = frappe.meta.get_docfield(doctype, fieldname);
		if (!df) return "";
		if (["Currency", "Float", "Int", "Percent"].includes(df.fieldtype)) return "eye-num";
		return ["Small Text", "Text", "Text Editor", "Long Text"].includes(df.fieldtype) ? "eye-wrap" : "";
	},

	is_number(doctype, fieldname) {
		const df = frappe.meta.get_docfield(doctype, fieldname);
		return df && ["Currency", "Float", "Int", "Percent"].includes(df.fieldtype);
	},

	link(doctype, name) {
		return frappe.utils.get_form_link(doctype, name, true);
	},

	button(label, action, primary = false) {
		return `<button class="btn btn-xs ${primary ? "btn-primary" : "btn-default"}" data-eye-action="${action}">${label}</button>`;
	},

	html(frm, fieldname, content, actions) {
		const field = frm.get_field(fieldname);
		if (!field) return;
		field.$wrapper.html(`<div class="eye-view">${content}</div>`);
		field.$wrapper.find("[data-eye-action]").on("click", (e) => {
			const fn = actions[$(e.currentTarget).attr("data-eye-action")];
			fn && fn();
		});
	},

	status_badge(doc) {
		if (doc.superseded) return `<span class="indicator-pill gray">${__("Superseded")}</span>`;
		if (doc.docstatus === 1) return `<span class="indicator-pill green">${__("Submitted")}</span>`;
		if (doc.docstatus === 2) return `<span class="indicator-pill red">${__("Cancelled")}</span>`;
		return `<span class="indicator-pill orange">${__("Draft")}</span>`;
	},

	services(frm) {
		return (frm.doc.items || []).map((r) => ({
			no: r.eye_service_no,
			label: `#${r.eye_service_no} ${r.item_name || r.item_code}`,
			qty: r.qty,
		}));
	},

	// ---------------------------------------------------------------- Cost Sheet tab

	render_costs(frm, view) {
		const sheet = view.cost_sheet;
		const pl_lines = Object.fromEntries(((view.pl && view.pl.lines) || []).map((l) => [l.service_no, l]));
		const can = view.can.costs && !view.locked;
		const toolbar = `<div class="eye-toolbar">${
			can ? this.button(__("Edit"), "edit", true) : ""
		}${sheet ? ` <span class="eye-doc">${this.link("Cost Sheet", sheet.name)} ${this.status_badge(sheet)}</span>` : ""}</div>`;
		if (!sheet) {
			this.html(
				frm,
				"eye_cost_html",
				toolbar + `<div class="eye-empty">${__("Add the deal's services first.")}</div>`,
				{ edit: () => this.edit_costs(frm) }
			);
			return;
		}
		const cards = `<div class="eye-cards">${[
			this.card("Cost Sheet", "currency", sheet),
			this.card("Cost Sheet", "deal_exchange_rate", sheet),
			this.card("Cost Sheet", "total_cost", sheet),
			this.card("Cost Sheet", "total_cost_deal", sheet, "eye-strong"),
		].join("")}</div>`;
		const fields = ["item_code", "description", "supplier", "qty", "uom", "rate", "line_currency", "exchange_rate", "amount", "base_amount"];
		const groups = this.services(frm)
			.map((s) => {
				const lines = sheet.lines.filter((l) => l.service_no === s.no);
				const pl_line = pl_lines[s.no];
				const total = pl_line
					? `<span class="eye-group-total">${this.label("PL Line", "cost")}: ${this.fmt("PL Line", "cost", pl_line.cost, view.pl)}</span>`
					: "";
				return `<div class="eye-group">
					<div class="eye-group-title">${frappe.utils.escape_html(s.label)} <span class="text-muted">× ${s.qty}</span>${total}</div>
					${lines.length ? this.table("Cost Line", fields, lines, sheet) : `<div class="eye-empty">${__("No costs yet")}</div>`}
				</div>`;
			})
			.join("");
		const note = `<div class="eye-note">${__("Costs are for the whole quantity of each service.")}</div>`;
		this.html(frm, "eye_cost_html", toolbar + cards + groups + note, {
			edit: () => this.edit_costs(frm),
		});
	},

	edit_costs(frm) {
		const view = frm.eye_view;
		const sheet = view.cost_sheet || {};
		const services = this.services(frm);
		const company_currency = erpnext.get_currency(frm.doc.company);
		const L = (f) => this.label("Cost Line", f);
		const dialog = new frappe.ui.Dialog({
			title: __("Edit Costs"),
			size: "extra-large",
			fields: [
				{
					fieldname: "currency",
					fieldtype: "Link",
					options: "Currency",
					label: this.label("Cost Sheet", "currency"),
					default: sheet.currency || company_currency,
					reqd: 1,
					onchange: () => this.fetch_rate(dialog, "currency", "deal_exchange_rate", frm.doc.currency),
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "deal_exchange_rate",
					fieldtype: "Float",
					precision: 9,
					label: `${this.label("Cost Sheet", "deal_exchange_rate")} (${frm.doc.currency})`,
					default: sheet.deal_exchange_rate || 1,
					reqd: 1,
				},
				{ fieldtype: "Section Break" },
				{
					fieldname: "services_html",
					fieldtype: "HTML",
					options: `<div class="eye-note">${__("Services")}: ${services
						.map((s) => frappe.utils.escape_html(s.label))
						.join(" · ")}</div>`,
				},
				{
					fieldname: "lines",
					fieldtype: "Table",
					label: __("Cost Lines"),
					in_place_edit: true,
					data: (sheet.lines || []).map((l) => ({ ...l, service_no: String(l.service_no) })),
					fields: [
						{ fieldname: "service_no", fieldtype: "Select", label: L("service_no"), options: services.map((s) => String(s.no)).join("\n"), in_list_view: 1, columns: 1, reqd: 1 },
						{ fieldname: "item_code", fieldtype: "Link", options: "Item", label: L("item_code"), in_list_view: 1, columns: 2, reqd: 1, get_query: () => ({ filters: { is_purchase_item: 1, disabled: 0 } }) },
						{ fieldname: "description", fieldtype: "Small Text", label: L("description") },
						{ fieldname: "supplier", fieldtype: "Link", options: "Supplier", label: L("supplier") },
						{ fieldname: "qty", fieldtype: "Float", label: L("qty"), in_list_view: 1, columns: 1, default: 1, reqd: 1 },
						{ fieldname: "uom", fieldtype: "Link", options: "UOM", label: L("uom") },
						{ fieldname: "rate", fieldtype: "Float", precision: 2, label: L("rate"), in_list_view: 1, columns: 2 },
						{ fieldname: "line_currency", fieldtype: "Link", options: "Currency", label: L("line_currency"), in_list_view: 1, columns: 2 },
						{ fieldname: "exchange_rate", fieldtype: "Float", precision: 9, label: L("exchange_rate"), in_list_view: 1, columns: 2 },
					],
				},
			],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				const lines = (values.lines || []).map((l) => ({ ...l, service_no: cint(l.service_no) }));
				const r = await frappe.call({
					method: API + "save_costs",
					args: { deal: frm.doc.name, lines, currency: values.currency, deal_exchange_rate: values.deal_exchange_rate },
					freeze: true,
				});
				dialog.hide();
				frm.eye_view = r.message;
				frm.reload_doc();
			},
		});
		dialog.show();
	},

	fetch_rate(dialog, from_field, to_field, to_currency) {
		const from = dialog.get_value(from_field);
		if (!from || !to_currency) return;
		if (from === to_currency) return dialog.set_value(to_field, 1);
		frappe
			.call("erpnext.setup.utils.get_exchange_rate", { from_currency: from, to_currency })
			.then((r) => r.message && dialog.set_value(to_field, r.message));
	},

	// ---------------------------------------------------------------- P&L tab

	render_pl(frm, view) {
		const pl = view.pl;
		const can = view.can.prices && !view.locked;
		const toolbar = `<div class="eye-toolbar">${can ? this.button(__("Edit Prices"), "edit", true) : ""}${
			pl
				? ` <span class="eye-doc">${this.link("Deal PL", pl.name)} ${this.status_badge(pl)} ${__("Revision")} ${pl.revision}</span>`
				: ""
		}</div>`;
		if (!pl) {
			this.html(frm, "eye_pl_html", toolbar + `<div class="eye-empty">${__("Add the deal's services first.")}</div>`, {
				edit: () => this.edit_prices(frm),
			});
			return;
		}
		const cards = `<div class="eye-cards">${[
			this.card("Deal PL", "total_selling", pl, "eye-strong"),
			this.card("Deal PL", "total_cost", pl),
			this.card("Deal PL", "total_profit", pl, pl.total_profit < 0 ? "eye-bad" : "eye-good"),
			this.card("Deal PL", "margin", pl, pl.below_minimum ? "eye-bad" : ""),
		].join("")}</div>`;

		let notes = "";
		if (frm.doc.eye_change_pending && view.approved_pl && view.approved_pl !== pl.name) {
			notes += `<div class="eye-alert eye-alert-info">${__(
				"A change is waiting. This is revision {0}; the approved P&L is {1}.",
				[pl.revision, this.link("Deal PL", view.approved_pl)]
			)}${pl.change_reason ? `<div><b>${this.label("Deal PL", "change_reason")}:</b> ${frappe.utils.escape_html(pl.change_reason)}</div>` : ""}</div>`;
		}
		if (pl.below_minimum) {
			const below = pl.lines.filter((l) => l.below_minimum);
			notes += `<div class="eye-alert eye-alert-warn"><b>${this.label("Deal PL", "below_minimum")}</b>${
				view.below_minimum_message ? `<div>${frappe.utils.escape_html(view.below_minimum_message)}</div>` : ""
			}<ul>${below
				.map(
					(l) =>
						`<li>#${l.service_no} ${frappe.utils.escape_html(l.item_name || l.item_code)}: ${this.label("PL Line", "margin")} ${this.fmt("PL Line", "margin", l.margin, pl)}, ${this.label("PL Line", "min_margin")} ${this.fmt("PL Line", "min_margin", l.min_margin, pl)}</li>`
				)
				.join("")}</ul></div>`;
		}
		if (pl.approval_status) {
			const cls = { Approved: "eye-alert-good", Rejected: "eye-alert-bad", Pending: "eye-alert-warn" }[pl.approval_status] || "eye-alert-info";
			const by = pl.approved_by ? ` · ${frappe.user.full_name(pl.approved_by)} · ${this.fmt("Deal PL", "approved_on", pl.approved_on, pl)}` : "";
			notes += `<div class="eye-alert ${cls}"><b>${this.label("Deal PL", "approval_status")}:</b> ${__(pl.approval_status)}${by}
				${pl.approval_reasons ? `<div>${frappe.utils.escape_html(pl.approval_reasons)}</div>` : ""}
				${pl.rejection_reason ? `<div><b>${this.label("Deal PL", "rejection_reason")}:</b> ${frappe.utils.escape_html(pl.rejection_reason)}</div>` : ""}</div>`;
		}
		const fields = ["service_no", "item_code", "qty", "cost", "margin", "rate", "amount", "profit", "min_margin"];
		// a minimum only shows where the item has one
		const lines = pl.lines.map((l) => (l.requires_min_margin ? l : { ...l, min_margin: null }));
		const revisions =
			view.revisions.length > 1
				? `<div class="eye-revisions"><b>${__("Revisions")}:</b> ${view.revisions
						.map((r) => `${this.link("Deal PL", r.name)} (${r.revision}) ${this.status_badge(r)}`)
						.join(" · ")}</div>`
				: "";
		this.html(frm, "eye_pl_html", toolbar + cards + notes + this.table("PL Line", fields, lines, pl) + revisions, {
			edit: () => this.edit_prices(frm),
		});
	},

	edit_prices(frm) {
		const view = frm.eye_view;
		const pl = view.pl;
		if (!pl) return;
		const company_currency = erpnext.get_currency(frm.doc.company);
		const L = (f) => this.label("PL Line", f);
		const rows = pl.lines.map((l) => ({
			service_no: l.service_no,
			service: `${l.item_name || l.item_code}`,
			qty: l.qty,
			cost: l.cost,
			margin: l.margin,
			rate: l.rate,
			fixed_price: l.fixed_price,
			no_cost: l.no_cost,
			min_margin: l.requires_min_margin ? l.min_margin : null,
		}));
		const recalc = () => {
			const lines = dialog.fields_dict.lines.grid.get_data();
			lines.forEach((l) => eye_crm.deal.price(l));
			dialog.fields_dict.lines.grid.refresh();
			dialog.fields_dict.summary.$wrapper.html(this.summary(lines, dialog.get_value("currency") || frm.doc.currency));
		};
		const dialog = new frappe.ui.Dialog({
			title: __("Edit Prices"),
			size: "extra-large",
			fields: [
				{
					fieldname: "currency",
					fieldtype: "Link",
					options: "Currency",
					label: this.label("Opportunity", "currency"),
					default: frm.doc.currency,
					reqd: 1,
					onchange: () => this.fetch_rate(dialog, "currency", "conversion_rate", company_currency),
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "conversion_rate",
					fieldtype: "Float",
					precision: 9,
					label: `${this.label("Opportunity", "conversion_rate")} (${company_currency})`,
					default: frm.doc.conversion_rate,
					reqd: 1,
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "margin_for_all",
					fieldtype: "Percent",
					label: __("Margin for All"),
					description: __("Sets every service's margin; a typed price stays typed."),
					onchange: () => {
						const m = dialog.get_value("margin_for_all");
						if (m === null || m === undefined || m === "") return;
						dialog.fields_dict.lines.grid.get_data().forEach((l) => {
							if (!l.no_cost) {
								l.margin = flt(m);
								l.fixed_price = 0;
							}
						});
						recalc();
					},
				},
				{ fieldtype: "Section Break" },
				{
					fieldname: "lines",
					fieldtype: "Table",
					label: __("Services"),
					cannot_add_rows: true,
					cannot_delete_rows: true,
					in_place_edit: true,
					data: rows,
					fields: [
						{ fieldname: "service_no", fieldtype: "Int", label: L("service_no"), read_only: 1, in_list_view: 1, columns: 1 },
						{ fieldname: "service", fieldtype: "Data", label: L("item_code"), read_only: 1, in_list_view: 1, columns: 2 },
						{ fieldname: "qty", fieldtype: "Float", label: L("qty"), read_only: 1, in_list_view: 1, columns: 1 },
						{ fieldname: "cost", fieldtype: "Float", precision: 2, label: L("cost"), read_only: 1, in_list_view: 1, columns: 1 },
						{
							fieldname: "margin", fieldtype: "Percent", label: L("margin"), in_list_view: 1, columns: 1,
							onchange() { if (this.doc) this.doc.fixed_price = 0; recalc(); },
						},
						{
							fieldname: "rate", fieldtype: "Float", precision: 2, label: L("rate"), in_list_view: 1, columns: 1,
							onchange() { if (this.doc) this.doc.fixed_price = 1; recalc(); },
						},
						{ fieldname: "amount", fieldtype: "Float", precision: 2, label: L("amount"), read_only: 1, in_list_view: 1, columns: 1 },
						{ fieldname: "profit", fieldtype: "Float", precision: 2, label: L("profit"), read_only: 1, in_list_view: 1, columns: 1 },
						{ fieldname: "no_cost", fieldtype: "Check", label: L("no_cost"), in_list_view: 1, columns: 1, onchange: () => recalc() },
						{ fieldname: "fixed_price", fieldtype: "Check", label: L("fixed_price"), onchange: () => recalc() },
						{ fieldname: "min_margin", fieldtype: "Percent", label: L("min_margin"), read_only: 1 },
					],
				},
				{ fieldname: "summary", fieldtype: "HTML" },
			],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				const lines = dialog.fields_dict.lines.grid.get_data().map((l) => ({
					service_no: l.service_no, margin: l.margin, rate: l.rate, fixed_price: l.fixed_price ? 1 : 0, no_cost: l.no_cost ? 1 : 0,
				}));
				const r = await frappe.call({
					method: API + "save_prices",
					args: { deal: frm.doc.name, lines, currency: values.currency, conversion_rate: values.conversion_rate },
					freeze: true,
				});
				dialog.hide();
				frm.eye_view = r.message;
				frm.reload_doc();
			},
		});
		dialog.show();
		recalc();
	},

	// the same rules as the server (eye_crm/eye/pricing.py), to show prices while they are typed
	price(l) {
		const cost = flt(l.cost);
		const qty = flt(l.qty) || 1;
		if (cost <= 0) {
			l.rate = flt(l.rate, 2);
			l.margin = l.rate > 0 ? 100 : flt(l.margin);
		} else if (l.fixed_price) {
			l.rate = flt(l.rate, 2);
			const amount = l.rate * qty;
			l.margin = amount ? flt(((amount - cost) / amount) * 100, 3) : 0;
		} else if (flt(l.margin) < 100) {
			l.rate = Math.ceil(Math.round(((cost / qty) / (1 - flt(l.margin) / 100)) * 100 * 1e6) / 1e6) / 100;
		}
		l.amount = flt(flt(l.rate) * qty, 2);
		l.profit = flt(l.amount - cost, 2);
		const actual = l.amount ? ((l.amount - cost) / l.amount) * 100 : 0;
		l.below = l.min_margin !== null && l.min_margin !== undefined && actual < flt(l.min_margin) - 0.005;
	},

	summary(lines, currency) {
		const cost = lines.reduce((a, l) => a + flt(l.cost), 0);
		const selling = lines.reduce((a, l) => a + flt(l.amount), 0);
		const profit = selling - cost;
		const margin = selling ? (profit / selling) * 100 : 0;
		const money = (v) => format_currency(v, currency);
		const below = lines.filter((l) => l.below);
		const label = (f) => this.label("Deal PL", f);
		return `<div class="eye-cards">
			<div class="eye-card eye-strong"><div class="eye-card-label">${label("total_selling")}</div><div class="eye-card-value">${money(selling)}</div></div>
			<div class="eye-card"><div class="eye-card-label">${label("total_cost")}</div><div class="eye-card-value">${money(cost)}</div></div>
			<div class="eye-card ${profit < 0 ? "eye-bad" : "eye-good"}"><div class="eye-card-label">${label("total_profit")}</div><div class="eye-card-value">${money(profit)}</div></div>
			<div class="eye-card ${below.length ? "eye-bad" : ""}"><div class="eye-card-label">${label("margin")}</div><div class="eye-card-value">${format_number(margin, null, 2)}%</div></div>
		</div>${
			below.length
				? `<div class="eye-alert eye-alert-warn">${__("Below the minimum margin")}: ${below
						.map((l) => `#${l.service_no} (${format_number(l.min_margin, null, 2)}%)`)
						.join(", ")}. ${__("The project will need approval to open.")}</div>`
				: ""
		}`;
	},

	// ---------------------------------------------------------------- Quotations tab

	render_quotations(frm, view) {
		const pl = view.pl;
		const can = this.can_quote(frm, view);
		const toolbar = `<div class="eye-toolbar">${can ? this.button(__("Update Quotation"), "update", true) : ""}</div>`;
		const latest = view.quotations.find((q) => !q.eye_superseded && q.docstatus < 2);
		let notes = "";
		if (latest && pl && latest.eye_pl_signature !== pl.signature) {
			notes = `<div class="eye-alert eye-alert-warn">${__(
				"The P&L changed after {0}: update the quotation before sending it.",
				[latest.name]
			)}</div>`;
		}
		const rows = view.quotations.map((q) => ({
			...q,
			name_html: this.link("Quotation", q.name),
			state: `${this.status_badge({ docstatus: q.docstatus, superseded: q.eye_superseded })} ${q.docstatus === 1 ? __(q.status) : ""}`,
		}));
		const head = [
			__("Quotation"),
			this.label("Quotation", "eye_quotation_type"),
			__("Status"),
			this.label("Quotation", "transaction_date"),
			this.label("Quotation", "valid_till"),
			this.label("Quotation", "net_total"),
			this.label("Quotation", "grand_total"),
			this.label("Quotation", "eye_revision_of"),
		];
		const body = rows
			.map(
				(q) => `<tr class="${q.eye_superseded ? "text-muted" : ""}">
				<td>${q.name_html}</td><td>${__(q.eye_quotation_type || "")}</td><td>${q.state}</td>
				<td>${this.fmt("Quotation", "transaction_date", q.transaction_date, q)}</td>
				<td>${this.fmt("Quotation", "valid_till", q.valid_till, q)}</td>
				<td class="eye-num">${this.fmt("Quotation", "net_total", q.net_total, q)}</td>
				<td class="eye-num">${this.fmt("Quotation", "grand_total", q.grand_total, q)}</td>
				<td>${q.eye_revision_of ? this.link("Quotation", q.eye_revision_of) : ""}</td></tr>`
			)
			.join("");
		const table = rows.length
			? `<div class="eye-table-wrap"><table class="eye-table"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`
			: `<div class="eye-empty">${__("No quotation yet.")}</div>`;
		this.html(frm, "eye_quotations_html", toolbar + notes + table, { update: () => this.update_quotation(frm) });
	},

	// a quotation can be made whenever the deal isn't waiting for an approval
	can_quote(frm, view) {
		const pl = view.pl;
		return view.can.quote && pl && pl.lines.length && !view.locked;
	},

	update_quotation(frm) {
		const has_previous = frm.eye_view.quotations.some((q) => !q.eye_superseded && q.docstatus < 2);
		const dialog = new frappe.ui.Dialog({
			title: __("Update Quotation"),
			fields: [
				{
					fieldname: "quotation_type",
					fieldtype: "Link",
					options: "Eye Quotation Type",
					label: this.label("Quotation", "eye_quotation_type"),
					default: "Full",
					reqd: 1,
					description: has_previous
						? __("Full: every service. Changes Only: what changed since the last quotation.")
						: "",
				},
			],
			primary_action_label: __("Make"),
			primary_action: async (values) => {
				const r = await frappe.call({
					method: API + "update_quotation",
					args: { deal: frm.doc.name, quotation_type: values.quotation_type },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Quotation {0} made", [r.message]), indicator: "green" });
				frm.reload_doc();
			},
		});
		dialog.show();
	},

	// ---------------------------------------------------------------- Billing tab

	render_billing(frm, view) {
		const billing = view.billing;
		if (!billing) return;
		const can = this.can_request(frm, view);
		const toolbar = `<div class="eye-toolbar">${can ? this.button(__("Request Invoice"), "request", true) : ""}</div>`;
		const B = (f) => this.label("Billing Request", f);
		const fields = ["expected_date", "total", "invoice_number", "collected_amount"];
		const body = billing.requests
			.map(
				(r) => `<tr>
				<td>${this.link("Billing Request", r.name)}</td>
				<td>${eye_crm.billing.stage_pill(r.billing_stage, billing.colors[r.billing_stage])}</td>
				${fields
					.map((f) => `<td class="${this.cell_class("Billing Request", f)}">${this.fmt("Billing Request", f, r[f], r)}</td>`)
					.join("")}</tr>`
			)
			.join("");
		const head = [__("Billing Request"), B("billing_stage"), ...fields.map((f) => B(f))]
			.map((h, i) => `<th class="${i > 1 && this.is_number("Billing Request", fields[i - 2]) ? "eye-num" : ""}">${h}</th>`)
			.join("");
		const table = billing.requests.length
			? `<div class="eye-table-wrap"><table class="eye-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
			: `<div class="eye-empty">${__("No billing request yet.")}</div>`;
		this.html(frm, "eye_billing_html", toolbar + table, { request: () => this.request_invoice(frm) });
	},

	can_request(frm, view) {
		return view.billing && view.billing.can_request && flt(frm.doc.eye_left_to_request) > 0;
	},

	request_invoice(frm) {
		eye_crm.billing.request_invoice(frm.doc.name, () => frm.reload_doc());
	},

	// ---------------------------------------------------------------- actions

	add_actions(frm, view) {
		const type = view.stage_type;
		const group = __("Deal");
		if (this.can_quote(frm, view)) {
			frm.add_custom_button(__("Quotation"), () => this.update_quotation(frm), __("Create"));
		}
		if (this.can_request(frm, view)) {
			frm.add_custom_button(__("Request Invoice"), () => this.request_invoice(frm), group);
		}
		if (view.can.move && ["Pipeline", "Quotation", "In Hand"].includes(type) && frm.doc.status !== "Lost") {
			frm.add_custom_button(__("Open Project"), () => this.open_project(frm), group);
		}
		if (view.can.decide && ["Approval", "Change Approval"].includes(type)) {
			frm.add_custom_button(__("Approve"), () => this.decide(frm, "approve"), group);
			frm.add_custom_button(__("Reject"), () => this.decide(frm, "reject"), group);
		}
		if (view.can.prices && type === "Opened" && frm.doc.eye_change_pending) {
			frm.add_custom_button(__("Send Change for Approval"), () => this.send_change(frm), group);
			frm.add_custom_button(__("Discard Change"), () => this.discard_change(frm), group);
		}
	},

	async open_project(frm) {
		// what is typed in the form goes first: the opening checks the saved deal
		if (frm.is_dirty()) await frm.save();
		eye_crm.open_project(frm.doc.name, () => frm.reload_doc());
	},

	decide(frm, action) {
		if (action === "approve") {
			frappe.confirm(__("Approve this deal?"), async () => {
				await frappe.call({ method: API + "approve", args: { deal: frm.doc.name }, freeze: true });
				frm.reload_doc();
			});
			return;
		}
		frappe.prompt(
			{ fieldname: "reason", fieldtype: "Small Text", label: this.label("Deal PL", "rejection_reason"), reqd: 1 },
			async ({ reason }) => {
				await frappe.call({ method: API + "reject", args: { deal: frm.doc.name, reason }, freeze: true });
				frm.reload_doc();
			},
			__("Reject"),
			__("Reject")
		);
	},

	send_change(frm) {
		frappe.prompt(
			{ fieldname: "reason", fieldtype: "Small Text", label: this.label("Deal PL", "change_reason"), reqd: 1 },
			async ({ reason }) => {
				await frappe.call({ method: API + "send_change", args: { deal: frm.doc.name, reason }, freeze: true });
				frm.reload_doc();
			},
			__("Send Change for Approval"),
			__("Send")
		);
	},

	discard_change(frm) {
		frappe.confirm(__("Drop the change and go back to the approved services, costs and prices?"), async () => {
			await frappe.call({ method: API + "discard_change", args: { deal: frm.doc.name }, freeze: true });
			frm.reload_doc();
		});
	},

	// ---------------------------------------------------------------- moving the deal

	async on_stage_change(frm) {
		const target = frm.doc.sales_stage;
		const before = frm.eye_stage_before;
		if (frm.is_new() || !target || target === before || frm.eye_moving) return;
		const revert = () => {
			frm.eye_moving = true;
			frm.set_value("sales_stage", before).then(() => (frm.eye_moving = false));
		};
		const ok = await this.ask_for_stage(frm, target);
		if (!ok) return revert();
		frm.save();
	},

	// asks for what the deal needs before it enters `stage` (eye_crm.ask_for_stage) and puts the
	// answers in the form. Resolves true when the deal is ready.
	async ask_for_stage(frm, stage) {
		const values = await eye_crm.ask_for_stage({
			doctype: "Opportunity",
			doc: frm.doc,
			stage,
			method: API + "what_is_missing",
			title: __("The deal can't enter {0} yet", [stage]),
		});
		if (values === null) return false;
		for (const [k, v] of Object.entries(values)) await frm.set_value(k, v);
		return true;
	},
});
