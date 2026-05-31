# aiTTO Blueprint

**Automated Intelligent Timetabling Optimizer** — a school/university timetable system built on genetic algorithms, aligned with the **ITC 2019** standard.

This document summarizes the project plan, architecture, references, and important notices. It is the single source of truth for how aiTTO should be designed and built.

---

## 1. Vision

Build a timetabling system that:

1. Loads and saves data in the **ITC 2019 XML format** ([format spec](https://www.itc2019.org/format), [competition site](https://www.itc2019.org/)).
2. Solves the **full university course timetabling problem**: assign **times**, **rooms**, and **students** to classes.
3. Uses a **hybrid genetic algorithm** combining ideas from Mahlous & Mahlous (2023), Rezaeipanah et al. (IPGALS, 2020), and the [ScholORs/itc-2019](https://github.com/ScholORs/itc-2019) reference implementation.
4. Supports **student preferences** (day, time period, friends) via compiled penalties or soft constraints.
5. Validates and scores solutions using **official ITC criteria** (DTF + weighted cost).

---

## 2. Important notices

### 2.1 ITC 2019 is the data and scoring standard

- All **problem instances** and **solutions** must use **ITC 2019 XML**, not custom Excel or ad-hoc formats.
- The Mahlous demo (`references/timetable_demo/`) is a **technique reference** for student-assignment operators only; its Excel I/O is **not** the production format.
- Full specification: [PATAT 2018 paper (ITC 2019)](https://www.patatconference.org/patat2018/files/proceedings/paper27.pdf).

### 2.2 ScholORs/itc-2019 is the code foundation

- Use [ScholORs/itc-2019](https://github.com/ScholORs/itc-2019) for: XML parsing, domain model, constraint evaluators, `Timetable` cost/DTF, and the `Algorithm` solver interface.
- Licensed under **GPL-3.0**. If you use or adapt this code, you must comply with GPL and **credit the repository** (see their README).
- Some evaluation pieces are incomplete in upstream (e.g. `calcStudentConflicts()` marked TODO) — aiTTO must complete these for correct scoring.

### 2.3 One unified problem, not two disconnected systems

ITC 2019 already combines:

- **Scheduling** — each class gets a time and room from pre-filtered domains.
- **Student sectioning** — each student is assigned to one class per subpart per course config, respecting parent-child links and class limits.

Earlier plans separated “Phase 1 (IPGALS)” and “Phase 2 (Mahlous)”. The blueprint treats them as **operator families inside one solver**, not separate pipelines with different file formats.

### 2.4 Search strategy: feasibility first, then cost

1. **DTF (Distance to Feasibility)** — count of hard constraint violations; target **DTF = 0**.
2. **Total cost** — minimize only when feasible (or primarily optimize DTF until feasible):

   ```
   TotalCost = w_student × StudentConflicts
             + w_time    × TimePenalties
             + w_room    × RoomPenalties
             + w_dist    × DistributionPenalties
   ```

   Weights come from the problem XML. Lower is better.

### 2.5 Student preferences are not native ITC fields

Mahlous-style preferences (day weights, AM/PM, friends) must be **compiled** into:

- Higher **time assignment penalties** in the problem instance, and/or
- Custom **soft distribution constraints**, and/or
- Post-GA **local search** on student assignments.

Collect preferences in the UI; emit valid ITC problem XML before solving.

### 2.6 Do not merge incompatible encodings

| Part | Encoding |
|------|----------|
| Class scheduling | Per class: index into `possibleTimes[]` and `possibleRooms[]` (or `-1` if unassigned) |
| Student sectioning | Per student/course: config + one class per subpart (or binary student×class matrix with repair) |

Use **one chromosome** with linked parts, or tightly coupled co-evolution; export result as **ITC solution XML** (student ids listed on each class).

### 2.7 Benchmarks and reproducibility

- Develop and test on **ITC 2019 benchmark instances** first.
- Report **mean ± std over 10 runs** (standard practice).
- Log runtime, NFE (function evaluations), DTF, and cost breakdown per criterion.

### 2.8 PowerShell environment

The project is developed and run in **PowerShell** on Windows. Provide `run.ps1` scripts for build, test, and solver runs.

---

## 3. Problem definition (ITC 2019)

### 3.1 Inputs (problem XML)

| Component | Role |
|-----------|------|
| **Times** | `nrWeeks`, `nrDays`, `slotsPerDay` (1 slot = 5 minutes, max 288/day) |
| **Rooms** | Capacity, unavailability, travel times between rooms |
| **Courses** | Hierarchy: Course → Config → Subpart → Class |
| **Classes** | Possible times/rooms (with penalties), capacity limit, optional parent class |
| **Students** | Required course ids |
| **Distribution constraints** | 17 types; hard (`required`) or soft (with penalty) |
| **Weights** | `timePenaltyWeight`, `roomPenaltyWeight`, `distributionPenaltyWeight`, `studentPenaltyWeight` |

### 3.2 Outputs (solution XML)

For **every** class: `id`, `start`, `days`, `weeks`, `room`, and list of **student ids** enrolled.

Plus solver metadata: runtime, technique name, author, institution (competition fields).

### 3.3 Sectioning rules (critical)

- Student chooses **one configuration** per course.
- Must attend **exactly one class per subpart** in that configuration.
- **Parent-child** class relations must be satisfied (e.g. Lab → Rec → Lec).
- **Class limit** must not be exceeded.

### 3.4 Distribution constraint types (ITC)

Pair-based: `SameStart`, `SameTime`, `DifferentTime`, `SameDays`, `DifferentDays`, `SameWeeks`, `DifferentWeeks`, `SameRoom`, `DifferentRoom`, `Overlap`, `NotOverlap`, `SameAttendees`, `Precedence`, `WorkDay`, `MinGap`.

Global: `MaxDays`, `MaxDayLoad`, `MaxBreaks`, `MaxBlock`.

Details: ITC 2019 specification Section 3.5 and ScholORs `dataset/constraints/`.

---

## 4. Research references

| Reference | Role in aiTTO |
|-----------|----------------|
| **Mahlous & Mahlous (2023)** — [PeerJ CS e1200](https://doi.org/10.7717/peerj-cs.1200), `references/peerj-cs-1200.pdf` | Student-boundary crossover, class mutation, repair/improve soft, tournament selection, fitness hashing, preference satisfaction |
| **Rezaeipanah et al. (2020)** — IPGALS, `references/A_hybrid_algorithm_for_the_uni.pdf` | Hybrid GA + local search, DTF criterion, 3× crossover/mutation, island model + shared memory, hard-safe operators |
| **ITC 2019** — [itc2019.org](https://www.itc2019.org/), [format](https://www.itc2019.org/format) | Data format, objective function, validation, benchmarks |
| **ScholORs/itc-2019** — [GitHub](https://github.com/ScholORs/itc-2019) | Java reference: Parser, Encoder, Decoder, `ProblemInstance`, constraints, `Algorithm` base class |
| **Mahlous demo** — `references/timetable_demo/` | Working GA for student assignment; use for operator ideas only |

---

## 5. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  ITC 2019 Problem XML  +  optional preference extensions     │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Core (ScholORs foundation)                                  │
│  Parser → ProblemInstance → Timetable → Constraint eval     │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  aiTTO Hybrid GA Solver                                      │
│  • Class operators (IPGALS)                                  │
│  • Student operators (Mahlous)                               │
│  • DTF improvement + Local search                            │
│  • Optional parallel islands + shared memory                 │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  ITC 2019 Solution XML  →  UI / reports / exports            │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Hybrid GA pipeline

```
1. Load ProblemInstance (ITC XML)
2. Initialize population:
   - Class genes: random-heuristic valid (time, room) from class domains
   - Student genes: greedy/random feasible sectioning per config/subpart
3. Evaluate DTF and TotalCost
4. Repeat until termination (max generations / time / NFE):
   a. Selection (tournament; optional shared-memory parent injection)
   b. Crossover:
      - Class: uniform / one-point / heuristic (hard-safe)
      - Student: student-boundary (Mahlous)
   c. Mutation:
      - Class: local / global / swap (IPGALS)
      - Student: swap within same subpart/module (Mahlous)
   d. Improvement: resolve unassigned classes (-1), reduce DTF
   e. Local search: improving moves on time/room and student assignments
   f. Elitism + optional island migration
5. Export best feasible solution → ITC Solution XML (Decoder)
6. Validate and report cost breakdown
```

---

## 7. Operator summary

| Operator | Source | Purpose |
|----------|--------|---------|
| Random-heuristic init | IPGALS | Feasible-ish starting schedules |
| Student-boundary crossover | Mahlous | Preserve per-student allocation blocks |
| Class crossover (×3) | IPGALS | Mix parent schedules without breaking hard rules |
| Class mutation (×3) | IPGALS | Explore time/room search space |
| Class / student swap mutation | Both | Fine-tune assignments |
| improveAllocations / DTF repair | Mahlous + IPGALS | Fix hard violations |
| improveSoftConstraints | Mahlous | Preference-guided class swaps |
| Local search | IPGALS | Unused (time, room) states; cost-improving moves |
| Island model + shared memory | IPGALS | Diversity, escape local optima |
| Fitness hashing | Mahlous | Cache duplicate chromosome evaluations |
| Parallel fitness | Mahlous | `IntStream.parallel` on population |

---

## 8. Project layout (target)

```
aiTTO/
├── BLUEPRINT.md                 ← this file
├── references/
│   ├── itc-2019/                ← ScholORs clone (GPL-3.0)
│   ├── timetable_demo/          ← Mahlous Java demo
│   ├── peerj-cs-1200.pdf
│   └── A_hybrid_algorithm_for_the_uni.pdf
├── data/
│   └── ITC2019_Dataset/         ← official benchmark XML instances
├── src/
│   ├── dataset/                 ← from ScholORs (or shared module)
│   ├── io/                      ← Parser, Encoder, Decoder
│   ├── solver/
│   │   ├── Algorithm.java
│   │   ├── GeneticAlgorithm.java
│   │   ├── operators/           ← crossover, mutation, repair, LS
│   │   ├── ParallelIsland.java
│   │   └── PreferenceCompiler.java
│   ├── ui/                      ← optional admin + student portal
│   └── Main.java
└── run.ps1
```

---

## 9. Implementation milestones

| # | Milestone | Exit criteria |
|---|-----------|---------------|
| **M1** | ITC foundation | Load XML; run baseline solver (e.g. HillClimbing); export solution XML |
| **M2** | Complete evaluation | `calcStudentConflicts()` + sectioning validation; DTF/cost dashboard |
| **M3** | Hybrid GA core | `GeneticAlgorithm extends Algorithm`; feasible solution on small instance |
| **M4** | Optimization | LS, islands, preference improvement; beat baseline on ≥1 benchmark |
| **M5** | School layer | UI, preference compiler, human-readable exports |

---

## 10. Suggested parameters (starting point)

| Parameter | Small (≤200 events) | Medium (200–400) | Large (>400) |
|-----------|---------------------|------------------|--------------|
| Population | 50 | 30–50 | 30 |
| Max generations | 75–2000 | 50–1000 | 50–500 |
| Crossover rate | 0.75–0.90 | 0.85 | 0.85 |
| Mutation rate | 0.10–0.35 | 0.10–0.15 | 0.15 |
| Islands (Z) | 3 | 5 | 10 |
| LS iterations | 500–2000 | 1000 | 500 |
| Elitism | Top 3–5 + global best | same | same |
| Tournament size | 5–8 | 5–8 | 5–8 |

Tune per instance using Taguchi-style sweeps (IPGALS methodology).

---

## 11. Evaluation metrics

| Metric | Target |
|--------|--------|
| **DTF** | 0 (feasible) |
| **Time penalty** | Minimize |
| **Room penalty** | Minimize |
| **Distribution penalty** | Minimize |
| **Student conflicts** | Minimize |
| **Total cost** | Compare vs baselines / literature |
| **Preference accuracy** | >90% where Mahlous-style prefs apply (internal KPI) |
| **Runtime / NFE** | Log every run |

---

## 12. Mapping Mahlous preferences → ITC

| Mahlous concept | aiTTO implementation |
|-----------------|----------------------|
| Day preference weights | Penalties on time patterns in problem XML |
| AM/PM per day | Slot-range penalties |
| Friend / group preference | Soft constraint or LS co-enrollment |
| Clash avoidance | ITC student conflict criterion |
| Missing / extra / wrong allocation | Sectioning repair operators + ITC structure rules |

---

## 13. School deployment workflow

```
School data (courses, rooms, students, teachers)
        ↓
Build or edit ITC 2019 Problem XML
        ↓
(Optional) Student preferences → PreferenceCompiler
        ↓
aiTTO Hybrid GA
        ↓
ITC 2019 Solution XML
        ↓
Decoder → per-student timetables, room usage, violation report
```

Use official ITC instances during development; add school-specific builders after the solver is stable.

---

## 14. Out of scope (for initial versions)

- Full custom room/teacher scheduling UI unrelated to ITC XML
- Committing GPL-derived code without license compliance
- Replacing ITC distribution constraint engine with a simplified custom ruleset
- Production reliance on incomplete ScholORs TODOs without implementing fixes

---

## 15. Quick reference links

- ITC 2019 home: https://www.itc2019.org/
- ITC 2019 format: https://www.itc2019.org/format
- ScholORs reference implementation: https://github.com/ScholORs/itc-2019
- Mahlous paper (DOI): https://doi.org/10.7717/peerj-cs.1200
- PATAT 2018 ITC specification paper: https://www.patatconference.org/patat2018/files/proceedings/paper27.pdf

---

## 16. Document history

| Version | Summary |
|---------|---------|
| 1.0 | Initial blueprint: ITC 2019 standard + ScholORs foundation + hybrid GA (Mahlous + IPGALS) |

---

*This blueprint consolidates planning from the research paper review, IPGALS hybrid analysis, and ITC 2019 format adoption. Update this file when architecture or scope decisions change.*
