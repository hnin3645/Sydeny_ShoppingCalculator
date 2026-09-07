import json
import unittest

from shopping_calculator import ExpenseEntry, ShoppingCalculator


def calculator_without_ui() -> ShoppingCalculator:
    calculator = ShoppingCalculator.__new__(ShoppingCalculator)
    calculator.people = ["msc", "nhy", "wpq", "zyf"]
    calculator.entries = []
    calculator.totals = {name: 0.0 for name in calculator.people}
    calculator.monthly_discount_enabled = False
    return calculator


class MonthlyDiscountTests(unittest.TestCase):
    def test_discount_changes_displayed_shares_without_mutating_entries(self):
        calculator = calculator_without_ui()
        entry = ExpenseEntry.create(["msc", "nhy"], 19.35)
        calculator.entries.append(entry)
        original_shares = dict(entry.shares)

        calculator.monthly_discount_enabled = True
        calculator.recalculate_totals()

        self.assertEqual(calculator.totals["msc"], 8.71)
        self.assertEqual(calculator.totals["nhy"], 8.70)
        self.assertEqual(entry.amount, 19.35)
        self.assertEqual(entry.shares, original_shares)

        calculator.monthly_discount_enabled = False
        calculator.recalculate_totals()
        self.assertEqual(calculator.totals["msc"], 9.68)
        self.assertEqual(calculator.totals["nhy"], 9.67)

    def test_each_product_share_is_rounded_after_discount(self):
        calculator = calculator_without_ui()
        calculator.entries.extend(
            [
                ExpenseEntry.create(["msc"], 5.00),
                ExpenseEntry.create(["msc"], 14.00),
                ExpenseEntry.create(["nhy"], 8.30),
            ]
        )
        calculator.monthly_discount_enabled = True

        calculator.recalculate_totals()

        self.assertEqual(calculator.totals["msc"], 17.10)
        self.assertEqual(calculator.totals["nhy"], 7.47)

    def test_wow_offer_row_is_not_imported_twice(self):
        calculator = calculator_without_ui()
        rows = calculator.parse_invoice_json(
            json.dumps(
                [
                    {"item": "#Kleenex Viva Paper Towels White 3pk", "price": 5.00, "priceText": "5.00"},
                    {"item": "WOW 10% OFFER", "price": -9.38, "priceText": "-9.38"},
                ]
            )
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item"], "#Kleenex Viva Paper Towels White 3pk")


if __name__ == "__main__":
    unittest.main()
