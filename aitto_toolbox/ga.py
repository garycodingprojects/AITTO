"""Reusable genetic-algorithm operators for timetable generation."""

from __future__ import annotations

import random
from collections.abc import Callable

from .evaluate import (
    attach_evaluation,
    class_has_unavailable_free_choice,
    time_overlaps_unavailability,
    times_overlap,
)
from .model import (
    ClassAssignment,
    ClassSection,
    GAHistoryEntry,
    GARunResult,
    GASettings,
    ProblemInstance,
    TimetableSolution,
)

ProgressCallback = Callable[[GAHistoryEntry, TimetableSolution], None]
_CANDIDATE_CACHE: dict[int, dict[int, list[ClassAssignment]]] = {}


def _fitness(solution: TimetableSolution) -> int:
    """Return a sortable fitness value, prioritizing hard-violation removal."""

    hard = solution.hard_violations if solution.hard_violations is not None else 1_000_000
    cost = solution.total_cost if solution.total_cost is not None else 1_000_000
    return hard * 1_000_000 + cost


def _same_cohort(left: ClassSection, right: ClassSection) -> bool:
    """Return true when two class sections represent the same student cohort."""

    return bool(left.cohort and left.cohort == right.cohort)


def _valid_domain_candidates(problem: ProblemInstance, class_id: int) -> list[ClassAssignment]:
    """
    Return candidate genes that satisfy per-class hard domain rules.

    The paper recommends starting from feasible or near-feasible individuals so
    the GA spends most of its effort optimizing rather than repeatedly escaping
    illegal regions. These candidates therefore exclude rooms that are too small
    and room/time pairs that hit room unavailability blocks.
    """

    section = problem.classes[class_id]
    candidates: list[ClassAssignment] = []

    for time_index, time in enumerate(section.times):
        for room_option in section.rooms:
            room = problem.rooms.get(room_option.room_id)
            if room is None or room.capacity < section.limit:
                continue
            if any(time_overlaps_unavailability(time, block) for block in room.unavailable):
                continue
            candidates.append(ClassAssignment(time_index=time_index, room_id=room_option.room_id))

    return candidates


def _raw_domain_candidates(problem: ProblemInstance, class_id: int) -> list[ClassAssignment]:
    """
    Return every XML-listed time/room pair for a class.

    This fallback keeps unsatisfiable or incomplete input data schedulable enough
    to be diagnosed by the evaluator instead of silently dropping the class.
    """

    section = problem.classes[class_id]
    return [
        ClassAssignment(time_index=time_index, room_id=room.room_id)
        for time_index, _time in enumerate(section.times)
        for room in section.rooms
    ]


def _base_candidate_cost(problem: ProblemInstance, class_id: int, candidate: ClassAssignment) -> int:
    """Return the static XML time/room preference cost for one candidate."""

    section = problem.classes[class_id]
    time = _selected_time(problem, class_id, candidate)
    if time is None:
        return 1_000_000

    room_penalty = 0
    for room_option in section.rooms:
        if room_option.room_id == candidate.room_id:
            room_penalty = room_option.penalty
            break

    return (
        time.penalty * problem.weights.get("time", 1)
        + room_penalty * problem.weights.get("room", 1)
    )


def _candidate_pool(problem: ProblemInstance, class_id: int) -> list[ClassAssignment]:
    """Return feasible domain candidates, falling back to raw XML choices."""

    problem_cache = _CANDIDATE_CACHE.setdefault(id(problem), {})
    if class_id not in problem_cache:
        candidates = _valid_domain_candidates(problem, class_id) or _raw_domain_candidates(problem, class_id)
        candidates.sort(key=lambda candidate: _base_candidate_cost(problem, class_id, candidate))
        problem_cache[class_id] = candidates
    return problem_cache[class_id]


def _candidate_subset(
    problem: ProblemInstance,
    class_id: int,
    rng: random.Random,
    max_candidates: int,
) -> list[ClassAssignment]:
    """
    Return a bounded candidate list for fast repeated local repair.

    Large classes can have hundreds of time/room pairs. We always keep the low
    static-cost prefix and add random alternatives so the GA remains diverse
    without rescoring every possible pair for every child chromosome.
    """

    candidates = _candidate_pool(problem, class_id)
    if len(candidates) <= max_candidates:
        return candidates

    prefix_size = max_candidates // 2
    prefix = candidates[:prefix_size]
    random_size = max_candidates - prefix_size
    return prefix + rng.sample(candidates[prefix_size:], random_size)


