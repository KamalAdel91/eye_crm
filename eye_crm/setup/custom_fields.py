"""The fields Eye CRM adds to ERPNext's doctypes, and how it lays out the deal.

Created once, when the app is installed. Every field and property setter carries the module
"Eye Deals", so uninstalling the app takes them away with it.
"""

import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Eye Deals"

# what a deal needs before it can enter a stage, as Customize Form keeps it (Mandatory Depends On);
# by the stage's order, so renaming a stage changes nothing
IN_HAND = "eval:doc.eye_stage_order >= 30"
PO_RECEIVED = 'eval:doc.eye_stage_order >= 30 && doc.eye_po_status == "Purchase Order (PO)"'


def _f(fieldname, fieldtype, label=None, **kw):
	d = {"fieldname": fieldname, "fieldtype": fieldtype, "module": MODULE}
	if label:
		d["label"] = label
	d.update(kw)
	return d


def custom_fields():
	return {
		"Sales Stage": [
			_f(
				"eye_stage_type",
				"Link",
				"Stage Type",
				options="Eye Stage Type",
				insert_after="stage_name",
				in_list_view=1,
				in_standard_filter=1,
				description="What the stage does. The app knows a stage by its type, not by its name.",
			),
			_f(
				"eye_stage_order",
				"Int",
				"Order",
				insert_after="eye_stage_type",
				in_list_view=1,
				description="Deals move up in this order. Field conditions use it too: doc.eye_stage_order",
			),
			_f("eye_color", "Color", "Color", insert_after="eye_stage_order"),
			_f("eye_column_break", "Column Break", insert_after="eye_color"),
			_f(
				"eye_roles",
				"Table MultiSelect",
				"Who Can Move Deals Into It",
				options="Eye Stage Role",
				insert_after="eye_column_break",
				description="Empty: anyone who can edit the deal.",
			),
			_f(
				"eye_checks",
				"Table MultiSelect",
				"Checks Before a Deal Enters",
				options="Eye Stage Check",
				insert_after="eye_roles",
			),
			_f("eye_description", "Small Text", "Description", insert_after="eye_checks"),
		],
		"Opportunity": [
			_f("eye_deal_tab", "Tab Break", "Deal", insert_after="naming_series"),
			_f(
				"eye_stage_type",
				"Link",
				"Stage Type",
				options="Eye Stage Type",
				insert_after="sales_stage",
				fetch_from="sales_stage.eye_stage_type",
				read_only=1,
				in_standard_filter=1,
			),
			_f(
				"eye_stage_order",
				"Int",
				"Stage Order",
				insert_after="eye_stage_type",
				fetch_from="sales_stage.eye_stage_order",
				read_only=1,
				hidden=1,
			),
			_f(
				"eye_change_pending",
				"Check",
				"A Change Is Waiting",
				insert_after="eye_stage_order",
				read_only=1,
				no_copy=1,
				depends_on="eval:doc.eye_change_pending",
				description="A financial change after the project opened; it applies once it is approved.",
			),
			_f(
				"eye_total_cost",
				"Currency",
				"Cost",
				options="currency",
				insert_after="base_opportunity_amount",
				read_only=1,
				no_copy=1,
			),
			_f(
				"eye_total_profit",
				"Currency",
				"Profit",
				options="currency",
				insert_after="eye_total_cost",
				read_only=1,
				no_copy=1,
			),
			_f("eye_margin", "Percent", "Margin", insert_after="eye_total_profit", read_only=1, no_copy=1),
			_f(
				"eye_below_minimum",
				"Check",
				"Below Minimum Margin",
				insert_after="eye_margin",
				read_only=1,
				no_copy=1,
			),
			_f("eye_po_section", "Section Break", "Customer PO", insert_after="eye_below_minimum"),
			_f(
				"eye_po_status",
				"Link",
				"PO Status",
				options="Eye PO Status",
				insert_after="eye_po_section",
				mandatory_depends_on=IN_HAND,
				in_standard_filter=1,
			),
			_f(
				"eye_po_no",
				"Data",
				"PO Number",
				insert_after="eye_po_status",
				mandatory_depends_on=PO_RECEIVED,
			),
			_f("eye_po_column", "Column Break", insert_after="eye_po_no"),
			_f(
				"eye_po_date",
				"Date",
				"PO Date",
				insert_after="eye_po_column",
				mandatory_depends_on=PO_RECEIVED,
			),
			_f("eye_po_attachment", "Attach", "PO Attachment", insert_after="eye_po_date"),
			_f(
				"eye_project_section",
				"Section Break",
				"Project",
				insert_after="eye_po_attachment",
				depends_on="eval:doc.eye_sales_order",
			),
			_f(
				"eye_sales_order",
				"Link",
				"Sales Order",
				options="Sales Order",
				insert_after="eye_project_section",
				read_only=1,
				no_copy=1,
			),
			_f("eye_project_column", "Column Break", insert_after="eye_sales_order"),
			_f(
				"eye_opened_on",
				"Date",
				"Project Opened On",
				insert_after="eye_project_column",
				read_only=1,
				no_copy=1,
			),
			_f("eye_cost_tab", "Tab Break", "Cost Sheet", insert_after="total"),
			_f(
				"eye_cost_sheet",
				"Link",
				"Cost Sheet",
				options="Cost Sheet",
				insert_after="eye_cost_tab",
				read_only=1,
				no_copy=1,
			),
			_f("eye_cost_html", "HTML", "Cost Sheet View", insert_after="eye_cost_sheet"),
			_f("eye_pl_tab", "Tab Break", "P&L", insert_after="eye_cost_html"),
			_f("eye_pl", "Link", "P&L", options="Deal PL", insert_after="eye_pl_tab", read_only=1, no_copy=1),
			_f("eye_pl_html", "HTML", "P&L View", insert_after="eye_pl"),
			_f("eye_quotations_tab", "Tab Break", "Quotations", insert_after="eye_pl_html"),
			_f(
				"eye_quotation",
				"Link",
				"Latest Quotation",
				options="Quotation",
				insert_after="eye_quotations_tab",
				read_only=1,
				no_copy=1,
			),
			_f("eye_quotations_html", "HTML", "Quotations View", insert_after="eye_quotation"),
		],
		"Opportunity Item": [
			_f(
				"eye_service_no",
				"Int",
				"Service #",
				insert_after="item_code",
				read_only=1,
				in_list_view=1,
				columns=1,
			),
			_f("eye_notes", "Small Text", "Notes", insert_after="description"),
			_f("eye_attachment", "Attach", "Attachment", insert_after="eye_notes"),
			_f(
				"eye_hide_in_pdf",
				"Check",
				"Hide in PDF",
				insert_after="eye_attachment",
				in_list_view=1,
				columns=1,
			),
		],
		"Item": [
			_f(
				"eye_requires_min_margin",
				"Link",
				"Requires Minimum Margin",
				options="Eye Yes No",
				insert_after="is_sales_item",
				depends_on="eval:doc.is_sales_item",
				mandatory_depends_on="eval:doc.is_sales_item",
			),
			_f(
				"eye_min_margin",
				"Percent",
				"Minimum Margin",
				insert_after="eye_requires_min_margin",
				depends_on="eval:doc.is_sales_item && doc.eye_requires_min_margin == 'Yes'",
				mandatory_depends_on="eval:doc.is_sales_item && doc.eye_requires_min_margin == 'Yes'",
			),
		],
		"Quotation": [
			_f("eye_section", "Section Break", "Eye CRM", insert_after="supplier_quotation", collapsible=1),
			_f(
				"eye_quotation_type",
				"Link",
				"Quotation Type",
				options="Eye Quotation Type",
				insert_after="eye_section",
				read_only=1,
				in_standard_filter=1,
			),
			_f(
				"eye_revision_of",
				"Link",
				"Revision Of",
				options="Quotation",
				insert_after="eye_quotation_type",
				read_only=1,
				no_copy=1,
			),
			_f(
				"eye_superseded",
				"Check",
				"Superseded",
				insert_after="eye_revision_of",
				read_only=1,
				no_copy=1,
				in_standard_filter=1,
				description="A newer quotation replaced this one.",
			),
			_f("eye_column", "Column Break", insert_after="eye_superseded"),
			_f("eye_pl", "Link", "P&L", options="Deal PL", insert_after="eye_column", read_only=1, no_copy=1),
			_f(
				"eye_pl_signature",
				"Data",
				"P&L Signature",
				insert_after="eye_pl",
				read_only=1,
				no_copy=1,
				hidden=1,
			),
			_f("eye_prepared_by", "Data", "Prepared By", insert_after="eye_pl_signature", read_only=1),
		],
		"Quotation Item": [
			_f("eye_service_no", "Int", "Service #", insert_after="item_code", read_only=1, columns=1),
			_f("eye_hide_in_pdf", "Check", "Hide in PDF", insert_after="description"),
		],
		"Sales Order": [
			_f("eye_section", "Section Break", "Eye CRM", insert_after="po_date", collapsible=1),
			_f(
				"eye_opportunity",
				"Link",
				"Deal",
				options="Opportunity",
				insert_after="eye_section",
				read_only=1,
				search_index=1,
				no_copy=1,
			),
			_f("eye_column", "Column Break", insert_after="eye_opportunity"),
			_f("eye_pl", "Link", "P&L", options="Deal PL", insert_after="eye_column", read_only=1, no_copy=1),
		],
		"Sales Order Item": [
			_f("eye_service_no", "Int", "Service #", insert_after="item_code", read_only=1, columns=1),
		],
	}


