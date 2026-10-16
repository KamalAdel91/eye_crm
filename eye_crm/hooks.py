app_name = "eye_crm"
app_title = "Eye CRM"
app_publisher = "Kamal Adel"
app_description = "Deals, costing, pricing, approvals and billing for Eye Advertising, on ERPNext"
app_email = "Kamal.adel@outlook.com"
app_license = "mit"

required_apps = ["erpnext"]

add_to_apps_screen = [
	{
		"name": "eye_crm",
		"logo": "/assets/eye_crm/images/eye-crm.svg",
		"title": "Eye CRM",
		"route": "/desk/eye-home",
		"has_permission": "eye_crm.eye.permissions.has_app_permission",
	}
]

# What the app puts on a site is made once, when it is installed (eye_crm.setup.install).
# After that the site owns it: a migrate never brings back what was changed or deleted from the
# desk. A later change from the app comes as a patch that makes that one change.
before_install = "eye_crm.setup.install.before_install"
after_install = "eye_crm.setup.install.after_install"
before_uninstall = "eye_crm.setup.install.before_uninstall"
setup_wizard_complete = "eye_crm.setup.install.after_setup_wizard"
# an app installed after this one (Nexlify Board) gets the app's settings in it then
after_app_install = "eye_crm.setup.install.after_app_install"

app_include_js = "eye_crm.bundle.js"
app_include_css = "eye_crm.bundle.css"

doctype_js = {
	"Opportunity": "public/js/opportunity.js",
	"Quotation": "public/js/quotation.js",
}
doctype_list_js = {"Quotation": "public/js/quotation_list.js"}

extend_doctype_class = {
	"Opportunity": "eye_crm.overrides.opportunity.EyeOpportunity",
	"Quotation": "eye_crm.overrides.quotation.EyeQuotation",
	"Sales Order": "eye_crm.overrides.sales_order.EyeSalesOrder",
	"Sales Stage": "eye_crm.overrides.sales_stage.EyeSalesStage",
	"Item": "eye_crm.overrides.item.EyeItem",
}

# a deal's documents follow the deal (eye_crm.eye.permissions)
has_permission = {
	"Cost Sheet": "eye_crm.eye.permissions.has_permission",
	"Deal PL": "eye_crm.eye.permissions.has_permission",
	"Quotation": "eye_crm.eye.permissions.has_permission",
	"Sales Order": "eye_crm.eye.permissions.has_permission",
	"Billing Request": "eye_crm.eye.permissions.has_permission",
}
permission_query_conditions = {
	"Cost Sheet": "eye_crm.eye.permissions.cost_sheet_query",
	"Deal PL": "eye_crm.eye.permissions.deal_pl_query",
	"Quotation": "eye_crm.eye.permissions.quotation_query",
	"Sales Order": "eye_crm.eye.permissions.sales_order_query",
	"Billing Request": "eye_crm.eye.permissions.billing_request_query",
}

override_doctype_dashboards = {
	"Opportunity": "eye_crm.overrides.dashboards.opportunity",
}
