"""Order payload validation that returns gaps, not exceptions.

A malformed order coming out of an ERP export is an everyday event, not an
exceptional one. This module walks the payload manually and returns every
problem it finds as an actionable gap (field path, problem, hint), so the
scenario can route the order to a fix-up queue with the full list attached.
No silent type coercion: a quantity of "2" is a mapping bug upstream and is
reported as one.
"""

from __future__ import annotations

from typing import Any

from .models import Gap


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_quantity(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


class OrderValidator:
    """Validates a synthetic order payload and accumulates evidence as it goes."""

    def validate(self, payload: dict[str, Any]) -> tuple[list[str], list[Gap]]:
        """Return (passed check names, gaps). Never raises on payload shape."""

        passed: list[str] = []
        gaps: list[Gap] = []

        def check(name: str, ok: bool, problem: str, hint: str) -> bool:
            if ok:
                passed.append(name)
            else:
                gaps.append(Gap(field=name, problem=problem, hint=hint))
            return ok

        check(
            "order_ref",
            _is_nonempty_str(payload.get("order_ref")),
            "missing or empty",
            "map the ERP order reference into order_ref as a non-empty string",
        )

        customer = payload.get("customer")
        if check(
            "customer",
            isinstance(customer, dict),
            "missing or not an object",
            "send customer as an object with name and email",
        ):
            assert isinstance(customer, dict)
            check(
                "customer.name",
                _is_nonempty_str(customer.get("name")),
                "missing or empty",
                "the 3PL prints this on the label; it cannot be blank",
            )
            email = customer.get("email")
            check(
                "customer.email",
                _is_nonempty_str(email)
                and "@" in email
                and "." in email.rsplit("@", 1)[-1],
                "missing or not a plausible email address",
                "delivery notifications bounce without a valid email",
            )

        address = payload.get("shipping_address")
        if check(
            "shipping_address",
            isinstance(address, dict),
            "missing or not an object",
            "send shipping_address as an object with line1, city, postal_code, country_code",
        ):
            assert isinstance(address, dict)
            for field_name in ("line1", "city", "postal_code"):
                check(
                    f"shipping_address.{field_name}",
                    _is_nonempty_str(address.get(field_name)),
                    "missing or empty",
                    f"the carrier rejects labels without {field_name}",
                )
            country = address.get("country_code")
            check(
                "shipping_address.country_code",
                isinstance(country, str) and len(country) == 2 and country.isalpha(),
                "must be a 2-letter ISO country code",
                "convert country names to ISO 3166-1 alpha-2 before export",
            )

        check(
            "shipping_method",
            _is_nonempty_str(payload.get("shipping_method")),
            "missing or empty",
            "resolve it first via POST /map/shipping-method",
        )

        lines = payload.get("lines")
        if not isinstance(lines, list):
            check(
                "lines",
                False,
                "missing or not a list",
                "send lines as a list of {sku, quantity} objects",
            )
        elif len(lines) == 0:
            check(
                "lines",
                False,
                "empty; an order needs at least one line",
                "empty exports usually mean the ERP search matched nothing upstream",
            )
        else:
            passed.append("lines")
            for i, line in enumerate(lines):
                if not isinstance(line, dict):
                    gaps.append(
                        Gap(
                            field=f"lines[{i}]",
                            problem="not an object",
                            hint="each line must be a {sku, quantity} object",
                        )
                    )
                    continue
                check(
                    f"lines[{i}].sku",
                    _is_nonempty_str(line.get("sku")),
                    "missing or empty",
                    "the 3PL picks by sku; a blank sku blocks the whole order",
                )
                quantity = line.get("quantity")
                check(
                    f"lines[{i}].quantity",
                    _is_quantity(quantity),
                    f"must be a positive integer, got {quantity!r}",
                    "no silent coercion here; fix the type at the export mapping",
                )

        return passed, gaps
