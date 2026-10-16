"""A deal from its first service to an open project, and its changes after."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from eye_crm.eye import changes, opening, stages
from eye_crm.eye.quotation import CHANGES_ONLY, latest_quotation, make_quotation
from eye_crm.tests import utils as u


def po():
	"""A customer PO: one per deal, as ERPNext allows one Sales Order per PO."""
	return {
		"eye_po_status": "Purchase Order (PO)",
		"eye_po_no": frappe.generate_hash(length=8),
		"eye_po_date": "2026-10-01",
	}


class EyeTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		u.make_exchange_rates()
		cls.it = u.items()
		cls.customer = u.make_customer()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def new_deal(self, booths=2, prints=10, booth_margin=None, **values):
		deal = u.make_deal([(self.it["booth"].name, booths), (self.it["print"].name, prints)], **values)
		u.add_costs(
			deal,
			[
				(1, self.it["wood"].name, 10, 500),  # EGP
				(1, self.it["labor"].name, 4, 1000),
				(2, self.it["labor"].name, 1, 200, "USD", 0),
			],
		)
		if booth_margin is not None:
			u.set_margins(deal, {1: booth_margin})
		deal.reload()
		return deal

	def to_in_hand(self, deal):
		deal = u.move(deal, "Quotation")
		return u.move(deal, "Deals in Hand", **po())

	def pl(self, deal):
		return frappe.get_doc("Deal PL", frappe.db.get_value("Opportunity", deal.name, "eye_pl"))


class TestDealDocuments(EyeTestCase):
	def test_services_get_numbers_and_documents(self):
		deal = self.new_deal()
		self.assertEqual([r.eye_service_no for r in deal.items], [1, 2])
		self.assertTrue(deal.eye_cost_sheet and deal.eye_pl)
		deal.append("items", {"item_code": self.it["print"].name, "qty": 1})
		deal.save()
		self.assertEqual(deal.items[-1].eye_service_no, 3)

	def test_costs_in_currencies_reach_the_pl(self):
		deal = self.new_deal()
		sheet = frappe.get_doc("Cost Sheet", deal.eye_cost_sheet)
		# sheet in EGP; 1 EGP = 0.02 USD; the last line is 200 USD = 10,000 EGP
		self.assertEqual(sheet.total_cost, 19000)
		self.assertEqual(sheet.total_cost_deal, 380)
		pl = self.pl(deal)
		self.assertEqual([line.cost for line in pl.lines], [180, 200])
		# the default margin, 30 %
		self.assertEqual([line.rate for line in pl.lines], [128.58, 28.58])
		self.assertEqual(flt(deal.opportunity_amount), pl.total_selling)

	def test_typed_price_stays_when_cost_changes(self):
		deal = self.new_deal()
		u.set_margins(deal, {}, rates={2: 40})
		u.add_costs(deal, [(2, self.it["labor"].name, 1, 1000)])  # +1,000 EGP = +20 USD
		line = self.pl(deal).lines[1]
		self.assertEqual((line.cost, line.rate), (220, 40))
		self.assertAlmostEqual(line.margin, 45.0, places=2)

	def test_removing_a_service_removes_its_costs(self):
		deal = self.new_deal()
		deal.items.pop()
		deal.save()
		sheet = frappe.get_doc("Cost Sheet", deal.eye_cost_sheet)
		self.assertEqual({line.service_no for line in sheet.lines}, {1})
		self.assertEqual([line.service_no for line in self.pl(deal).lines], [1])


class TestStages(EyeTestCase):
	def test_a_stage_asks_for_its_fields(self):
		deal = u.move(self.new_deal(), "Quotation")
		with self.assertRaises(stages.StageError) as e:
			u.move(deal, "Deals in Hand")
		self.assertEqual([f["fieldname"] for f in e.exception.missing_fields], ["eye_po_status"])
		with self.assertRaises(stages.StageError):
			u.move(deal, "Deals in Hand", eye_po_status="Purchase Order (PO)")  # PO number and date
		self.assertEqual(u.move(deal, "Deals in Hand", **po()).eye_stage_type, stages.IN_HAND)

	def test_a_stage_runs_its_checks(self):
		deal = u.make_deal([(self.it["booth"].name, 1)])
		with self.assertRaises(stages.StageError) as e:
			u.move(deal, "Open Project", **po())
		self.assertEqual({c["key"] for c in e.exception.failed_checks}, {"costs", "prices"})

	def test_system_stages_are_not_entered_by_hand(self):
		deal = self.new_deal()
		for stage in ("Needs Approval", "Project Opened", "Change Approval"):
			with self.subTest(stage=stage), self.assertRaises(stages.StageError):
				u.move(deal, stage)

	def test_who_can_move_deals_into_a_stage(self):
		stage = frappe.get_doc("Sales Stage", "Quotation")
		stage.append("eye_roles", {"role": "Accounts Manager"})
		stage.save()
		try:
			frappe.set_user(u.make_user("eye.sales1@example.com", ["Sales User"]).name)
			deal = self.new_deal()
			with self.assertRaises(stages.StageError):
				u.move(deal, "Quotation")
		finally:
			frappe.set_user("Administrator")
			stage.reload()
			stage.set("eye_roles", [])
			stage.save()

	def test_order_change_reaches_the_deals(self):
		deal = self.new_deal()
		stage = frappe.get_doc("Sales Stage", "Estimation")
		stage.eye_stage_order = 5
		stage.save()
		try:
			self.assertEqual(frappe.db.get_value("Opportunity", deal.name, "eye_stage_order"), 5)
		finally:
			stage.eye_stage_order = 10
			stage.save()


class TestQuotations(EyeTestCase):
	def test_quotation_stage_makes_the_quotation(self):
		deal = u.move(self.new_deal(), "Quotation")
		quotation = frappe.get_doc("Quotation", deal.eye_quotation)
		pl = self.pl(deal)
		self.assertEqual(quotation.docstatus, 0)
		self.assertEqual(quotation.eye_quotation_type, "Full")
		self.assertEqual([r.rate for r in quotation.items], [line.rate for line in pl.lines])
		self.assertEqual(quotation.conversion_rate, 50)

	def test_quotation_prices_come_from_the_pl(self):
		deal = u.move(self.new_deal(), "Quotation")
		quotation = frappe.get_doc("Quotation", deal.eye_quotation)
		quotation.items[0].rate = 1
		with self.assertRaises(frappe.ValidationError):
			quotation.save()

	def test_update_quotation(self):
		deal = u.move(self.new_deal(), "Quotation")
		first = deal.eye_quotation
		u.set_margins(deal, {2: 50})
		deal.reload()
		second = make_quotation(deal)
		self.assertEqual(frappe.db.get_value("Quotation", first, "eye_superseded"), 1)
		self.assertEqual(second.eye_revision_of, first)
		u.set_margins(deal, {1: 40})
		deal.reload()
		changes_only = make_quotation(deal, CHANGES_ONLY)
		self.assertEqual([r.eye_service_no for r in changes_only.items], [1])
		self.assertEqual(latest_quotation(deal.name).name, changes_only.name)


class TestOpening(EyeTestCase):
	def test_opens_without_approval(self):
		deal = self.to_in_hand(self.new_deal())
		deal = u.move(deal, "Open Project")
		self.assertEqual(deal.eye_stage_type, stages.OPENED)
		self.assertEqual(frappe.db.get_value("Deal PL", deal.eye_pl, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Cost Sheet", deal.eye_cost_sheet, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Quotation", deal.eye_quotation, "docstatus"), 1)
		so = frappe.get_doc("Sales Order", deal.eye_sales_order)
		pl = self.pl(deal)
		self.assertEqual(so.docstatus, 1)
		self.assertEqual(
			[(r.eye_service_no, r.rate) for r in so.items],
			[(line.service_no, line.rate) for line in pl.lines],
		)
		self.assertEqual((so.po_no, so.eye_pl), (deal.eye_po_no, pl.name))

	def test_below_minimum_needs_approval(self):
		deal = self.to_in_hand(self.new_deal(booth_margin=20))
		deal = u.move(deal, "Open Project")
		self.assertEqual(deal.eye_stage_type, stages.APPROVAL)
		self.assertEqual(self.pl(deal).approval_status, "Pending")
		self.assertFalse(deal.eye_sales_order)
		# locked while it waits
		with self.assertRaises(frappe.ValidationError):
			u.set_margins(deal, {1: 35})
		deal = opening.approve(deal.name)
		deal.reload()
		self.assertEqual(deal.eye_stage_type, stages.OPENED)
		self.assertTrue(deal.eye_sales_order)
		self.assertEqual(self.pl(deal).approval_status, "Approved")

	def test_reject_sends_the_deal_back(self):
		deal = self.to_in_hand(self.new_deal(booth_margin=20))
		deal = u.move(deal, "Open Project")
		with self.assertRaises(frappe.ValidationError):
			opening.reject(deal.name, "")
		opening.reject(deal.name, "Margin too low")
		deal.reload()
		pl = self.pl(deal)
		self.assertEqual(deal.sales_stage, "Deals in Hand")
		self.assertEqual(
			(pl.approval_status, pl.rejection_reason, pl.docstatus), ("Rejected", "Margin too low", 0)
		)

	def test_approving_needs_submit_on_the_pl(self):
		deal = self.to_in_hand(self.new_deal(booth_margin=20))
		deal = u.move(deal, "Open Project")
		frappe.set_user(u.make_user("eye.sales1@example.com", ["Sales User"]).name)
		with self.assertRaises(frappe.PermissionError):
			opening.approve(deal.name)


class TestChanges(EyeTestCase):
	def opened(self):
		deal = u.move(self.to_in_hand(self.new_deal()), "Open Project")
		self.assertEqual(deal.eye_stage_type, stages.OPENED)
		return deal

	def test_change_is_approved_and_updates_the_sales_order(self):
		deal = self.opened()
		approved = deal.eye_pl
		deal.items[1].qty = 20
		deal.save()
		deal.reload()
		self.assertEqual(deal.eye_change_pending, 1)
		revision = self.pl(deal)
		self.assertEqual(
			(revision.revision, revision.docstatus, revision.previous_revision), (2, 0, approved)
		)
		changes.send_for_approval(deal.name, "More prints")
		deal.reload()
		self.assertEqual(deal.eye_stage_type, stages.CHANGE_APPROVAL)
		changes.approve(deal.name)
		deal.reload()
		self.assertEqual((deal.eye_stage_type, deal.eye_change_pending), (stages.OPENED, 0))
		self.assertEqual(frappe.db.get_value("Deal PL", approved, "superseded"), 1)
		so = frappe.get_doc("Sales Order", deal.eye_sales_order)
		self.assertEqual([r.qty for r in so.items], [2, 20])
		self.assertEqual(so.eye_pl, revision.name)

	def test_new_service_reaches_the_sales_order(self):
		deal = self.opened()
		deal.append("items", {"item_code": self.it["print"].name, "qty": 5})
		deal.save()
		u.set_margins(deal, {}, rates={3: 10})
		changes.send_for_approval(deal.name, "Extra prints")
		changes.approve(deal.name)
		so = frappe.get_doc("Sales Order", frappe.db.get_value("Opportunity", deal.name, "eye_sales_order"))
		self.assertEqual([(r.eye_service_no, r.qty, r.rate) for r in so.items][-1], (3, 5, 10))

	def test_discard_puts_the_services_back(self):
		deal = self.opened()
		approved = deal.eye_pl
		deal.items[0].qty = 9
		deal.items[1].description = "New words"
		deal.save()
		changes.discard(deal.name)
		deal.reload()
		self.assertEqual(deal.eye_change_pending, 0)
		self.assertEqual(deal.eye_pl, approved)
		self.assertEqual(deal.items[0].qty, 2)
		# not a financial change: it stays
		self.assertEqual(deal.items[1].description, "New words")
		self.assertFalse(frappe.db.exists("Deal PL", {"previous_revision": approved}))

	def test_reject_keeps_the_change_with_its_reason(self):
		deal = self.opened()
		deal.items[1].qty = 30
		deal.save()
		changes.send_for_approval(deal.name, "More")
		changes.reject(deal.name, "Not agreed with the client")
		deal.reload()
		pl = self.pl(deal)
		self.assertEqual((deal.eye_stage_type, deal.eye_change_pending), (stages.OPENED, 1))
		self.assertEqual(
			(pl.approval_status, pl.rejection_reason), ("Rejected", "Not agreed with the client")
		)

	def test_description_change_needs_no_approval(self):
		deal = self.opened()
		deal.items[0].description = "Bigger letters"
		deal.save()
		deal.reload()
		self.assertEqual(deal.eye_change_pending, 0)


class TestVisibility(EyeTestCase):
	def test_documents_follow_the_deal(self):
		mine = u.make_user("eye.sales1@example.com", ["Sales User"])
		other = u.make_user("eye.sales2@example.com", ["Sales User"])
		frappe.set_user(mine.name)
		deal = self.new_deal()
		frappe.set_user(other.name)
		self.assertFalse(frappe.has_permission("Opportunity", "read", deal.name))
		self.assertFalse(frappe.has_permission("Deal PL", "read", deal.eye_pl))
		self.assertNotIn(deal.eye_pl, frappe.get_list("Deal PL", pluck="name"))
		# the Salesperson gets the deal
		frappe.set_user(mine.name)
		deal.reload()
		deal.opportunity_owner = other.name
		deal.save()
		frappe.set_user(other.name)
		self.assertTrue(frappe.has_permission("Deal PL", "read", deal.eye_pl))
		self.assertIn(deal.eye_pl, frappe.get_list("Deal PL", pluck="name"))
