"""Sales stages. The app knows a stage by its type (Eye Stage Type), never by its name: names,
order, colors, who may move a deal into a stage and what the deal needs first are all set on the
Sales Stage, from the desk.

What a deal needs before it enters a stage comes from two places:
- its fields, through Mandatory Depends On in Customize Form (by doc.eye_stage_order or
  doc.eye_stage_type, so renaming a stage breaks nothing)
- the stage's checks (Eye Check), for what a field condition can't say
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from eye_crm.eye import conditions

# the types the code acts on
PIPELINE = "Pipeline"
QUOTATION = "Quotation"
IN_HAND = "In Hand"
OPENING = "Opening"
APPROVAL = "Approval"
OPENED = "Opened"
CHANGE_APPROVAL = "Change Approval"

# while a deal waits in these, its services, costs and prices are locked
LOCKED_TYPES = (APPROVAL, CHANGE_APPROVAL)


class StageError(frappe.ValidationError):
	"""A deal can't enter a stage. Carries what is missing, so the form can ask for it."""

	def __init__(self, message, missing_fields=None, failed_checks=None):
		super().__init__(message)
		self.missing_fields = missing_fields or []
		self.failed_checks = failed_checks or []


def get_stage(name):
	if not name:
		return None
	stage = frappe.get_cached_doc("Sales Stage", name)
	stage_type = stage.get("eye_stage_type")
	return frappe._dict(
		name=stage.name,
		type=stage_type,
		order=cint(stage.get("eye_stage_order")),
		system_only=cint(frappe.get_cached_value("Eye Stage Type", stage_type, "system_only"))
		if stage_type
		else 0,
		roles=[r.role for r in stage.get("eye_roles") or []],
		checks=[c.check for c in stage.get("eye_checks") or []],
	)


def stage_of_type(stage_type, required=True):
	"""The first stage (by order) of a type."""
	name = frappe.db.get_value(
		"Sales Stage", {"eye_stage_type": stage_type}, "name", order_by="eye_stage_order asc"
	)
	if not name and required:
		frappe.throw(
			_("There is no Sales Stage of type {0}. Add one, or give that type to a stage.").format(
				frappe.bold(_(stage_type))
			),
			title=_("Missing Stage"),
		)
	return name


def type_of(stage_name):
	return frappe.get_cached_value("Sales Stage", stage_name, "eye_stage_type") if stage_name else None


def apply_stage_fields(deal):
	stage = get_stage(deal.sales_stage)
	deal.eye_stage_type = stage.type if stage else None
	deal.eye_stage_order = stage.order if stage else 0
	return stage


def blocked_move(deal, old, new, user=None):
	"""Why the user can't move the deal from stage `old` into `new` (None: they can)."""
	if deal.flags.get("eye_system_move"):
		return None
	if old and old.system_only and (not new or new.name != old.name):
		return _("The deal is in {0}: only its actions move it from there.").format(frappe.bold(old.name))
	if new and new.system_only:
		return _("Deals enter {0} by an action, not by hand.").format(frappe.bold(new.name))
	if new and new.roles and not set(new.roles) & set(frappe.get_roles(user or frappe.session.user)):
		return _("Only {0} can move deals into {1}.").format(
			", ".join(frappe.bold(_(r)) for r in new.roles), frappe.bold(new.name)
		)
	return None


def check_move(deal, old_stage_name, user=None):
	"""Raise StageError when the deal can't move from `old_stage_name` into its stage."""
	new = get_stage(deal.sales_stage)
	blocked = blocked_move(deal, get_stage(old_stage_name), new, user)
	if blocked:
		raise StageError(blocked)
	if not new:
		return

	problems = what_is_missing(deal, new)
	if problems["missing_fields"] or problems["failed_checks"]:
		lines = [
			_("{0} is needed").format(frappe.bold(_(f["label"]))) for f in problems["missing_fields"]
		] + [c["message"] for c in problems["failed_checks"]]
		raise StageError(
			_("The deal can't enter {0} yet:").format(frappe.bold(new.name))
			+ "<ul>"
			+ "".join(f"<li>{line}</li>" for line in lines)
			+ "</ul>",
			missing_fields=problems["missing_fields"],
			failed_checks=problems["failed_checks"],
		)


def what_is_missing(deal, stage):
	"""The fields and checks the deal still needs for `stage`, evaluated as if it were in it."""
	from eye_crm.eye.checks import run_checks

	before = (deal.eye_stage_type, deal.eye_stage_order, deal.sales_stage)
	deal.eye_stage_type, deal.eye_stage_order, deal.sales_stage = stage.type, stage.order, stage.name
	try:
		# Nexlify Board tries the save before its popup asks for the fields
		missing = [] if deal.flags.get("nx_skip_required") else missing_fields(deal)
	finally:
		deal.eye_stage_type, deal.eye_stage_order, deal.sales_stage = before
	return {"missing_fields": missing, "failed_checks": run_checks(deal, stage.checks)}


NUMBERS = ("Currency", "Float", "Int", "Percent")


def missing_fields(doc, prefix=None, zero_is_empty=False):
	"""Fields whose Mandatory Depends On holds and that are empty (only those whose name starts with
	`prefix`, if given). With `zero_is_empty`, a required number must be more than 0."""
	meta = frappe.get_meta(doc.doctype)
	out = []
	for df in meta.fields:
		if not df.mandatory_depends_on or df.fieldtype in frappe.model.no_value_fields:
			continue
		if prefix and not df.fieldname.startswith(prefix):
			continue
		try:
			required = conditions.evaluate(df.mandatory_depends_on, doc)
		except conditions.ConditionError:
			# outside what the server reads: the form still enforces it
			continue
		value = doc.get(df.fieldname)
		empty = is_empty(value, df) or (zero_is_empty and df.fieldtype in NUMBERS and not flt(value))
		if required and empty:
			out.append({"fieldname": df.fieldname, "label": df.label, "fieldtype": df.fieldtype})
	return out


def is_empty(value, df):
	"""As Frappe judges a mandatory field: 0 is a value, an empty editor is not."""
	from frappe.utils import cstr, strip_html

	if df.fieldtype in frappe.model.table_fields:
		return not value
	return value in (None, []) or not strip_html(cstr(value)).strip()
