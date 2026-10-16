import json
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

M = "Eye Crm"
STAGES = ["Estimation", "Proposal", "Project Won", "Quote approved"]

PERMS = [
    {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
    {"role": "Sales Manager", "read": 1, "write": 1, "create": 1},
    {"role": "Sales User", "read": 1},
]

LISTS = {
    "Deal Nature": {"values": ["Pass-Through Cost", "Service"]},
    "Service Type": {
        "extra": [{"fieldname": "deal_nature", "label": "Deal Nature", "fieldtype": "Link",
                   "options": "Deal Nature", "reqd": 1, "in_list_view": 1}],
        "values": [("Event", "Pass-Through Cost"), ("Booths", "Service"), ("Printing", "Service"),
                   ("eDetailing", "Service"), ("SM Content", "Service")],
    },
    "PO Status": {"values": ["To receive the PO this month", "Purchase Order (PO)"]},
    "Pricing Status": {"values": ["With Production", "Priced"]},
}


def _make_list_doctype(name, extra):
    if frappe.db.exists("DocType", name):
        if frappe.db.get_value("Module Def", frappe.db.get_value("DocType", name, "module"), "app_name") != "eye_crm_v1":
            frappe.throw(f"DocType '{name}' already exists in another app")
        return
    frappe.get_doc({
        "doctype": "DocType", "name": name, "module": M, "custom": 0,
        "autoname": "field:title", "naming_rule": "By fieldname", "quick_entry": 1,
        "fields": [{"fieldname": "title", "label": "Name", "fieldtype": "Data",
                    "reqd": 1, "unique": 1, "in_list_view": 1}] + (extra or []),
        "permissions": PERMS,
    }).insert()


def _seed(name, values):
    for v in values:
        title, nature = (v if isinstance(v, tuple) else (v, None))
        if frappe.db.exists(name, title):
            continue
        d = {"doctype": name, "title": title}
        if nature:
            d["deal_nature"] = nature
        frappe.get_doc(d).insert(ignore_permissions=True)


def setup():
    for s in STAGES:
        if not frappe.db.exists("Sales Stage", s):
            frappe.get_doc({"doctype": "Sales Stage", "stage_name": s}).insert(ignore_permissions=True)

    for name, cfg in LISTS.items():
        _make_list_doctype(name, cfg.get("extra"))
    frappe.db.commit()
    for name, cfg in LISTS.items():
        _seed(name, cfg["values"])

    po_wait = "eval:doc.custom_po_status=='To receive the PO this month'"
    po_in = "eval:doc.custom_po_status=='Purchase Order (PO)'"
    create_custom_fields({
        "Opportunity": [
            {"fieldname": "custom_deal_section", "label": "Deal", "fieldtype": "Section Break", "insert_after": "sales_stage", "module": M},
            {"fieldname": "custom_pricing_status", "label": "Pricing", "fieldtype": "Link", "options": "Pricing Status",
             "read_only": 1, "insert_after": "custom_deal_section", "module": M},
            {"fieldname": "custom_po_status", "label": "Purchase Order", "fieldtype": "Link", "options": "PO Status",
             "insert_after": "custom_pricing_status", "module": M},
            {"fieldname": "custom_expected_po_date", "label": "Expected PO Date", "fieldtype": "Date",
             "depends_on": po_wait, "mandatory_depends_on": po_wait, "insert_after": "custom_po_status", "module": M},
            {"fieldname": "custom_po_no", "label": "PO Number", "fieldtype": "Data",
             "depends_on": po_in, "mandatory_depends_on": po_in, "insert_after": "custom_expected_po_date", "module": M},
        ],
        "Opportunity Item": [
            {"fieldname": "custom_cost", "label": "Cost (Production)", "fieldtype": "Currency",
             "options": "currency", "in_list_view": 1, "insert_after": "qty", "module": M},
            {"fieldname": "custom_margin", "label": "Margin %", "fieldtype": "Percent",
             "in_list_view": 1, "insert_after": "custom_cost", "module": M},
        ],
    })
    frappe.db.commit()
    print("Eye CRM structure ready")


APP_ROLES = {"System Manager", "Sales User", "Sales Manager", "Production", "Accounts User", "Accounts Manager", "Management"}
EYE_SIDEBAR_LINKS = {"Service Type", "Deal Nature", "PO Status", "Pricing Status", "Pricing Request"}


def has_app_permission():
    return bool(APP_ROLES & set(frappe.get_roles()))


def _ensure(doctype, name, data):
    if frappe.db.exists(doctype, name):
        return
    frappe.get_doc({"doctype": doctype, **data}).insert(ignore_permissions=True)


def _blocks(*rows):
    out = []
    for i, (kind, key, value, col) in enumerate(rows):
        data = {"col": col}
        if kind == "header":
            data["text"] = f'<span class="h4"><b>{value}</b></span>'
        else:
            data[key] = value
        out.append({"id": f"eye{i:07d}", "type": kind, "data": data})
    return json.dumps(out)


def _f(*conds):
    return json.dumps([list(c) + [False] for c in conds])


def setup_app_ui():
    for m in ("Eye Home", "Eye Sales", "Eye Production"):
        _ensure("Module Def", m, {"module_name": m, "app_name": "eye_crm_v1"})

    cards = {
        "Open Opportunities": ("Opportunity", _f(("Opportunity", "status", "=", "Open")), None, "#3B82F6"),
        "Won This Month": ("Opportunity", _f(("Opportunity", "sales_stage", "in", ["Project Won", "Quote approved"]),
                                             ("Opportunity", "modified", "Timespan", "this month")), None, "#10B981"),
        "Open Pricing Requests": ("Pricing Request", _f(("Pricing Request", "docstatus", "=", "0")), None, "#F59E0B"),
        "Overdue Pricing Requests": ("Pricing Request", _f(("Pricing Request", "docstatus", "=", "0")),
                                     json.dumps([["Pricing Request", "required_by", "<", "frappe.datetime.get_today()"]]), "#EF4444"),
    }
    for label, (dt, flt_json, dyn, color) in cards.items():
        _ensure("Number Card", label, {
            "name": label, "label": label, "type": "Document Type", "document_type": dt, "function": "Count",
            "filters_json": flt_json, "dynamic_filters_json": dyn or "[]", "color": color,
            "is_public": 1, "is_standard": 1, "module": "Eye Home",
        })

    charts = {
        "Deals by Stage": {"chart_type": "Group By", "document_type": "Opportunity", "group_by_type": "Count",
                           "group_by_based_on": "sales_stage", "type": "Bar",
                           "filters_json": _f(("Opportunity", "status", "!=", "Lost"))},
        "Pricing Requests per Month": {"chart_type": "Count", "document_type": "Pricing Request", "based_on": "creation",
                                       "timeseries": 1, "timespan": "Last Year", "time_interval": "Monthly",
                                       "type": "Line", "filters_json": _f(("Pricing Request", "docstatus", "!=", "2"))},
    }
    for name, d in charts.items():
        _ensure("Dashboard Chart", name, {"chart_name": name, "is_public": 1, "is_standard": 1,
                                          "module": "Eye Home", **d})

    def shortcut(label, dt, color, stats=None):
        return {"type": "DocType", "link_to": dt, "label": label, "doc_view": "List", "color": color,
                "stats_filter": stats or "[]"}

    def roles(*r):
        return [{"role": x} for x in r]

    workspaces = {
        "Eye Home": {
            "icon": "chart-column", "roles": roles("System Manager"),
            "number_cards": [{"number_card_name": c, "label": c} for c in cards],
            "charts": [{"chart_name": c, "label": c} for c in charts],
            "content": _blocks(("header", None, "Overview", 12),
                               *[("number_card", "number_card_name", c, 3) for c in cards],
                               ("chart", "chart_name", "Deals by Stage", 6),
                               ("chart", "chart_name", "Pricing Requests per Month", 12)),
        },
        "Eye Sales": {
            "icon": "handshake", "roles": roles("Sales User", "Sales Manager", "System Manager"),
            "number_cards": [{"number_card_name": "Open Opportunities", "label": "Open Opportunities"}],
            "shortcuts": [shortcut("Opportunities", "Opportunity", "Blue", _f(("Opportunity", "status", "=", "Open"))),
                          shortcut("Pricing Requests", "Pricing Request", "Orange", _f(("Pricing Request", "docstatus", "=", "0"))),
                          shortcut("Quotations", "Quotation", "Green"),
                          shortcut("Customers", "Customer", "Grey")],
            "content": _blocks(("header", None, "Sales", 12),
                               ("number_card", "number_card_name", "Open Opportunities", 4),
                               ("header", None, "Go to", 12),
                               ("shortcut", "shortcut_name", "Opportunities", 3),
                               ("shortcut", "shortcut_name", "Pricing Requests", 3),
                               ("shortcut", "shortcut_name", "Quotations", 3),
                               ("shortcut", "shortcut_name", "Customers", 3)),
        },
        "Eye Production": {
            "icon": "factory", "roles": roles("Production", "System Manager"),
            "number_cards": [{"number_card_name": c, "label": c} for c in ("Open Pricing Requests", "Overdue Pricing Requests")],
            "shortcuts": [shortcut("Open Requests", "Pricing Request", "Orange", _f(("Pricing Request", "docstatus", "=", "0"))),
                          shortcut("Items", "Item", "Grey")],
            "content": _blocks(("header", None, "Pricing", 12),
                               ("number_card", "number_card_name", "Open Pricing Requests", 6),
                               ("number_card", "number_card_name", "Overdue Pricing Requests", 6),
                               ("header", None, "Go to", 12),
                               ("shortcut", "shortcut_name", "Open Requests", 4),
                               ("shortcut", "shortcut_name", "Items", 4)),
        },
    }
    for label, d in workspaces.items():
        _ensure("Workspace", label, {"label": label, "title": label, "module": label, "public": 1,
                                     "standard": 1, "type": "Workspace", **d})

    def link(label, dt, child=0, link_type="DocType"):
        return {"type": "Link", "label": label, "link_type": link_type, "link_to": dt, "child": child, "collapsible": 1}

    def section(label, icon):
        return {"type": "Section Break", "label": label, "icon": icon, "indent": 1, "collapsible": 1}

    sidebars = {
        "Eye Home": ("chart-column", [
            link("Home", "Eye Home", link_type="Workspace"),
            link("Opportunity", "Opportunity"), link("Pricing Request", "Pricing Request"), link("Quotation", "Quotation"),
            section("Setup", "settings"),
            link("Service Type", "Service Type", 1), link("Deal Nature", "Deal Nature", 1),
            link("PO Status", "PO Status", 1), link("Pricing Status", "Pricing Status", 1),
            link("Sales Stage", "Sales Stage", 1), link("Print Format", "Print Format", 1),
        ]),
        "Eye Sales": ("handshake", [
            link("Home", "Eye Sales", link_type="Workspace"),
            link("Opportunity", "Opportunity"), link("Pricing Request", "Pricing Request"),
            link("Quotation", "Quotation"), link("Customer", "Customer"), link("Contact", "Contact"),
            section("Reports", "sheet"),
            link("Sales Pipeline Analytics", "Sales Pipeline Analytics", 1, "Report"),
            link("Opportunity Summary by Sales Stage", "Opportunity Summary by Sales Stage", 1, "Report"),
        ]),
        "Eye Production": ("factory", [
            link("Home", "Eye Production", link_type="Workspace"),
            link("Pricing Request", "Pricing Request"), link("Item", "Item"),
        ]),
    }
    for title, (icon, items) in sidebars.items():
        _ensure("Sidebar", title, {"title": title, "module": title, "app": "eye_crm_v1", "header_icon": icon,
                                   "standard": 1, "items": items})

    if not frappe.db.exists("Dock", {"app": "eye_crm_v1", "standard": 1}):
        frappe.get_doc({"doctype": "Dock", "app": "eye_crm_v1", "standard": 1, "items": [
            {"link_type": "Workspace", "link_to": "Eye Home", "title": "Home", "icon": "chart-column"},
            {"link_type": "Workspace", "link_to": "Eye Sales", "title": "Sales", "icon": "handshake"},
            {"link_type": "Workspace", "link_to": "Eye Production", "title": "Production", "icon": "factory"},
        ]}).insert(ignore_permissions=True)

    for cs in frappe.get_all("Custom Sidebar", filters={"module": "CRM"}, fields=["name", "user"]):
        if cs.user:
            continue
        doc = frappe.get_doc("Custom Sidebar", cs.name)
        keep = [r for r in doc.sidebar_items
                if not (r.added and (r.link_to in EYE_SIDEBAR_LINKS or r.label == "Eye Setup"))]
        if not keep:
            frappe.delete_doc("Custom Sidebar", cs.name, ignore_permissions=True, force=True)
        elif len(keep) != len(doc.sidebar_items):
            doc.set("sidebar_items", keep)
            doc.save(ignore_permissions=True)

    frappe.db.commit()
    frappe.clear_cache()
    print("Eye CRM app UI ready")


def rebuild_pricing():
    # clear test pricing data
    for t in ("Pricing Request Cost", "Pricing Request Item", "Pricing Request"):
        if frappe.db.table_exists(t):
            frappe.db.delete(t)
    frappe.db.delete("ToDo", {"reference_type": "Pricing Request"})
    frappe.db.sql("update tabOpportunity set custom_pricing_status = NULL")

    # remove what the old design added
    for cf in ("Opportunity-custom_send_to_production", "Opportunity Item-custom_cost", "Opportunity Item-custom_margin"):
        if frappe.db.exists("Custom Field", cf):
            frappe.delete_doc("Custom Field", cf, ignore_permissions=True, force=True)
    for ps in frappe.get_all("Property Setter", filters={"doc_type": "Opportunity Item", "module": M}, pluck="name"):
        frappe.delete_doc("Property Setter", ps, ignore_permissions=True, force=True)

    # cost elements, statuses and the cost breakdown table on the Pricing Request
    if not frappe.db.exists("Item Group", "Cost Elements"):
        frappe.get_doc({"doctype": "Item Group", "item_group_name": "Cost Elements",
                        "parent_item_group": "All Item Groups"}).insert(ignore_permissions=True)
    if not frappe.db.exists("Pricing Status", "Returned to Sales"):
        frappe.get_doc({"doctype": "Pricing Status", "title": "Returned to Sales"}).insert(ignore_permissions=True)

    if not frappe.db.exists("DocType", "Pricing Request Cost"):
        frappe.get_doc({
            "doctype": "DocType", "name": "Pricing Request Cost", "module": M, "custom": 0,
            "istable": 1, "editable_grid": 1,
            "fields": [
                {"fieldname": "sales_item", "label": "For Line", "fieldtype": "Autocomplete", "reqd": 1, "in_list_view": 1, "columns": 2, "permlevel": 1},
                {"fieldname": "sales_item_row", "label": "Line Ref", "fieldtype": "Data", "hidden": 1, "read_only": 1},
                {"fieldname": "item_code", "label": "Cost Element", "fieldtype": "Link", "options": "Item", "reqd": 1, "in_list_view": 1, "columns": 2, "permlevel": 1},
                {"fieldname": "description", "label": "Description", "fieldtype": "Small Text", "permlevel": 1},
                {"fieldname": "qty", "label": "Qty", "fieldtype": "Float", "default": "1", "in_list_view": 1, "columns": 1, "permlevel": 1},
                {"fieldname": "uom", "label": "UOM", "fieldtype": "Link", "options": "UOM", "permlevel": 1},
                {"fieldname": "rate", "label": "Unit Cost", "fieldtype": "Currency", "options": "currency", "in_list_view": 1, "columns": 2, "permlevel": 1},
                {"fieldname": "amount", "label": "Amount", "fieldtype": "Currency", "options": "currency", "read_only": 1, "in_list_view": 1, "columns": 2},
                {"fieldname": "supplier", "label": "Supplier", "fieldtype": "Link", "options": "Supplier", "in_list_view": 1, "columns": 1, "permlevel": 1},
                {"fieldname": "notes", "label": "Notes", "fieldtype": "Small Text", "permlevel": 1},
            ],
        }).insert()

    dt = frappe.get_doc("DocType", "Pricing Request")
    have = {x.fieldname for x in dt.fields}
    new = {
        "status": ({"fieldname": "status", "label": "Status", "fieldtype": "Link", "options": "Pricing Status",
                    "read_only": 1, "in_list_view": 1, "in_standard_filter": 1}, "required_by"),
        "costs_sb": ({"fieldname": "costs_sb", "label": "Cost Breakdown", "fieldtype": "Section Break"}, "items"),
        "costs": ({"fieldname": "costs", "label": "Cost Elements", "fieldtype": "Table",
                   "options": "Pricing Request Cost", "permlevel": 1}, "costs_sb"),
        "qa_sb": ({"fieldname": "qa_sb", "label": "Questions", "fieldtype": "Section Break", "collapsible": 1}, "costs"),
        "production_question": ({"fieldname": "production_question", "label": "Question from Production",
                                 "fieldtype": "Small Text", "read_only": 1}, "qa_sb"),
        "sales_reply": ({"fieldname": "sales_reply", "label": "Reply from Sales", "fieldtype": "Small Text",
                         "read_only": 1}, "production_question"),
    }
    for fieldname, (df, after) in new.items():
        if fieldname in have:
            continue
        pos = next(i for i, x in enumerate(dt.fields) if x.fieldname == after) + 1
        dt.fields.insert(pos, frappe.get_doc({"doctype": "DocField", **df}))
        have.add(fieldname)
    for i, x in enumerate(dt.fields, 1):
        x.idx = i
        if x.fieldname == "items":
            x.label = "Requirements"
    dt.save()

    from frappe.permissions import add_permission, update_permission_property
    if not frappe.db.exists("Custom DocPerm", {"parent": "Item", "role": "Production"}):
        add_permission("Item", "Production", 0)
    for ptype in ("write", "create"):
        update_permission_property("Item", "Production", 0, ptype, 1)

    # child tables on the Opportunity
    if not frappe.db.exists("DocType", "Opportunity Requirement"):
        frappe.get_doc({
            "doctype": "DocType", "name": "Opportunity Requirement", "module": M, "custom": 0,
            "istable": 1, "editable_grid": 1,
            "fields": [
                {"fieldname": "description", "label": "Description", "fieldtype": "Small Text", "reqd": 1, "in_list_view": 1, "columns": 4},
                {"fieldname": "qty", "label": "Qty", "fieldtype": "Float", "default": "1", "in_list_view": 1, "columns": 1},
                {"fieldname": "notes", "label": "Notes", "fieldtype": "Small Text", "in_list_view": 1, "columns": 3},
                {"fieldname": "attachment", "label": "Attachment", "fieldtype": "Attach", "in_list_view": 1, "columns": 2},
            ],
        }).insert()

    if not frappe.db.exists("DocType", "Opportunity Costing"):
        frappe.get_doc({
            "doctype": "DocType", "name": "Opportunity Costing", "module": M, "custom": 0,
            "istable": 1, "editable_grid": 1,
            "fields": [
                {"fieldname": "requirement", "label": "Requirement", "fieldtype": "Data", "hidden": 1, "read_only": 1},
                {"fieldname": "description", "label": "Description", "fieldtype": "Small Text", "read_only": 1, "in_list_view": 1, "columns": 3},
                {"fieldname": "qty", "label": "Qty", "fieldtype": "Float", "read_only": 1, "in_list_view": 1, "columns": 1},
                {"fieldname": "cost", "label": "Total Cost", "fieldtype": "Currency", "options": "currency", "read_only": 1, "in_list_view": 1, "columns": 2},
                {"fieldname": "margin", "label": "Margin %", "fieldtype": "Percent", "in_list_view": 1, "columns": 1},
                {"fieldname": "selling", "label": "Selling Amount", "fieldtype": "Currency", "options": "currency", "read_only": 1, "in_list_view": 1, "columns": 2},
                {"fieldname": "pricing_request", "label": "Pricing Request", "fieldtype": "Link", "options": "Pricing Request", "read_only": 1, "in_list_view": 1, "columns": 1},
            ],
        }).insert()

    # Pricing Request lines = the requirements, not items
    dt = frappe.get_doc("DocType", "Pricing Request Item")
    dt.set("fields", [])
    for df in [
        {"fieldname": "requirement", "label": "Requirement", "fieldtype": "Data", "hidden": 1, "read_only": 1},
        {"fieldname": "description", "label": "Description", "fieldtype": "Small Text", "read_only": 1, "in_list_view": 1, "columns": 4},
        {"fieldname": "qty", "label": "Qty", "fieldtype": "Float", "read_only": 1, "in_list_view": 1, "columns": 1},
        {"fieldname": "notes", "label": "Notes", "fieldtype": "Small Text", "read_only": 1, "in_list_view": 1, "columns": 2},
        {"fieldname": "attachment", "label": "Attachment", "fieldtype": "Attach", "read_only": 1, "in_list_view": 1, "columns": 1},
        {"fieldname": "cost", "label": "Total Cost", "fieldtype": "Currency", "options": "currency", "read_only": 1, "in_list_view": 1, "columns": 2},
    ]:
        dt.append("fields", df)
    dt.save()

    # the Pricing tab
    def f(fieldname, after, **kw):
        return {"fieldname": fieldname, "insert_after": after, "module": M, **kw}

    create_custom_fields({"Opportunity": [
        f("custom_pricing_status", "custom_pricing_tab", label="Pricing Status", fieldtype="Link",
          options="Pricing Status", read_only=1, in_standard_filter=1),
        f("custom_pricing_required_by", "custom_pricing_status", label="Required By", fieldtype="Date"),
        f("custom_pricing_notes", "custom_pricing_required_by", label="Notes for Production", fieldtype="Small Text"),
        f("custom_requirements", "custom_pricing_notes", label="Requirements", fieldtype="Table",
          options="Opportunity Requirement"),
        f("custom_costing_sb", "custom_requirements", label="Costing", fieldtype="Section Break"),
        f("custom_default_margin", "custom_costing_sb", label="Margin for all lines %", fieldtype="Percent"),
        f("custom_costing_cb", "custom_default_margin", fieldtype="Column Break"),
        f("custom_total_cost", "custom_costing_cb", label="Total Cost", fieldtype="Currency",
          options="currency", read_only=1),
        f("custom_total_selling", "custom_total_cost", label="Minimum Selling Total", fieldtype="Currency",
          options="currency", read_only=1),
        f("custom_costing_table_sb", "custom_total_selling", fieldtype="Section Break"),
        f("custom_costing", "custom_costing_table_sb", label="Costing", fieldtype="Table",
          options="Opportunity Costing"),
        f("custom_costing_summary", "custom_costing", fieldtype="HTML"),
        f("custom_pricing_sb", "custom_costing_summary", label="Pricing Requests", fieldtype="Section Break",
          collapsible=1),
        f("custom_pricing_requests_html", "custom_pricing_sb", fieldtype="HTML"),
    ]})

    frappe.db.commit()
    frappe.clear_cache()
    print("Pricing rebuilt")


COST_ELEMENTS = {
    ("VEN", "Venue & Hospitality"): [
        ("Venue Rental", "Day"), ("Catering", "Nos"), ("Coffee Break", "Nos"),
        ("Hotel Accommodation", "Nos"), ("Flight Tickets", "Nos"),
    ],
    ("BTH", "Booth & Fabrication"): [
        ("Carpentry & Wood Works", "Nos"), ("Paint & Finishing", "Square Meter"), ("Flooring & Carpet", "Square Meter"),
        ("Furniture Rental", "Nos"), ("Lighting & Electrical", "Nos"), ("Booth Installation", "Nos"),
        ("Booth Dismantling", "Nos"), ("Booth Space Rental", "Square Meter"),
    ],
    ("PRT", "Printing"): [
        ("Offset Printing", "Nos"), ("Digital Printing", "Nos"), ("Roll-up & Banner", "Nos"),
        ("Flex & Sticker Printing", "Square Meter"), ("Lamination & Binding", "Nos"),
    ],
    ("GFT", "Giveaways & Gifts"): [
        ("Promotional Gifts", "Nos"), ("Gift Packaging", "Nos"), ("Logo Branding on Gifts", "Nos"),
    ],
    ("AVT", "AV & Technology"): [
        ("LED Screen Rental", "Day"), ("Sound System & Microphones", "Day"), ("Projector Rental", "Day"),
        ("Tablet / iPad Rental", "Day"), ("Event Internet", "Day"),
    ],
    ("DIG", "Digital & eDetailing"): [
        ("Software Development", "Hour"), ("Software Licenses", "Nos"), ("Hosting & Domains", "Nos"),
        ("UI / UX Design", "Hour"),
    ],
    ("CRT", "Creative & Content"): [
        ("Graphic Design", "Hour"), ("Copywriting", "Nos"), ("Translation", "Nos"), ("Photography", "Day"),
        ("Videography", "Day"), ("Video Editing", "Hour"), ("Motion Graphics", "Nos"),
    ],
    ("SMM", "Social Media"): [
        ("Paid Ads Spend", "Nos"), ("Influencer Fees", "Nos"), ("Page Management", "Nos"),
    ],
    ("MAN", "Manpower"): [
        ("Hostesses & Ushers", "Day"), ("Event Organizers", "Day"), ("Technicians", "Day"),
        ("Onsite Setup Crew", "Day"),
    ],
    ("LOG", "Logistics"): [
        ("Transportation & Shipping", "Nos"), ("Storage", "Day"), ("Customs Clearance", "Nos"),
    ],
    ("MED", "Medical & Regulatory"): [
        ("Speaker Fees", "Nos"), ("CME Accreditation", "Nos"), ("MOH Approvals", "Nos"),
    ],
    ("OTH", "Fees & Other"): [
        ("Permits & Government Fees", "Nos"), ("Insurance", "Nos"), ("Miscellaneous Expenses", "Nos"),
    ],
}


def seed_cost_elements():
    if not frappe.db.exists("Item Group", "Cost Elements"):
        frappe.get_doc({"doctype": "Item Group", "item_group_name": "Cost Elements",
                        "parent_item_group": "All Item Groups", "is_group": 1}).insert(ignore_permissions=True)
    else:
        frappe.db.set_value("Item Group", "Cost Elements", "is_group", 1)

    for uom in {u for items in COST_ELEMENTS.values() for _, u in items}:
        if not frappe.db.exists("UOM", uom):
            frappe.get_doc({"doctype": "UOM", "uom_name": uom}).insert(ignore_permissions=True)

    made = 0
    for (code, group), items in COST_ELEMENTS.items():
        if not frappe.db.exists("Item Group", group):
            frappe.get_doc({"doctype": "Item Group", "item_group_name": group,
                            "parent_item_group": "Cost Elements"}).insert(ignore_permissions=True)
        for i, (name, uom) in enumerate(items, 1):
            item_code = f"CE-{code}-{i:03d}"
            if frappe.db.exists("Item", item_code):
                continue
            frappe.get_doc({
                "doctype": "Item", "item_code": item_code, "item_name": name, "description": name,
                "item_group": group, "stock_uom": uom, "is_stock_item": 0,
                "is_sales_item": 0, "is_purchase_item": 1, "include_item_in_manufacturing": 0,
            }).insert(ignore_permissions=True)
            made += 1
    frappe.db.commit()
    print(f"Cost elements ready ({made} new items)")


def _rebuild_fields(dt, new, drop=()):
    rows = [{k: v for k, v in f.as_dict().items()
             if k not in ("name", "parent", "parentfield", "parenttype", "idx", "creation", "modified")}
            for f in dt.fields if f.fieldname not in drop]
    have = {r["fieldname"] for r in rows}
    for after, df in new:
        if df["fieldname"] in have:
            continue
        pos = next(i for i, r in enumerate(rows) if r["fieldname"] == after) + 1
        rows.insert(pos, df)
        have.add(df["fieldname"])
    dt.set("fields", [])
    for r in rows:
        dt.append("fields", r)


def setup_pricing_change():
    # start clean: test pricing data only
    for t in ("Pricing Request Cost", "Pricing Request Item", "Pricing Request"):
        frappe.db.delete(t)
    if frappe.db.table_exists("Pricing Change"):
        frappe.db.delete("Pricing Change Line")
        frappe.db.delete("Pricing Change")
    frappe.db.delete("ToDo", {"reference_type": ["in", ["Pricing Request", "Pricing Change"]]})
    frappe.db.sql("update tabOpportunity set custom_pricing_status = NULL")
    frappe.db.sql("delete from `tabOpportunity Costing`")

    for st in ("In Pricing", "Change Requested"):
        if not frappe.db.exists("Pricing Status", st):
            frappe.get_doc({"doctype": "Pricing Status", "title": st}).insert(ignore_permissions=True)

    if not frappe.db.exists("DocType", "Pricing Change Line"):
        frappe.get_doc({
            "doctype": "DocType", "name": "Pricing Change Line", "module": M, "custom": 0,
            "istable": 1, "editable_grid": 1,
            "fields": [
                {"fieldname": "line", "label": "Line", "fieldtype": "Data", "read_only": 1, "in_list_view": 1, "columns": 3},
                {"fieldname": "field", "label": "Field", "fieldtype": "Data", "read_only": 1, "in_list_view": 1, "columns": 2},
                {"fieldname": "old_value", "label": "Old", "fieldtype": "Small Text", "read_only": 1, "in_list_view": 1, "columns": 2},
                {"fieldname": "new_value", "label": "New", "fieldtype": "Small Text", "read_only": 1, "in_list_view": 1, "columns": 3},
            ],
        }).insert()

    if not frappe.db.exists("DocType", "Pricing Change"):
        perm = lambda role, **kw: {"role": role, "permlevel": 0, "read": 1, **kw}
        frappe.get_doc({
            "doctype": "DocType", "name": "Pricing Change", "module": M, "custom": 0,
            "autoname": "format:PCH-{YYYY}-{#####}", "track_changes": 1,
            "sort_field": "creation", "sort_order": "DESC",
            "fields": [
                {"fieldname": "pricing_request", "label": "Pricing Request", "fieldtype": "Link", "options": "Pricing Request", "reqd": 1, "read_only": 1, "in_list_view": 1, "in_standard_filter": 1},
                {"fieldname": "opportunity", "label": "Opportunity", "fieldtype": "Link", "options": "Opportunity", "read_only": 1, "in_standard_filter": 1},
                {"fieldname": "requested_by_side", "label": "Requested By", "fieldtype": "Select", "options": "Sales\nProduction", "read_only": 1, "in_list_view": 1},
                {"fieldname": "cb1", "fieldtype": "Column Break"},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nPending\nApproved\nRejected", "default": "Draft", "read_only": 1, "in_list_view": 1, "in_standard_filter": 1},
                {"fieldname": "decided_by", "label": "Decided By", "fieldtype": "Link", "options": "User", "read_only": 1},
                {"fieldname": "sb1", "fieldtype": "Section Break"},
                {"fieldname": "reason", "label": "Reason", "fieldtype": "Small Text", "read_only": 1},
                {"fieldname": "response", "label": "Response", "fieldtype": "Small Text", "read_only": 1},
                {"fieldname": "lines", "label": "Changes", "fieldtype": "Table", "options": "Pricing Change Line", "read_only": 1},
                {"fieldname": "payload", "label": "Payload", "fieldtype": "Long Text", "hidden": 1, "read_only": 1},
            ],
            "permissions": [
                perm("System Manager", write=1, create=1, delete=1),
                perm("Sales Manager", write=1, create=1),
                perm("Sales User", write=1, create=1),
                perm("Production", write=1, create=1),
            ],
        }).insert()

    dt = frappe.get_doc("DocType", "Pricing Request")
    dt.is_submittable = 0
    for p in dt.permissions:
        p.submit = p.cancel = p.amend = 0
    _rebuild_fields(dt, [
        ("status", {"fieldname": "pending_change", "label": "Pending Change", "fieldtype": "Link",
                    "options": "Pricing Change", "read_only": 1}),
        ("pending_change", {"fieldname": "sales_started", "label": "Sales Started", "fieldtype": "Check",
                            "read_only": 1, "hidden": 1}),
        ("sales_started", {"fieldname": "approved_costs", "label": "Approved Costs", "fieldtype": "Long Text",
                           "read_only": 1, "hidden": 1}),
    ], drop=("amended_from",))
    dt.save()

    open_filter = json.dumps([["Pricing Request", "status", "in",
                               ["With Production", "In Pricing", "Returned to Sales", "Change Requested"], False]])
    for card in ("Open Pricing Requests", "Overdue Pricing Requests"):
        if frappe.db.exists("Number Card", card):
            d = frappe.get_doc("Number Card", card)
            d.filters_json = open_filter
            d.save(ignore_permissions=True)
    if frappe.db.exists("Dashboard Chart", "Pricing Requests per Month"):
        d = frappe.get_doc("Dashboard Chart", "Pricing Requests per Month")
        d.filters_json = "[]"
        d.save(ignore_permissions=True)
    for ws in ("Eye Sales", "Eye Production"):
        if frappe.db.exists("Workspace", ws):
            d = frappe.get_doc("Workspace", ws)
            for sc in d.shortcuts:
                if sc.link_to == "Pricing Request":
                    sc.stats_filter = open_filter
            d.save(ignore_permissions=True)

    for sb in ("Eye Sales", "Eye Production"):
        if frappe.db.exists("Sidebar", sb):
            d = frappe.get_doc("Sidebar", sb)
            if not any(i.link_to == "Pricing Change" for i in d.items):
                d.append("items", {"type": "Link", "label": "Pricing Change", "link_type": "DocType",
                                   "link_to": "Pricing Change", "collapsible": 1})
                d.save(ignore_permissions=True)

    frappe.db.commit()
    frappe.clear_cache()
    print("Pricing Change ready")


def add_change_shortcuts():
    stats = json.dumps([["Pricing Change", "status", "=", "Pending", False]])
    for ws in ("Eye Sales", "Eye Production"):
        if not frappe.db.exists("Workspace", ws):
            continue
        d = frappe.get_doc("Workspace", ws)
        if any(sc.link_to == "Pricing Change" for sc in d.shortcuts):
            continue
        d.append("shortcuts", {"type": "DocType", "link_to": "Pricing Change", "label": "Change Requests",
                               "doc_view": "List", "color": "Red", "stats_filter": stats})
        blocks = json.loads(d.content or "[]")
        blocks.append({"id": f"eyech{len(blocks):05d}", "type": "shortcut",
                       "data": {"shortcut_name": "Change Requests", "col": 4 if ws == "Eye Production" else 3}})
        d.content = json.dumps(blocks)
        d.save(ignore_permissions=True)
    frappe.db.commit()
    print("Change Requests shortcuts ready")


EYE_STAGES = ["Estimation", "Proposal", "Quotation", "Project Won", "Quote approved"]


def setup_stages():
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter

    for s in EYE_STAGES:
        if not frappe.db.exists("Sales Stage", s):
            frappe.get_doc({"doctype": "Sales Stage", "stage_name": s}).insert(ignore_permissions=True)

    old = frappe.get_all("Sales Stage", filters={"name": ["not in", EYE_STAGES]}, pluck="name")
    if old:
        frappe.db.sql("update tabOpportunity set sales_stage = 'Estimation' where sales_stage in %s", (tuple(old),))
        for s in old:
            frappe.delete_doc("Sales Stage", s, ignore_permissions=True, force=True)

    ps = make_property_setter("Opportunity", "sales_stage", "default", "Estimation", "Text",
                              validate_fields_for_doctype=False)
    frappe.db.set_value("Property Setter", ps.name, "module", M)
    frappe.db.commit()
    frappe.clear_cache(doctype="Opportunity")
    print("Stages:", ", ".join(EYE_STAGES), "| removed:", ", ".join(old) or "-")


def restyle_sidebars():
    open_prq = json.dumps([["Pricing Request", "status", "in",
                            ["With Production", "In Pricing", "Returned to Sales", "Change Requested"]]])
    pending_chg = json.dumps([["Pricing Change", "status", "=", "Pending"]])
    cost_items = json.dumps([["Item", "item_group", "descendants of (inclusive)", "Cost Elements"]])
    open_opp = json.dumps([["Opportunity", "status", "=", "Open"]])

    def link(label, to, icon=None, link_type="DocType", child=0, filters=None):
        row = {"type": "Link", "label": label, "link_type": link_type, "link_to": to,
               "icon": icon, "child": child, "collapsible": 1}
        if filters:
            row["filters"] = filters
        return row

    def section(label, icon, closed=0):
        return {"type": "Section Break", "label": label, "icon": icon, "indent": 1,
                "collapsible": 1, "keep_closed": closed}

    def sub(label, to, link_type="DocType", filters=None):
        return link(label, to, link_type=link_type, child=1, filters=filters)

    layouts = {
        "Eye Home": ("chart-column", [
            link("Home", "Eye Home", "house", "Workspace"),
            link("Opportunities", "Opportunity", "lightbulb"),
            link("Pricing Requests", "Pricing Request", "calculator"),
            link("Change Requests", "Pricing Change", "git-compare", filters=pending_chg),
            link("Quotations", "Quotation", "file-text"),
            section("Masters", "database"),
            sub("Customers", "Customer"), sub("Contacts", "Contact"),
            sub("Cost Elements", "Item", filters=cost_items), sub("Suppliers", "Supplier"),
            section("Setup", "settings", 1),
            sub("Service Types", "Service Type"), sub("Deal Natures", "Deal Nature"),
            sub("PO Statuses", "PO Status"), sub("Pricing Statuses", "Pricing Status"),
            sub("Sales Stages", "Sales Stage"), sub("Print Formats", "Print Format"),
            section("Reports", "sheet", 1),
            sub("Sales Pipeline Analytics", "Sales Pipeline Analytics", "Report"),
            sub("Opportunity Summary by Sales Stage", "Opportunity Summary by Sales Stage", "Report"),
        ]),
        "Eye Sales": ("handshake", [
            link("Home", "Eye Sales", "house", "Workspace"),
            link("Opportunities", "Opportunity", "lightbulb"),
            link("Open Deals", "Opportunity", "list-checks", filters=open_opp),
            link("Quotations", "Quotation", "file-text"),
            section("Pricing", "calculator"),
            sub("Pricing Requests", "Pricing Request"),
            sub("Change Requests", "Pricing Change", filters=pending_chg),
            section("Customers", "users-round"),
            sub("Customers", "Customer"), sub("Contacts", "Contact"),
            section("Reports", "sheet", 1),
            sub("Sales Pipeline Analytics", "Sales Pipeline Analytics", "Report"),
            sub("Opportunity Summary by Sales Stage", "Opportunity Summary by Sales Stage", "Report"),
        ]),
        "Eye Production": ("factory", [
            link("Home", "Eye Production", "house", "Workspace"),
            link("Open Requests", "Pricing Request", "calculator", filters=open_prq),
            link("All Pricing Requests", "Pricing Request", "layers"),
            link("Change Requests", "Pricing Change", "git-compare", filters=pending_chg),
            section("Costing", "boxes"),
            sub("Cost Elements", "Item", filters=cost_items),
            sub("Suppliers", "Supplier"),
        ]),
    }
    for title, (icon, items) in layouts.items():
        if not frappe.db.exists("Sidebar", title):
            continue
        d = frappe.get_doc("Sidebar", title)
        d.header_icon = icon
        d.set("items", [])
        for row in items:
            d.append("items", row)
        d.save(ignore_permissions=True)

    from frappe.permissions import add_permission
    if not frappe.db.exists("Custom DocPerm", {"parent": "Supplier", "role": "Production"}):
        add_permission("Supplier", "Production", 0)

    frappe.db.commit()
    frappe.clear_cache()
    print("Sidebars restyled")


def create_deals_board():
    meta = frappe.get_meta("Opportunity")
    extra = [f for f in ("custom_pricing_status", "custom_total_selling", "custom_total_cost", "total",
                         "opportunity_amount", "currency", "customer_name")
             if meta.has_field(f)]
    card = [f for f in ("customer_name", "total", "expected_closing") if meta.has_field(f)]

    if frappe.db.exists("Kanban Board", "Deals"):
        board = frappe.get_doc("Kanban Board", "Deals")
    else:
        board = frappe.new_doc("Kanban Board")
        board.kanban_board_name = "Deals"
        board.reference_doctype = "Opportunity"
    board.field_name = "sales_stage"
    board.update({"is_standard": "Yes", "module": "Eye Sales", "private": 0, "use_kanban_v2": 1,
                  "show_assigned_to": 1, "fields": json.dumps(extra)})
    board.set("columns", [])
    for s in EYE_STAGES:
        board.append("columns", {"column_name": s, "status": "Active"})
    if meta.has_field("customer_name"):
        board.title_field = "customer_name"
    board.set("card_fields", [])
    for f in card:
        board.append("card_fields", {"fieldname": f})
    if board.is_new():
        board.insert(ignore_permissions=True)
    else:
        board.save(ignore_permissions=True)

    for ws in ("Eye Sales", "Eye Home"):
        if not frappe.db.exists("Workspace", ws):
            continue
        d = frappe.get_doc("Workspace", ws)
        if not any(sc.label == "Deals Board" for sc in d.shortcuts):
            d.append("shortcuts", {"type": "DocType", "link_to": "Opportunity", "label": "Deals Board",
                                   "doc_view": "Kanban", "kanban_board": "Deals", "color": "Blue"})
            blocks = json.loads(d.content or "[]")
            pos = next((i for i, b in enumerate(blocks) if b.get("type") == "shortcut"), len(blocks))
            blocks.insert(pos, {"id": "eyedeals01", "type": "shortcut", "data": {"shortcut_name": "Deals Board", "col": 3}})
            d.content = json.dumps(blocks)
            d.save(ignore_permissions=True)
    if frappe.db.exists("Sidebar", "Eye Sales"):
        d = frappe.get_doc("Sidebar", "Eye Sales")
        if not any(i.label == "Deals Board" for i in d.items):
            rows = [r.as_dict() for r in d.items]
            rows.insert(1, {"type": "Link", "label": "Deals Board", "link_type": "URL",
                            "url": "/app/opportunity/view/kanban/Deals", "icon": "kanban", "collapsible": 1})
            d.set("items", [])
            for r in rows:
                for k in ("name", "parent", "parentfield", "parenttype", "idx", "creation", "modified"):
                    r.pop(k, None)
                d.append("items", r)
            d.save(ignore_permissions=True)

    frappe.db.commit()
    frappe.clear_cache()
    print("Deals board ready:", ", ".join(EYE_STAGES))


def create_deals_board():
    meta = frappe.get_meta("Opportunity")
    extra = [f for f in ("custom_pricing_status", "custom_total_selling", "custom_total_cost", "total",
                         "opportunity_amount", "currency", "customer_name")
             if meta.has_field(f)]
    card = [f for f in ("customer_name", "total", "expected_closing") if meta.has_field(f)]

    if frappe.db.exists("Kanban Board", "Deals"):
        board = frappe.get_doc("Kanban Board", "Deals")
    else:
        board = frappe.new_doc("Kanban Board")
        board.kanban_board_name = "Deals"
        board.reference_doctype = "Opportunity"
    board.field_name = "sales_stage"
    board.update({"is_standard": "Yes", "module": "Eye Sales", "private": 0, "use_kanban_v2": 1,
                  "show_assigned_to": 1, "fields": json.dumps(extra)})
    board.set("columns", [])
    for s in EYE_STAGES:
        board.append("columns", {"column_name": s, "status": "Active"})
    if meta.has_field("customer_name"):
        board.title_field = "customer_name"
    board.set("card_fields", [])
    for f in card:
        board.append("card_fields", {"fieldname": f})
    if board.is_new():
        board.insert(ignore_permissions=True)
    else:
        board.save(ignore_permissions=True)

    for ws in ("Eye Sales", "Eye Home"):
        if not frappe.db.exists("Workspace", ws):
            continue
        d = frappe.get_doc("Workspace", ws)
        if not any(sc.label == "Deals Board" for sc in d.shortcuts):
            d.append("shortcuts", {"type": "DocType", "link_to": "Opportunity", "label": "Deals Board",
                                   "doc_view": "Kanban", "kanban_board": "Deals", "color": "Blue"})
            blocks = json.loads(d.content or "[]")
            pos = next((i for i, b in enumerate(blocks) if b.get("type") == "shortcut"), len(blocks))
            blocks.insert(pos, {"id": "eyedeals01", "type": "shortcut", "data": {"shortcut_name": "Deals Board", "col": 3}})
            d.content = json.dumps(blocks)
            d.save(ignore_permissions=True)
    if frappe.db.exists("Sidebar", "Eye Sales"):
        d = frappe.get_doc("Sidebar", "Eye Sales")
        if not any(i.label == "Deals Board" for i in d.items):
            rows = [r.as_dict() for r in d.items]
            rows.insert(1, {"type": "Link", "label": "Deals Board", "link_type": "URL",
                            "url": "/app/opportunity/view/kanban/Deals", "icon": "kanban", "collapsible": 1})
            d.set("items", [])
            for r in rows:
                for k in ("name", "parent", "parentfield", "parenttype", "idx", "creation", "modified"):
                    r.pop(k, None)
                d.append("items", r)
            d.save(ignore_permissions=True)

    frappe.db.commit()
    frappe.clear_cache()
    print("Deals board ready:", ", ".join(EYE_STAGES))
