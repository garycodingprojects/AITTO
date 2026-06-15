"""Prototype scoring for aiTTO timetable solutions.

This evaluator is intentionally explicit instead of fully official ITC 2019.
It gives the GA useful guidance while keeping every penalty easy to explain in
the GUI and future LLM tool calls.
"""

from __future__ import annotations

from collections import defaultdict

from .model import (
    ClassAssignment,
    ClassSection,
    EvaluationResult,
    ProblemInstance,
    TimeOption,
    TimetableSolution,
    UnavailablePeriod,
)

_BITMASK_CACHE: dict[str, int] = {}
_UNAVAILABLE_FREE_CACHE: dict[tuple[int, int], bool] = {}


def _bitmask(bits: str) -> int:
    """Convert a day/week bitstring to an integer mask for fast overlap checks."""

    if bits not in _BITMASK_CACHE:
        _BITMASK_CACHE[bits] = int(bits or "0", 2)
    return _BITMASK_CACHE[bits]


def bitstrings_overlap(left: str, right: str) -> bool:
    """Return true if two day/week bitstrings share at least one active bit."""

    return bool(_bitmask(left) & _bitmask(right))


def intervals_overlap(start_a: int, length_a: int, start_b: int, length_b: int) -> bool:
    """Return true if two half-open slot intervals overlap."""

    end_a = start_a + length_a
    end_b = start_b + length_b
    return start_a < end_b and start_b < end_a


def times_overlap(left: TimeOption, right: TimeOption) -> bool:
    """Return true when two time options overlap in weeks, days, and slots."""

    return (
        bitstrings_overlap(left.weeks, right.weeks)
        and bitstrings_overlap(left.days, right.days)
        and intervals_overlap(left.start, left.length, right.start, right.length)
    )


def time_overlaps_unavailability(time: TimeOption, block: UnavailablePeriod) -> bool:
    """Return true when a selected class time hits a room unavailable block."""

    return (
        bitstrings_overlap(time.weeks, block.weeks)
        and bitstrings_overlap(time.days, block.days)
        and intervals_overlap(time.start, time.length, block.start, block.length)
    )


def class_has_unavailable_free_choice(problem: ProblemInstance, section: ClassSection) -> bool:
    """
    Return true when at least one allowed time/room pair avoids room unavailability.

    The generated dataset uses room-unavailability blocks for non-teaching days.
    Because a compact ITC-style weekly time option applies the same week bitstring
    to every active day, many classes have no representation that can skip only a
    Monday holiday while still meeting on the other days that week. In that case,
    room unavailability is not repairable by the GA and should not dominate every
    timetable as a hard violation.
    """

    cache_key = (id(problem), section.id)
    if cache_key in _UNAVAILABLE_FREE_CACHE:
        return _UNAVAILABLE_FREE_CACHE[cache_key]

    for time in section.times:
        for room_option in section.rooms:
            room = problem.rooms.get(room_option.room_id)
            if room is None:
                continue
            if not any(time_overlaps_unavailability(time, block) for block in room.unavailable):
                _UNAVAILABLE_FREE_CACHE[cache_key] = True
                return True

    _UNAVAILABLE_FREE_CACHE[cache_key] = False
    return False


def _selected_time(section: ClassSection, assignment: ClassAssignment) -> TimeOption | None:
    """Return a selected time option, or None if the chromosome is invalid."""

    if 0 <= assignment.time_index < len(section.times):
        return section.times[assignment.time_index]
    return None


def _same_students_or_cohort(left: ClassSection, right: ClassSection) -> bool:
    """
    Approximate student conflicts for the prototype dataset.

    The generated XML names classes by cohort and creates synthetic students per
    cohort. Until full student sectioning is implemented, same-cohort overlaps
    are the most useful proxy for shared student attendance.
    """

    return bool(left.cohort and left.cohort == right.cohort)


def _student_cohort(external_id: str) -> str:
    """Extract the cohort prefix from generated ids like FS123456-1A-01."""

    parts = external_id.rsplit("-", 1)
    return parts[0] if len(parts) == 2 else external_id


