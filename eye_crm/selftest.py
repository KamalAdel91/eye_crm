"""Eye CRM self-test: the whole cycle on a real site, then everything is rolled back.

	bench --site SITE execute eye_crm.selftest.run

Made for a rehearsal site (a copy of the real one): a customer, an item and a deal go from
Estimation to Quote approved, a Sales Order is made, an invoice is requested, invoiced and
collected, and every report runs. Nothing it makes is kept. It raises if any check fails.
"""

import frappe
from frappe.utils import add_days, flt, nowdate
from frappe.utils.safe_exec import call_whitelisted_function

ACC = "Accounts, please approve"
SCRIPTS = [
	"Eye Pricing API", "Eye Billing API", "Eye Books API", "Eye Flow Steps", "Eye Zoho Webhook",
	"Eye Opportunity Before Validate", "Eye Opportunity Before Save", "Eye Opportunity After Save",
	"Eye Quotation Before Save", "Eye Quotation After Save", "Eye Billing Request Before Save",
	"Eye Billing Request After Save", "Eye Billing Request Before Delete", "Eye Books Every 5 Minutes",
	"Eye Opportunity Permission", "Eye Billing Request Permission",
]
REPORTS = ["Eye Revenue on Hand", "Eye Won Not Billed", "Eye Billing Pipeline", "Eye Collections",
           "Eye Pricing Turnaround", "Eye Deal PL"]

results = []


def check(label, ok, info=""):
	results.append((label, bool(ok)))
	print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"   [{info}]"))


def api(method, **kwargs):
	out = call_whitelisted_function(method, **kwargs)
	return out.get("result") if isinstance(out, dict) else out


def error_of(fn):
	try:
		fn()
	except Exception as e:
		frappe.clear_messages()
		return str(e)
	return ""


def first(doctype, filters=None):
	rows = frappe.get_all(doctype, filters=filters or {}, pluck="name", limit=1)
	return rows[0] if rows else None


def run():
	frappe.set_user("Administrator")
	frappe.local.lang = "en"  # the checks read English messages
	results.clear()
	try:
		setup_checks()
		cycle()
	except Exception as e:
		print(frappe.get_traceback())
		check("the cycle ran to the end", False, repr(e)[:300])
	finally:
		frappe.db.rollback()
		frappe.clear_messages()
	failed = [r[0] for r in results if not r[1]]
	print(f"\nEye self-test: {len(results) - len(failed)} passed, {len(failed)} failed")
	if failed:
		raise Exception("Eye self-test failed: " + "; ".join(failed))
	return "ok"


def setup_checks():
	from frappe.utils.safe_exec import is_safe_exec_enabled

	check("server scripts are enabled on this bench", is_safe_exec_enabled())
	from RestrictedPython import compile_restricted
	from frappe.utils.safe_exec import FrappeTransformer

	for name in SCRIPTS:
		err = "missing or disabled"
		if frappe.db.exists("Server Script", {"name": name, "disabled": 0}):
			err = error_of(lambda n=name: compile_restricted(frappe.db.get_value("Server Script", n, "script"),
			                                                 filename=n, policy=FrappeTransformer, mode="exec"))
		check(f"server script {name}", not err, err[:200])
	check("the 5-minute job is scheduled", frappe.db.exists("Scheduled Job Type", {"server_script": "Eye Books Every 5 Minutes"}))
	deals = [c.column_name for c in frappe.get_doc("Kanban Board", "Deals").columns] if frappe.db.exists("Kanban Board", "Deals") else []
	check("the Deals board has Accounts' column", ACC in deals, deals)
	check("the Billing board is there", frappe.db.exists("Kanban Board", {"name": "Billing", "reference_doctype": "Billing Request"}))
	check("Sales Stage 'Accounts, please approve'", frappe.db.exists("Sales Stage", ACC))
	for dt, field in [("Opportunity", "custom_accounts_approval"), ("Opportunity", "custom_sales_order"),
	                  ("Sales Order Item", "custom_service_type"), ("Item", "custom_zoho_item_id"),
	                  ("Customer", "custom_zoho_contact_id")]:
		check(f"field {dt}.{field}", frappe.get_meta(dt).has_field(field))
	check("accounting mode answers", api("eye.books", op="mode") in ("Manual", "Zoho"))
	for name in ["Eye Opportunity Permission", "Eye Billing Request Permission"]:
		err = error_of(lambda n=name: frappe.get_doc("Server Script", n).get_permission_query_conditions("Guest"))
		check(f"{name} runs", not err, err)


