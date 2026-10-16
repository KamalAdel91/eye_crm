"""Billing an open project: requests, their stages and the deal's totals; changes once billing has
started; the notifications; and the boards' columns."""

import frappe
from frappe.utils import flt

from eye_crm.eye import api, billing, board, changes, opening, stages
from eye_crm.eye.sales_order import has_billing
from eye_crm.eye.stages import StageError
from eye_crm.tests import utils as u
from eye_crm.tests.test_deal_cycle import EyeTestCase

SALES = "eye.sales1@example.com"
OTHER_SALES = "eye.sales2@example.com"
ACCOUNTS = "eye.accounts@example.com"


class BillingTestCase(EyeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		u.make_user(SALES, ["Sales User"])
		u.make_user(OTHER_SALES, ["Sales User"])
		u.make_user(ACCOUNTS, ["Accounts User"])

	def opened(self, **values):
		"""A project open without approval. Its Sales Order: #1 booths 257.16, #2 prints 285.80 (USD)."""
		deal = u.move(self.to_in_hand(self.new_deal(**values)), "Open Project")
		self.assertEqual(deal.eye_stage_type, stages.OPENED)
		return deal

	def request(self, deal, amounts, stage=None, **values):
		lines = [{"service_no": no, "amount": amount} for no, amount in amounts.items()]
		name = billing.make_request(deal.name, lines, billing_stage=stage, **values)
		return frappe.get_doc("Billing Request", name)

	def move(self, request, stage, **values):
		request.reload()
		request.update(values)
		request.billing_stage = stage
		request.save()
		request.reload()
		return request

	def deal_numbers(self, deal):
		return frappe.db.get_value(
			"Opportunity",
			deal.name,
			[
				"eye_requested_amount",
				"eye_left_to_request",
				"eye_invoiced_amount",
				"eye_invoiced_percent",
				"eye_collected_amount",
				"eye_collected_percent",
			],
			as_dict=True,
		)


class TestBillingRequests(BillingTestCase):
	def test_a_request_takes_the_sales_order(self):
		deal = self.opened()
		request = self.request(deal, {1: 100})
		self.assertEqual(request.billing_stage, "To be invoiced")
		self.assertEqual(request.stage_type, billing.DRAFT)
		self.assertEqual(
			(request.sales_order, request.currency, request.customer),
			(deal.eye_sales_order, "USD", deal.party_name),
		)
		row = request.items[0]
		self.assertEqual(
			(row.service_no, row.so_amount, row.requested_before, row.available, row.amount, row.percent),
			(1, 257.16, 0, 257.16, 100, 38.89),
		)
		self.assertEqual(request.total, 100)
		numbers = self.deal_numbers(deal)
		self.assertEqual((numbers.eye_requested_amount, numbers.eye_left_to_request), (100, 442.96))
		self.assertTrue(has_billing(deal.eye_sales_order))

	def test_requests_never_ask_for_more_than_the_service(self):
		deal = self.opened()
		self.request(deal, {1: 200})
		with self.assertRaises(frappe.ValidationError):
			self.request(deal, {1: 100})
		second = self.request(deal, {1: 57.16, 2: 10})
		self.assertEqual((second.items[0].requested_before, second.items[0].available), (200, 57.16))
		with self.assertRaises(frappe.ValidationError):
			second.items[1].amount = -5
			second.save()

	def test_a_new_request_needs_the_open_project(self):
		deal = self.to_in_hand(self.new_deal())
		with self.assertRaises(frappe.ValidationError):
			billing.get_new_request(deal.name)

	def test_where_a_request_can_start(self):
		deal = self.opened()
		with self.assertRaises(StageError):
			self.request(deal, {1: 50}, stage="Invoiced")
		sent = self.request(deal, {1: 50}, stage="Finance, please issue")
		self.assertEqual(sent.stage_type, billing.REQUESTED)
		self.assertTrue(sent.sent_on)

	def test_nothing_to_invoice_stays_a_draft(self):
		deal = self.opened()
		request = billing.new_request(deal)
		request.insert()
		self.assertEqual(request.total, 0)
		with self.assertRaises(StageError):
			self.move(request, "Finance, please issue")

	def test_finance_issues_the_invoice_and_records_the_payment(self):
		frappe.set_user(SALES)
		deal = self.opened()
		request = self.request(deal, {1: 100, 2: 85.80})
		request = self.move(request, "Finance, please issue")
		self.assertTrue(request.sent_on)
		# only Finance moves a request into Invoiced
		with self.assertRaises(StageError):
			self.move(request, "Invoiced")

		frappe.set_user(ACCOUNTS)
		with self.assertRaises(StageError) as needs:
			self.move(request, "Invoiced")
		self.assertEqual(
			[f["fieldname"] for f in needs.exception.missing_fields], ["invoice_number", "invoice_date"]
		)
		request = self.move(
			request, "Invoiced", invoice_number="INV-0001", invoice_date="2026-10-16", invoice_id="9876543"
		)
		numbers = self.deal_numbers(deal)
		self.assertEqual((numbers.eye_invoiced_amount, numbers.eye_invoiced_percent), (185.80, 34.22))
		# an issued invoice keeps its amounts, and its request
		with self.assertRaises(frappe.ValidationError):
			request.items[0].amount = 90
			request.save()
		request.reload()
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Billing Request", request.name)
		frappe.set_user(ACCOUNTS)
		# nothing collected is no payment
		with self.assertRaises(StageError) as needs:
			self.move(request, "Collected", collected_on="2026-10-20")
		self.assertEqual([f["fieldname"] for f in needs.exception.missing_fields], ["collected_amount"])
		with self.assertRaises(frappe.ValidationError):
			self.move(request, "Collected", collected_amount=200, collected_on="2026-10-20")
		request = self.move(request, "Collected", collected_amount=185.80, collected_on="2026-10-20")
		numbers = self.deal_numbers(deal)
		self.assertEqual((numbers.eye_collected_amount, numbers.eye_collected_percent), (185.80, 34.22))

		# Sales can't type the invoice
		frappe.set_user(SALES)
		other = self.request(deal, {1: 50})
		other.invoice_number = "MINE"
		other.save()
		other.reload()
		self.assertFalse(other.invoice_number)

	def test_requests_follow_the_deal(self):
		frappe.set_user(SALES)
		deal = self.opened()
		request = self.request(deal, {1: 10})
		frappe.set_user(OTHER_SALES)
		self.assertFalse(frappe.has_permission("Billing Request", "read", request.name))
		self.assertNotIn(request.name, frappe.get_list("Billing Request", pluck="name"))
		frappe.set_user(ACCOUNTS)
		self.assertTrue(frappe.has_permission("Billing Request", "write", request.name))

	def test_finance_sees_the_deal_and_decides(self):
		deal = self.to_in_hand(self.new_deal(booth_margin=20))
		deal = u.move(deal, "Open Project")
		frappe.set_user(ACCOUNTS)
		view = api.deal_view(deal.name)
		self.assertEqual(view["pl"]["name"], deal.eye_pl)
		self.assertTrue(view["quotations"])
		# Finance decides; prices and costs belong to whoever works on the deal
		self.assertEqual(
			(view["can"]["decide"], view["can"]["prices"], view["can"]["costs"]), (True, False, False)
		)
		with self.assertRaises(frappe.PermissionError):
			api.save_prices(deal.name, [])

	def test_deleting_a_draft_gives_its_amount_back(self):
		deal = self.opened()
		request = self.request(deal, {2: 285.80})
		self.assertEqual(self.deal_numbers(deal).eye_left_to_request, 257.16)
		frappe.delete_doc("Billing Request", request.name)
		self.assertEqual(self.deal_numbers(deal).eye_left_to_request, 542.96)


class TestBillingAndChanges(BillingTestCase):
	def try_save(self, doc):
		frappe.db.savepoint("eye_try")
		try:
			doc.save()
		except frappe.ValidationError:
			frappe.db.rollback(save_point="eye_try")
			raise

	def test_a_change_keeps_what_billing_asked_for(self):
		deal = self.opened()
		self.request(deal, {2: 285.80})
		deal.reload()
		deal.items[1].qty = 5
		with self.assertRaises(frappe.ValidationError):
			self.try_save(deal)
		deal.reload()
		deal.set("items", deal.items[:1])
		with self.assertRaises(frappe.ValidationError):
			self.try_save(deal)
		# more prints at the same cost sell each one for less: 12 x 23.81 is below what is asked
		deal.reload()
		deal.items[1].qty = 12
		with self.assertRaises(frappe.ValidationError):
			self.try_save(deal)
		# a higher price is fine
		api.save_prices(
			deal.name, [{"service_no": 2, "rate": 30, "fixed_price": 1, "margin": 0, "no_cost": 0}]
		)
		changes.send_for_approval(deal.name, "Higher price")
		changes.approve(deal.name)
		self.assertEqual(self.deal_numbers(deal).eye_left_to_request, flt(257.16 + 300 - 285.80, 2))

	def test_billing_keeps_the_currency(self):
		deal = self.opened()
		self.request(deal, {1: 10})
		frappe.db.savepoint("eye_try")
		with self.assertRaises(frappe.ValidationError):
			api.save_prices(deal.name, [], currency=u.currency(), conversion_rate=1)
		frappe.db.rollback(save_point="eye_try")


class TestNotifications(BillingTestCase):
	def logs(self, user, document_type, document_name):
		return frappe.get_all(
			"Notification Log",
			filters={"for_user": user, "document_type": document_type, "document_name": document_name},
			pluck="subject",
		)

	def test_finance_hears_of_approvals_and_requests(self):
		deal = self.to_in_hand(self.new_deal(booth_margin=20, opportunity_owner=SALES))
		deal = u.move(deal, "Open Project")
		self.assertEqual(deal.eye_approval_status, "Pending")
		self.assertTrue(any("needs approval" in s for s in self.logs(ACCOUNTS, "Opportunity", deal.name)))
		frappe.set_user(ACCOUNTS)
		opening.approve(deal.name)
		self.assertEqual(frappe.db.get_value("Opportunity", deal.name, "eye_approval_status"), "Approved")
		self.assertTrue(any("Approved" in s for s in self.logs(SALES, "Opportunity", deal.name)))

		frappe.set_user("Administrator")
		request = self.request(deal, {1: 50}, stage="Finance, please issue")
		self.assertTrue(
			any("Invoice requested" in s for s in self.logs(ACCOUNTS, "Billing Request", request.name))
		)
		frappe.set_user(ACCOUNTS)
		self.move(request, "Invoiced", invoice_number="INV-7", invoice_date="2026-10-16")
		self.assertTrue(any("INV-7" in s for s in self.logs(SALES, "Billing Request", request.name)))


class TestBoards(BillingTestCase):
	def columns(self, board_name):
		return [
			(c.column_name, c.indicator)
			for c in frappe.get_doc("Kanban Board", board_name).columns
			if c.status == "Active"
		]

	def test_the_boards_follow_the_stages(self):
		stage_names = frappe.get_all("Sales Stage", order_by="eye_stage_order asc", pluck="name")
		self.assertEqual([c for c, _i in self.columns("Deals")], stage_names)
		self.assertEqual(
			[c for c, _i in self.columns("Billing")],
			frappe.get_all("Billing Stage", order_by="sequence asc", pluck="name"),
		)
		stage = frappe.get_doc(
			{
				"doctype": "Sales Stage",
				"stage_name": "_Test Eye Stage",
				"eye_stage_type": "Pipeline",
				"eye_stage_order": 25,
				"eye_color": "#EF4444",
			}
		).insert()
		try:
			names = [c for c, _i in self.columns("Deals")]
			self.assertEqual(names.index("_Test Eye Stage"), names.index("Quotation") + 1)
			self.assertIn(("_Test Eye Stage", "Red"), self.columns("Deals"))
			stage.eye_color = "#22C55E"
			stage.save()
			self.assertIn(("_Test Eye Stage", "Green"), self.columns("Deals"))
			frappe.rename_doc("Sales Stage", stage.name, "_Test Eye Stage 2")
			names = [c for c, _i in self.columns("Deals")]
			self.assertIn("_Test Eye Stage 2", names)
			self.assertNotIn("_Test Eye Stage", names)
		finally:
			for name in ("_Test Eye Stage", "_Test Eye Stage 2"):
				if frappe.db.exists("Sales Stage", name):
					frappe.delete_doc("Sales Stage", name)
		self.assertEqual([c for c, _i in self.columns("Deals")], stage_names)

	def test_nearest_column_color(self):
		self.assertEqual(
			[board.indicator(c) for c in ("#22C55E", "#1DA7DF", "#F59E0B", "", "not a color")],
			["Green", "Blue", "Yellow", "Gray", "Gray"],
		)

	def test_the_flow_says_what_each_stage_needs(self):
		deal = self.new_deal()
		flow = board.flow("Opportunity", deal.name)
		self.assertEqual(flow["field"], "sales_stage")
		steps = {(s["stage"], s["label"]): s for s in flow["steps"]}
		self.assertTrue(steps[("Quotation", "Prices Set")]["done"])
		self.assertEqual(steps[("Deals in Hand", "Fill PO Status")]["action"], "fields:eye_po_status")
		# a field is asked once, at the first stage that needs it
		self.assertNotIn(("Open Project", "Fill PO Status"), steps)

	def test_the_board_asks_for_fields_in_its_popup(self):
		# Nexlify Board's dry run before its popup: fields are left to the popup, checks still count
		deal = self.new_deal()
		deal.flags.nx_skip_required = True
		problems = stages.what_is_missing(deal, stages.get_stage("Deals in Hand"))
		self.assertEqual(problems["missing_fields"], [])
		self.assertTrue(problems["failed_checks"])