# (doctype, fieldname or None for the doctype, property, value, property_type)
PROPERTY_SETTERS = [
	("Sales Stage", None, "sort_field", "eye_stage_order", "Data"),
	("Sales Stage", None, "sort_order", "ASC", "Data"),
	("Opportunity", "sales_stage", "default", "Estimation", "Text"),
	("Opportunity", "sales_stage", "in_standard_filter", "1", "Check"),
	("Opportunity", "title", "hidden", "0", "Check"),
	("Opportunity", "title", "label", "Deal Name", "Data"),
	("Opportunity", "title", "in_list_view", "1", "Check"),
	("Opportunity", "opportunity_owner", "label", "Salesperson", "Data"),
	("Opportunity", "transaction_date", "label", "Date", "Data"),
	("Opportunity", "section_break_14", "label", "Value", "Data"),
	("Opportunity", "opportunity_amount", "label", "Selling", "Data"),
	("Opportunity", "opportunity_amount", "read_only", "1", "Check"),
	("Opportunity", "base_opportunity_amount", "label", "Selling (Company Currency)", "Data"),
	("Opportunity", "probability", "hidden", "1", "Check"),
	("Opportunity", "organization_details_section", "hidden", "1", "Check"),
	("Opportunity", "utm_analytics_section", "hidden", "1", "Check"),
	("Opportunity", "items_section", "label", "Services", "Data"),
	("Opportunity", "items", "label", "Services", "Data"),
	("Opportunity", "section_break_32", "hidden", "1", "Check"),
	("Opportunity Item", "rate", "reqd", "0", "Check"),
	("Opportunity Item", "rate", "hidden", "1", "Check"),
	("Opportunity Item", "rate", "in_list_view", "0", "Check"),
	("Opportunity Item", "amount", "reqd", "0", "Check"),
	("Opportunity Item", "amount", "hidden", "1", "Check"),
	("Opportunity Item", "amount", "in_list_view", "0", "Check"),
	("Opportunity Item", "base_rate", "reqd", "0", "Check"),
	("Opportunity Item", "base_rate", "hidden", "1", "Check"),
	("Opportunity Item", "base_amount", "reqd", "0", "Check"),
	("Opportunity Item", "base_amount", "hidden", "1", "Check"),
	("Opportunity Item", "quantity_and_rate_section", "hidden", "1", "Check"),
	("Opportunity Item", "item_code", "columns", "4", "Int"),
	("Opportunity Item", "qty", "columns", "2", "Int"),
	("Opportunity Item", "uom", "in_list_view", "1", "Check"),
	("Opportunity Item", "uom", "columns", "2", "Int"),
	("Opportunity Item", "section_break_6", "label", "Details", "Data"),
]

