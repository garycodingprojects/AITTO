"""
Convert the local Excel dataset into an ITC 2019-style problem XML file.

The source workbooks in ``dataset/`` are planning spreadsheets, not a complete
ITC 2019 instance. In particular, they contain cohort/class rows rather than
individual student records, and they do not define exact weekly teaching slots.
This converter therefore creates a standards-shaped ITC 2019 instance using
documented assumptions:

* Each row in ``students.xlsx`` is treated as a cohort.
* Each cohort is expanded into synthetic individual students.
* Each module becomes one ITC course with one config and one subpart.
* Each module/cohort pair becomes one class section.
* Possible times are generated from regular weekday teaching slots.
* Holidays and non-teaching days from the academic calendar are emitted as
  room unavailability entries.

The generated XML is intended as a practical starting instance for solver
development. When real enrollment counts, teacher availability, or exact
meeting patterns become available, replace the assumptions in this script with
those source fields.
"""

from __future__ import annotations

import argparse
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook
from xml.dom import minidom


REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "dataset"
DEFAULT_OUTPUT = DATASET_DIR / "itc2019" / "aitto_dataset.xml"

# ITC 2019 uses 5-minute slots. 09:00 is slot 108.
SLOT_MINUTES = 5
DEFAULT_DAY_COUNT = 7
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES

# Keep the generated instance compact while still giving the solver choices.
DEFAULT_COHORT_SIZE = 30
DEFAULT_SESSION_HOURS = 2
DEFAULT_TEACHING_STARTS = ["09:00", "11:00", "14:00", "16:00"]

# Weekday indexes follow ITC binary strings: Monday, Tuesday, ..., Sunday.
WEEKDAY_INDEX = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}

# Common day patterns used to approximate one, two, or three meetings per week.
DAY_PATTERNS = {
    1: ["1000000", "0100000", "0010000", "0001000", "0000100"],
    2: ["1010000", "0101000", "0010100", "1001000", "0100100"],
    3: ["1010100", "0101010", "1110000"],
}


@dataclass(frozen=True)
class RoomRow:
    """Source room row plus the numeric id required by ITC XML."""

    id: int
    name: str
    capacity: int
    room_type: str


@dataclass(frozen=True)
class ModuleRow:
    """A module/course row from ``modules_set_A.xlsx``."""

    id: int
    code: str
    title: str
    contact_hours: int
    room_type: str
    semesters: tuple[int, ...]


@dataclass(frozen=True)
class CohortRow:
    """A programme/class cohort from ``students.xlsx``."""

    id: int
    course: str
    class_name: str


def read_first_sheet(path: Path) -> list[tuple]:
    """Return all rows from the first worksheet, skipping temporary Excel files."""

    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    return list(ws.iter_rows(values_only=True))


def normalize_header(value: object) -> str:
    """Normalize a spreadsheet header for robust column lookup."""

    return str(value or "").strip().lower()


def safe_int(value: object, default: int = 0) -> int:
    """Convert a spreadsheet value to int while tolerating blank cells."""

    if value is None or value == "":
        return default
    return int(float(value))


def load_rooms(path: Path) -> list[RoomRow]:
    """Load classroom metadata and assign sequential numeric ITC ids."""

    rows = read_first_sheet(path)
    headers = [normalize_header(v) for v in rows[0]]
    idx_name = headers.index("classroom")
    idx_capacity = headers.index("capacity")
    idx_type = headers.index("type")

    rooms: list[RoomRow] = []
    for room_id, row in enumerate(rows[1:], start=1):
        if not row[idx_name]:
            continue
        rooms.append(
            RoomRow(
                id=len(rooms) + 1,
                name=str(row[idx_name]).strip(),
                capacity=safe_int(row[idx_capacity], DEFAULT_COHORT_SIZE),
                room_type=str(row[idx_type] or "Classroom").strip(),
            )
        )
    return rooms


