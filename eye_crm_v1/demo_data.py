import frappe
from frappe.utils import today

CUSTOMER = "MSD Animal Health KSA"


def make_demo_quotation():
    company = frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name")[0]
    abbr = frappe.db.get_value("Company", company, "abbr")

    if not frappe.db.exists("Customer", CUSTOMER):
        frappe.get_doc({"doctype": "Customer", "customer_name": CUSTOMER, "customer_type": "Company"}).insert()

    contact = frappe.db.get_value("Dynamic Link",
        {"parenttype": "Contact", "link_doctype": "Customer", "link_name": CUSTOMER}, "parent")
    if not contact:
        contact = frappe.get_doc({"doctype": "Contact", "first_name": "Dr. Hesham", "last_name": "Hussein",
            "links": [{"link_doctype": "Customer", "link_name": CUSTOMER}]}).insert().name

    group = "Services" if frappe.db.exists("Item Group", "Services") else "All Item Groups"
    lines = [("Booth giveaways development", 500, 120), ("Branded tote bags", 300, 85.5), ("Printing & delivery", 1, 4500)]
    for code, _, _ in lines:
        if not frappe.db.exists("Item", code):
            frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": code, "item_group": group,
                "stock_uom": "Nos", "is_stock_item": 0}).insert()

    taxes = []
    vat = f"VAT 14% - {abbr}"
    parent = frappe.db.get_value("Account", {"company": company, "account_name": "Duties and Taxes", "is_group": 1})
    if parent and not frappe.db.exists("Account", vat):
        frappe.get_doc({"doctype": "Account", "account_name": "VAT 14%", "parent_account": parent,
            "company": company, "account_type": "Tax", "tax_rate": 14}).insert()
    if frappe.db.exists("Account", vat):
        taxes = [{"charge_type": "On Net Total", "account_head": vat, "description": "VAT 14%", "rate": 14}]

    q = frappe.get_doc({
        "doctype": "Quotation", "quotation_to": "Customer", "party_name": CUSTOMER,
        "company": company, "contact_person": contact, "transaction_date": today(),
        "items": [{"item_code": c, "qty": qty, "rate": r} for c, qty, r in lines],
        "taxes": taxes,
    })
    if frappe.get_meta("Quotation").has_field("custom_quotation_title"):
        q.custom_quotation_title = "Booth giveaways development quotation"
    q.insert()
    frappe.db.commit()
    print(q.name)
