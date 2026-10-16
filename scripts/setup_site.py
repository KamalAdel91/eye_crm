"""Finish ERPNext's setup wizard on a new site, with the company of an old site (or Eye's defaults).

cd sites && ../env/bin/python ../apps/eye_crm/scripts/setup_site.py NEW_SITE [OLD_SITE]
"""

import sys

import frappe
from frappe.utils import getdate, nowdate

DEFAULTS = {
	"language": "English",
	"country": "Egypt",
	"timezone": "Africa/Cairo",
	"currency": "EGP",
	"company_name": "Eye Advertising",
	"company_abbr": "EYE",
	"chart_of_accounts": "Standard",
}


def from_old_site(site):
	frappe.init(site=site, sites_path=".")
	frappe.connect()
	try:
		company = (
			frappe.db.get_single_value("Global Defaults", "default_company")
			or frappe.get_all("Company", pluck="name", limit=1)[0]
		)
		c = frappe.db.get_value(
			"Company",
			company,
			["company_name", "abbr", "country", "default_currency", "chart_of_accounts"],
			as_dict=True,
		)
		system = frappe.get_single("System Settings")
		fy = frappe.db.get_value(
			"Fiscal Year",
			{"year_start_date": ["<=", nowdate()], "year_end_date": [">=", nowdate()], "disabled": 0},
			["year_start_date", "year_end_date"],
			as_dict=True,
		)
		return {
			"language": frappe.db.get_value("Language", system.language, "language_name") or "English",
			"country": c.country or system.country,
			"timezone": system.time_zone,
			"currency": c.default_currency,
			"company_name": c.company_name,
			"company_abbr": c.abbr,
			"chart_of_accounts": c.chart_of_accounts or "Standard",
			**(
				{"fy_start_date": str(fy.year_start_date), "fy_end_date": str(fy.year_end_date)} if fy else {}
			),
		}
	finally:
		frappe.destroy()


def setup(site, args):
	frappe.init(site=site, sites_path=".")
	frappe.connect()
	try:
		frappe.set_user("Administrator")
		if frappe.db.get_single_value("System Settings", "setup_complete"):
			print(f"{site}: setup already done")
			return
		year = getdate(nowdate()).year
		args = {"fy_start_date": f"{year}-01-01", "fy_end_date": f"{year}-12-31", **args, "setup_demo": 0}
		from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

		print(
			f"{site}: setup {args['company_name']} ({args['company_abbr']}), {args['currency']}:",
			setup_complete(args),
		)
		frappe.db.commit()
	finally:
		frappe.destroy()


if __name__ == "__main__":
	new_site = sys.argv[1]
	old_site = sys.argv[2] if len(sys.argv) > 2 else None
	setup(new_site, from_old_site(old_site) if old_site else dict(DEFAULTS))
