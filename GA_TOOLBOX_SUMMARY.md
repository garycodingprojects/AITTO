# Python GA Timetable Toolbox — Quick Index

Documentation is split into two files:

| Document | Contents |
|----------|----------|
| [GA_TOOLBOX_PLAN.md](GA_TOOLBOX_PLAN.md) | Goals, scope, architecture, data model, GA design, LLM toolbox intent |
| [GA_TOOLBOX_BUILD.md](GA_TOOLBOX_BUILD.md) | Module layout, build pipeline, run steps, validation, extension guide |
| [GA_TOOLBOX_CONCEPTS.md](GA_TOOLBOX_CONCEPTS.md) | Chromosome structure, assignment format, weeks/days encoding, GA parameters |

## Quick start

```powershell
python .\scripts\run_ga_toolbox.py --gui
```

```powershell
python .\scripts\run_ga_toolbox.py --generations 100 --population 50 --seed 1
```

Default input: `dataset/itc2019/aitto_dataset.xml`

Constraint catalogs:

- `dataset/hardconstraints.xlsx`
- `dataset/softconstraints.xlsx`

These workbook rows are loaded by the toolbox and mapped into the prototype
fitness function where the current XML model has enough structured data.

## Public Python API

```python
from aitto_toolbox import GASettings, load_problem, run_ga
```

See [GA_TOOLBOX_BUILD.md](GA_TOOLBOX_BUILD.md) for LLM integration examples.
