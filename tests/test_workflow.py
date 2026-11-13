"""Workflow wiring: shell syntax of every script and the container guard of the step scripts."""
import glob, os, subprocess
import pytest
from conftest import ROOT

@pytest.mark.parametrize("script", sorted(glob.glob(f"{ROOT}/src/*.sh") + glob.glob(f"{ROOT}/containers/*.sh")))
def test_bash_syntax(script):
    subprocess.run(["bash", "-n", script], check=True)

@pytest.mark.parametrize("script", ["refs.sh", "alpine.sh", "lungo.sh", "filter.sh", "download.sh", "ena.sh", "summary.sh"])
def test_scripts_refuse_outside_the_container(script, tmp_path):
    r = subprocess.run(["bash", f"{ROOT}/src/{script}"], capture_output=True, text=True,
                       env=dict(os.environ, KV_OUT=str(tmp_path), TOOLS=str(tmp_path)))
    assert r.returncode != 0 and "refusing to run outside the container" in r.stdout + r.stderr
