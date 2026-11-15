"""The primary synthetic demo borrower. Its profile comes from the synthetic dataset (app/synthetic.py), so the
declared liabilities always agree with the generated loan documents. Every person, business and figure is invented."""

from copy import deepcopy
from typing import Any

from .synthetic import PRIMARY_SCENARIO, SCENARIOS, build_dataset

DEMO_BORROWER_ID = "demo-synthetic-001"
DEMO_PROFILE: dict[str, Any] = build_dataset(SCENARIOS[PRIMARY_SCENARIO])["profile"]


def demo_profile() -> dict[str, Any]:
    return deepcopy(DEMO_PROFILE)
