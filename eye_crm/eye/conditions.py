"""Field conditions written on the desk, evaluated on the server.

`depends_on` and `mandatory_depends_on` are JavaScript, written in Customize Form, for example
	eval:doc.eye_stage_order >= 30 && doc.eye_po_status == "Purchase Order (PO)"
The form runs them in the browser. A deal can also move without its form (from a board, an API
call, an action button), so the server runs the same rule: this module reads the usual subset of
JavaScript, writes the Python for it, and runs that with frappe.safe_eval.

The subset: doc.field, literals (numbers, strings, true/false/null/undefined, [lists]),
! && || == != === !== < > <= >= + - * / %, brackets, .length, .includes(), .indexOf(),
.startsWith(), in_list(), cint(), flt(), frappe.user.has_role(), frappe.session.user.
Anything else raises ConditionError: the caller then leaves that rule to the form.
"""

import re
from types import SimpleNamespace

import frappe
from frappe.utils import cint, flt


class ConditionError(Exception):
	pass


_TOKEN = re.compile(
	r"""
	(?P<ws>\s+)
	|(?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
	|(?P<num>\d+(?:\.\d+)?)
	|(?P<op>===|!==|==|!=|>=|<=|&&|\|\||[!<>()\[\],.+\-*/%])
	|(?P<name>[A-Za-z_$][\w$]*)
	""",
	re.VERBOSE,
)

_LITERALS = {"true": "True", "false": "False", "null": "None", "undefined": "None"}
_METHODS = {"includes": "eye_includes", "indexOf": "eye_index_of", "startsWith": "eye_starts_with"}
_FUNCTIONS = {"in_list", "cint", "flt"}


def _tokenize(expr: str) -> list[tuple[str, str]]:
	tokens, pos = [], 0
	while pos < len(expr):
		m = _TOKEN.match(expr, pos)
		if not m:
			raise ConditionError(f"cannot read {expr[pos : pos + 12]!r}")
		pos = m.end()
		if m.lastgroup != "ws":
			tokens.append((m.lastgroup, m.group()))
	return tokens


class _Parser:
	"""Recursive descent over the JavaScript subset, emitting Python source."""

	def __init__(self, tokens):
		self.tokens = tokens
		self.i = 0

	def peek(self, value=None):
		if self.i >= len(self.tokens):
			return None
		tok = self.tokens[self.i]
		return tok if value is None or tok[1] == value else None

	def take(self, value=None):
		tok = self.peek(value)
		if tok is None:
			raise ConditionError(f"expected {value!r}" if value else "unexpected end")
		self.i += 1
		return tok

	def parse(self):
		out = self.or_expr()
		if self.i != len(self.tokens):
			raise ConditionError(f"unexpected {self.tokens[self.i][1]!r}")
		return out

	def or_expr(self):
		left = self.and_expr()
		while self.peek("||"):
			self.take()
			right = self.and_expr()
			left = f"({left} if eye_truthy({left}) else {right})"
		return left

	def and_expr(self):
		left = self.equality()
		while self.peek("&&"):
			self.take()
			right = self.equality()
			left = f"({right} if eye_truthy({left}) else {left})"
		return left

	def equality(self):
		left = self.relational()
		while (tok := self.peek()) and tok[1] in ("==", "!=", "===", "!=="):
			self.take()
			right = self.relational()
			eq = f"eye_eq({left}, {right})"
			left = eq if tok[1] in ("==", "===") else f"(not {eq})"
		return left

	def relational(self):
		left = self.additive()
		while (tok := self.peek()) and tok[1] in ("<", ">", "<=", ">="):
			self.take()
			right = self.additive()
			left = f"eye_compare({left}, {tok[1]!r}, {right})"
		return left

	def additive(self):
		left = self.multiplicative()
		while (tok := self.peek()) and tok[1] in ("+", "-"):
			self.take()
			left = f"({left} {tok[1]} {self.multiplicative()})"
		return left

	def multiplicative(self):
		left = self.unary()
		while (tok := self.peek()) and tok[1] in ("*", "/", "%"):
			self.take()
			left = f"({left} {tok[1]} {self.unary()})"
		return left

	def unary(self):
		if self.peek("!"):
			self.take()
			return f"(not eye_truthy({self.unary()}))"
		if (tok := self.peek()) and tok[1] in ("-", "+"):
			self.take()
			return f"({tok[1]}{self.unary()})"
		return self.postfix()

	def postfix(self):
		expr = self.primary()
		while True:
			if self.peek("."):
				self.take()
				kind, name = self.take()
				if kind != "name":
					raise ConditionError(f"expected a name after '.', got {name!r}")
				if self.peek("("):
					args = self.arguments()
					if expr == "frappe.user" and name == "has_role":
						expr = f"frappe.user.has_role({args})"
					elif name in _METHODS:
						expr = f"{_METHODS[name]}({expr}, {args})"
					else:
						raise ConditionError(f"method {name}() is not supported")
				elif name == "length":
					expr = f"eye_len({expr})"
				elif name.startswith(("_", "$")):
					expr = f"eye_get({expr}, {name!r})"
				else:
					expr = f"{expr}.{name}"
			elif self.peek("["):
				self.take()
				index = self.or_expr()
				self.take("]")
				expr = f"eye_item({expr}, {index})"
			else:
				return expr

	def arguments(self):
		self.take("(")
		args = []
		while not self.peek(")"):
			args.append(self.or_expr())
			if not self.peek(")"):
				self.take(",")
		self.take(")")
		return ", ".join(args)

	def primary(self):
		kind, value = self.take()
		if kind in ("num", "str"):
			return value
		if value == "(":
			inner = self.or_expr()
			self.take(")")
			return f"({inner})"
		if value == "[":
			items = []
			while not self.peek("]"):
				items.append(self.or_expr())
				if not self.peek("]"):
					self.take(",")
			self.take("]")
			return "[" + ", ".join(items) + "]"
		if kind == "name":
			if value in _LITERALS:
				return _LITERALS[value]
			if value in _FUNCTIONS:
				return f"{value}({self.arguments()})"
			if value in ("doc", "frappe"):
				return value
			raise ConditionError(f"unknown name {value!r}")
		raise ConditionError(f"unexpected {value!r}")


