"""Copy the masters of an old site to a new one: what deals need, not the deals themselves.

	cd sites && ../env/bin/python ../apps/eye_crm/scripts/copy_masters.py OLD_SITE NEW_SITE

Only what the new site doesn't have is added; nothing there is overwritten. Links to records the
new site doesn't have (a warehouse, an account, an employee) are left empty. Users keep their
passwords and get only the roles the new site has. The quotation PDF's texts and images come from
the old site's Proposal Template, when it has one.
"""

import os
import shutil
import sys

import frappe

# in the order they link to each other; trees are copied parents first
MASTERS = [
	"UOM",
	"Brand",
	"Item Group",
	"Customer Group",
	"Territory",
	"Supplier Group",
	"Sales Person",
	"Industry Type",
	"Market Segment",
	"Opportunity Type",
	"UTM Source",
	"Terms and Conditions",
	"Payment Term",
	"Payment Terms Template",
	"Price List",
	"Currency Exchange",
	"Item",
	"Item Price",
	"Customer",
	"Supplier",
	"Address",
	"Contact",
	"Sales Taxes and Charges Template",
	"User",
]
TREES = {"Item Group", "Customer Group", "Territory", "Supplier Group", "Sales Person"}
SKIP_USERS = {"Administrator", "Guest"}
# v1's fields, by their v2 names
FIELD_MAP = {
	"Item": {"custom_needs_min_margin": "eye_requires_min_margin", "custom_min_margin": "eye_min_margin"},
}
PDF_FIELDS = [
	"brand_color",
	"logo",
	"logo_white",
	"check_icon",
	"cover_title",
	"side_text",
	"about_title",
	"about",
	"why_title",
	"why_points",
	"references_title",
	"references_image",
	"prices_title",
]


def connect(site):
	frappe.init(site=site, sites_path=".")
	frappe.connect()
	frappe.set_user("Administrator")


def read(site):
	"""Everything to copy, read from the old site."""
	connect(site)
	try:
		data = {}
		for doctype in MASTERS:
			if not frappe.db.table_exists(doctype):
				continue
			order = "lft asc" if doctype in TREES else "creation asc"
			filters = {}
			if doctype == "User":
				filters = {"user_type": "System User", "name": ["not in", list(SKIP_USERS)]}
			names = frappe.get_all(doctype, filters=filters, pluck="name", order_by=order)
			if doctype == "Item":
				# templates before their variants
				names.sort(key=lambda n: frappe.db.get_value("Item", n, "variant_of") is not None)
			data[doctype] = [frappe.get_doc(doctype, n).as_dict(convert_dates_to_str=True) for n in names]
		data["__auth"] = frappe.db.sql(
			"select doctype, name, fieldname, password, encrypted from __Auth where doctype = 'User'",
			as_dict=True,
		)
		data["__pdf"] = read_pdf_design()
		data["__files_path"] = os.path.abspath(frappe.get_site_path("public", "files"))
		return data
	finally:
		frappe.destroy()


def read_pdf_design():
	"""v1's Proposal Template ("Eye Advertising"), as the new Eye CRM Settings' PDF values."""
	if not frappe.db.table_exists("Proposal Template"):
		return {}
	name = frappe.db.get_value("Proposal Template", {}, "name", order_by="creation asc")
	if not name:
		return {}
	t = frappe.get_doc("Proposal Template", name)
	out = {f: t.get(f) for f in PDF_FIELDS if t.get(f) is not None}
	if t.get("terms"):
		out["default_terms"] = t.terms
	files = [v for v in out.values() if isinstance(v, str) and v.startswith("/files/")]
	out["__files"] = [
		frappe.get_doc("File", f).as_dict()
		for f in frappe.get_all("File", filters={"file_url": ["in", files]}, pluck="name")
	]
	return out


