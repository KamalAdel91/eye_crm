# Copyright (c) 2026, Kamal Adel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from eye_crm.eye import deal as deals
from eye_crm.eye import stages


class CostSheet(Document):
	def before_insert(self):
		check_one_per_deal(self)

	def validate(self):
		deal = frappe.get_doc("Opportunity", self.opportunity)
		if not self.flags.get("eye_system"):
			check_deal_unlocked(deal, self)
		self.company = deal.company
		self.deal_currency = deal.currency
		if not flt(self.deal_exchange_rate):
			self.deal_exchange_rate = deals.exchange_rate(self.currency, self.deal_currency)
		self.calculate(deal)

	def calculate(self, deal):
		services = {cint(r.eye_service_no): r.item_code for r in deal.items}
		for line in self.lines:
			if cint(line.service_no) not in services:
				frappe.throw(
					_("Row #{0}: the deal has no service #{1}.").format(line.idx, line.service_no),
					title=_("Unknown Service"),
				)
			line.service_item = services[cint(line.service_no)]
			line.line_currency = line.line_currency or self.currency
			if line.line_currency == self.currency:
				line.exchange_rate = 1
			elif not flt(line.exchange_rate):
				line.exchange_rate = deals.exchange_rate(line.line_currency, self.currency)
			line.amount = flt(flt(line.qty) * flt(line.rate), 2)
			line.base_amount = flt(line.amount * flt(line.exchange_rate), 2)
		self.total_cost = flt(sum(flt(line.base_amount) for line in self.lines), 2)
		self.total_cost_deal = flt(sum(deals.service_costs(self).values()), 2)

	def before_submit(self):
		if not self.flags.get("eye_system"):
			frappe.throw(_("A Cost Sheet is submitted when its project opens or its change is approved."))

	def on_update(self):
		"""The P&L takes the new costs."""
		if self.flags.get("eye_system") or self.docstatus != 0:
			return
		deal = frappe.get_doc("Opportunity", self.opportunity)
		pl = deals.get_pl(deal)
		if pl and pl.docstatus == 0:
			deals.sync_pl(pl, deal, self)
			pl.flags.ignore_permissions = True
			pl.flags.eye_system = True
			pl.save()


def check_deal_unlocked(deal, doc):
	if deal.eye_stage_type in stages.LOCKED_TYPES:
		frappe.throw(
			_("Deal {0} is waiting for approval: its {1} can't change until it is decided.").format(
				frappe.bold(deal.name), _(doc.doctype)
			),
			title=_("Waiting for Approval"),
		)
	if doc.docstatus == 0 and cint(doc.get("superseded")):
		frappe.throw(_("{0} {1} was replaced by a newer revision.").format(_(doc.doctype), doc.name))


def check_one_per_deal(doc):
	"""A deal has one Cost Sheet and one P&L; a revision is made by the app, from the deal."""
	if doc.flags.get("eye_system"):
		return
	existing = frappe.db.get_value(
		doc.doctype, {"opportunity": doc.opportunity, "docstatus": ["<", 2], "superseded": 0}, "name"
	)
	if existing:
		frappe.throw(
			_("Deal {0} already has {1} {2}: change that one, from the deal.").format(
				frappe.bold(doc.opportunity), _(doc.doctype), frappe.bold(existing)
			),
			title=_("One per Deal"),
		)
