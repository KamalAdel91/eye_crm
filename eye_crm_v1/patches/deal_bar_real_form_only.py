"""Eye Deal Bar: draw only on the real form, not on the stand-in form of Nexlify Board's move popup.

Changes only those two lines of the site's script; a script edited there from the desk is left as it is.
"""

import frappe

OLD = "\t\tconst layout = frm.layout && frm.layout.wrapper;\n\t\tif (!layout) return;\n"
NEW = (
	"\t\t// only on the real form: Nexlify Board's move popup runs this script on a stand-in form\n"
	"\t\tconst layout = frm.layout && frm.layout.wrapper;\n"
	'\t\tif (!layout || typeof layout !== "object") return;\n'
)


def execute():
	if not frappe.db.exists("Client Script", "Eye Deal Bar"):
		return
	script = frappe.db.get_value("Client Script", "Eye Deal Bar", "script") or ""
	if OLD in script:
		frappe.db.set_value("Client Script", "Eye Deal Bar", "script", script.replace(OLD, NEW))
