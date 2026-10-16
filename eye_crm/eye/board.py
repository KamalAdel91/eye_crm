"""The boards: Deals (deals by Sales Stage) and Billing (billing requests by Billing Stage).

They are Frappe Kanban Boards, made once when the app is installed; after that they belong to the
site. Their columns follow the stages: a stage added, renamed, reordered, recolored or deleted
changes its column on every board of that field. A move on a board is a save like any other, so a
deal's or a request's stage rules hold there too.

When Nexlify Board is installed, its Flow screen asks `flow` what each stage ahead still needs.
"""

import frappe
from frappe import _

from eye_crm.eye import billing, stages

# the board's DocType -> its stage field, the stage DocType, and that DocType's order and color
STAGE_FIELDS = {
	"Opportunity": ("sales_stage", "Sales Stage", "eye_stage_order", "eye_color"),
	"Billing Request": ("billing_stage", "Billing Stage", "sequence", "color"),
}

# a Kanban column's colors, by the color each looks like
INDICATORS = {
	"Blue": "#2490EF",
	"Cyan": "#06B6D4",
	"Gray": "#94A3B8",
	"Green": "#22C55E",
	"Light Blue": "#7DD3FC",
	"Orange": "#F97316",
	"Pink": "#EC4899",
	"Purple": "#8B5CF6",
	"Red": "#EF4444",
	"Yellow": "#F59E0B",
}


def _rgb(color):
	color = (color or "").strip().lstrip("#")
	if len(color) == 3:
		color = "".join(c * 2 for c in color)
	if len(color) != 6:
		return None
	try:
		return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))
	except ValueError:
		return None


def indicator(color):
	"""The Kanban column color nearest to a stage's color."""
	rgb = _rgb(color)
	if not rgb:
		return "Gray"
	return min(
		INDICATORS,
		key=lambda name: sum((a - b) ** 2 for a, b in zip(rgb, _rgb(INDICATORS[name]), strict=True)),
	)


def _stages(doctype):
	_field, stage_doctype, order_field, color_field = STAGE_FIELDS[doctype]
	return frappe.get_all(
		stage_doctype,
		fields=["name", f"{color_field} as color"],
		order_by=f"{order_field} asc, creation asc",
	)


def _boards(doctype):
	# a standard board belongs to its app: only developer mode changes it
	return frappe.get_all(
		"Kanban Board",
		filters={
			"reference_doctype": doctype,
			"field_name": STAGE_FIELDS[doctype][0],
			"is_standard": ["!=", "Yes"],
		},
		pluck="name",
	)


def make_board(doctype, board_name, title_field, card_fields, module):
	"""A Kanban board of `doctype` with a column per stage, in their order. Made once."""
	if frappe.db.exists("Kanban Board", board_name):
		return None
	meta = frappe.get_meta(doctype)
	board = frappe.get_doc(
		{
			"doctype": "Kanban Board",
			"kanban_board_name": board_name,
			"reference_doctype": doctype,
			"field_name": STAGE_FIELDS[doctype][0],
			"module": module,
			"is_standard": "No",
			"private": 0,
			"use_kanban_v2": 1,
			"title_field": title_field,
			"show_assigned_to": 1,
			"columns": [
				{"column_name": s.name, "status": "Active", "indicator": indicator(s.color)}
				for s in _stages(doctype)
			],
			"card_fields": [
				{"fieldname": f, "label": meta.get_label(f)} for f in card_fields if meta.get_field(f)
			],
		}
	)
	board.flags.ignore_permissions = True
	board.insert()
	return board


def sync_columns(doctype, recolor=None):
	"""Every board of `doctype` gets a column per stage, in the stages' order: a new stage's column is
	added, a deleted one's removed. `recolor`: the stage whose color changed. A column's own color,
	set on the board, is kept otherwise."""
	ordered = _stages(doctype)
	position = {s.name: i for i, s in enumerate(ordered)}
	colors = {s.name: s.color for s in ordered}
	for name in _boards(doctype):
		board = frappe.get_doc("Kanban Board", name)
		before = [(c.column_name, c.indicator, c.status) for c in board.columns]
		columns = [c for c in board.columns if c.column_name in position]
		have = {c.column_name for c in columns}
		for s in ordered:
			if s.name not in have:
				columns.append(
					frappe._dict(
						column_name=s.name, status="Active", indicator=indicator(s.color), order=None
					)
				)
		columns.sort(key=lambda c: position[c.column_name])
		for c in columns:
			if recolor and c.column_name == recolor:
				c.indicator = indicator(colors.get(recolor))
		if [(c.column_name, c.indicator, c.status) for c in columns] == before:
			continue
		board.set(
			"columns",
			[
				{"column_name": c.column_name, "status": c.status, "indicator": c.indicator, "order": c.order}
				for c in columns
			],
		)
		board.flags.ignore_permissions = True
		board.save()


