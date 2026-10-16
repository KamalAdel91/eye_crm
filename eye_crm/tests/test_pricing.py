"""Prices from costs: selling = cost / (1 - margin), margins on the selling price."""

from frappe.tests import UnitTestCase

from eye_crm.eye import pricing


class TestPricing(UnitTestCase):
	def test_selling_rate(self):
		self.assertEqual(pricing.selling_rate(100, 20), 125.0)
		self.assertEqual(pricing.selling_rate(100, 0), 100.0)
		# rounded up, so the margin is never less than asked: 100 / 0.7 = 142.857...
		self.assertEqual(pricing.selling_rate(100, 30), 142.86)
		self.assertIsNone(pricing.selling_rate(100, 100))
		self.assertIsNone(pricing.selling_rate(0, 30))

	def test_round_up_ignores_float_noise(self):
		self.assertEqual(pricing.round_up(12.3), 12.3)
		self.assertEqual(pricing.round_up(12.301), 12.31)

	def test_margin_of(self):
		self.assertAlmostEqual(pricing.margin_of(100, 125), 20.0)
		self.assertEqual(pricing.margin_of(0, 50), 100.0)
		self.assertEqual(pricing.margin_of(10, 0), 0.0)

	def test_below_minimum_allows_rounding(self):
		self.assertFalse(pricing.is_below_minimum(29.996, 30))
		self.assertTrue(pricing.is_below_minimum(29.99, 30))
		self.assertFalse(pricing.is_below_minimum(30, 30))

	def test_price_from_margin(self):
		line = pricing.price_line(cost=180, qty=2, margin=20, rate=None, driver="margin")
		self.assertEqual(line["unit_cost"], 90.0)
		self.assertEqual(line["rate"], 112.5)
		self.assertEqual(line["amount"], 225.0)
		self.assertEqual(line["profit"], 45.0)
		self.assertAlmostEqual(line["actual_margin"], 20.0)

	def test_typed_price(self):
		line = pricing.price_line(cost=100, qty=1, margin=99, rate=150, driver="rate")
		self.assertEqual(line["rate"], 150.0)
		self.assertAlmostEqual(line["margin"], 33.333, places=3)

	def test_no_cost(self):
		# priced by hand: the margin is 100 %
		line = pricing.price_line(cost=0, qty=3, margin=30, rate=40, driver="margin")
		self.assertEqual((line["rate"], line["amount"], line["margin"]), (40.0, 120.0, 100.0))
		# not priced yet: the margin waits for a cost
		line = pricing.price_line(cost=0, qty=3, margin=30, rate=0, driver="margin")
		self.assertEqual((line["rate"], line["margin"]), (0.0, 30.0))

	def test_totals(self):
		total = pricing.totals([{"cost": 100, "amount": 125}, {"cost": 0, "amount": 75}])
		self.assertEqual(total["total_cost"], 100.0)
		self.assertEqual(total["total_selling"], 200.0)
		self.assertEqual(total["total_profit"], 100.0)
		self.assertEqual(total["margin"], 50.0)
