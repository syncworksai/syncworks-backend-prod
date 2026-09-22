"""Safe, team-specific badge rules.

Rules are league-local and are not silently rewritten after a season. Existing
Game Books are never altered; coach changes re-evaluate displayed achievements.
"""
from copy import deepcopy
from rest_framework.exceptions import ValidationError

DEFAULT_BADGE_RULES = {
    "POWER": {"enabled": True, "thresholds": [3, 8, 16, 30]},
    "CONTACT": {"enabled": True, "thresholds": [[0.450, 10], [0.550, 20], [0.650, 35], [0.750, 60]]},
    "SPEED": {"enabled": True, "thresholds": [3, 7, 12, 20]},
    "CLUTCH": {"enabled": True, "thresholds": [1, 3, 5, 8]},
}


def get_team_badge_rules(team):
    saved = team.badge_rules if isinstance(team.badge_rules, dict) else {}
    result = deepcopy(DEFAULT_BADGE_RULES)
    for key in result:
        entry = saved.get(key)
        if isinstance(entry, dict) and "enabled" in entry and "thresholds" in entry:
            result[key] = deepcopy(entry)
    return result


def validate_badge_rules(proposed):
    if not isinstance(proposed, dict) or set(proposed) != set(DEFAULT_BADGE_RULES):
        raise ValidationError({"rules": "Provide exactly Power, Contact, Speed and Clutch rules."})
    normalized = {}
    for key in DEFAULT_BADGE_RULES:
        entry = proposed[key]
        if not isinstance(entry, dict) or set(entry) != {"enabled", "thresholds"} or not isinstance(entry["enabled"], bool):
            raise ValidationError({"rules": f"{key} needs an enabled toggle and four ordered thresholds."})
        values = entry["thresholds"]
        if not isinstance(values, list) or len(values) != 4:
            raise ValidationError({"rules": f"{key} must have four thresholds: Bronze, Silver, Gold, Diamond."})
        if key == "CONTACT":
            out = []
            for pair in values:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValidationError({"rules": "Contact goals require [batting_average, minimum_at_bats]."})
                avg, ab = pair
                if (isinstance(avg, bool) or not isinstance(avg, (int, float))
                        or not 0.050 <= avg <= 1.0 or round(avg, 3) != avg
                        or isinstance(ab, bool) or not isinstance(ab, int) or not 1 <= ab <= 500):
                    raise ValidationError({"rules": "Contact AVG must be .050–1.000 and at-bats 1–500."})
                out.append([float(avg), ab])
            if any(out[i][0] <= out[i-1][0] or out[i][1] <= out[i-1][1] for i in range(1, 4)):
                raise ValidationError({"rules": "Each higher Contact tier must require a higher AVG and more at-bats."})
        else:
            if (any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 999 for v in values)
                    or any(values[i] <= values[i-1] for i in range(1, 4))):
                raise ValidationError({"rules": f"{key} thresholds must be strictly increasing whole numbers, 1–999."})
            out = list(values)
        normalized[key] = {"enabled": entry["enabled"], "thresholds": out}
    return normalized
