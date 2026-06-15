"""Core data structures for the aiTTO genetic-algorithm toolbox.

The toolbox intentionally keeps the model smaller than full ITC 2019. It stores
the parts needed by the prototype solver: rooms, class domains, student course
requirements, soft distribution constraints, and selected time/room assignments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DEFAULT_DATASET_XML = Path("dataset") / "itc2019" / "aitto_dataset.xml"
DEFAULT_HARD_CONSTRAINTS = Path("dataset") / "hardconstraints.xlsx"
DEFAULT_SOFT_CONSTRAINTS = Path("dataset") / "softconstraints.xlsx"


@dataclass(frozen=True)
class UnavailablePeriod:
    """A room block where teaching is not allowed."""

    days: str
    start: int
    length: int
    weeks: str


@dataclass(frozen=True)
class Room:
    """A teaching room and its calendar unavailability."""

    id: int
    name: str
    capacity: int
    room_type: str
    unavailable: tuple[UnavailablePeriod, ...] = ()


@dataclass(frozen=True)
class RoomOption:
    """A possible room assignment for a class."""

    room_id: int
    penalty: int


@dataclass(frozen=True)
class TimeOption:
    """A possible time assignment for a class."""

    days: str
    start: int
    length: int
    weeks: str
    penalty: int


@dataclass(frozen=True)
class ClassSection:
    """A schedulable class section with room and time domains."""

    id: int
    course_id: int
    course_code: str
    name: str
    cohort: str
    limit: int
    rooms: tuple[RoomOption, ...]
    times: tuple[TimeOption, ...]


@dataclass(frozen=True)
class Course:
    """A course/module containing one or more class sections."""

    id: int
    code: str
    title: str
    class_ids: tuple[int, ...]


@dataclass(frozen=True)
class Student:
    """A synthetic student and the courses they must attend."""

    id: int
    external_id: str
    course_ids: tuple[int, ...]


@dataclass(frozen=True)
class DistributionConstraint:
    """A simplified distribution constraint, currently focused on NotOverlap."""

    constraint_type: str
    class_ids: tuple[int, ...]
    penalty: int = 0
    required: bool = False


@dataclass(frozen=True)
class ConstraintDefinition:
    """A workbook-defined rule description and its current toolbox support state."""

    category: str
    constraint_type: str
    description: str
    supported: bool
    implementation: str


@dataclass(frozen=True)
class ProblemInstance:
    """The complete parsed timetable problem used by the prototype GA."""

    name: str
    nr_days: int
    nr_weeks: int
    slots_per_day: int
    weights: dict[str, int]
    rooms: dict[int, Room]
    courses: dict[int, Course]
    classes: dict[int, ClassSection]
    students: dict[int, Student]
    distributions: tuple[DistributionConstraint, ...]
    hard_constraints: tuple[ConstraintDefinition, ...] = ()
    soft_constraints: tuple[ConstraintDefinition, ...] = ()
    source_path: Path | None = None

    @property
    def cohorts(self) -> tuple[str, ...]:
        """Return sorted cohort labels for active class sections."""

        return tuple(sorted({section.cohort for section in self.classes.values() if section.cohort}))


@dataclass(frozen=True)
class ClassAssignment:
    """The selected time and room for one class in a chromosome."""

    time_index: int
    room_id: int


@dataclass
class TimetableSolution:
    """A complete assignment plus cached evaluation metadata."""

    assignments: dict[int, ClassAssignment]
    total_cost: int | None = None
    hard_violations: int | None = None
    breakdown: dict[str, int] = field(default_factory=dict)
    generation: int = 0

    def clone(self) -> "TimetableSolution":
        """Return a shallow copy that can be safely mutated by GA operators."""

        return TimetableSolution(
            assignments=dict(self.assignments),
            total_cost=self.total_cost,
            hard_violations=self.hard_violations,
            breakdown=dict(self.breakdown),
            generation=self.generation,
        )


@dataclass(frozen=True)
class EvaluationResult:
    """Transparent scoring output for one solution."""

    hard_violations: int
    total_cost: int
    breakdown: dict[str, int]
    messages: tuple[str, ...] = ()

    @property
    def fitness(self) -> int:
        """Single sortable value: prioritize feasibility, then weighted cost."""

        return self.hard_violations * 1_000_000 + self.total_cost


@dataclass(frozen=True)
class GASettings:
    """User-facing knobs for the prototype genetic algorithm."""

    population_size: int = 50
    generations: int = 100
    mutation_rate: float = 0.15
    crossover_rate: float = 0.85
    tournament_size: int = 4
    elitism: int = 2
    seed: int | None = 1


@dataclass(frozen=True)
class GAHistoryEntry:
    """One row of GA progress for CLI and GUI visualization."""

    generation: int
    best_hard_violations: int
    best_total_cost: int
    best_fitness: int


@dataclass
class GARunResult:
    """The best solution and generation-by-generation progress."""

    best_solution: TimetableSolution
    history: list[GAHistoryEntry]


def slot_to_time(slot: int, slots_per_day: int) -> str:
    """Convert a slot index to HH:MM using the problem's slot resolution."""

    if slots_per_day <= 0:
        return "00:00"
    minutes_per_slot = (24 * 60) // slots_per_day
    minutes = slot * minutes_per_slot
    return f"{minutes // 60:02d}:{minutes % 60:02d}"