# the deal's layout: Deal, Contacts, Services, Cost Sheet, P&L, Quotations, then ERPNext's own tabs
OPPORTUNITY_ORDER = [
	"eye_deal_tab",
	"title",
	"opportunity_from",
	"party_name",
	"customer_name",
	"column_break0",
	"opportunity_owner",
	"transaction_date",
	"expected_closing",
	"column_break_10",
	"sales_stage",
	"eye_stage_type",
	"eye_stage_order",
	"status",
	"eye_change_pending",
	"section_break_14",
	"currency",
	"conversion_rate",
	"column_break_36",
	"opportunity_amount",
	"base_opportunity_amount",
	"column_break_17",
	"eye_total_cost",
	"eye_total_profit",
	"eye_margin",
	"eye_below_minimum",
	"eye_po_section",
	"eye_po_status",
	"eye_po_no",
	"eye_po_column",
	"eye_po_date",
	"eye_po_attachment",
	"eye_project_section",
	"eye_sales_order",
	"eye_project_column",
	"eye_opened_on",
	"lost_detail_section",
	"lost_reasons",
	"order_lost_reason",
	"column_break_56",
	"competitors",
	"more_info",
	"company",
	"opportunity_type",
	"naming_series",
	"column_break1",
	"language",
	"probability",
	"amended_from",
	"first_response_time",
	"organization_details_section",
	"no_of_employees",
	"annual_revenue",
	"customer_group",
	"column_break_23",
	"industry",
	"market_segment",
	"website",
	"column_break_31",
	"city",
	"state",
	"country",
	"territory",
	"utm_analytics_section",
	"utm_source",
	"utm_medium",
	"column_break_emai",
	"utm_campaign",
	"utm_content",
	"contact_info",
	"primary_contact_section",
	"contact_person",
	"job_title",
	"column_break_54",
	"contact_email",
	"contact_mobile",
	"column_break_22",
	"whatsapp",
	"phone",
	"phone_ext",
	"address_contact_section",
	"address_html",
	"customer_address",
	"address_display",
	"column_break3",
	"contact_html",
	"contact_display",
	"items_section",
	"items",
	"section_break_32",
	"base_total",
	"column_break_33",
	"total",
	"eye_cost_tab",
	"eye_cost_sheet",
	"eye_cost_html",
	"eye_pl_tab",
	"eye_pl",
	"eye_pl_html",
	"eye_quotations_tab",
	"eye_quotation",
	"eye_quotations_html",
	"activities_tab",
	"open_activities_html",
	"all_activities_section",
	"all_activities_html",
	"notes_tab",
	"notes_html",
	"notes",
	"dashboard_tab",
]

