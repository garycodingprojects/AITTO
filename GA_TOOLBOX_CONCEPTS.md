# GA Toolbox Concepts Guide

This document summarizes how the aiTTO Python GA toolbox represents timetables,
how assignment lines are read, and what the main GA settings mean. It complements
[GA_TOOLBOX_PLAN.md](GA_TOOLBOX_PLAN.md) and [GA_TOOLBOX_BUILD.md](GA_TOOLBOX_BUILD.md).

Default dataset: `dataset/itc2019/aitto_dataset.xml`  
Slot model: **30-minute slots**, `slotsPerDay=48` (08:30 = slot 17, 17:30 = slot 35).

---

## 1. Chromosome structure

### What is a chromosome?

A **chromosome** is one complete **timetable candidate**: a full set of time and
room decisions for every class section in the problem.

In code:

| Layer | Python type | Meaning |
|-------|-------------|---------|
| Chromosome | `TimetableSolution` | Whole timetable |
| Gene map | `assignments: dict[int, ClassAssignment]` | One entry per `class_id` |
| Gene | `ClassAssignment(time_index, room_id)` | Time option + room for that class |

```python
# One gene
ClassAssignment(time_index=6, room_id=9)

# One chromosome (simplified)
TimetableSolution(assignments={
    1: ClassAssignment(time_index=6, room_id=9),   # MAT2001-FS123456-1A
    2: ClassAssignment(time_index=3, room_id=4), # MAT2001-FS123456-1B
    # ... one gene per class section
})
```

### Chromosome length

Length = number of **class sections** in the loaded XML (often about 45 when three
cohorts each take 15 modules). Classes with no time or room domain are skipped.

### What each gene stores

Each gene stores **indices into XML domains**, not raw clock times or room names.

| Field | Meaning |
|-------|---------|
| `time_index` | Which `<time>` option (0, 1, 2, …) from that class’s allowed list |
| `room_id` | Which allowed `<room id="…">` was chosen |

Decoding looks up `section.times[time_index]` and `problem.rooms[room_id]`.

### What is not in the chromosome (prototype)

| Fixed in XML | Evolved by GA |
|--------------|----------------|
| Which classes exist | — |
| Allowed time options per class | Which `time_index` |
| Allowed rooms per class | Which `room_id` |
| Student course enrollments | — |
| Cohort per section name | — |

Full ITC **student sectioning** (choosing among multiple sections per subpart) is
planned in `BLUEPRINT.md` but not encoded in genes yet.

### Population

```text
Population (e.g. 50 chromosomes)
├── Timetable 1: { class_1 → (time_i, room_j), … }
├── Timetable 2: { … }
└── Timetable 50: { … }
```

The GA compares fitness, keeps elites, and breeds new timetables via selection,
crossover, mutation, and repair.

### GA operators (per gene / per class)

| Operator | Effect |
|----------|--------|
| **Initialize** | Random valid `time_index` and `room_id` per class |
| **Crossover** | For each class, child inherits gene from parent A or B (50/50) |
| **Mutation** | With probability `mutation_rate`, change time and/or room within domain |
| **Repair** | Fix missing or invalid genes |

### Fitness

```text
fitness = hard_violations × 1,000,000 + total_cost
```

- **Hard violations first** (clashes, room overlap, capacity, allocations, …).
- **Total cost** = sum of soft penalties (time, room, distribution, …).
- Lower is better.

---

## 2. Reading an assignment line (GUI / log)

The toolbox prints each scheduled class like:

```text
MAT2001-FS123456-1A -> C323c, 1010000, 11:30-13:30, penalty=6
```

Format:

```text
{class name} -> {room}, {days}, {start}-{end}, penalty={time penalty}
```

### `MAT2001-FS123456-1A` — class section

| Part | Meaning |
|------|---------|
| `MAT2001` | Module/course code |
| `FS123456` | Programme code |
| `1A` | Class group |

XML example:

```xml
<class id="1" limit="30" name="MAT2001-FS123456-1A" cohort="FS123456-1A">
```

### `C323c` — room

Physical room chosen for that section (from allowed `<room>` options).

### `1010000` — days (weekday pattern)

Seven characters: **Mon Tue Wed Thu Fri Sat Sun**.

```text
1 0 1 0 1 0 0  →  Monday, Wednesday, Friday
```

From XML attribute `days="1010000"`.

### `11:30-13:30` — clock time

From `start` and `length` in **30-minute slots**:

