"""sample_meta.py: concurrent writers to one sample JSON inside an analysis must not lose records."""
import json, os, subprocess, sys
from conftest import ROOT

def test_concurrent_writes(tmp_path):
    out = tmp_path / "results" / "run1"; (out / "meta").mkdir(parents=True)
    env = dict(os.environ, KV_ROOT=str(tmp_path), KV_OUT=str(out))
    ps = [subprocess.Popen([sys.executable, f"{ROOT}/src/sample_meta.py", "S", f"step{i}", f"n={i}"], env=env) for i in range(20)]
    assert all(p.wait() == 0 for p in ps)
    d = json.load(open(out / "meta/S.json"))
    assert sorted(d["steps"]) == sorted(f"step{i}" for i in range(20))
    assert all(d["steps"][f"step{i}"]["n"] == i for i in range(20))
