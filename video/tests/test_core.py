"""Unit tests for generic pieces: quote check, wrapping, label placement, stage contract."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from vidpipe.inputs import Pages


class QuoteCheck(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "p010.txt").write_text("Глины наиболее радиоактивны из осадочных пород.\nВторая фраза стра-\nницы.", "utf-8")
        (self.d / "p011.txt").write_text("Песчаники менее активны.", "utf-8")
        (self.d / "README.md").write_text("Песчаники менее активны. Это не страница главы.", "utf-8")

    def test_exact_on_cited_page(self):
        P = Pages(self.d)
        self.assertEqual(P.find_quote("Глины наиболее радиоактивны", 10)["status"], "verified")
        self.assertEqual(P.find_quote("Вторая фраза страницы", 10)["status"], "verified")   # hyphenation

    def test_wrong_page(self):
        P = Pages(self.d)
        self.assertEqual(P.find_quote("Глины наиболее радиоактивны", 30)["status"], "wrong_page")

    def test_edited_quote_is_not_verified(self):
        P = Pages(self.d)       # one word changed: similar, but not the book's text
        self.assertEqual(P.find_quote("Глины наименее радиоактивны из осадочных пород", 10)["status"], "near")

    def test_fake_quote(self):
        P = Pages(self.d)
        self.assertEqual(P.find_quote("Этой фразы нет нигде в тексте главы", 10)["status"], "not_found")

    def test_readme_is_not_a_page(self):
        P = Pages(self.d)
        self.assertEqual(sorted(k for k in P.pages), [10, 11])


class Wrap(unittest.TestCase):
    def test_symbol_never_starts_a_line(self):
        from vidpipe.overlays import wrap_runs, font
        f = font("Inter-Bold.otf", 40)
        for w in (200, 300, 420):
            lines = [[t for t, _, _ in ln] for ln in wrap_runs("иззубренность = флуктуации", f, w)]
            self.assertTrue(all(ln[0] != "=" for ln in lines), lines)


class Placement(unittest.TestCase):
    def test_callouts_avoid_moving_object_and_each_other(self):
        from vidpipe.templates.base import Ctx, place_callouts
        from vidpipe.util import RES_DIR, read_json
        from vidpipe.inputs import DomainPack
        theme = read_json(RES_DIR / "themes" / "F.json")
        ctx = Ctx(720, 1280, 30, 4.0, theme, DomainPack(None), "ru", read_json(RES_DIR / "i18n.json"))
        n = ctx.n
        ys = np.linspace(900, 300, n)                     # an object moving up through the middle column
        obj = {"boxes": np.column_stack([np.full(n, 330), ys - 60, np.full(n, 390), ys + 60]), "w": 14.0}
        labels = [{"text": "первая подпись", "size": 23, "target": (360, 600), "t0": 0.5},
                  {"text": "вторая подпись", "size": 23, "target": (360, 620), "t0": 1.0}]
        res = place_callouts(ctx, labels, [obj], (40, 262, 680, 962))
        a, b = res[0]["box"], res[1]["box"]
        self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], (a, b))
        for r, L in zip(res, labels):
            x0, y0, x1, y1 = r["box"]
            for f in range(int(L["t0"] * 30), n, 5):
                ob = obj["boxes"][f]
                self.assertFalse(x0 < ob[2] and ob[0] < x1 and y0 < ob[3] and ob[1] < y1, (r["box"], ob))


class StageContract(unittest.TestCase):
    def test_missing_inputs_fail_fast(self):
        from vidpipe.cli import check_inputs, MissingInputs
        d = Path(tempfile.mkdtemp())
        (d / "00_brief.json").write_text('{"video_id": "x"}', "utf-8")
        with self.assertRaises(MissingInputs) as cm:
            check_inputs(d, ["layout", "render"])
        self.assertIn("--from script", str(cm.exception))
        check_inputs(d, ["script", "shotlist", "specs", "models", "audio", "layout"])   # producers run first: ok


if __name__ == "__main__":
    unittest.main()
