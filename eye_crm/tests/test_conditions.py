"""Desk conditions (Mandatory Depends On), read on the server."""

from frappe.tests import IntegrationTestCase

from eye_crm.eye.conditions import ConditionError, evaluate, to_python

DOC = {
	"eye_stage_order": 30,
	"eye_po_status": "Purchase Order (PO)",
	"items": [{"qty": 2}],
	"empty": None,
	"__islocal": 1,
	"code": "abc",
	"number_text": "5",
}


class TestConditions(IntegrationTestCase):
	def test_reads_the_usual_javascript(self):
		cases = {
			"eval:doc.eye_stage_order >= 30 && doc.eye_po_status == 'Purchase Order (PO)'": True,
			"eval:doc.eye_stage_order >= 40": False,
			"eval:doc.empty >= 1": False,
			"eval:!doc.empty": True,
			"eval:doc.items.length > 0": True,
			"eval:doc.items[0].qty === 2": True,
			"eval:['A', 'Purchase Order (PO)'].includes(doc.eye_po_status)": True,
			"eval:in_list(['A', 'B'], doc.eye_po_status)": False,
			"eval:doc.__islocal": True,
			"eval:doc.code.startsWith('ab') || doc.empty": True,
			"eval:doc.number_text == 5": True,
			"eval:frappe.user.has_role('System Manager')": True,
			"eval:(doc.eye_stage_order + 10) % 20 == 0": True,
			"eval:doc.missing != null": False,
			"eye_po_status": True,
			"empty": False,
		}
		for expression, expected in cases.items():
			with self.subTest(expression=expression):
				self.assertEqual(evaluate(expression, DOC, user="Administrator"), expected)

	def test_refuses_what_it_does_not_read(self):
		for expression in ("eval:doc.a ? 1 : 2", "eval:window.location", "eval:doc.a.toUpperCase()"):
			with self.subTest(expression=expression), self.assertRaises(ConditionError):
				to_python(expression)

	def test_no_way_out_of_the_document(self):
		# dunder names are read as fields of the document, never as Python attributes
		self.assertFalse(evaluate("eval:doc.__class__.__mro__", DOC, user="Administrator"))
