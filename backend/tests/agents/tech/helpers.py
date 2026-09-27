"""Helpers shared by the Tech tests."""


def scenario(scenarios: dict, scenario_id: str) -> dict:
    return next(s for s in scenarios["scenarios"] if s["id"] == scenario_id)
