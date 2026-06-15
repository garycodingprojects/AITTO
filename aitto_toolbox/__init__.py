"""Python toolbox for prototype timetable generation with a genetic algorithm."""

from .ga import run_ga
from .io_xml import load_problem, write_solution_json, write_solution_xml
from .model import GASettings, ProblemInstance, TimetableSolution

__all__ = [
    "GASettings",
    "ProblemInstance",
    "TimetableSolution",
    "load_problem",
    "run_ga",
    "write_solution_json",
    "write_solution_xml",
]

