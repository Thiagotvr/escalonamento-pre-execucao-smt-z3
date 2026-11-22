"""Concrete temperature monitoring application (P1: A1-A3, P2: A4-A7, P3: S, A8).

Each segment is implemented as a stateful cooperative Task whose step(unit_index)
performs real I/O, data validation, filtering, statistical computation, state
publication, consistent snapshotting, and file logging across its exact C_i units.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO


class WorkloadError(RuntimeError):
    """Raised on application/workload errors (invalid data, insufficient samples, etc.)."""


class StateConsistencyError(WorkloadError):
    """Raised when S detects a torn/inconsistent read of SharedState (A7/S interleaving)."""


@dataclass(frozen=True)
class ApplicationConfig:
    application_id: str = "temperature_fixture_v1"
    input_rows: int = 120
    min_valid_samples: int = 12
    moving_average_window: int = 5
    valid_temperature_min: float = -20.0
    valid_temperature_max: float = 80.0
    alert_threshold: float = 30.0
    control_threshold: float = 28.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "input_rows": self.input_rows,
            "min_valid_samples": self.min_valid_samples,
            "moving_average_window": self.moving_average_window,
            "valid_temperature_min": self.valid_temperature_min,
            "valid_temperature_max": self.valid_temperature_max,
            "alert_threshold": self.alert_threshold,
            "control_threshold": self.control_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplicationConfig:
        return cls(
            application_id=str(data["application_id"]),
            input_rows=int(data["input_rows"]),
            min_valid_samples=int(data["min_valid_samples"]),
            moving_average_window=int(data["moving_average_window"]),
            valid_temperature_min=float(data["valid_temperature_min"]),
            valid_temperature_max=float(data["valid_temperature_max"]),
            alert_threshold=float(data["alert_threshold"]),
            control_threshold=float(data["control_threshold"]),
        )


def load_application_config(path: str | Path) -> ApplicationConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ApplicationConfig.from_dict(data)


def default_application_config() -> ApplicationConfig:
    return ApplicationConfig()


def compute_file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_temperature_fixture(path: str | Path, rows: int = 120) -> str:
    """Generate the deterministic temperature_fixture_v1 CSV and return its SHA-256."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["instante,temperatura"]
    for i in range(rows):
        temp = 24.0 + i / 10.0
        lines.append(f"{i},{temp:.1f}")
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return compute_file_sha256(file_path)


def _partition_bounds(total: int, parts: int) -> list[tuple[int, int]]:
    """Split range(total) into `parts` contiguous balanced slices."""
    base, rem = divmod(total, parts)
    bounds: list[tuple[int, int]] = []
    start = 0
    for idx in range(parts):
        size = base + (1 if idx < rem else 0)
        bounds.append((start, start + size))
        start += size
    return bounds


@dataclass(frozen=True)
class UnitResult:
    segment_id: str
    unit_index: int
    done: bool
    state_version: int
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SharedState:
    """Shared state E = (versão, instante, indicadores, alerta, comando).

    Initialized as E0 (version 0, no processed block, alert='sem_dados', command='desligado').
    `update_started_version` acts as a seqlock guard so any torn read caused by an
    invalid interleaving between A7 and S is deterministically detected.
    """

    version: int = 0
    update_started_version: int = 0
    block_id: str | None = None
    instante: int | None = None
    indicators: dict[str, float] | None = None
    alert: str = "sem_dados"
    alert_active: bool = False
    command: str = "desligado"
    ventilation_on: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "block_id": self.block_id,
            "instante": self.instante,
            "indicators": copy.deepcopy(self.indicators),
            "alert": self.alert,
            "alert_active": self.alert_active,
            "command": self.command,
            "ventilation_on": self.ventilation_on,
        }


@dataclass
class ApplicationContext:
    """Isolated runtime context created fresh for every single schedule execution."""

    config: ApplicationConfig
    input_path: Path
    output_path: Path
    block_id: str = "block_1"
    shared_state: SharedState = field(default_factory=SharedState)

    # Inter-segment pipeline buffers (within P1 -> P2 and P3)
    raw_rows: list[tuple[str, str]] | None = None
    valid_samples: list[tuple[int, float]] | None = None
    rejected_count: int = 0
    filtered_samples: list[tuple[int, float]] | None = None
    indicators: dict[str, float] | None = None
    local_alert: str | None = None
    local_alert_active: bool | None = None
    local_command: str | None = None
    local_ventilation_on: bool | None = None

    # Private copy produced by S and exclusively consumed by A8
    private_copy: dict[str, Any] | None = None
    written_record: dict[str, Any] | None = None

    # Completion flags for auditability
    completed_segments: set[str] = field(default_factory=set)


