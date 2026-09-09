"""Strict, versioned scenario settings for tools, replays and authored content."""

from dataclasses import dataclass, field

from engine.definitions import (
    DEFAULT_PLAYER_ROSTER,
    DIFFICULTY,
    MAX_PLAYER_UNITS,
    OPERATION_MISSIONS,
    OPERATION_VARIANTS,
    OPERATION_WEATHER,
    OPERATION_ENEMY_STRENGTHS,
    OPERATION_DEFENSE_DURATIONS,
    ROLES,
)


class ScenarioError(ValueError):
    def __init__(self, field, message):
        self.field = field
        super().__init__(f"{field}: {message}")


def _object(value, allowed, location):
    if not isinstance(value, dict):
        raise ScenarioError(location, "expected an object")
    for key in value:
        if key not in allowed:
            raise ScenarioError(f"{location}.{key}", "unknown field")


def _choice(value, choices, location):
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, int, float))
        or value not in choices
    ):
        raise ScenarioError(location, f"expected one of {tuple(choices)!r}")


@dataclass(frozen=True)
class Scenario:
    seed: int = 42
    difficulty: str = "Hard"
    player_roster: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_PLAYER_ROSTER)
    )
    reserve_count: int = 0
    mission: str = "assault"
    variant: str = "auto"
    weather: str = "auto"
    enemy_strength: float = 1.0
    defense_duration: int = 300

    def __post_init__(self):
        if type(self.seed) is not int:
            raise ScenarioError("scenario.seed", "expected an integer")
        if (
            type(self.reserve_count) is not int
            or not 0 <= self.reserve_count <= MAX_PLAYER_UNITS
        ):
            raise ScenarioError(
                "scenario.reserve_count",
                f"expected an integer from 0 to {MAX_PLAYER_UNITS}",
            )
        if (
            not isinstance(self.player_roster, (list, tuple))
            or not 1 <= len(self.player_roster) <= MAX_PLAYER_UNITS
        ):
            raise ScenarioError(
                "scenario.player_roster", f"expected 1 to {MAX_PLAYER_UNITS} roles"
            )
        object.__setattr__(self, "player_roster", tuple(self.player_roster))
        for index, role in enumerate(self.player_roster):
            _choice(role, ROLES, f"scenario.player_roster[{index}]")
        _choice(self.difficulty, DIFFICULTY, "scenario.difficulty")
        for name, choices in (
            ("mission", OPERATION_MISSIONS),
            ("variant", OPERATION_VARIANTS),
            ("weather", OPERATION_WEATHER),
            ("enemy_strength", OPERATION_ENEMY_STRENGTHS),
            ("defense_duration", OPERATION_DEFENSE_DURATIONS),
        ):
            _choice(getattr(self, name), choices, f"scenario.operation.{name}")

    @property
    def operation_config(self):
        return {
            name: getattr(self, name)
            for name in (
                "mission",
                "variant",
                "weather",
                "enemy_strength",
                "defense_duration",
            )
        }

    def to_dict(self):
        return dict(
            schema_version=1,
            seed=self.seed,
            difficulty=self.difficulty,
            player_roster=list(self.player_roster),
            reserve_count=self.reserve_count,
            operation=self.operation_config,
        )

    @classmethod
    def from_dict(cls, payload):
        _object(
            payload,
            {
                "schema_version",
                "seed",
                "difficulty",
                "player_roster",
                "reserve_count",
                "operation",
            },
            "scenario",
        )
        if (
            type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1
        ):
            raise ScenarioError("scenario.schema_version", "supported version is 1")
        operation = payload.get("operation", {})
        _object(
            operation,
            {"mission", "variant", "weather", "enemy_strength", "defense_duration"},
            "scenario.operation",
        )
        settings = {
            key: value
            for key, value in payload.items()
            if key not in ("schema_version", "operation")
        }
        return cls(**settings, **operation)

    @classmethod
    def from_game(cls, game):
        """Export initial settings, not the current battle state."""
        return cls(
            seed=game.seed,
            difficulty=game.difficulty,
            player_roster=game.player_roster,
            reserve_count=game.reserve_count,
            **game.operation_config,
        )

    def create_game(self):
        from engine.simulation import RealTimeGame

        return RealTimeGame(
            seed=self.seed,
            difficulty=self.difficulty,
            player_roster=list(self.player_roster),
            reserve_count=self.reserve_count,
            operation_config=self.operation_config,
        )