def load_modules(path: Path) -> list[ModuleRow]:
    """Load module rows, ignoring category headings in the workbook."""

    rows = read_first_sheet(path)
    header_row_index = next(
        i for i, row in enumerate(rows) if "Module Code" in [str(v) for v in row if v]
    )
    headers = [normalize_header(v) for v in rows[header_row_index]]

    idx_code = headers.index("module code")
    idx_title = headers.index("module title")
    idx_hours = headers.index("contact hours")
    idx_room_type = headers.index("room type")
    semester_columns = {
        int(re.search(r"\d+", header).group(0)): i
        for i, header in enumerate(headers)
        if header.startswith("sem ") and re.search(r"\d+", header)
    }

    modules: list[ModuleRow] = []
    for row in rows[header_row_index + 1 :]:
        code = row[idx_code]
        title = row[idx_title]
        if not code or not title or not str(code).strip()[0].isalnum():
            continue

        semesters = tuple(
            sem for sem, col in sorted(semester_columns.items()) if str(row[col] or "").strip().upper() == "P"
        )
        if not semesters:
            continue

        modules.append(
            ModuleRow(
                id=len(modules) + 1,
                code=str(code).strip(),
                title=str(title).strip(),
                contact_hours=safe_int(row[idx_hours], DEFAULT_SESSION_HOURS),
                room_type=str(row[idx_room_type] or "Classroom").strip(),
                semesters=semesters,
            )
        )
    return modules


def load_cohorts(path: Path) -> list[CohortRow]:
    """Load cohort rows from the student workbook."""

    rows = read_first_sheet(path)
    headers = [normalize_header(v) for v in rows[0]]
    idx_course = headers.index("course")
    idx_class = headers.index("class")

    cohorts: list[CohortRow] = []
    for row in rows[1:]:
        if not row[idx_course] or not row[idx_class]:
            continue
        cohorts.append(
            CohortRow(
                id=len(cohorts) + 1,
                course=str(row[idx_course]).strip(),
                class_name=str(row[idx_class]).strip(),
            )
        )
    return cohorts