def _selected_time(problem: ProblemInstance, class_id: int, assignment: ClassAssignment):
    """Return the selected time option for a gene, or None when it is invalid."""

    section = problem.classes[class_id]
    if 0 <= assignment.time_index < len(section.times):
        return section.times[assignment.time_index]
    return None


def _domain_violation_count(problem: ProblemInstance, class_id: int, assignment: ClassAssignment | None) -> int:
    """Count hard per-class domain violations for one proposed assignment."""

    section = problem.classes[class_id]
    if assignment is None:
        return 1

    time = _selected_time(problem, class_id, assignment)
    if time is None:
        return 1

    allowed_room_ids = {room.room_id for room in section.rooms}
    if assignment.room_id not in allowed_room_ids:
        return 1

    room = problem.rooms.get(assignment.room_id)
    if room is None:
        return 1

    violations = 0
    if room.capacity < section.limit:
        violations += 1
    if class_has_unavailable_free_choice(problem, section) and any(
        time_overlaps_unavailability(time, block) for block in room.unavailable
    ):
        violations += 1
    return violations


def _distribution_conflict_score(
    problem: ProblemInstance,
    class_id: int,
    candidate_time,
    assignments: dict[int, ClassAssignment],
) -> tuple[int, int]:
    """
    Return required and soft NotOverlap conflicts caused by one candidate.

    Required distributions are hard constraints. Optional distributions are kept
    as soft costs, but using them here gives the repair step useful pressure to
    avoid same-module overlaps when a non-clashing alternative exists.
    """

    hard_conflicts = 0
    soft_cost = 0
    distribution_weight = problem.weights.get("distribution", 1)

    for distribution in problem.distributions:
        if distribution.constraint_type != "NotOverlap" or class_id not in distribution.class_ids:
            continue

        for other_id in distribution.class_ids:
            if other_id == class_id or other_id not in assignments:
                continue
            other_time = _selected_time(problem, other_id, assignments[other_id])
            if other_time is None or not times_overlap(candidate_time, other_time):
                continue

            if distribution.required:
                hard_conflicts += 1
            else:
                soft_cost += distribution.penalty * distribution_weight

    return hard_conflicts, soft_cost


def _candidate_score(
    problem: ProblemInstance,
    class_id: int,
    candidate: ClassAssignment,
    assignments: dict[int, ClassAssignment],
) -> tuple[int, int]:
    """
    Score a candidate against already assigned classes.

    The first tuple element is the hard-conflict count and always dominates. The
    second element is soft cost, so ties prefer lower XML penalties and fewer
    optional NotOverlap clashes.
    """

    section = problem.classes[class_id]
    time = _selected_time(problem, class_id, candidate)
    if time is None:
        return (1_000_000, 1_000_000)

    hard_conflicts = _domain_violation_count(problem, class_id, candidate)
    soft_cost = time.penalty * problem.weights.get("time", 1)

    for room_option in section.rooms:
        if room_option.room_id == candidate.room_id:
            soft_cost += room_option.penalty * problem.weights.get("room", 1)
            break

    for other_id, other_assignment in assignments.items():
        if other_id == class_id:
            continue

        other_time = _selected_time(problem, other_id, other_assignment)
        if other_time is None or not times_overlap(time, other_time):
            continue

        other_section = problem.classes[other_id]
        if candidate.room_id == other_assignment.room_id:
            hard_conflicts += 1
        if _same_cohort(section, other_section):
            hard_conflicts += 1

    distribution_hard, distribution_soft = _distribution_conflict_score(problem, class_id, time, assignments)
    hard_conflicts += distribution_hard
    soft_cost += distribution_soft
    return hard_conflicts, soft_cost


def _best_candidate(
    problem: ProblemInstance,
    class_id: int,
    assignments: dict[int, ClassAssignment],
    rng: random.Random,
    sample_best: int = 3,
    max_candidates: int = 16,
) -> ClassAssignment | None:
    """
    Pick a low-conflict candidate while preserving some population diversity.

    The top few candidates are sampled randomly instead of always choosing the
    single best one. This mirrors the paper's advice to avoid identical initial
    chromosomes while still keeping hard constraints under control.
    """

    scored = [
        (_candidate_score(problem, class_id, candidate, assignments), rng.random(), candidate)
        for candidate in _candidate_subset(problem, class_id, rng, max_candidates)
    ]
    if not scored:
        return None

    scored.sort(key=lambda item: (item[0][0], item[0][1], item[1]))
    top = scored[: max(sample_best, 1)]
    return rng.choice(top)[2]


