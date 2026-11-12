"""Shared fixtures: repo paths and module loading for KNOCKIN-VAL unit tests."""
import importlib.util, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load(name):
    spec = importlib.util.spec_from_file_location(name, f"{ROOT}/src/{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m