def evaluate_solution(problem: ProblemInstance, solution: TimetableSolution) -> EvaluationResult:
    """Score a solution using hard violations plus weighted soft costs."""

    hard_violations = 0
    breakdown: dict[str, int] = defaultdict(int)
    messages: list[str] = []

    selected_times: dict[int, TimeOption] = {}
    selected_rooms: dict[int, int] = {}
    selected_classes_by_cohort_course: dict[tuple[str, int], list[int]] = defaultdict(list)
    selected_course_ids_by_cohort: dict[str, set[int]] = defaultdict(set)
    selected_meetings_by_cohort_day: dict[tuple[str, int], int] = defaultdict(int)

    for class_id, section in problem.classes.items():
        assignment = solution.assignments.get(class_id)
        if assignment is None:
            hard_violations += 1
            breakdown["missing_assignment"] += 1
            messages.append(f"Class {class_id} has no assignment.")
            continue

        time = _selected_time(section, assignment)
        if time is None:
            hard_violations += 1
            breakdown["invalid_time"] += 1
            messages.append(f"Class {class_id} has invalid time index {assignment.time_index}.")
            continue

        allowed_room_ids = {room.room_id for room in section.rooms}
        if assignment.room_id not in allowed_room_ids:
            hard_violations += 1
            breakdown["invalid_room"] += 1
            messages.append(f"Class {class_id} uses unavailable room id {assignment.room_id}.")
            continue

        selected_times[class_id] = time
        selected_rooms[class_id] = assignment.room_id
        selected_classes_by_cohort_course[(section.cohort, section.course_id)].append(class_id)
        selected_course_ids_by_cohort[section.cohort].add(section.course_id)
        for day_index, active in enumerate(time.days[: problem.nr_days]):
            if active == "1":
                selected_meetings_by_cohort_day[(section.cohort, day_index)] += 1

        room_option = next(room for room in section.rooms if room.room_id == assignment.room_id)
        breakdown["time_penalty"] += time.penalty * problem.weights.get("time", 1)
        breakdown["room_penalty"] += room_option.penalty * problem.weights.get("room", 1)

        room = problem.rooms.get(assignment.room_id)
        if room is None:
            hard_violations += 1
            breakdown["unknown_room"] += 1
            continue

        if room.capacity < section.limit:
            hard_violations += 1
            breakdown["room_capacity"] += section.limit - room.capacity

        for unavailable in room.unavailable:
            if not time_overlaps_unavailability(time, unavailable):
                continue
            if class_has_unavailable_free_choice(problem, section):
                hard_violations += 1
                breakdown["room_unavailable"] += 1
            else:
                breakdown["unavoidable_room_unavailable"] += 1
            break

    assigned_class_ids = sorted(selected_times)
    for index, left_id in enumerate(assigned_class_ids):
        left = problem.classes[left_id]
        left_time = selected_times[left_id]
        left_room = selected_rooms[left_id]

        for right_id in assigned_class_ids[index + 1 :]:
            right = problem.classes[right_id]
            right_time = selected_times[right_id]
            if not times_overlap(left_time, right_time):
                continue

            if left_room == selected_rooms[right_id]:
                hard_violations += 1
                breakdown["room_overlap"] += 1

            if _same_students_or_cohort(left, right):
                hard_violations += 1
                breakdown["cohort_overlap"] += 1

    for student in problem.students.values():
        cohort = _student_cohort(student.external_id)
        required_courses = set(student.course_ids)
        for course_id in required_courses:
            allocated_classes = selected_classes_by_cohort_course.get((cohort, course_id), [])
            if not allocated_classes:
                hard_violations += 1
                breakdown["missing_allocation"] += 1
            elif len(allocated_classes) > 1:
                hard_violations += len(allocated_classes) - 1
                breakdown["extra_allocation"] += len(allocated_classes) - 1

        for course_id in selected_course_ids_by_cohort.get(cohort, set()):
            if course_id not in required_courses:
                hard_violations += 1
                breakdown["incorrect_allocation"] += 1

    for distribution in problem.distributions:
        if distribution.constraint_type != "NotOverlap":
            continue
        class_ids = [class_id for class_id in distribution.class_ids if class_id in selected_times]
        for index, left_id in enumerate(class_ids):
            for right_id in class_ids[index + 1 :]:
                if not times_overlap(selected_times[left_id], selected_times[right_id]):
                    continue
                if distribution.required:
                    hard_violations += 1
                    breakdown["required_distribution"] += 1
                else:
                    weighted = distribution.penalty * problem.weights.get("distribution", 1)
                    breakdown["distribution_penalty"] += weighted

    for (_cohort, _day_index), meeting_count in selected_meetings_by_cohort_day.items():
        if meeting_count == 1:
            breakdown["single_course_day_penalty"] += problem.weights.get("student", 1)

    total_cost = sum(
        value
        for key, value in breakdown.items()
        if key.endswith("_penalty") or key in {"room_capacity"}
    )
    return EvaluationResult(
        hard_violations=hard_violations,
        total_cost=total_cost,
        breakdown=dict(sorted(breakdown.items())),
        messages=tuple(messages[:25]),
    )


def attach_evaluation(problem: ProblemInstance, solution: TimetableSolution) -> TimetableSolution:
    """Evaluate a solution and cache the result fields on the solution object."""

    result = evaluate_solution(problem, solution)
    solution.hard_violations = result.hard_violations
    solution.total_cost = result.total_cost
    solution.breakdown = result.breakdown
    return solution