class Task:
    """Base class for a cooperative segment task with C_i discrete units."""

    segment_id: str
    expected_units: int

    def __init__(self, context: ApplicationContext) -> None:
        self.context = context
        self._next_expected_unit = 1
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    def step(self, unit_index: int) -> UnitResult:
        if self._done:
            raise WorkloadError(
                f"Segment {self.segment_id} already completed; unexpected unit {unit_index}."
            )
        if unit_index != self._next_expected_unit:
            raise WorkloadError(
                f"Segment {self.segment_id} expected unit {self._next_expected_unit}, got {unit_index}."
            )
        if unit_index < 1 or unit_index > self.expected_units:
            raise WorkloadError(
                f"Segment {self.segment_id} unit_index {unit_index} out of range 1..{self.expected_units}."
            )
        details = self._execute_unit(unit_index)
        self._next_expected_unit += 1
        if unit_index == self.expected_units:
            self._done = True
            self.context.completed_segments.add(self.segment_id)
        return UnitResult(
            segment_id=self.segment_id,
            unit_index=unit_index,
            done=self._done,
            state_version=self.context.shared_state.version,
            details=details,
        )

    def _execute_unit(self, unit_index: int) -> dict[str, Any]:
        raise NotImplementedError

    def cleanup(self) -> None:
        """Release any open handles in case execution aborts mid-segment."""


