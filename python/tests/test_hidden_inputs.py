"""Explicitly selected hidden files work; Finder resource-fork sidecars do not."""
from pathlib import Path

from compare_workbooks import assert_workbooks_equal
from test_engine import EngineTestCase
import engine


class HiddenInputTests(EngineTestCase):
    def test_explicit_hidden_paypal_has_same_output_as_visible_input(self):
        visible = self.paypal("visible.csv")
        hidden = self.inputs / ".hidden.csv"
        hidden.write_bytes(visible.read_bytes())
        expected = self.baseline("paypal", visible, self.rules)
        actual = {Path(p).name: Path(p) for p in self.execute(self.request("paypal", [hidden]))}
        self.assertEqual(set(expected), set(actual))
        for name in expected:
            assert_workbooks_equal(expected[name], actual[name])
        self.assertEqual(hidden.read_bytes(), visible.read_bytes())

    def test_hidden_invoice_retains_production_filename_fallback(self):
        rows = [["RE-1", "invalid", "invalid", "invalid", "Customer", "1,00", "1,19", "1,19", "", ""]]
        hidden = self.invoice(".hidden.csv", rows=rows)
        actual = self.compare_with_baseline("sevdesk", hidden)
        self.assertEqual(set(actual), {".hidden.xlsx"})

    def test_appledouble_sidecars_are_rejected_without_output(self):
        for mode in ("paypal", "sevdesk"):
            with self.subTest(mode=mode):
                source = self.paypal("._export.csv") if mode == "paypal" else self.invoice("._export.csv")
                with self.assertRaises(engine.JobError):
                    self.execute(self.request(mode, [source]))
                self.assertEqual(list(self.output.iterdir()), [])