def load_calendar(path: Path) -> tuple[int, dict[int, set[int]], list[tuple[int, int]]]:
    """
    Read the daily academic calendar.

    Returns:
        nr_weeks: Number of academic weeks in the source calendar.
        regular_weekdays_by_week: week -> set(weekday indexes that are regular teaching days).
        unavailable_days: list of (week_index, weekday_index) pairs for non-regular days.
    """

    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb["Daily Calendar"]
    headers = [normalize_header(v) for v in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    idx_week = headers.index("week")
    idx_day = headers.index("day of week")
    idx_event = headers.index("event type")

    regular_weekdays_by_week: dict[int, set[int]] = {}
    unavailable_days: list[tuple[int, int]] = []
    max_week = 1

    for row in ws.iter_rows(min_row=2, values_only=True):
        week = safe_int(row[idx_week], 1)
        day_name = str(row[idx_day] or "").strip()
        event_type = str(row[idx_event] or "Regular").strip()
        if day_name not in WEEKDAY_INDEX:
            continue

        weekday = WEEKDAY_INDEX[day_name]
        max_week = max(max_week, week)

        if event_type == "Regular" and weekday < 5:
            regular_weekdays_by_week.setdefault(week, set()).add(weekday)
        else:
            unavailable_days.append((week, weekday))

    return max_week, regular_weekdays_by_week, unavailable_days


def semester_weeks(
    regular_weekdays_by_week: dict[int, set[int]],
    semesters: Iterable[int],
) -> str:
    """
    Build an ITC weeks bitstring for the given semesters.

    The source workbook marks modules as Sem 1 / Sem 2 / Sem 3, but does not
    define exact teaching weeks per semester. The ranges below follow the
    academic calendar events:

    * Semester 1: weeks 1-19, before the January revision/exam period.
    * Semester 2: weeks 22-42, before the late-June revision/exam period.
    * Semester 3: weeks 43-53, retained for future summer/third-semester data.
    """

    semester_ranges = {
        1: range(1, 20),
        2: range(22, 43),
        3: range(43, 54),
    }
    selected_weeks: set[int] = set()
    for semester in semesters:
        selected_weeks.update(semester_ranges.get(semester, []))

    if not selected_weeks:
        selected_weeks.update(regular_weekdays_by_week.keys())

    nr_weeks = max(max(regular_weekdays_by_week.keys(), default=1), 53)
    return "".join(
        "1" if week in selected_weeks and regular_weekdays_by_week.get(week) else "0"
        for week in range(1, nr_weeks + 1)
    )


def time_to_slot(value: str) -> int:
    """Convert ``HH:MM`` into an ITC 5-minute slot index."""

    hour, minute = [int(part) for part in value.split(":")]
    return (hour * 60 + minute) // SLOT_MINUTES


def module_meetings_per_week(module: ModuleRow) -> tuple[int, int]:
    """
    Approximate weekly meeting count and length from contact hours.

    The source gives total contact hours only. We cap each meeting at roughly
    two hours by default and spread larger modules over multiple weekly days.
    """

    active_semesters = max(len(module.semesters), 1)
    nominal_weeks = 18 * active_semesters
    weekly_hours = max(module.contact_hours / nominal_weeks, 1.0)
    meetings = min(max(math.ceil(weekly_hours / DEFAULT_SESSION_HOURS), 1), 3)
    meeting_hours = max(math.ceil(weekly_hours / meetings), 1)
    return meetings, meeting_hours * 60 // SLOT_MINUTES


def make_time_options(module: ModuleRow, weeks: str) -> list[dict[str, str | int]]:
    """Create a small domain of possible ITC time assignments for a module."""

    meetings, length = module_meetings_per_week(module)
    day_patterns = DAY_PATTERNS.get(meetings, DAY_PATTERNS[1])

    options: list[dict[str, str | int]] = []
    for days_index, days in enumerate(day_patterns):
        for start_index, start_text in enumerate(DEFAULT_TEACHING_STARTS):
            options.append(
                {
                    "days": days,
                    "start": time_to_slot(start_text),
                    "length": length,
                    "weeks": weeks,
                    # Earlier, regular weekday slots are preferred. Later slots remain valid.
                    "penalty": days_index + start_index,
                }
            )
    return options


def make_weeks_bit(nr_weeks: int, one_based_week: int) -> str:
    """Create a weeks bitstring with exactly one selected week."""

    return "".join("1" if idx == one_based_week else "0" for idx in range(1, nr_weeks + 1))


def make_days_bit(weekday: int) -> str:
    """Create a days bitstring with exactly one selected day."""

    return "".join("1" if idx == weekday else "0" for idx in range(DEFAULT_DAY_COUNT))


def add_xml_comment(parent: ET.Element, text: str) -> None:
    """Append a formatted XML comment for human-readable conversion notes."""

    parent.append(ET.Comment(f" {text} "))


def build_xml(
    rooms: list[RoomRow],
    modules: list[ModuleRow],
    cohorts: list[CohortRow],
    nr_weeks: int,
    regular_weekdays_by_week: dict[int, set[int]],
    unavailable_days: list[tuple[int, int]],
    cohort_size: int,
) -> ET.ElementTree:
    """Build an ITC 2019-compatible XML document."""

    root = ET.Element(
        "problem",
        {
            "name": "AITTO-Dataset-2025-26",
            "nrDays": str(DEFAULT_DAY_COUNT),
            "nrWeeks": str(nr_weeks),
            "slotsPerDay": str(SLOTS_PER_DAY),
        },
    )
    add_xml_comment(
        root,
        "Generated from dataset/*.xlsx by scripts/convert_dataset_to_itc2019.py. "
        "Cohorts are expanded into synthetic students because the source does not contain individual enrollment rows.",
    )

    ET.SubElement(
        root,
        "optimization",
        {
            "time": "1",
            "room": "1",
            "distribution": "1",
            "student": "1",
        },
    )

    rooms_el = ET.SubElement(root, "rooms")
    for room in rooms:
        room_el = ET.SubElement(
            rooms_el,
            "room",
            {
                "id": str(room.id),
                "capacity": str(room.capacity),
                "name": room.name,
                "type": room.room_type,
            },
        )
        for week, weekday in unavailable_days:
            ET.SubElement(
                room_el,
                "unavailable",
                {
                    "days": make_days_bit(weekday),
                    "start": "0",
                    "length": str(SLOTS_PER_DAY),
                    "weeks": make_weeks_bit(nr_weeks, week),
                },
            )

    courses_el = ET.SubElement(root, "courses")
    class_id = 1
    subpart_id = 1
    config_id = 1
    class_ids_by_module: dict[int, list[int]] = {}

    for module in modules:
        course_el = ET.SubElement(
            courses_el,
            "course",
            {"id": str(module.id), "code": module.code, "title": module.title},
        )
        config_el = ET.SubElement(course_el, "config", {"id": str(config_id)})
        config_id += 1
        subpart_el = ET.SubElement(
            config_el,
            "subpart",
            {"id": str(subpart_id), "name": "Main"},
        )
        subpart_id += 1

        weeks = semester_weeks(regular_weekdays_by_week, module.semesters)
        time_options = make_time_options(module, weeks)
        matching_rooms = [room for room in rooms if room.room_type.lower() == module.room_type.lower()]
        if not matching_rooms:
            matching_rooms = rooms

        class_ids_by_module[module.id] = []
        for cohort in cohorts:
            class_el = ET.SubElement(
                subpart_el,
                "class",
                {
                    "id": str(class_id),
                    "limit": str(cohort_size),
                    "name": f"{module.code}-{cohort.course}-{cohort.class_name}",
                    "cohort": f"{cohort.course}-{cohort.class_name}",
                },
            )
            class_ids_by_module[module.id].append(class_id)
            class_id += 1

            for room in matching_rooms:
                # Matching room types are preferred. The solver can still choose among them by capacity.
                penalty = 0 if room.capacity >= cohort_size else cohort_size - room.capacity
                ET.SubElement(class_el, "room", {"id": str(room.id), "penalty": str(penalty)})

            for option in time_options:
                ET.SubElement(
                    class_el,
                    "time",
                    {
                        "days": str(option["days"]),
                        "start": str(option["start"]),
                        "length": str(option["length"]),
                        "weeks": str(option["weeks"]),
                        "penalty": str(option["penalty"]),
                    },
                )

    distributions_el = ET.SubElement(root, "distributions")
    add_xml_comment(
        distributions_el,
        "Generated soft NotOverlap constraints keep sections of the same module from being scheduled at identical times where possible.",
    )
    for module in modules:
        ids = class_ids_by_module.get(module.id, [])
        if len(ids) < 2:
            continue
        distribution_el = ET.SubElement(distributions_el, "distribution", {"type": "NotOverlap", "penalty": "1"})
        for cid in ids:
            ET.SubElement(distribution_el, "class", {"id": str(cid)})

    students_el = ET.SubElement(root, "students")
    student_id = 1
    for cohort in cohorts:
        for offset in range(cohort_size):
            student_el = ET.SubElement(
                students_el,
                "student",
                {
                    "id": str(student_id),
                    "externalId": f"{cohort.course}-{cohort.class_name}-{offset + 1:02d}",
                },
            )
            for module in modules:
                ET.SubElement(student_el, "course", {"id": str(module.id)})
            student_id += 1

    return ET.ElementTree(root)


def write_pretty_xml(tree: ET.ElementTree, path: Path) -> None:
    """Write XML with stable indentation for review and version control."""

    rough = ET.tostring(tree.getroot(), encoding="utf-8")
    parsed = minidom.parseString(rough)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8"), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse PowerShell-friendly command line arguments."""

    parser = argparse.ArgumentParser(description="Convert local Excel dataset to ITC 2019 XML.")
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR, help="Folder containing source .xlsx files.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output ITC 2019 XML path.")
    parser.add_argument(
        "--cohort-size",
        type=int,
        default=DEFAULT_COHORT_SIZE,
        help="Synthetic student count per cohort row in students.xlsx.",
    )
    return parser.parse_args()


def main() -> None:
    """Load source workbooks and write the ITC 2019 XML instance."""

    args = parse_args()
    dataset_dir = args.dataset_dir
    rooms = load_rooms(dataset_dir / "classroom.xlsx")
    modules = load_modules(dataset_dir / "modules_set_A.xlsx")
    cohorts = load_cohorts(dataset_dir / "students.xlsx")
    nr_weeks, regular_weekdays_by_week, unavailable_days = load_calendar(
        dataset_dir / "academic_calendar_2025_26.xlsx"
    )

    tree = build_xml(
        rooms=rooms,
        modules=modules,
        cohorts=cohorts,
        nr_weeks=nr_weeks,
        regular_weekdays_by_week=regular_weekdays_by_week,
        unavailable_days=unavailable_days,
        cohort_size=args.cohort_size,
    )
    write_pretty_xml(tree, args.output)

    print(f"Wrote {args.output}")
    print(f"Rooms: {len(rooms)}")
    print(f"Courses/modules: {len(modules)}")
    print(f"Cohorts: {len(cohorts)}")
    print(f"Classes/sections: {len(modules) * len(cohorts)}")
    print(f"Synthetic students: {len(cohorts) * args.cohort_size}")


if __name__ == "__main__":
    main()
