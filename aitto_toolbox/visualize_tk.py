"""Tkinter visualization for the aiTTO GA toolbox."""

from __future__ import annotations

import sys
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, Canvas, Listbox, StringVar, Tk, Text
from tkinter import messagebox, ttk

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aitto_toolbox.ga import run_ga
from aitto_toolbox.io_xml import load_problem
from aitto_toolbox.model import (
    ClassAssignment,
    DAY_NAMES,
    DEFAULT_DATASET_XML,
    GASettings,
    GARunResult,
    ProblemInstance,
    TimetableSolution,
    slot_to_time,
)

TEACHING_START_TIME = "08:30"
TEACHING_END_TIME = "17:30"
SLOT_PIXEL_HEIGHT = 30


class TimetableToolboxApp:
    """Small desktop app for loading XML, running GA, and viewing schedules."""

    def __init__(self, input_path: str | Path = DEFAULT_DATASET_XML) -> None:
        self.input_path = Path(input_path)
        self.problem: ProblemInstance | None = None
        self.result: GARunResult | None = None
        self.root = Tk()
        self.root.title("aiTTO Python GA Toolbox")
        self.root.geometry("1180x780")

        self.population_var = StringVar(value="50")
        self.generations_var = StringVar(value="100")
        self.mutation_var = StringVar(value="0.15")
        self.seed_var = StringVar(value="1")
        self.view_mode_var = StringVar(value="Room")
        self.view_target_var = StringVar()

        self._build()
        self.load_dataset()

    def _build(self) -> None:
        """Create widgets for the toolbox viewer."""

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=BOTH, expand=True)

        top = ttk.Frame(outer)
        top.pack(fill=X)
        ttk.Label(top, text="Input XML").pack(side=LEFT)
        self.path_var = StringVar(value=str(self.input_path))
        ttk.Entry(top, textvariable=self.path_var).pack(side=LEFT, fill=X, expand=True, padx=8)
        ttk.Button(top, text="Load", command=self.load_dataset).pack(side=LEFT)

        notebook = ttk.Notebook(outer)
        notebook.pack(fill=BOTH, expand=True, pady=(10, 0))

        self.summary_text = Text(notebook, height=12, wrap="word")
        notebook.add(self.summary_text, text="Summary")

        run_frame = ttk.Frame(notebook, padding=10)
        notebook.add(run_frame, text="Run GA")
        self._build_run_tab(run_frame)

        visual_frame = ttk.Frame(notebook, padding=10)
        notebook.add(visual_frame, text="Visualize")
        self._build_visual_tab(visual_frame)

    def _build_run_tab(self, parent: ttk.Frame) -> None:
        """Create controls and logs for GA execution."""

        controls = ttk.Frame(parent)
        controls.pack(fill=X)

        for label, variable, width in (
            ("Population", self.population_var, 8),
            ("Generations", self.generations_var, 8),
            ("Mutation", self.mutation_var, 8),
            ("Seed", self.seed_var, 8),
        ):
            ttk.Label(controls, text=label).pack(side=LEFT)
            ttk.Entry(controls, textvariable=variable, width=width).pack(side=LEFT, padx=(4, 14))

        ttk.Button(controls, text="Run GA", command=self.run_ga_from_gui).pack(side=RIGHT)

        panes = ttk.PanedWindow(parent, orient="horizontal")
        panes.pack(fill=BOTH, expand=True, pady=(10, 0))

        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=1)

        ttk.Label(left, text="Progress").pack(anchor="w")
        self.progress_list = Listbox(left)
        self.progress_list.pack(fill=BOTH, expand=True)

        ttk.Label(right, text="Best solution details").pack(anchor="w")
        self.details_text = Text(right, wrap="word")
        self.details_text.pack(fill=BOTH, expand=True)

    def _build_visual_tab(self, parent: ttk.Frame) -> None:
        """Create the scrollable timetable canvas with room and cohort views."""

        controls = ttk.Frame(parent)
        controls.pack(fill=X)
        ttk.Label(controls, text="View by").pack(side=LEFT)
        self.view_mode_combo = ttk.Combobox(
            controls,
            textvariable=self.view_mode_var,
            state="readonly",
            values=("Room", "Cohort"),
            width=10,
        )
        self.view_mode_combo.pack(side=LEFT, padx=8)
        self.view_mode_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_view_targets())

        ttk.Label(controls, text="Selection").pack(side=LEFT)
        self.view_target_combo = ttk.Combobox(controls, textvariable=self.view_target_var, state="readonly", width=42)
        self.view_target_combo.pack(side=LEFT, padx=8)
        self.view_target_combo.bind("<<ComboboxSelected>>", lambda _event: self.draw_timetable())
        ttk.Button(controls, text="Refresh View", command=self.draw_timetable).pack(side=LEFT)

        ttk.Label(
            controls,
            text=f"Initial view: {TEACHING_START_TIME}-{TEACHING_END_TIME}; scroll for other slots.",
        ).pack(side=RIGHT)

        canvas_frame = ttk.Frame(parent)
        canvas_frame.pack(fill=BOTH, expand=True, pady=(10, 0))
        self.canvas = Canvas(canvas_frame, background="white", height=620)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.timeline_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.timeline_scroll.pack(side=RIGHT, fill=Y)
        self.canvas.configure(yscrollcommand=self.timeline_scroll.set)

    def load_dataset(self) -> None:
        """Load the XML dataset and refresh summary widgets."""

        try:
            self.input_path = Path(self.path_var.get())
            self.problem = load_problem(self.input_path)
        except Exception as exc:  # noqa: BLE001 - shown in a user-facing dialog.
            messagebox.showerror("Load failed", str(exc))
            return

        self.result = None
        self.summary_text.delete("1.0", END)
        self.summary_text.insert(END, self._summary_text())
        self.progress_list.delete(0, END)
        self.details_text.delete("1.0", END)

        self.refresh_view_targets()

    def _summary_text(self) -> str:
        """Return readable dataset statistics for the Summary tab."""

        if self.problem is None:
            return "No dataset loaded."
        return "\n".join(
            [
                f"Problem: {self.problem.name}",
                f"Source: {self.problem.source_path}",
                f"Days: {self.problem.nr_days}",
                f"Weeks: {self.problem.nr_weeks}",
                f"Slots per day: {self.problem.slots_per_day}",
                f"Rooms: {len(self.problem.rooms)}",
                f"Courses/modules: {len(self.problem.courses)}",
                f"Classes/sections: {len(self.problem.classes)}",
                f"Students: {len(self.problem.students)}",
                f"Cohorts: {len(self.problem.cohorts)}",
                f"Distribution constraints: {len(self.problem.distributions)}",
                f"Hard constraint catalog rows: {len(self.problem.hard_constraints)}",
                f"Soft constraint catalog rows: {len(self.problem.soft_constraints)}",
                "",
                "Cohorts:",
                *[f"  {cohort}" for cohort in self.problem.cohorts],
                "",
                "Supported hard constraints:",
                *[f"  {item.constraint_type}: {item.implementation}" for item in self.problem.hard_constraints if item.supported],
                "",
                "Supported soft constraints:",
                *[f"  {item.constraint_type}: {item.implementation}" for item in self.problem.soft_constraints if item.supported],
            ]
        )

    def run_ga_from_gui(self) -> None:
        """Run the GA using values from the control panel."""

        if self.problem is None:
            messagebox.showwarning("No dataset", "Load an XML dataset first.")
            return

        try:
            settings = GASettings(
                population_size=int(self.population_var.get()),
                generations=int(self.generations_var.get()),
                mutation_rate=float(self.mutation_var.get()),
                seed=int(self.seed_var.get()),
            )
        except ValueError as exc:
            messagebox.showerror("Invalid GA setting", str(exc))
            return

        self.progress_list.delete(0, END)
        self.details_text.delete("1.0", END)

        def on_progress(entry, _solution) -> None:
            if entry.generation == 0 or entry.generation == settings.generations or entry.generation % 10 == 0:
                self.progress_list.insert(
                    END,
                    f"Gen {entry.generation:>4}: hard={entry.best_hard_violations}, cost={entry.best_total_cost}",
                )
                self.root.update_idletasks()

        self.result = run_ga(self.problem, settings, progress_callback=on_progress)
        self._show_best_solution()
        self.draw_timetable()

    def _show_best_solution(self) -> None:
        """Display the best solution cost breakdown and assignments."""

        if self.problem is None or self.result is None:
            return

        best = self.result.best_solution
        self.details_text.delete("1.0", END)
        self.details_text.insert(END, f"Best generation: {best.generation}\n")
        self.details_text.insert(END, f"Hard violations: {best.hard_violations}\n")
        self.details_text.insert(END, f"Total cost: {best.total_cost}\n\n")
        self.details_text.insert(END, "Breakdown:\n")
        for key, value in sorted(best.breakdown.items()):
            self.details_text.insert(END, f"  {key}: {value}\n")
        self.details_text.insert(END, "\nAssignments:\n")

        for class_id, assignment in sorted(best.assignments.items()):
            section = self.problem.classes[class_id]
            time = section.times[assignment.time_index]
            room = self.problem.rooms[assignment.room_id]
            start = slot_to_time(time.start, self.problem.slots_per_day)
            end = slot_to_time(time.start + time.length, self.problem.slots_per_day)
            self.details_text.insert(
                END,
                f"  {section.name} -> {room.name}, {time.days}, {start}-{end}, penalty={time.penalty}\n",
            )

    def refresh_view_targets(self) -> None:
        """Refresh the selection combobox when switching room/cohort view."""

        if self.problem is None:
            self.view_target_combo["values"] = ()
            self.view_target_var.set("")
            return

        if self.view_mode_var.get() == "Cohort":
            values = list(self.problem.cohorts)
        else:
            values = [f"{room.id}: {room.name}" for room in self.problem.rooms.values()]

        self.view_target_combo["values"] = values
        if values:
            self.view_target_var.set(values[0])
        else:
            self.view_target_var.set("")
        self.draw_timetable()

    def draw_timetable(self) -> None:
        """Draw the best timetable for the selected room or cohort."""

        self.canvas.delete("all")
        if self.problem is None:
            return

        width = max(self.canvas.winfo_width(), 900)
        left_margin = 80
        top_margin = 40
        bottom_margin = 40
        day_width = (width - left_margin - 20) / max(self.problem.nr_days, 1)
        slot_height = SLOT_PIXEL_HEIGHT
        content_height = top_margin + self.problem.slots_per_day * slot_height + bottom_margin

        for day_index, day_name in enumerate(DAY_NAMES[: self.problem.nr_days]):
            x0 = left_margin + day_index * day_width
            self.canvas.create_text(x0 + day_width / 2, 20, text=day_name)
            self.canvas.create_line(x0, top_margin, x0, content_height - bottom_margin, fill="#cccccc")
        self.canvas.create_line(width - 20, top_margin, width - 20, content_height - bottom_margin, fill="#cccccc")

        for slot in range(0, self.problem.slots_per_day + 1, 2):
            y = top_margin + slot * slot_height
            self.canvas.create_line(left_margin, y, width - 20, y, fill="#eeeeee")
            self.canvas.create_text(40, y, text=slot_to_time(slot, self.problem.slots_per_day), anchor="w")

        solution = self.result.best_solution if self.result is not None else self._first_domain_solution()
        self._draw_solution_blocks(solution, left_margin, top_margin, day_width, slot_height)
        self.canvas.configure(scrollregion=(0, 0, width, content_height))
        self._scroll_to_teaching_window()

    def _selected_room_id(self) -> int | None:
        """Read the selected room id from the combobox label."""

        value = self.view_target_var.get()
        if ":" not in value:
            return None
        return int(value.split(":", 1)[0])

    def _selected_cohort(self) -> str:
        """Read the selected cohort label."""

        return self.view_target_var.get()

    def _displayed_classes(self, solution: TimetableSolution) -> list[tuple[int, ClassAssignment]]:
        """Filter assignments by the selected Room or Cohort view."""

        if self.problem is None:
            return []

        if self.view_mode_var.get() == "Cohort":
            cohort = self._selected_cohort()
            return [
                (class_id, assignment)
                for class_id, assignment in solution.assignments.items()
                if self.problem.classes[class_id].cohort == cohort
            ]

        room_id = self._selected_room_id()
        if room_id is None:
            return []
        return [
            (class_id, assignment)
            for class_id, assignment in solution.assignments.items()
            if assignment.room_id == room_id
        ]

    def _first_domain_solution(self) -> TimetableSolution:
        """Build a deterministic preview using each class's first valid option."""

        assert self.problem is not None
        assignments = {}
        for class_id, section in self.problem.classes.items():
            if section.times and section.rooms:
                assignments[class_id] = ClassAssignment(time_index=0, room_id=section.rooms[0].room_id)
        return TimetableSolution(assignments=assignments)

    def _draw_solution_blocks(
        self,
        solution: TimetableSolution,
        left_margin: int,
        top_margin: int,
        day_width: float,
        slot_height: float,
    ) -> None:
        """Draw class blocks for the selected room or cohort."""

        assert self.problem is not None
        header = self._view_header()
        self.canvas.create_text(left_margin + 6, 8, anchor="nw", text=header)

        for class_id, assignment in self._displayed_classes(solution):
            section = self.problem.classes[class_id]
            time = section.times[assignment.time_index]
            room = self.problem.rooms.get(assignment.room_id)
            for day_index, active in enumerate(time.days[: self.problem.nr_days]):
                if active != "1":
                    continue
                x0 = left_margin + day_index * day_width + 4
                x1 = x0 + day_width - 8
                y0 = top_margin + time.start * slot_height + 2
                y1 = top_margin + (time.start + time.length) * slot_height - 2
                self.canvas.create_rectangle(x0, y0, x1, y1, fill="#b9d7ff", outline="#3a6ea5")
                self.canvas.create_text(
                    x0 + 4,
                    y0 + 4,
                    anchor="nw",
                    text=self._block_label(section.course_code, section.cohort, room.name if room else ""),
                    width=max(day_width - 12, 40),
                )

    def _block_label(self, course_code: str, cohort: str, room_name: str) -> str:
        """Return a compact class label suitable for the timetable block."""

        if self.view_mode_var.get() == "Cohort":
            return f"{course_code}\n{room_name}"
        return f"{course_code}\n{cohort}"

    def _view_header(self) -> str:
        """Return the current timetable header."""

        if self.problem is None:
            return ""
        if self.view_mode_var.get() == "Cohort":
            return f"Cohort view: {self._selected_cohort()}"
        room_id = self._selected_room_id()
        if room_id is None:
            return "Room view"
        return f"Room view: {self.problem.rooms[room_id].name}"

    def _slot_for_time(self, text: str) -> int:
        """Convert HH:MM to the current problem's slot index."""

        assert self.problem is not None
        hour, minute = [int(part) for part in text.split(":")]
        minutes_per_slot = (24 * 60) // self.problem.slots_per_day
        return (hour * 60 + minute) // minutes_per_slot

    def _scroll_to_teaching_window(self) -> None:
        """Initialise the canvas view at 08:30 while retaining full-day scrolling."""

        if self.problem is None:
            return
        self.root.update_idletasks()
        start_slot = self._slot_for_time(TEACHING_START_TIME)
        y = 40 + start_slot * SLOT_PIXEL_HEIGHT
        _, top, _, bottom = self.canvas.bbox("all") or (0, 0, 1, 1)
        span = max(bottom - top, 1)
        self.canvas.yview_moveto(max(min((y - top) / span, 1.0), 0.0))

    def run(self) -> None:
        """Start the Tkinter event loop."""

        self.root.mainloop()


def main() -> None:
    """Open the toolbox viewer using the default dataset."""

    TimetableToolboxApp().run()


if __name__ == "__main__":
    main()