def clean(doctype, row, meta=None):
	"""Keep the fields the new site has, and only the links it can resolve."""
	meta = meta or frappe.get_meta(doctype)
	for old, new in FIELD_MAP.get(doctype, {}).items():
		if row.get(old) is not None and not row.get(new):
			row[new] = row[old]
	known = {df.fieldname: df for df in meta.fields}
	out = {
		k: v
		for k, v in row.items()
		if k in known or k in ("name", "doctype", "owner", "creation", "idx", "docstatus")
	}
	for fieldname, df in known.items():
		value = out.get(fieldname)
		if df.fieldtype == "Link" and value and not frappe.db.exists(df.options, value):
			out[fieldname] = None
		elif df.fieldtype == "Dynamic Link" and value:
			target = out.get(df.options)
			if not target or not frappe.db.exists(target, value):
				out[fieldname] = None
		elif df.fieldtype in frappe.model.table_fields and value:
			child_meta = frappe.get_meta(df.options)
			out[fieldname] = [clean(df.options, dict(r), child_meta) for r in value]
	out["doctype"] = doctype
	out["owner"] = "Administrator"
	return out


def write(site, data):
	connect(site)
	frappe.flags.in_import = True
	frappe.flags.mute_emails = True
	added = {}
	try:
		roles = set(frappe.get_all("Role", pluck="name"))
		for doctype in MASTERS:
			for row in data.get(doctype, []):
				if frappe.db.exists(doctype, row["name"]):
					continue
				if doctype == "Item Price" and frappe.db.exists(
					"Item Price",
					{
						"item_code": row.get("item_code"),
						"price_list": row.get("price_list"),
						"uom": row.get("uom"),
					},
				):
					continue
				doc = clean(doctype, dict(row))
				if doctype == "Item" and doc.get("is_sales_item") and not doc.get("eye_requires_min_margin"):
					doc["eye_requires_min_margin"] = "No"
				if doctype == "User":
					doc["roles"] = [r for r in doc.get("roles", []) if r.get("role") in roles]
					doc["send_welcome_email"] = 0
				if doctype == "Sales Taxes and Charges Template" and any(
					not t.get("account_head") for t in doc.get("taxes", [])
				):
					print(f"  skipped {doctype} {row['name']}: its accounts are not on {site}")
					continue
				try:
					insert(doc, row["name"])
					added[doctype] = added.get(doctype, 0) + 1
				except Exception as e:
					frappe.db.rollback(save_point="eye_copy")
					print(f"  skipped {doctype} {row['name']}: {e}")
		copy_passwords(data["__auth"])
		copy_pdf_design(data["__pdf"], data["__files_path"])
		frappe.db.commit()
		for doctype, count in added.items():
			print(f"  {doctype}: {count}")
	finally:
		frappe.destroy()


def insert(data, name):
	frappe.db.savepoint("eye_copy")
	doc = frappe.get_doc(data)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.flags.no_welcome_mail = True
	doc.insert(set_name=name)


def copy_passwords(rows):
	users = set(frappe.get_all("User", pluck="name"))
	for row in rows:
		if row.name in users and row.name not in SKIP_USERS:
			frappe.db.sql(
				"""insert ignore into __Auth (doctype, name, fieldname, password, encrypted)
				values (%s, %s, %s, %s, %s)""",
				(row.doctype, row.name, row.fieldname, row.password, row.encrypted),
			)


def copy_pdf_design(design, old_files_path):
	if not design:
		return
	for f in design.pop("__files", []):
		filename = os.path.basename(f["file_url"])
		target = frappe.get_site_path("public", "files", filename)
		source = os.path.join(old_files_path, filename)
		if os.path.exists(source) and not os.path.exists(target):
			shutil.copy2(source, target)
		if not frappe.db.exists("File", {"file_url": f["file_url"]}):
			frappe.get_doc(
				{"doctype": "File", "file_url": f["file_url"], "file_name": f["file_name"], "is_private": 0}
			).insert(ignore_permissions=True)
	settings = frappe.get_single("Eye CRM Settings")
	for field, value in design.items():
		if field == "default_terms" and not frappe.db.exists("Terms and Conditions", value):
			continue
		settings.set(field, value)
	settings.flags.ignore_permissions = True
	settings.save()
	print("  quotation PDF: from the Proposal Template")


if __name__ == "__main__":
	old_site, new_site = sys.argv[1], sys.argv[2]
	print(f"Reading {old_site}")
	data = read(old_site)
	print(f"Writing {new_site}")
	write(new_site, data)
