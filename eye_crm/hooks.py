app_name = "eye_crm"
app_title = "Eye CRM"
app_publisher = "Kamal Adel"
app_description = "Deals, costing, pricing, approvals and billing for Eye Advertising, on ERPNext"
app_email = "Kamal.adel@outlook.com"
app_license = "mit"

required_apps = ["erpnext"]

# What the app puts on a site is created once, when it is installed (eye_crm.setup.install).
# After that the site owns it: a migrate never brings back what was changed or deleted from the
# desk. A later change from the app comes as a patch that makes that one change.
after_install = "eye_crm.setup.install.after_install"
before_uninstall = "eye_crm.setup.install.before_uninstall"