def rename_column(doctype, old, new):
	"""A stage renamed: its column keeps its cards, order and color under the new name."""
	for name in _boards(doctype):
		board = frappe.get_doc("Kanban Board", name)
		columns = [c for c in board.columns if c.column_name == old]
		if not columns:
			continue
		if any(c.column_name == new for c in board.columns):
			# merged into a stage that has its column already
			board.set("columns", [c for c in board.columns if c.column_name != old])
		else:
			for c in columns:
				c.column_name = new
		board.flags.ignore_permissions = True
		board.save()


# ---------------------------------------------------------------- Nexlify Board's Flow


def _step(stage, label, done, action="", action_label=None, waiting_on=None):
	return {
		"stage": stage,
		"label": label,
		"done": bool(done),
		"action": action,
		"action_label": action_label or _("Open"),
		"waiting_on": waiting_on,
	}


def _roles_step(stage, roles, user_roles):
	if roles and not set(roles) & user_roles:
		names = ", ".join(_(r) for r in roles)
		return _step(stage, _("Moved by {0}").format(names), False, waiting_on=names)
	return None


@frappe.whitelist()
def flow(doctype, name):
	"""Nexlify Board's Flow Steps Method (Nexlify Board Settings): what each stage ahead needs."""
	if doctype == "Opportunity":
		return _deal_flow(name)
	if doctype == "Billing Request":
		return _billing_flow(name)
	return {}


def _deal_flow(name):
	deal = frappe.get_doc("Opportunity", name)
	deal.check_permission("read")
	current = stages.get_stage(deal.sales_stage)
	names = frappe.get_all("Sales Stage", order_by="eye_stage_order asc", pluck="name")
	user_roles = set(frappe.get_roles())
	steps, asked = [], set()
	for stage_name in names:
		info = stages.get_stage(stage_name)
		if info.system_only or (current and info.order <= current.order):
			continue
		if step := _roles_step(stage_name, info.roles, user_roles):
			steps.append(step)
		problems = stages.what_is_missing(deal, info)
		failed = {c["check"] for c in problems["failed_checks"]}
		# a check or a field shows at the first stage that asks for it
		for check in info.checks:
			if check in asked:
				continue
			asked.add(check)
			title = frappe.get_cached_value("Eye Check", check, "title") or check
			steps.append(_step(stage_name, _(title), check not in failed, action="form"))
		for f in problems["missing_fields"]:
			if f["fieldname"] in asked:
				continue
			asked.add(f["fieldname"])
			steps.append(
				_step(
					stage_name,
					_("Fill {0}").format(_(f["label"])),
					False,
					action=f"fields:{f['fieldname']}",
					action_label=_("Fill in"),
				)
			)
	return {"field": "sales_stage", "stages": names, "steps": steps}


def _billing_flow(name):
	request = frappe.get_doc("Billing Request", name)
	request.check_permission("read")
	current = billing.get_stage(request.billing_stage)
	names = frappe.get_all("Billing Stage", order_by="sequence asc", pluck="name")
	user_roles = set(frappe.get_roles())
	steps, asked = [], set()
	for stage_name in names:
		info = billing.get_stage(stage_name)
		if current and info.order <= current.order:
			continue
		if step := _roles_step(stage_name, info.roles, user_roles):
			steps.append(step)
		problems = billing.what_is_missing(request, info)
		for c in problems["failed_checks"]:
			if c["check"] not in asked:
				asked.add(c["check"])
				steps.append(_step(stage_name, c["message"], False, action="form"))
		for f in problems["missing_fields"]:
			if f["fieldname"] not in asked:
				asked.add(f["fieldname"])
				steps.append(
					_step(
						stage_name,
						_("Fill {0}").format(_(f["label"])),
						False,
						action=f"fields:{f['fieldname']}",
						action_label=_("Fill in"),
					)
				)
	return {"field": "billing_stage", "stages": names, "steps": steps}
