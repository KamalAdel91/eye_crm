import frappe


def install_quotation_format():
    path = frappe.get_app_path("eye_crm_v1", "templates", "eye_quotation.html")
    html = open(path, encoding="utf-8").read()
    name = "Eye Quotation"

    if frappe.db.exists("Print Format", name):
        pf = frappe.get_doc("Print Format", name)
    else:
        pf = frappe.new_doc("Print Format")
        pf.name = name

    pf.update({
        "doc_type": "Quotation",
        "module": "Eye Crm",
        "custom_format": 1,
        "print_format_type": "Jinja",
        "standard": "No",
        "pdf_generator": "wkhtmltopdf",
        "html": html,
    })
    pf.save(ignore_permissions=True)
    frappe.db.commit()
    print(f"Print Format '{name}' installed")
