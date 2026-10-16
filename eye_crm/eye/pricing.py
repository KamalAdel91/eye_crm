"""Prices from costs. Margins are on the selling price: selling = cost ÷ (1 - margin).

Pure functions, so the rules can be tested without a site.
"""

import math

from frappe.utils import flt

# a margin this close under the minimum is rounding, not a lower price
MARGIN_TOLERANCE = 0.005


def round_up(value: float, precision: int = 2) -> float:
	"""Round up to `precision` decimals, so a price never gives less than the margin asked for."""
	factor = 10**precision
	# round first: 12.3 * 100 is 1230.0000000000002 and must stay 12.30
	return math.ceil(round(flt(value) * factor, 6)) / factor


def selling_rate(unit_cost: float, margin: float, precision: int = 2) -> float | None:
	"""Unit price that gives `margin` % of the selling price. None when there is nothing to price
	from: no cost, or a margin of 100 % or more."""
	unit_cost, margin = flt(unit_cost), flt(margin)
	if unit_cost <= 0 or margin >= 100:
		return None
	return round_up(unit_cost / (1 - margin / 100), precision)


def margin_of(cost: float, selling: float) -> float:
	"""Margin on the selling price, in %. A service sold with no cost has a margin of 100 %."""
	cost, selling = flt(cost), flt(selling)
	if selling == 0:
		return 0.0
	return (selling - cost) / selling * 100


def is_below_minimum(margin: float, minimum: float) -> bool:
	return flt(margin) < flt(minimum) - MARGIN_TOLERANCE


def price_line(
	cost: float,
	qty: float,
	margin: float | None,
	rate: float | None,
	driver: str,
	precision: int = 2,
) -> dict:
	"""Price one service.

	cost    the service's total cost, in the deal currency
	driver  "margin": the price comes from the margin (the usual case)
	        "rate":   the unit price was typed, and the margin follows from it
	A service with no cost is priced by hand: its margin is 100 %.
	"""
	cost, qty = flt(cost, precision), flt(qty)
	unit_cost = flt(cost / qty, precision) if qty else 0.0

	if cost <= 0:
		# nothing to price from: the price is typed, and until it is the margin waits for a cost
		rate = flt(rate, precision)
		margin = 100.0 if rate > 0 else flt(margin)
	elif driver == "rate" and rate is not None:
		rate = flt(rate, precision)
		margin = margin_of(cost, rate * qty)
	else:
		margin = flt(margin)
		rate = selling_rate(cost / qty if qty else 0, margin, precision) or 0.0

	amount = flt(rate * qty, precision)
	return {
		"unit_cost": unit_cost,
		"margin": flt(margin, 3),
		"rate": rate,
		"amount": amount,
		"profit": flt(amount - cost, precision),
		# what the price really gives, after rounding: this is what the minimum is checked against
		"actual_margin": margin_of(cost, amount),
	}


def totals(lines: list[dict], precision: int = 2) -> dict:
	cost = flt(sum(flt(line.get("cost")) for line in lines), precision)
	selling = flt(sum(flt(line.get("amount")) for line in lines), precision)
	return {
		"total_cost": cost,
		"total_selling": selling,
		"total_profit": flt(selling - cost, precision),
		"margin": flt(margin_of(cost, selling), 3),
	}