def make_masters():
	company = frappe.defaults.get_global_default("company") or first("Company")
	group = first("Customer Group", {"is_group": 0})
	territory = first("Territory", {"is_group": 0})
	customer = frappe.get_doc({"doctype": "Customer", "customer_name": "Eye Selftest Customer", "customer_type": "Company",
	                           "customer_group": group, "territory": territory}).insert(ignore_permissions=True)
	contact = frappe.get_doc({"doctype": "Contact", "first_name": "Eye", "last_name": "Selftest",
	                          "links": [{"link_doctype": "Customer", "link_name": customer.name}]}).insert(ignore_permissions=True)
	service = first("Service Type")
	item = frappe.get_doc({"doctype": "Item", "item_code": "EYE-SELFTEST-ITEM", "item_name": "Eye Selftest Booth",
	                       "item_group": first("Item Group", {"is_group": 0}), "stock_uom": "Nos" if frappe.db.exists("UOM", "Nos") else first("UOM"),
	                       "is_stock_item": 0, "is_sales_item": 1, "include_item_in_manufacturing": 0,
	                       "custom_service_type": service}).insert(ignore_permissions=True)
	return company, customer, contact, service, item


def cycle():
	company, customer, contact, service, item = make_masters()

	# a deal with one requirement and its sales item, priced by Production at 800, 25% margin
	opp = frappe.get_doc({
		"doctype": "Opportunity", "opportunity_from": "Customer", "party_name": customer.name, "company": company,
		"sales_stage": "Estimation", "contact_person": contact.name, "expected_closing": add_days(nowdate(), 20),
		"custom_requirements": [{"item_code": item.name, "description": "Booth 3x3", "qty": 1}],
	}).insert(ignore_permissions=True)
	check("a deal saves at Estimation", opp.sales_stage == "Estimation")

	opp.reload()
	opp.append("custom_costing", {"requirement": opp.custom_requirements[0].name, "description": "Booth 3x3", "qty": 1,
	                              "cost": 800, "margin": 25})
	opp.flags.eye_pricing = True
	opp.save(ignore_permissions=True)
	check("the costing makes it Priced, minimum selling 1000",
	      opp.custom_pricing_status == "Priced" and flt(opp.custom_total_selling) == 1000,
	      (opp.custom_pricing_status, opp.custom_total_selling))
	lines = [i for i in opp.items if i.get("custom_requirement") == opp.custom_requirements[0].name]
	check("the priced requirement is an Items line at the selling price",
	      len(lines) == 1 and lines[0].item_code == item.name and flt(lines[0].rate) == 1000,
	      [(i.item_code, i.rate, i.get("custom_requirement")) for i in opp.items])

	opp.reload()
	opp.sales_stage = "Project Won"
	err = error_of(lambda: opp.save(ignore_permissions=True))
	check("the deal can't skip to Project Won without a quotation", "Quotation created" in err, err[:200])

	steps = api("eye.pricing", op="stage_check", name=opp.name, to="Project Won")
	check("stage_check names the quotation as missing", [s["key"] for s in steps["missing"]] == ["quotation"], steps["missing"])

	from erpnext.crm.doctype.opportunity.opportunity import make_quotation

	q = make_quotation(opp.name)
	q.valid_till = add_days(nowdate(), 30)
	check("the quotation takes the items and their prices", [(i.item_code, flt(i.rate)) for i in q.items] == [(item.name, 1000)],
	      [(i.item_code, i.rate) for i in q.items])
	q.insert(ignore_permissions=True)
	check("a quotation moves the deal to Quotation", frappe.db.get_value("Opportunity", opp.name, "sales_stage") == "Quotation")

	opp = frappe.get_doc("Opportunity", opp.name)
	opp.sales_stage = "Project Won"
	opp.save(ignore_permissions=True)
	check("with everything done the deal is Project Won", opp.sales_stage == "Project Won")
	pl = api("eye.pricing", op="pl_view", name=opp.name)
	check("the PL view answers", bool(pl))

	if frappe.db.exists("DocType", "Nexlify Board DocType") and frappe.db.exists(
		"Nexlify Board DocType", {"reference_doctype": "Opportunity"}
	):
		# PO Status is required from Accounts' stage by its field setting, held on save by the board
		opp.reload()
		opp.sales_stage = ACC
		err = error_of(lambda: opp.save(ignore_permissions=True))
		label = frappe.get_meta("Opportunity").get_label("custom_po_status")
		check("Accounts' stage needs PO Status (field setting)", label in err, err[:200])
	opp.reload()
	opp.custom_po_status = "Purchase Order (PO)"
	opp.custom_po_no = "PO-SELFTEST"
	opp.sales_stage = ACC
	opp.save(ignore_permissions=True)
	check("with the PO the deal waits on Accounts",
	      frappe.db.get_value("Opportunity", opp.name, "custom_accounts_approval") == "Pending")

	flow = api("eye.flow", doctype="Opportunity", name=opp.name)
	check("eye.flow gives every stage and its steps", flow.get("stages") and len(flow.get("steps") or []) > 5, flow)
	if "nexlify_board" in frappe.get_installed_apps() and frappe.db.get_value(
		"Nexlify Board DocType", {"reference_doctype": "Opportunity"}, "flow_method"
	):
		board_flow = frappe.get_attr("nexlify_board.transition_rules.get_flow")("Opportunity", opp.name, board="Deals")
		with_steps = [s["name"] for s in board_flow.get("stages", []) if s.get("steps")]
		check("Nexlify Board's Flow shows Eye's steps", ACC in with_steps or "Quote approved" in with_steps, with_steps)

	r = api("eye.pricing", op="approve_project", name=opp.name, note="selftest")
	so = frappe.db.get_value("Opportunity", opp.name, "custom_sales_order")
	check("Accounts approve: Quote approved", frappe.db.get_value("Opportunity", opp.name, "sales_stage") == "Quote approved")
	check("approval makes and submits the Sales Order", so and frappe.db.get_value("Sales Order", so, "docstatus") == 1, r)
	check("the Sales Order line keeps the service type",
	      so and frappe.db.get_value("Sales Order Item", {"parent": so}, "custom_service_type") == service)

	lines = api("eye.billing", op="so_lines", opportunity=opp.name)
	row = lines["rows"][0]
	br = api("eye.billing", op="create", opportunity=opp.name, expected_date=add_days(nowdate(), 10),
	         rows=frappe.as_json([{"so_detail": row["so_detail"], "qty": 0.5}]))
	doc = frappe.get_doc("Billing Request", br)
	check("an invoice request takes half the line", flt(doc.total) == 500 and doc.billing_stage == "To be invoiced", doc.total)
	err = error_of(lambda: api("eye.billing", op="create", opportunity=opp.name, expected_date=nowdate(),
	                           rows=frappe.as_json([{"so_detail": row["so_detail"], "qty": 0.6}])))
	check("a request can't bill more than is left", "left" in err, err[:200])

	doc.billing_stage = "Finance, please issue"
	doc.save(ignore_permissions=True)
	check("the request goes to Finance", frappe.db.get_value("Billing Request", br, "sent_on"))
	api("eye.billing", op="mark_invoiced", name=br, invoice_number="INV-SELFTEST", invoice_date=nowdate())
	api("eye.billing", op="mark_collected", name=br, collected_on=nowdate())
	d = frappe.db.get_value("Opportunity", opp.name, ["custom_billed_amount", "custom_collected_amount"], as_dict=True)
	check("invoiced and collected roll up to the deal", flt(d.custom_billed_amount) == 500 and flt(d.custom_collected_amount) == 500, d)

	from frappe.desk.query_report import run as run_report

	for name in REPORTS:
		err = ""
		rows = []
		try:
			out = run_report(name, filters={}, ignore_prepared_report=True)
			rows = out.get("result") or []
		except Exception as e:
			err = repr(e)
		check(f"report {name}", not err, err[:200])
	won = run_report("Eye Revenue on Hand", filters={}, ignore_prepared_report=True).get("result") or []
	check("Revenue on Hand shows the deal less what is invoiced",
	      any(r.get("opportunity") == opp.name and flt(r.get("on_hand")) == 500 for r in won if isinstance(r, dict)))

	# Accounts send a deal back
	opp2 = frappe.copy_doc(frappe.get_doc("Opportunity", opp.name))
	opp2.sales_stage = "Estimation"
	opp2.insert(ignore_permissions=True)
	frappe.db.set_value("Opportunity", opp2.name, {"sales_stage": ACC, "custom_accounts_approval": "Pending"})
	api("eye.pricing", op="reject_project", name=opp2.name, reason="selftest: price too low")
	check("a rejection sends the deal back to Project Won",
	      frappe.db.get_value("Opportunity", opp2.name, ["sales_stage", "custom_accounts_approval"]) == ("Project Won", "Rejected"))
