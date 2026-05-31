# Dataset Converter Summary

This document summarizes `scripts/convert_dataset_to_itc2019.py`, the program
that converts the local Excel planning dataset into an aiTTO XML timetable
dataset. The XML is based on the ITC 2019 structure, but aiTTO intentionally
uses a 30-minute slot model to reduce solver computation.

## Purpose

The converter reads school planning workbooks from `dataset/` and generates:

- rooms and room unavailability
- courses/modules
- class sections for assigned cohort/module combinations
- synthetic students for active cohorts
- student course enrollments
- soft distribution constraints between sections of the same module

The default output file is:

```text
dataset/itc2019/aitto_dataset.xml
```

## Source Workbooks

The standard dataset folder is `dataset/`. The converter expects these files by
default:

- `classroom.xlsx` for classroom names, capacities, and room types.
- `students.xlsx` for cohort rows. Each row is treated as one cohort.
- `academic_calendar_2025_26.xlsx` for regular teaching days and unavailable
  calendar days.
- `modules_set_*.xlsx` for module sets. Multiple module-set workbooks can be
  loaded at the same time.

`TeachingLoad.xlsx` exists in the dataset, but it is not currently encoded into
the XML because the current XML structure does not yet model teacher allocation
directly.

## PowerShell Usage

Run the converter with default files:

```powershell
python .\scripts\convert_dataset_to_itc2019.py
```

Open the Tkinter GUI:

```powershell
python .\scripts\convert_dataset_to_itc2019.py --gui
```

Change the synthetic cohort size:

```powershell
python .\scripts\convert_dataset_to_itc2019.py --cohort-size 25
```

Change the teaching window and slot increment:

```powershell
python .\scripts\convert_dataset_to_itc2019.py `
  --teaching-start 08:30 `
  --teaching-end 17:30 `
  --duration-increment-minutes 30
```

Assign module sets from the command line:

```powershell
python .\scripts\convert_dataset_to_itc2019.py `
  --module-file .\dataset\modules_set_A.xlsx `
  --module-file .\dataset\modules_set_B.xlsx `
  --cohort-module FS123456-1A=modules_set_A `
  --cohort-module FS123457-1B=None
```

`None` means the cohort is omitted from the XML.

## GUI Features

The GUI supports:

- selecting the dataset folder and individual source workbooks
- selecting the output XML file
- adding or removing multiple `modules_set_*.xlsx` workbooks
- assigning a module set to selected cohorts
- applying one module set to all cohorts
- choosing `None` for cohorts that should be excluded from the XML
- changing the synthetic student count per active cohort
- changing the teaching start time, teaching end time, and duration increment
- generating the XML
- opening a viewer for the output XML with summary, tree, and raw XML tabs

Newly loaded cohorts default to `None`. This keeps the generated problem small
until the user explicitly assigns module sets.

## Time Slot Model

aiTTO uses 30-minute slots, not the original ITC 2019 5-minute slots.

Important defaults:

- earliest teaching time: `08:30`
- latest teaching end time: `17:30`
- duration increment: `30` minutes
- slots per day: `48`
- `08:30` is slot `17`
- `17:30` is slot `35`

The XML `start` and `length` values are counted in 30-minute slots. For example,
a 2-hour class has `length="4"`.

The converter validates that:

- the teaching start time is earlier than the teaching end time
- the duration increment is positive
- the duration increment is a multiple of 30 minutes
- the teaching start and end times align to the 30-minute slot model

## Calendar Model

The converter reads the `Daily Calendar` sheet from the academic calendar
workbook.

Regular weekday teaching days are used for possible teaching weeks. Non-regular
days, weekends, holidays, revision weeks, exams, and summer break are written as
room unavailability periods.

The XML keeps 7 days because the timetable calendar is Monday through Sunday.
Teaching is normally generated for weekdays, while unavailable periods block
non-teaching days.

The XML week count comes from the maximum week number in the calendar workbook.
For the current dataset, this is 53 weeks.

## Cohort And Module Assignment

Each row in `students.xlsx` is treated as one cohort using:

```text
Course-Class
```

For example:

```text
FS123456-1A
```

Each module-set workbook gets a label from its filename stem. For example:

```text
modules_set_A.xlsx -> modules_set_A
```

The assignment rules are:

- `None` means the cohort is omitted from the XML completely.
- Assigned cohorts generate synthetic students.
- Each assigned module/cohort pair generates one class section.
- Student records are created only for cohorts that have at least one assigned
  module.
- Courses/modules are written only when at least one active cohort uses them.

This design reduces computation by avoiding unused cohorts, unused students, and
unused module sections.

## Module And Class Generation

Each active module becomes one course with:

- one configuration
- one subpart named `Main`
- one class section per active cohort assigned to that module

Room choices are generated from rooms matching the module's room type. If no
matching room type exists, all rooms are allowed as a fallback.

Room penalties are based on capacity:

- `0` if the room capacity is at least the cohort size
- otherwise, the penalty is the missing capacity

Time options are generated from:

- the module semester flags
- the academic calendar
- the teaching start/end times
- the 30-minute duration increment
- weekday meeting patterns

The source workbooks currently provide total contact hours, not exact weekly
lesson patterns. The converter estimates weekly meetings and rounds durations up
to the configured duration increment.

## Output Structure

The generated XML contains these main sections:

- `<optimization>` with current weight values for time, room, distribution, and
  student objectives.
- `<rooms>` with room metadata and unavailable periods.
- `<courses>` with active modules, configs, subparts, classes, rooms, and time
  options.
- `<distributions>` with soft `NotOverlap` constraints between sections of the
  same module.
- `<students>` with synthetic student records and course enrollments for active
  cohorts.

## Important Notices

- The XML is ITC 2019-style, but it is not a strict untouched ITC 2019 instance
  because aiTTO uses 30-minute slots to reduce search difficulty.
- Cohorts assigned to `None` are intentionally excluded from the XML.
- The default GUI assignment is `None`, so generating immediately after reload
  may produce an XML with no classes or students until module sets are assigned.
- The converter creates synthetic students because the source data has cohorts,
  not individual enrollment records.
- Teacher load is not encoded yet.
- Module durations and meeting patterns are approximations based on available
  contact-hour data.
- Calendar unavailable periods are applied to rooms for full days.
- Multiple module-set workbooks are supported. Duplicate module codes are
  deduplicated globally so the XML does not create duplicate courses for the
  same module code.
- The converter writes pretty-printed XML for easier review.

## Key Implementation Areas

The main responsibilities in `scripts/convert_dataset_to_itc2019.py` are:

- workbook loading: `load_rooms()`, `load_modules()`, `load_cohorts()`,
  `load_calendar()`
- module-set handling: `discover_module_files()`, `load_module_sets()`
- cohort assignment: `build_cohort_modules()`,
  `parse_cohort_module_assignments()`
- time generation: `TimeSlotSettings`, `validate_time_slot_settings()`,
  `module_meetings_per_week()`, `make_time_options()`
- XML building: `build_xml()`, `write_pretty_xml()`
- shared conversion entry point: `convert_dataset()`
- CLI handling: `parse_args()`, `main()`
- GUI handling: `ConverterGui`

## Recommended Workflow

1. Open the GUI:

   ```powershell
   python .\scripts\convert_dataset_to_itc2019.py --gui
   ```

2. Reload the dataset after changing workbook paths or module-set files.

3. Assign module sets only to cohorts that should be included in the problem.

4. Keep unused cohorts as `None`.

5. Confirm the teaching window and duration increment.

6. Generate the XML.

7. Use the XML viewer to check summary counts before running a solver.