def _hard_conflict_counts(problem: ProblemInstance, assignments: dict[int, ClassAssignment]) -> dict[int, int]:
    """Return a per-class count of hard conflicts in the current chromosome."""

    conflicts: dict[int, int] = {}
    selected_times: dict[int, object] = {}

    for class_id in problem.classes:
        assignment = assignments.get(class_id)
        domain_conflicts = _domain_violation_count(problem, class_id, assignment)
        if domain_conflicts:
            conflicts[class_id] = conflicts.get(class_id, 0) + domain_conflicts
            continue

        if assignment is not None:
            time = _selected_time(problem, class_id, assignment)
            if time is not None:
                selected_times[class_id] = time

    assigned_ids = sorted(selected_times)
    for index, left_id in enumerate(assigned_ids):
        left = problem.classes[left_id]
        left_assignment = assignments[left_id]
        left_time = selected_times[left_id]

        for right_id in assigned_ids[index + 1 :]:
            right = problem.classes[right_id]
            right_assignment = assignments[right_id]
            right_time = selected_times[right_id]
            if not times_overlap(left_time, right_time):
                continue

            if left_assignment.room_id == right_assignment.room_id:
                conflicts[left_id] = conflicts.get(left_id, 0) + 1
                conflicts[right_id] = conflicts.get(right_id, 0) + 1
            if _same_cohort(left, right):
                conflicts[left_id] = conflicts.get(left_id, 0) + 1
                conflicts[right_id] = conflicts.get(right_id, 0) + 1

    for distribution in problem.distributions:
        if distribution.constraint_type != "NotOverlap" or not distribution.required:
            continue

        class_ids = [class_id for class_id in distribution.class_ids if class_id in selected_times]
        for index, left_id in enumerate(class_ids):
            for right_id in class_ids[index + 1 :]:
                if times_overlap(selected_times[left_id], selected_times[right_id]):
                    conflicts[left_id] = conflicts.get(left_id, 0) + 1
                    conflicts[right_id] = conflicts.get(right_id, 0) + 1

    return conflicts


def random_solution(problem: ProblemInstance, rng: random.Random) -> TimetableSolution:
    """Create one chromosome using a conflict-aware constructive heuristic."""

    assignments: dict[int, ClassAssignment] = {}
    class_ids = [
        class_id
        for class_id, section in problem.classes.items()
        if section.times and section.rooms
    ]
    class_ids.sort(key=lambda class_id: (len(_candidate_pool(problem, class_id)), rng.random()))

    for class_id in class_ids:
        candidate = _best_candidate(problem, class_id, assignments, rng)
        if candidate is None:
            continue
        assignments[class_id] = candidate
    return TimetableSolution(assignments=assignments)


def repair_solution(problem: ProblemInstance, solution: TimetableSolution, rng: random.Random) -> TimetableSolution:
    """Repair missing, invalid, and clashing genes with local rescheduling."""

    repaired = solution.clone()
    for class_id, section in problem.classes.items():
        if not section.times or not section.rooms:
            repaired.assignments.pop(class_id, None)
            continue

        assignment = repaired.assignments.get(class_id)
        if _domain_violation_count(problem, class_id, assignment):
            others = {other_id: other for other_id, other in repaired.assignments.items() if other_id != class_id}
            candidate = _best_candidate(problem, class_id, others, rng)
            if candidate is not None:
                repaired.assignments[class_id] = candidate

    for _pass_index in range(3):
        conflicts = _hard_conflict_counts(problem, repaired.assignments)
        if not conflicts:
            break

        conflicted_ids = sorted(conflicts, key=lambda class_id: (-conflicts[class_id], rng.random()))
        improved = False
        for class_id in conflicted_ids:
            if class_id not in repaired.assignments:
                continue

            others = {other_id: other for other_id, other in repaired.assignments.items() if other_id != class_id}
            current = repaired.assignments[class_id]
            current_score = _candidate_score(problem, class_id, current, others)
            candidate = _best_candidate(problem, class_id, others, rng, sample_best=1)
            if candidate is None:
                continue

            candidate_score = _candidate_score(problem, class_id, candidate, others)
            if candidate_score < current_score:
                repaired.assignments[class_id] = candidate
                improved = True

        if not improved:
            break

    repaired.hard_violations = None
    repaired.total_cost = None
    repaired.breakdown = {}
    return repaired


