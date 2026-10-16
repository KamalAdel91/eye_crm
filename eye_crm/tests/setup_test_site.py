"""A fresh test site needs ERPNext's setup wizard done before the tests run (CI).

bench --site test_site execute eye_crm.tests.setup_test_site.run
"""

import frappe
from frappe.utils import getdate, nowdate


def run():
	if frappe.db.get_single_value("System Settings", "setup_complete"):
		return
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	year = getdate(nowdate()).year
	setup_complete(
		{
			"language": "English",
			"country": "Egypt",
			"timezone": "Africa/Cairo",
			"currency": "EGP",
			"company_name": "Eye Advertising",
			"company_abbr": "EYE",
			"chart_of_accounts": "Standard",
			"fy_start_date": f"{year}-01-01",
			"fy_end_date": f"{year}-12-31",
			"setup_demo": 0,
		}
	)
	frappe.db.commit()