class A1Task(Task):
    """A1 (2 units): Open CSV, verify header, read 60 + 60 rows, close file."""

    segment_id = "A1"
    expected_units = 2

    def __init__(self, context: ApplicationContext) -> None:
        super().__init__(context)
        self._fh: TextIO | None = None
        self._reader: Any = None
        self._rows: list[tuple[str, str]] = []

    def _execute_unit(self, unit_index: int) -> dict[str, Any]:
        half = self.context.config.input_rows // 2
        if unit_index == 1:
            if not self.context.input_path.exists():
                raise WorkloadError(f"Input CSV not found: {self.context.input_path}")
            self._fh = self.context.input_path.open("r", encoding="utf-8", newline="")
            self._reader = csv.reader(self._fh)
            try:
                header = next(self._reader)
            except StopIteration as exc:
                self.cleanup()
                raise WorkloadError("Input CSV is empty (missing header).") from exc
            if [col.strip() for col in header] != ["instante", "temperatura"]:
                self.cleanup()
                raise WorkloadError(
                    f"Unexpected CSV header {header!r}; expected ['instante', 'temperatura']."
                )
            read_now = 0
            for _ in range(half):
                try:
                    row = next(self._reader)
                except StopIteration:
                    break
                if len(row) != 2:
                    self.cleanup()
                    raise WorkloadError(f"Malformed CSV row (expected 2 columns): {row!r}")
                self._rows.append((row[0], row[1]))
                read_now += 1
            return {"rows_read": read_now}

        # Unit 2: read remaining rows and close file before returning
        assert self._reader is not None and self._fh is not None
        read_now = 0
        try:
            for row in self._reader:
                if len(row) != 2:
                    raise WorkloadError(f"Malformed CSV row (expected 2 columns): {row!r}")
                self._rows.append((row[0], row[1]))
                read_now += 1
        finally:
            self.cleanup()

        if len(self._rows) != self.context.config.input_rows:
            raise WorkloadError(
                f"Expected {self.context.config.input_rows} CSV rows, got {len(self._rows)}."
            )
        self.context.raw_rows = self._rows
        return {"rows_read": read_now, "total_rows": len(self._rows)}

    def cleanup(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None
                self._reader = None


class A2Task(Task):
    """A2 (1 unit): Convert and validate samples, enforce inclusive range and minimum count."""

    segment_id = "A2"
    expected_units = 1

    def _execute_unit(self, unit_index: int) -> dict[str, Any]:
        if self.context.raw_rows is None:
            raise WorkloadError("A2 requires raw_rows produced by A1.")
        cfg = self.context.config
        valid: list[tuple[int, float]] = []
        rejected = 0
        for raw_inst, raw_temp in self.context.raw_rows:
            try:
                inst = int(raw_inst.strip())
                temp = float(raw_temp.strip())
            except ValueError:
                rejected += 1
                continue
            if not math.isfinite(temp):
                rejected += 1
                continue
            if temp < cfg.valid_temperature_min or temp > cfg.valid_temperature_max:
                rejected += 1
                continue
            valid.append((inst, temp))

        self.context.valid_samples = valid
        self.context.rejected_count = rejected
        if len(valid) < cfg.min_valid_samples:
            raise WorkloadError(
                f"Insufficient valid samples: got {len(valid)}, minimum required is {cfg.min_valid_samples}."
            )
        return {"valid_count": len(valid), "rejected_count": rejected}


class A3Task(Task):
    """A3 (3 units): Moving average filter across 3 balanced partitions preserving window."""

    segment_id = "A3"
    expected_units = 3

    def __init__(self, context: ApplicationContext) -> None:
        super().__init__(context)
        self._window: deque[float] = deque(maxlen=context.config.moving_average_window)
        self._window_sum: float = 0.0
        self._filtered: list[tuple[int, float]] = []
        self._bounds: list[tuple[int, int]] | None = None

    def _execute_unit(self, unit_index: int) -> dict[str, Any]:
        if self.context.valid_samples is None:
            raise WorkloadError("A3 requires valid_samples produced by A2.")
        if self._bounds is None:
            self._bounds = _partition_bounds(len(self.context.valid_samples), self.expected_units)

        start, end = self._bounds[unit_index - 1]
        for inst, temp in self.context.valid_samples[start:end]:
            if len(self._window) == self._window.maxlen:
                self._window_sum -= self._window[0]
            self._window.append(temp)
            self._window_sum += temp
            avg = self._window_sum / len(self._window)
            self._filtered.append((inst, avg))

        if unit_index == self.expected_units:
            self.context.filtered_samples = self._filtered

        return {"partition": [start, end], "processed": end - start}


class A4Task(Task):
    """A4 (4 units): Compute min, max, mean, and population variance in 4 resumable partitions."""

    segment_id = "A4"
    expected_units = 4

    def __init__(self, context: ApplicationContext) -> None:
        super().__init__(context)
        self._bounds: list[tuple[int, int]] | None = None
        # Each partial: (count, sum_x, sum_x2, mean, m2, min_val, max_val)
        self._partials: list[tuple[int, float, float, float, float, float, float]] = []

    def _execute_unit(self, unit_index: int) -> dict[str, Any]:
        if self.context.filtered_samples is None:
            raise WorkloadError("A4 requires filtered_samples produced by A3.")
        if self._bounds is None:
            self._bounds = _partition_bounds(
                len(self.context.filtered_samples), self.expected_units
            )

        start, end = self._bounds[unit_index - 1]
        values = [temp for _, temp in self.context.filtered_samples[start:end]]
        count = len(values)
        if count > 0:
            sum_x = math.fsum(values)
            sum_x2 = math.fsum(v * v for v in values)
            mean = sum_x / count
            m2 = math.fsum((v - mean) ** 2 for v in values)
            min_v = min(values)
            max_v = max(values)
            self._partials.append((count, sum_x, sum_x2, mean, m2, min_v, max_v))

        details: dict[str, Any] = {"partition": [start, end], "count": count}
        if unit_index == self.expected_units:
            # Combine partials using Chan's parallel variance algorithm for numerical stability
            if not self._partials:
                raise WorkloadError("A4 received zero filtered samples.")
            tot_n, _, _, comb_mean, comb_m2, comb_min, comb_max = self._partials[0]
            for n_b, _, _, mean_b, m2_b, min_b, max_b in self._partials[1:]:
                delta = mean_b - comb_mean
                new_n = tot_n + n_b
                comb_mean = comb_mean + delta * (n_b / new_n)
                comb_m2 = comb_m2 + m2_b + (delta * delta) * (tot_n * n_b / new_n)
                tot_n = new_n
                if min_b < comb_min:
                    comb_min = min_b
                if max_b > comb_max:
                    comb_max = max_b

            pop_variance = max(0.0, comb_m2 / tot_n)
            self.context.indicators = {
                "count": float(tot_n),
                "min": comb_min,
                "max": comb_max,
                "mean": comb_mean,
                "variance": pop_variance,
            }
            details["indicators"] = copy.deepcopy(self.context.indicators)

        return details


class A5Task(Task):
    """A5 (1 unit): Classify alert based on max filtered temperature >= alert_threshold."""

    segment_id = "A5"
    expected_units = 1

    def _execute_unit(self, unit_index: int) -> dict[str, Any]:
        if self.context.indicators is None:
            raise WorkloadError("A5 requires indicators produced by A4.")
        active = self.context.indicators["max"] >= self.context.config.alert_threshold
        label = "alerta_ativo" if active else "normal"
        self.context.local_alert_active = active
        self.context.local_alert = label
        return {"alert_active": active, "alert": label}


class A6Task(Task):
    """A6 (1 unit): Compute virtual ventilation command based on mean >= control_threshold."""

    segment_id = "A6"
    expected_units = 1

    def _execute_unit(self, unit_index: int) -> dict[str, Any]:
        if self.context.indicators is None:
            raise WorkloadError("A6 requires indicators produced by A4.")
        on = self.context.indicators["mean"] >= self.context.config.control_threshold
        cmd = "ligado" if on else "desligado"
        self.context.local_ventilation_on = on
        self.context.local_command = cmd
        return {"ventilation_on": on, "command": cmd}


class A7Task(Task):
    """A7 (2 units): Publish indicators/alert in unit 1 and command/metadata/version in unit 2."""

    segment_id = "A7"
    expected_units = 2

    def _execute_unit(self, unit_index: int) -> dict[str, Any]:
        if (
            self.context.indicators is None
            or self.context.local_alert is None
            or self.context.local_alert_active is None
            or self.context.local_command is None
            or self.context.local_ventilation_on is None
            or self.context.filtered_samples is None
        ):
            raise WorkloadError("A7 requires outputs from A4, A5, and A6.")

        st = self.context.shared_state
        if unit_index == 1:
            st.update_started_version = st.version + 1
            st.indicators = copy.deepcopy(self.context.indicators)
            st.alert = self.context.local_alert
            st.alert_active = self.context.local_alert_active
            return {"phase": "indicators_and_alert_written", "target_version": st.update_started_version}

        # Unit 2: finalize publication
        st.command = self.context.local_command
        st.ventilation_on = self.context.local_ventilation_on
        st.block_id = self.context.block_id
        st.instante = self.context.filtered_samples[-1][0]
        st.version = st.update_started_version
        return {"phase": "published", "published_version": st.version}


class STask(Task):
    """S (2 units): Copy shared state into a private snapshot and verify version consistency."""

    segment_id = "S"
    expected_units = 2

    def __init__(self, context: ApplicationContext) -> None:
        super().__init__(context)
        self._v1: int = -1
        self._u1: int = -1
        self._partial: dict[str, Any] = {}

    def _execute_unit(self, unit_index: int) -> dict[str, Any]:
        st = self.context.shared_state
        if unit_index == 1:
            self._v1 = st.version
            self._u1 = st.update_started_version
            self._partial = {
                "indicators": copy.deepcopy(st.indicators),
                "alert": st.alert,
                "alert_active": st.alert_active,
            }
            return {"phase": "first_half_copied", "version_start": self._v1}

        v2 = st.version
        u2 = st.update_started_version
        if not (self._v1 == v2 == self._u1 == u2):
            raise StateConsistencyError(
                "Inconsistent shared state observed during S copy: "
                f"(v1={self._v1}, u1={self._u1}, v2={v2}, u2={u2}). "
                "Indicates concurrent interleaving between A7 and S."
            )

        self._partial["version"] = v2
        self._partial["block_id"] = st.block_id
        self._partial["instante"] = st.instante
        self._partial["command"] = st.command
        self._partial["ventilation_on"] = st.ventilation_on
        self.context.private_copy = self._partial
        return {"phase": "copy_verified", "copied_version": v2}


class A8Task(Task):
    """A8 (3 units): Format/open, write, and flush/close output record using ONLY S's copy."""

    segment_id = "A8"
    expected_units = 3

    def __init__(self, context: ApplicationContext) -> None:
        super().__init__(context)
        self._fh: TextIO | None = None
        self._payload_text: str | None = None
        self._record: dict[str, Any] | None = None

    def _execute_unit(self, unit_index: int) -> dict[str, Any]:
        if unit_index == 1:
            if self.context.private_copy is None:
                raise WorkloadError("A8 requires private_copy produced by S.")
            self._record = {
                "application_id": self.context.config.application_id,
                "recorded_state": copy.deepcopy(self.context.private_copy),
            }
            self._payload_text = (
                json.dumps(self._record, indent=2, ensure_ascii=False) + "\n"
            )
            self.context.output_path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.context.output_path.open("w", encoding="utf-8")
            return {"phase": "formatted_and_opened", "bytes": len(self._payload_text.encode("utf-8"))}

        if unit_index == 2:
            assert self._fh is not None and self._payload_text is not None
            written = self._fh.write(self._payload_text)
            return {"phase": "written", "chars_written": written}

        # Unit 3: flush and close before completing the segment
        assert self._fh is not None
        try:
            self._fh.flush()
        finally:
            self.cleanup()
        self.context.written_record = self._record
        return {"phase": "flushed_and_closed", "output_path": str(self.context.output_path)}

    def cleanup(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None


@dataclass
class TaskRegistry:
    tasks: dict[str, Task]
    context: ApplicationContext

    def get(self, segment_id: str) -> Task:
        if segment_id not in self.tasks:
            raise WorkloadError(f"No task registered for segment {segment_id!r}.")
        return self.tasks[segment_id]

    def cleanup(self) -> None:
        for task in self.tasks.values():
            task.cleanup()


def build_tasks(
    application_config: ApplicationConfig,
    input_path: str | Path,
    output_path: str | Path,
    *,
    block_id: str = "block_1",
) -> TaskRegistry:
    """Create a fresh TaskRegistry and ApplicationContext without running any I/O."""
    ctx = ApplicationContext(
        config=application_config,
        input_path=Path(input_path),
        output_path=Path(output_path),
        block_id=block_id,
    )
    task_list: list[Task] = [
        A1Task(ctx),
        A2Task(ctx),
        A3Task(ctx),
        A4Task(ctx),
        A5Task(ctx),
        A6Task(ctx),
        A7Task(ctx),
        STask(ctx),
        A8Task(ctx),
    ]
    return TaskRegistry(tasks={t.segment_id: t for t in task_list}, context=ctx)


def run_sequential_reference(
    application_config: ApplicationConfig,
    input_path: str | Path,
) -> dict[str, Any]:
    """Simple single-pass sequential reference implementation of P1 + P2 for testing."""
    path = Path(input_path)
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        if [c.strip() for c in header] != ["instante", "temperatura"]:
            raise WorkloadError(f"Unexpected header: {header!r}")
        rows = list(reader)

    if len(rows) != application_config.input_rows:
        raise WorkloadError(
            f"Expected {application_config.input_rows} rows, got {len(rows)}."
        )

    valid: list[tuple[int, float]] = []
    rejected = 0
    for r_inst, r_temp in rows:
        try:
            inst = int(r_inst.strip())
            temp = float(r_temp.strip())
        except ValueError:
            rejected += 1
            continue
        if (
            not math.isfinite(temp)
            or temp < application_config.valid_temperature_min
            or temp > application_config.valid_temperature_max
        ):
            rejected += 1
            continue
        valid.append((inst, temp))

    if len(valid) < application_config.min_valid_samples:
        raise WorkloadError("Insufficient valid samples.")

    w = application_config.moving_average_window
    filtered: list[tuple[int, float]] = []
    for idx, (inst, _) in enumerate(valid):
        lo = max(0, idx - w + 1)
        window_vals = [t for _, t in valid[lo : idx + 1]]
        filtered.append((inst, math.fsum(window_vals) / len(window_vals)))

    vals = [t for _, t in filtered]
    n = len(vals)
    mean = math.fsum(vals) / n
    variance = math.fsum((v - mean) ** 2 for v in vals) / n
    min_v = min(vals)
    max_v = max(vals)

    alert_active = max_v >= application_config.alert_threshold
    ventilation_on = mean >= application_config.control_threshold
    return {
        "valid_count": len(valid),
        "rejected_count": rejected,
        "filtered_samples": filtered,
        "indicators": {
            "count": float(n),
            "min": min_v,
            "max": max_v,
            "mean": mean,
            "variance": variance,
        },
        "alert_active": alert_active,
        "alert": "alerta_ativo" if alert_active else "normal",
        "ventilation_on": ventilation_on,
        "command": "ligado" if ventilation_on else "desligado",
        "last_instante": filtered[-1][0],
    }