def evaluate_population(problem: ProblemInstance, population: list[TimetableSolution]) -> None:
    """Attach evaluation scores to every solution in place."""

    for solution in population:
        attach_evaluation(problem, solution)


def tournament_select(
    population: list[TimetableSolution],
    rng: random.Random,
    tournament_size: int,
) -> TimetableSolution:
    """Select one parent using tournament selection."""

    size = min(max(tournament_size, 1), len(population))
    contenders = rng.sample(population, size)
    return min(contenders, key=_fitness)


def crossover(
    left: TimetableSolution,
    right: TimetableSolution,
    rng: random.Random,
    crossover_rate: float,
) -> TimetableSolution:
    """Uniformly mix class genes from two parents."""

    if rng.random() > crossover_rate:
        return left.clone()

    class_ids = sorted(set(left.assignments) | set(right.assignments))
    child_assignments: dict[int, ClassAssignment] = {}
    for class_id in class_ids:
        if class_id in left.assignments and class_id in right.assignments:
            child_assignments[class_id] = left.assignments[class_id] if rng.random() < 0.5 else right.assignments[class_id]
        elif class_id in left.assignments:
            child_assignments[class_id] = left.assignments[class_id]
        else:
            child_assignments[class_id] = right.assignments[class_id]
    return TimetableSolution(assignments=child_assignments)


def mutate(
    problem: ProblemInstance,
    solution: TimetableSolution,
    rng: random.Random,
    mutation_rate: float,
) -> TimetableSolution:
    """Randomly change selected time and/or room genes within valid domains."""

    mutated = solution.clone()
    for class_id, section in problem.classes.items():
        if class_id not in mutated.assignments or not section.times or not section.rooms:
            continue
        if rng.random() >= mutation_rate:
            continue

        current = mutated.assignments[class_id]
        time_index = current.time_index
        room_id = current.room_id
        if rng.random() < 0.7:
            time_index = rng.randrange(len(section.times))
        if rng.random() < 0.5:
            room_id = rng.choice(section.rooms).room_id
        mutated.assignments[class_id] = ClassAssignment(time_index=time_index, room_id=room_id)
    return mutated


def run_ga(
    problem: ProblemInstance,
    settings: GASettings | None = None,
    progress_callback: ProgressCallback | None = None,
) -> GARunResult:
    """Run the prototype GA and return the best timetable found."""

    settings = settings or GASettings()
    rng = random.Random(settings.seed)
    population_size = max(settings.population_size, 2)
    elitism = min(max(settings.elitism, 1), population_size)

    population = [random_solution(problem, rng) for _ in range(population_size)]
    population = [repair_solution(problem, solution, rng) for solution in population]
    evaluate_population(problem, population)

    history: list[GAHistoryEntry] = []
    best = min(population, key=_fitness).clone()
    best.generation = 0

    def record(generation: int, best_solution: TimetableSolution) -> None:
        entry = GAHistoryEntry(
            generation=generation,
            best_hard_violations=best_solution.hard_violations or 0,
            best_total_cost=best_solution.total_cost or 0,
            best_fitness=_fitness(best_solution),
        )
        history.append(entry)
        if progress_callback is not None:
            progress_callback(entry, best_solution.clone())

    record(0, best)

    for generation in range(1, max(settings.generations, 0) + 1):
        population.sort(key=_fitness)
        next_population = [solution.clone() for solution in population[:elitism]]

        while len(next_population) < population_size:
            parent_a = tournament_select(population, rng, settings.tournament_size)
            parent_b = tournament_select(population, rng, settings.tournament_size)
            child = crossover(parent_a, parent_b, rng, settings.crossover_rate)
            child = mutate(problem, child, rng, settings.mutation_rate)
            child = repair_solution(problem, child, rng)
            next_population.append(child)

        population = next_population
        evaluate_population(problem, population)
        generation_best = min(population, key=_fitness).clone()
        generation_best.generation = generation
        if _fitness(generation_best) < _fitness(best):
            best = generation_best
        record(generation, best)

    return GARunResult(best_solution=best, history=history)

