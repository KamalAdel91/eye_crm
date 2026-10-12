import frappe

DT, FIELD = "Opportunity", "sales_stage"
RULES = [
    ("Proposal", ["custom_service_type", "custom_deal_nature", "contact_person", "expected_closing"],
     "Fill the deal basics before moving to Proposal"),
    ("Project Won", ["expected_closing"],
     "Set the closing date before Project Won"),
    ("Quote approved", ["custom_po_status", "custom_po_number", "custom_po_date", "custom_po_attachment"],
     "The approval needs the PO details"),
]


def run():
    meta = frappe.get_meta(DT)
    for to, fields, message in RULES:
        present = [f for f in fields if meta.has_field(f)]
        skipped = [f for f in fields if f not in present]
        if not present:
            print(f"{to}: no fields found, skipped")
            continue
        name = frappe.db.get_value("Transition Rule", {"reference_doctype": DT, "stage_field": FIELD, "to_value": to})
        doc = frappe.get_doc("Transition Rule", name) if name else frappe.new_doc("Transition Rule")
        doc.update({"enabled": 1, "reference_doctype": DT, "stage_field": FIELD, "from_value": None,
                    "to_value": to, "message": message})
        doc.set("required_fields", [{"fieldname": f, "label": meta.get_label(f)} for f in present])
        doc.save(ignore_permissions=True)
        print(f"{to}: {doc.name} -> {present}" + (f"  (not found: {skipped})" if skipped else ""))
    frappe.db.commit()