| XML | Calculation | Result |
|-----|-------------|--------|
| `start="23"` | 23 × 30 min | **11:30** start |
| `length="4"` | 4 × 30 min | **2 hours** |
| End | slot 27 | **13:30** |

### `penalty=6` — soft time cost

Preference cost of that time option (lower is better). Added to `total_cost`, not
the same as hard violations. Room options can have separate room penalties.

---

## 3. The `weeks` bitstring (not shown in short GUI lines)

Each `<time>` option also has a `weeks` attribute: a **53-character** string for
academic weeks 1–53 (`nrWeeks="53"`).

- `1` = class runs that week (with the given days and slot time).
- `0` = not scheduled that week.

Example (same slot as above):

```xml
<time days="1010000" start="23" length="4"
     weeks="11111111111111110110000000000000000000000000000000000"
     penalty="6"/>
```

### How weeks are built (converter)

From `scripts/convert_dataset_to_itc2019.py`, `semester_weeks()`:

1. **Semester ranges** (from module Sem 1 / 2 / 3 flags):

| Semester | Weeks |
|----------|-------|
| 1 | 1–19 |
| 2 | 22–42 |
| 3 | 43–53 |

2. **Academic calendar** — week must have at least one “Regular” weekday or the
   bit is forced to `0` (revision, exams, holidays).

```text
weeks bit = (week in semester range) AND (week has regular teaching in calendar)
```

### Plain-language schedule

For the example gene:

> **MAT2001** for cohort **FS123456-1A** in **C323c**, on **Mon/Wed/Fri** from
> **11:30–13:30**, during **Semester 1 weeks that are still “Regular”** in the
> calendar (not every week 1–19 may be `1`).

### Overlap rule (simplified)

Two classes conflict if they overlap in **weeks**, **days**, and **slot interval**.

---

## 4. Three bitstrings + slots (reference)

| Field | Length | Each position |
|-------|--------|----------------|
| `days` | 7 | Mon … Sun |
| `weeks` | 53 | Academic week 1 … 53 |
| `start` / `length` | slots | Time within the day (30 min per slot) |

---

## 5. GA settings (GUI / CLI)

| Setting | Default | Meaning |
|---------|---------|---------|
| **Population** | 50 | How many timetable candidates exist at once |
| **Generations** | 100 | How many evolution rounds after the initial population |
| **Mutation** | 0.15 | Per-class probability of changing time and/or room |
| **Seed** | 1 | Random seed for reproducible runs |

### Population

More candidates → more diversity, slower runs. Each candidate is a full
`TimetableSolution`.

### Generations

One generation: sort by fitness → keep elite → create children (select, crossover,
mutate, repair) → re-score → update best.

`generations=100` means ~100 improvement rounds, not 100 total timetables only.

### Mutation rate

Default `0.15`: each class has 15% chance per child to get a new time and/or room
from allowed options. Too low → stagnation; too high → destroys good timetables.

### Seed

Same seed + same settings + same data → same random choices → repeatable results.
Use different seeds to test stability.

### Example CLI

```powershell
python .\scripts\run_ga_toolbox.py `
  --population 50 `
  --generations 100 `
  --mutation-rate 0.15 `
  --seed 1
```

### Suggested starting values (current dataset scale)

| Setting | Value | Notes |
|---------|-------|-------|
| Population | 50 | Increase if results are weak |
| Generations | 100–200 | More for harder feasibility |
| Mutation | 0.15 | Per-class rate |
| Seed | 1 | Change to compare runs |

---

## 6. Chromosome vs blueprint (long term)

| Blueprint (full solver) | Prototype chromosome |
|-------------------------|----------------------|
| Class: time + room genes | Yes |
| Student: sectioning genes | No (fixed cohort sections) |
| Hybrid GA + local search | Baseline GA only |
| Official ITC DTF/cost | Simplified evaluator |

---

## 7. Related files

| File | Role |
|------|------|
| `aitto_toolbox/model.py` | `ClassAssignment`, `TimetableSolution`, `GASettings` |
| `aitto_toolbox/ga.py` | Init, crossover, mutation, `run_ga()` |
| `aitto_toolbox/evaluate.py` | Fitness and constraint breakdown |
| `aitto_toolbox/visualize_tk.py` | GUI assignment lines and timetable grid |
| `scripts/convert_dataset_to_itc2019.py` | Builds `days`, `weeks`, time domains in XML |
| [GA_TOOLBOX_SUMMARY.md](GA_TOOLBOX_SUMMARY.md) | Quick index and commands |
