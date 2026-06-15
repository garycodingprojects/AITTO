"""PowerShell-friendly entry point for the aiTTO Python GA toolbox."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aitto_toolbox.ga import run_ga
from aitto_toolbox.io_xml import load_problem, write_solution_json, write_solution_xml
from aitto_toolbox.model import DEFAULT_DATASET_XML, GASettings


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for CLI or GUI toolbox runs."""

    parser = argparse.ArgumentParser(description="Run the aiTTO Python GA timetable toolbox.")
    parser.add_argument("--input", type=Path, default=DEFAULT_DATASET_XML, help="Input aiTTO XML dataset.")
    parser.add_argument("--population", type=int, default=50, help="GA population size.")
    parser.add_argument("--generations", type=int, default=100, help="Number of GA generations.")
    parser.add_argument("--mutation-rate", type=float, default=0.15, help="Per-class mutation probability.")
    parser.add_argument("--crossover-rate", type=float, default=0.85, help="Uniform crossover probability.")
    parser.add_argument("--tournament-size", type=int, default=4, help="Tournament selection size.")
    parser.add_argument("--elitism", type=int, default=2, help="Number of elite solutions to preserve.")
    parser.add_argument("--seed", type=int, default=1, help="Random seed for reproducible runs.")
    parser.add_argument("--json-output", type=Path, help="Optional JSON solution output path.")
    parser.add_argument("--xml-output", type=Path, help="Optional XML solution output path.")
    parser.add_argument("--gui", action="store_true", help="Open the Tkinter toolbox viewer.")
    return parser.parse_args()


def main() -> None:
    """Run either the CLI solver or the Tkinter visualizer."""

    args = parse_args()
    if args.gui:
        from aitto_toolbox.visualize_tk import TimetableToolboxApp

        TimetableToolboxApp(args.input).run()
        return

    problem = load_problem(args.input)
    settings = GASettings(
        population_size=args.population,
        generations=args.generations,
        mutation_rate=args.mutation_rate,
        crossover_rate=args.crossover_rate,
        tournament_size=args.tournament_size,
        elitism=args.elitism,
        seed=args.seed,
    )
    result = run_ga(problem, settings)
    best = result.best_solution

    print(f"Problem: {problem.name}")
    print(f"Classes: {len(problem.classes)}")
    print(f"Rooms: {len(problem.rooms)}")
    print(f"Students: {len(problem.students)}")
    print(f"Generations: {settings.generations}")
    print(f"Best hard violations: {best.hard_violations}")
    print(f"Best total cost: {best.total_cost}")
    print("Breakdown:")
    for key, value in sorted(best.breakdown.items()):
        print(f"  {key}: {value}")

    if args.json_output:
        write_solution_json(problem, best, args.json_output)
        print(f"Wrote JSON solution: {args.json_output}")
    if args.xml_output:
        write_solution_xml(problem, best, args.xml_output)
        print(f"Wrote XML solution: {args.xml_output}")


if __name__ == "__main__":
    main()

