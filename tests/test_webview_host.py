import json
import shutil
import subprocess
import unittest

import app_browser
import webview_host


EVERYDAY_ACTIVITY_URL = "https://www.everyday.com.au/index.html#/my-activity"

RECEIPT_TEXT = """Description
$
Banana Cavendish
1.307 kg NET @ $4.90/kg
6.40
WW Lean Beef Mince 1kg
19.35
#Brioche Gourmet Sliced Loaf 500g
8.80
WW Minced Garlic 250g
1.25
^Pace Farm Free Range Eggs XL 12pk 700g
6.90
^Bega Cheese Slices Colby 250g
6.40
Pauls Zymil Thickened Cream L/Free 300ml
4.45"""


class ReceiptParserTests(unittest.TestCase):
    def test_weight_line_is_quantity_info_not_product_name(self):
        rows = webview_host.parse_generic_receipt_text(RECEIPT_TEXT)

        self.assertEqual(rows[0]["item"], "Banana Cavendish")
        self.assertEqual(rows[0]["quantityInfo"], "1.307 kg NET @ $4.90/kg")
        self.assertEqual(rows[0]["price"], 6.40)
        self.assertEqual(len(rows), 7)

    def test_weight_and_total_on_same_line_are_separated(self):
        rows = webview_host.parse_generic_receipt_text(
            "Banana Cavendish\n1.307 kg NET @ $4.90/kg 6.40"
        )

        self.assertEqual(
            rows[0],
            {
                "item": "Banana Cavendish",
                "quantityInfo": "1.307 kg NET @ $4.90/kg",
                "price": 6.40,
                "priceText": "6.40",
            },
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the JavaScript regression test")
    def test_javascript_rejects_partial_structured_weight_row(self):
        # The structured candidates deliberately omit "Banana Cavendish",
        # matching the Everyday layout that caused the regression. The script
        # must abandon that incomplete view and use ordered body text instead.
        candidates = [
            "1.307 kg NET @ $4.90/kg 6.40",
            "WW Lean Beef Mince 1kg 19.35",
            "#Brioche Gourmet Sliced Loaf 500g 8.80",
            "WW Minced Garlic 250g 1.25",
            "^Pace Farm Free Range Eggs XL 12pk 700g 6.90",
            "^Bega Cheese Slices Colby 250g 6.40",
            "Pauls Zymil Thickened Cream L/Free 300ml 4.45",
        ]
        harness = f"""
const candidateTexts = {json.dumps(candidates)};
const candidates = candidateTexts.map(innerText => ({{
  innerText,
  querySelector: () => null
}}));
global.document = {{
  querySelectorAll: selector => selector === '[class*="item"],[class*="line"],[class*="product"],[class*="receipt"]' ? candidates : [],
  body: {{ innerText: {json.dumps(RECEIPT_TEXT)} }}
}};
console.log({webview_host.INVOICE_EXTRACTOR_EVAL_JS});
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", harness],
            check=True,
            capture_output=True,
            text=True,
        )
        rows = json.loads(completed.stdout)

        self.assertEqual(rows[0]["item"], "Banana Cavendish")
        self.assertEqual(rows[0]["quantityInfo"], "1.307 kg NET @ $4.90/kg")
        self.assertEqual(rows[0]["price"], 6.40)
        self.assertEqual(len(rows), 7)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the JavaScript regression test")
    def test_javascript_coles_style_dom_pairs_weight_with_product(self):
        dom_rows = [
            ["Banana Cavendish", ""],
            ["1.307 kg NET @ $4.90/kg", "6.40"],
            ["WW Lean Beef Mince 1kg", "19.35"],
        ]
        harness = f"""
const domRows = {json.dumps(dom_rows)}.map(([text, price]) => ({{
  querySelector: selector => selector === 'p'
    ? {{ innerText: text }}
    : (selector === 'span.text-right.price' && price ? {{ innerText: price }} : null)
}}));
global.document = {{
  querySelectorAll: selector => selector === 'div.sub-heading.items' ? domRows : [],
  body: {{ innerText: '' }}
}};
console.log({webview_host.INVOICE_EXTRACTOR_EVAL_JS});
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", harness],
            check=True,
            capture_output=True,
            text=True,
        )
        rows = json.loads(completed.stdout)

        self.assertEqual(
            rows[0],
            {
                "item": "Banana Cavendish",
                "quantityInfo": "1.307 kg NET @ $4.90/kg",
                "price": 6.40,
                "priceText": "6.40",
            },
        )


class BrowserDefaultTests(unittest.TestCase):
    def test_everyday_activity_is_the_default_page(self):
        self.assertEqual(app_browser.DEFAULT_START_URL, EVERYDAY_ACTIVITY_URL)
        self.assertEqual(webview_host.DEFAULT_START_URL, EVERYDAY_ACTIVITY_URL)


if __name__ == "__main__":
    unittest.main()
