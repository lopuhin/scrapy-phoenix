"""Gate checks that don't need a spider: scope and variation (docs/DESIGN.md §7)."""

import json
import subprocess
from types import SimpleNamespace

from zyte_common_items import Product

from selfheal.gate import check_fields, check_scope, check_variation, tracked_files


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "pkg" / "variants").mkdir(parents=True)
    (tmp_path / "pkg" / "variants" / "product_v1.py").write_text("v1\n")
    (tmp_path / "pkg" / "items.py").write_text("checks\n")
    return tracked_files(tmp_path)


def test_scope_accepts_one_new_variant_module(tmp_path):
    baseline = _repo(tmp_path)
    (tmp_path / "pkg" / "variants" / "product_v2.py").write_text("v2\n")
    check = check_scope(tmp_path, baseline, "pkg/variants", "pkg/variants/product_v2.py")
    assert check.ok, check.problems


def test_scope_rejects_edits_and_files_elsewhere(tmp_path):
    baseline = _repo(tmp_path)
    (tmp_path / "pkg" / "variants" / "product_v2.py").write_text("v2\n")
    (tmp_path / "pkg" / "variants" / "product_v1.py").write_text("edited\n")
    (tmp_path / "pkg" / "items.py").unlink()
    (tmp_path / "notes.txt").write_text("x\n")
    check = check_scope(tmp_path, baseline, "pkg/variants", "pkg/variants/product_v2.py")
    assert not check.ok
    assert check.problems == [
        "modified or deleted: pkg/items.py",
        "modified or deleted: pkg/variants/product_v1.py",
        "added outside pkg/variants/: notes.txt",
    ]


def test_scope_requires_the_candidate_file(tmp_path):
    baseline = _repo(tmp_path)
    check = check_scope(tmp_path, baseline, "pkg/variants", "pkg/variants/product_v2.py")
    assert check.problems == ["candidate is not a new file: pkg/variants/product_v2.py"]


def _accepted(names):
    return [(SimpleNamespace(url=f"https://e.com/{i}"), None, SimpleNamespace(name=n))
            for i, n in enumerate(names)]


def test_variation_catches_a_constant_name():
    check = check_variation(_accepted(["Shop header"] * 3))
    assert not check.ok and "name is the same on all 3 pages" in check.problems[0]
    assert check_variation(_accepted(["A", "B", "C"])).ok
    assert check_variation(_accepted(["Same", "Same"])).ok  # too few pages to judge


def _fixtures(tmp_path, outputs):
    owner = tmp_path / "sandbox_spider.variants.product_v1.ProductPageV1"
    for i, output in enumerate(outputs):
        (owner / str(i)).mkdir(parents=True)
        (owner / str(i) / "output.json").write_text(json.dumps(output))
    return tmp_path


def test_fields_missing_unless_declared_absent(tmp_path):
    fixtures = _fixtures(tmp_path, [{"name": "TV", "brand": "Sony"},
                                    {"name": "Phone", "brand": "Apple"}])
    books = [(None, None, {"name": "Book", "brand": None})]
    check = check_fields(books, fixtures, Product)
    assert not check.ok and "fills brand" in check.problems[0]
    check = check_fields(books, fixtures, Product, {"brand": "books show Publisher"})
    assert check.ok and "brand declared absent: books show Publisher" in check.detail
    tvs = [(None, None, {"name": "TV", "brand": "Sony"})]
    check = check_fields(tvs, fixtures, Product, {"brand": "nope"})
    assert check.problems == ["brand is declared absent but filled on a held page"]