OPPORTUNITY_ITEM_ORDER = [
	"eye_service_no",
	"item_code",
	"item_name",
	"col_break1",
	"uom",
	"qty",
	"section_break_6",
	"description",
	"eye_notes",
	"eye_attachment",
	"eye_hide_in_pdf",
	"column_break_8",
	"brand",
	"item_group",
	"image",
	"image_view",
	"quantity_and_rate_section",
	"base_rate",
	"base_amount",
	"column_break_16",
	"rate",
	"amount",
]

FIELD_ORDERS = {"Opportunity": OPPORTUNITY_ORDER, "Opportunity Item": OPPORTUNITY_ITEM_ORDER}


def make_custom_fields():
	# update=False: a field that is already there (changed from Customize Form, say) is left alone
	create_custom_fields(custom_fields(), ignore_validate=True, update=False)


def make_property_setters():
	for doctype, fieldname, prop, value, ptype in PROPERTY_SETTERS:
		set_once(doctype, fieldname, prop, value, ptype)
	for doctype, order in FIELD_ORDERS.items():
		meta_fields = {df.fieldname for df in frappe.get_meta(doctype).fields}
		# a field ERPNext no longer has, or one of ours that was deleted, is left out
		set_once(doctype, None, "field_order", json.dumps([f for f in order if f in meta_fields]), "Data")


def set_once(doctype, fieldname, prop, value, ptype):
	"""A property setter the app wants, made only if the site has none for it yet."""
	filters = {"doc_type": doctype, "property": prop}
	if fieldname:
		filters["field_name"] = fieldname
	else:
		filters["doctype_or_field"] = "DocType"
	if frappe.db.exists("Property Setter", filters):
		return
	frappe.make_property_setter(
		{
			"doctype": doctype,
			"doctype_or_field": "DocField" if fieldname else "DocType",
			"fieldname": fieldname,
			"property": prop,
			"value": value,
			"property_type": ptype,
		},
		validate_fields_for_doctype=False,
		is_system_generated=False,
		module=MODULE,
	)
