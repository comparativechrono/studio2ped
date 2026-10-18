"""studio2ped_standalone.py must be the package in one file, and behave exactly as the package does."""
import importlib.util
import os
import subprocess
import sys

import pytest

import studio2ped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "studio2ped_standalone.py")
DATA = os.path.join(os.path.dirname(__file__), "data")
EXAMPLES = ["okafor", "price", "lynch", "cf-cousins", "features"]

pytestmark = pytest.mark.skipif(not os.path.exists(SCRIPT), reason="the standalone script is not here")


def test_the_script_is_up_to_date():
    """If this fails, run: python tools/make_standalone.py"""
    spec = importlib.util.spec_from_file_location("make_standalone", os.path.join(ROOT, "tools", "make_standalone.py"))
    maker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(maker)
    with open(SCRIPT, encoding="utf-8") as fh:
        assert fh.read() == maker.build()


@pytest.mark.parametrize("ids", ["numbers", "text"])
def test_the_script_writes_what_the_package_writes(tmp_path, ids):
    for name in EXAMPLES:
        src = os.path.join(DATA, name + ".studio.json")
        script_dir = tmp_path / ("script-" + name)
        script_dir.mkdir()
        done = subprocess.run([sys.executable, SCRIPT, src, "-d", str(script_dir), "--ids", ids],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        package = studio2ped.convert_file(src, output_dir=str(tmp_path), ids=ids)
        for path, text in package.files:
            with open(script_dir / os.path.basename(path), encoding="utf-8") as fh:
                assert fh.read() == text, name


def test_the_script_reports_its_version():
    done = subprocess.run([sys.executable, SCRIPT, "--version"], capture_output=True, text=True)
    assert done.stdout.strip() == "studio2ped " + studio2ped.__version__