def to_python(expression: str) -> str:
	"""The Python for a desk condition (with or without the `eval:` prefix)."""
	expression = (expression or "").strip()
	if expression.startswith("eval:"):
		expression = expression[5:].strip()
	elif re.fullmatch(r"[A-Za-z_]\w*", expression):
		# a bare fieldname: the field has a value
		expression = f"doc.{expression}"
	if not expression:
		raise ConditionError("empty condition")
	return _Parser(_tokenize(expression)).parse()


# what the translated code may call: JavaScript's truthiness and loose comparisons


def _truthy(value):
	if value is None or value is False:
		return False
	if isinstance(value, int | float):
		return value != 0
	if isinstance(value, str):
		return value != ""
	return True


def _number(value):
	if isinstance(value, bool):
		return int(value)
	if isinstance(value, int | float):
		return value
	if value is None or value == "":
		return 0 if value == "" else None
	try:
		return float(value)
	except TypeError, ValueError:
		return None


def _eq(a, b):
	if a is None or b is None:
		return a is None and b is None
	if isinstance(a, str) and isinstance(b, str):
		return a == b
	na, nb = _number(a), _number(b)
	if na is not None and nb is not None:
		return na == nb
	return a == b


def _compare(a, op, b):
	if isinstance(a, str) and isinstance(b, str):
		x, y = a, b
	else:
		x, y = _number(a), _number(b)
		if x is None or y is None:
			return False
	return {"<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]


def _includes(container, value):
	if container is None:
		return False
	if isinstance(container, str):
		return str(value) in container
	return any(_eq(v, value) for v in container)


def _index_of(container, value):
	if container is None:
		return -1
	if isinstance(container, str):
		return container.find(str(value))
	for i, v in enumerate(container):
		if _eq(v, value):
			return i
	return -1


def _len(value):
	return len(value) if value is not None else 0


class _JSObject:
	"""A document as the condition sees it: every name is a field, even `items` or `get`, which a
	dict would answer with its own methods."""

	__slots__ = ("_data",)

	def __init__(self, data):
		object.__setattr__(self, "_data", data)

	def __getattribute__(self, key):
		return object.__getattribute__(self, "_data").get(key)


def _field(obj, key):
	if isinstance(obj, _JSObject):
		return object.__getattribute__(obj, "_data").get(key)
	return None


def _item(container, index):
	if isinstance(container, _JSObject):
		return _field(container, index)
	try:
		return container[int(index)] if isinstance(container, list | str) else None
	except IndexError, TypeError, ValueError:
		return None


def _as_js_object(value):
	if isinstance(value, dict):
		return _JSObject({k: _as_js_object(v) for k, v in value.items()})
	if isinstance(value, list):
		return [_as_js_object(v) for v in value]
	return value


def evaluate(expression: str, doc, user: str | None = None) -> bool:
	"""Run a desk condition against `doc` (a Document or a dict). Raises ConditionError when the
	condition is outside the subset this module reads."""
	code = to_python(expression)
	data = doc.as_dict(convert_dates_to_str=True) if hasattr(doc, "as_dict") else dict(doc)
	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	context = {
		"doc": _as_js_object(data),
		"frappe": SimpleNamespace(
			user=SimpleNamespace(has_role=lambda *r: any(x in roles for x in r), name=user),
			session=SimpleNamespace(user=user),
		),
		"in_list": lambda lst, value: _includes(lst, value),
		"cint": cint,
		"flt": flt,
		"eye_truthy": _truthy,
		"eye_eq": _eq,
		"eye_compare": _compare,
		"eye_includes": _includes,
		"eye_index_of": _index_of,
		"eye_starts_with": lambda s, p: isinstance(s, str) and s.startswith(str(p)),
		"eye_len": _len,
		"eye_get": _field,
		"eye_item": _item,
	}
	try:
		return _truthy(frappe.safe_eval(code, context))
	except ConditionError:
		raise
	except Exception as e:
		raise ConditionError(f"{expression}: {e}") from e
