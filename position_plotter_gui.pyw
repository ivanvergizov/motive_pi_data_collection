# %%

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from functools import partial
from typing import Literal, TypeVar, TypedDict

from dependency_check import ensure_dependencies_or_exit

ensure_dependencies_or_exit()

import numpy as np

from OpenGL import GL

import pyqtgraph as pg
import pyqtgraph.opengl as gl
from pyqtgraph.opengl.GLGraphicsItem import GLGraphicsItem
from pyqtgraph.opengl.items.GLTextItem import GLTextItem
from pyqtgraph.graphicsItems.AxisItem import AxisItem
from pyqtgraph.graphicsItems.PlotItem.PlotItem import PlotItem
from pyqtgraph.graphicsItems.ViewBox.ViewBox import ViewBox
from pyqtgraph.graphicsItems.PlotDataItem import PlotDataItem

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QSurfaceFormat,
    QVector3D
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGraphicsGridLayout,
    QGraphicsScene,
    QGraphicsView,
    QGraphicsWidget,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget
)

from motive_io import (
    RigidBodyData,
    TrackingSession,
    load_motive_rigid_body_csv
)

from rigid_body_gl import (
    create_body_vertices,
    make_body_mesh_item,
    transform_body_vertices,
    update_body_mesh_item,
)
from rigid_body_math import (
    motive_positions_to_display,
    quaternion_xyzw_to_xyz_degrees
)
from signal_processing import smooth_tracking_positions_and_rotations

T = TypeVar("T")


def require_not_none(
        value: T | None,
        error_message: str) -> T:

    if value is None:
        raise RuntimeError(error_message)

    return value

SignalDataType = Literal[
    "position",
    "euler",
    "quaternion"
]

class SignalDefinition(TypedDict):
    data_type: SignalDataType
    index: int

@dataclass(frozen=True)
class PlotSignalSelection:
    body_name: str
    signal_label: str

class BodyDisplaySettings(TypedDict):
    shape: str
    length: float
    width: float
    height: float
    color: str

SIGNAL_DEFINITIONS: dict[str, SignalDefinition] = {
    "Position X": {
        "data_type": "position",
        "index": 0
    },
    "Position Y": {
        "data_type": "position",
        "index": 1
    },
    "Position Z": {
        "data_type": "position",
        "index": 2
    },
    "Euler X": {
        "data_type": "euler",
        "index": 0
    },
    "Euler Y": {
        "data_type": "euler",
        "index": 1
    },
    "Euler Z": {
        "data_type": "euler",
        "index": 2
    },
    "Quaternion X": {
        "data_type": "quaternion",
        "index": 0
    },
    "Quaternion Y": {
        "data_type": "quaternion",
        "index": 1
    },
    "Quaternion Z": {
        "data_type": "quaternion",
        "index": 2
    },
    "Quaternion W": {
        "data_type": "quaternion",
        "index": 3
    },
}

PLOT_COLORS = [
    "#e31212",
    "#fa7704",
    "#f7f308",
    "#2bdc0b",
    "#15dbfa",
    "#fe21f3",
    "#be018c",
    "#942f2f",
    "#934907",
    "#9d9c2f",
    "#437c39",
    "#2c808d",
    "#81217c",
    "#80002f",
    "#890346"
]

DEFAULT_PLAYBACK_MSAA_SAMPLES = 4

PLAYBACK_RESOLUTION_OPTIONS = [
    "Current widget size",
    "1280 x 720",
    "1920 x 1080",
    "2560 x 1440",
    "3840 x 2160"
]

MSAA_OPTIONS = [
    "Off",
    "2x",
    "4x",
    "8x",
    "16x"
]

SSAA_OPTIONS = [
    "1x",
    "2x",
    "3x",
    "4x"
]

def color_for_curve(curve_index: int) -> str:
    return PLOT_COLORS[curve_index % len(PLOT_COLORS)]

def configure_default_opengl_format(msaa_samples: int) -> None:
    surface_format = QSurfaceFormat()
    surface_format.setSamples(msaa_samples)
    QSurfaceFormat.setDefaultFormat(surface_format)


def parse_resolution_option(
        resolution_text: str
) -> tuple[int, int] | None:

    if resolution_text == "Current widget size":
        return None

    width_text, height_text = (
        part.strip()
        for part in resolution_text.lower().split(
            "x",
            maxsplit=1
        )
    )

    return int(width_text), int(height_text)


def create_gl_view_widget(
        msaa_samples: int
) -> gl.GLViewWidget:

    surface_format = QSurfaceFormat.defaultFormat()
    surface_format.setSamples(msaa_samples)

    view_widget = gl.GLViewWidget()
    view_widget.setFormat(surface_format)
    view_widget.setBackgroundColor(
        QColor(255, 255, 255, 255)
    )
    view_widget.setStyleSheet(
        "background-color: white;"
    )
    view_widget.setCameraPosition(
        distance=2.0,
        elevation=25.0,
        azimuth=45.0
    )

    return view_widget



@dataclass(frozen=True)
class RoomBounds:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float
    x_tick: float
    y_tick: float
    z_tick: float

    def center_vector(self) -> QVector3D:
        return QVector3D(
            float((self.x_min + self.x_max) / 2.0),
            float((self.y_min + self.y_max) / 2.0),
            float((self.z_min + self.z_max) / 2.0)
        )

    def spans(self) -> tuple[float, float, float]:
        return (
            float(self.x_max - self.x_min),
            float(self.y_max - self.y_min),
            float(self.z_max - self.z_min)
        )


def nice_tick_spacing(
        span: float,
        target_tick_count: int = 8
) -> float:
    safe_span = max(float(span), 1.0e-9)
    raw_spacing = safe_span / max(target_tick_count, 1)
    exponent = math.floor(math.log10(raw_spacing))
    magnitude = 10.0 ** exponent
    normalized = raw_spacing / magnitude

    if normalized <= 1.0:
        multiplier = 1.0
    elif normalized <= 2.0:
        multiplier = 2.0
    elif normalized <= 5.0:
        multiplier = 5.0
    else:
        multiplier = 10.0

    return float(multiplier * magnitude)


def calculate_room_axis_bounds(
        values: np.ndarray,
        minimum_padding: float
) -> tuple[float, float, float]:
    finite_values = np.asarray(values, dtype=float)
    finite_values = finite_values[np.isfinite(finite_values)]

    if finite_values.size == 0:
        return -1.0, 1.0, 0.25

    data_minimum = float(np.min(finite_values))
    data_maximum = float(np.max(finite_values))
    data_span = data_maximum - data_minimum

    if data_span <= 1.0e-9:
        half_span = max(
            abs(data_minimum) * 0.1,
            minimum_padding,
            0.25
        )
        data_minimum -= half_span
        data_maximum += half_span
        data_span = data_maximum - data_minimum

    padding = max(
        minimum_padding,
        data_span * 0.08,
        0.05
    )

    padded_span = data_span + 2.0 * padding
    tick_spacing = nice_tick_spacing(padded_span)

    axis_minimum = (
        math.floor(
            (data_minimum - padding) / tick_spacing
        )
        * tick_spacing
    )

    axis_maximum = (
        math.ceil(
            (data_maximum + padding) / tick_spacing
        )
        * tick_spacing
    )

    if axis_maximum <= axis_minimum:
        axis_maximum = axis_minimum + tick_spacing

    return (
        float(axis_minimum),
        float(axis_maximum),
        float(tick_spacing)
    )


def calculate_room_bounds(
        positions_by_body: dict[str, np.ndarray],
        minimum_padding: float
) -> RoomBounds:
    valid_positions: list[np.ndarray] = []

    for positions in positions_by_body.values():
        position_array = np.asarray(
            positions,
            dtype=float
        )

        if (
            position_array.ndim == 2
            and position_array.shape[1] == 3
            and position_array.size > 0
        ):
            valid_positions.append(position_array)

    if not valid_positions:
        return RoomBounds(
            x_min=-1.0,
            x_max=1.0,
            y_min=-1.0,
            y_max=1.0,
            z_min=-1.0,
            z_max=1.0,
            x_tick=0.25,
            y_tick=0.25,
            z_tick=0.25
        )

    combined_positions = np.vstack(valid_positions)

    x_min, x_max, x_tick = calculate_room_axis_bounds(
        combined_positions[:, 0],
        minimum_padding
    )

    y_min, y_max, y_tick = calculate_room_axis_bounds(
        combined_positions[:, 1],
        minimum_padding
    )

    z_min, z_max, z_tick = calculate_room_axis_bounds(
        combined_positions[:, 2],
        minimum_padding
    )

    return RoomBounds(
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        z_min=z_min,
        z_max=z_max,
        x_tick=x_tick,
        y_tick=y_tick,
        z_tick=z_tick
    )


def axis_tick_values(
        axis_minimum: float,
        axis_maximum: float,
        tick_spacing: float
) -> np.ndarray:
    tick_count = max(
        1,
        int(
            round(
                (axis_maximum - axis_minimum)
                / tick_spacing
            )
        )
    )

    return axis_minimum + (
        np.arange(tick_count + 1, dtype=float)
        * tick_spacing
    )


def format_axis_tick(
        value: float,
        tick_spacing: float
) -> str:
    if abs(value) < tick_spacing * 1.0e-8:
        value = 0.0

    exponent = math.floor(
        math.log10(max(abs(tick_spacing), 1.0e-12))
    )

    decimal_places = max(0, -exponent)
    return f"{value:.{decimal_places}f}"


def create_text_font(
        point_size: int,
        bold: bool = False
) -> QFont:
    font = QFont("Helvetica", point_size)
    font.setBold(bold)
    return font


def create_default_3d_grid() -> gl.GLGridItem:
    grid = gl.GLGridItem()
    grid.setSize(x=2.0, y=2.0)
    grid.setSpacing(x=0.1, y=0.1)
    grid.setColor((0, 0, 0, 150))
    return grid


def center_scroll_area_on_widget(
        scroll_area: QScrollArea
) -> None:
    horizontal_bar = scroll_area.horizontalScrollBar()
    vertical_bar = scroll_area.verticalScrollBar()

    horizontal_bar.setValue(
        (
            horizontal_bar.minimum()
            + horizontal_bar.maximum()
        ) // 2
    )

    vertical_bar.setValue(
        (
            vertical_bar.minimum()
            + vertical_bar.maximum()
        ) // 2
    )


def read_gl_framebuffer_samples(
        view_widget: gl.GLViewWidget
) -> int | None:
    if not view_widget.isValid():
        return None

    view_widget.makeCurrent()

    try:
        sample_value = GL.glGetIntegerv(
            GL.GL_SAMPLES
        )

        sample_array = np.asarray(
            sample_value
        ).reshape(-1)

        if sample_array.size == 0:
            return None

        samples = int(sample_array[0])

        if samples <= 1:
            return 0

        return samples

    finally:
        view_widget.doneCurrent()


class SignalPlotTab(QWidget):

    def __init__(self) -> None:
        super().__init__()

        self.session: TrackingSession | None = None
        self.source_file_path: str | None = None
        self.signal_selections: list[
            PlotSignalSelection
        ] = []

        self.updating_signal_tree = False

        self.smoothed_positions_by_body: dict[
            str,
            np.ndarray
        ] = {}

        self.smoothed_quaternions_by_body: dict[
            str,
            np.ndarray
        ] = {}

        self.smoothed_euler_by_body: dict[
            str,
            np.ndarray
        ] = {}

        self.plot_widget = pg.PlotWidget()

        self.plot_item: PlotItem = require_not_none(
            self.plot_widget.getPlotItem(),
            "The PlotWidget did not create a PlotItem."
        )

        self.viewboxes_by_data_type: dict[
            SignalDataType,
            ViewBox
        ] = {}

        self.axes_by_data_type: dict[
            SignalDataType,
            AxisItem
        ] = {}

        self.curves_by_data_type: dict[
            SignalDataType,
            list[PlotDataItem]
        ] = {
            "position": [],
            "euler": [],
            "quaternion": []
        }

        self.base_y_ranges_by_data_type: dict[
            SignalDataType,
            tuple[float, float] | None
        ] = {
            "position": None,
            "euler": None,
            "quaternion": None
        }

        self.legend = self.plot_item.addLegend()

        self.load_button = QPushButton(
            "Load Motive CSV"
        )

        self.update_plot_button = QPushButton(
            "Update plot"
        )
        self.update_plot_button.setEnabled(False)

        self.status_label = QLabel(
            "No CSV loaded."
        )

        self.signal_tree = QTreeWidget()

        self.smoothing_checkbox = QCheckBox(
            "Apply smoothing"
        )

        self.smoothing_seconds_spinbox = (
            QDoubleSpinBox()
        )

        self.raw_values_checkbox = QCheckBox(
            "Plot values before interpolation"
        )

        self.axis_scale_spinboxes: dict[
            SignalDataType,
            QDoubleSpinBox
        ] = {}

        self._build_layout()

    def _build_layout(self) -> None:
        self._configure_plot()

        settings_container = QWidget()

        settings_layout = QVBoxLayout(
            settings_container
        )

        settings_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop
        )

        settings_layout.addWidget(
            self._create_data_source_group()
        )

        settings_layout.addWidget(
            self._create_signal_selection_group()
        )

        self.update_plot_button.clicked.connect(
            self.force_update_plot
        )

        settings_layout.addWidget(
            self.update_plot_button
        )

        settings_layout.addWidget(
            self._create_smoothing_group()
        )

        settings_layout.addWidget(
            self._create_plot_options_group()
        )

        settings_layout.addWidget(
            self._create_axis_scale_group()
        )

        settings_layout.addStretch()

        settings_scroll_area = QScrollArea()
        settings_scroll_area.setWidgetResizable(True)
        settings_scroll_area.setMinimumWidth(340)

        settings_scroll_area.setWidget(
            settings_container
        )

        layout = QHBoxLayout(self)

        layout.addWidget(
            settings_scroll_area
        )

        layout.addWidget(
            self.plot_widget,
            stretch=1
        )

    def _configure_plot(self) -> None:
        self.plot_widget.setBackground("w")

        self.plot_item.showGrid(
            x=True,
            y=True
        )

        self.plot_item.setLabel(
            "bottom",
            "Time",
            units="s"
        )

        self._create_plot_axes()

    def _create_data_source_group(
            self) -> QGroupBox:

        group = QGroupBox(
            "Data source"
        )

        layout = QVBoxLayout(group)

        self.load_button.clicked.connect(
            self.load_csv
        )

        self.status_label.setWordWrap(True)

        layout.addWidget(
            self.load_button
        )

        layout.addWidget(
            self.status_label
        )

        return group

    def _create_signal_selection_group(
            self) -> QGroupBox:

        group = QGroupBox(
            "Bodies and signals"
        )

        layout = QVBoxLayout(group)

        self.signal_tree.setHeaderLabels(
            ["Rigid body and signal"]
        )

        self.signal_tree.setRootIsDecorated(True)
        self.signal_tree.setAlternatingRowColors(True)
        self.signal_tree.setEnabled(False)
        self.signal_tree.setMinimumHeight(280)

        self.signal_tree.itemChanged.connect(
            self.handle_signal_tree_changed
        )

        layout.addWidget(
            self.signal_tree
        )

        return group

    def _create_smoothing_group(
            self) -> QGroupBox:

        group = QGroupBox(
            "Plot smoothing"
        )

        layout = QVBoxLayout(group)

        self.smoothing_checkbox.setEnabled(False)

        self.smoothing_checkbox.stateChanged.connect(
            self.handle_smoothing_settings_changed
        )

        self.smoothing_seconds_spinbox.setMinimum(
            0.00
        )

        self.smoothing_seconds_spinbox.setMaximum(
            5.00
        )

        self.smoothing_seconds_spinbox.setSingleStep(
            0.05
        )

        self.smoothing_seconds_spinbox.setDecimals(
            2
        )

        self.smoothing_seconds_spinbox.setValue(
            0.25
        )

        self.smoothing_seconds_spinbox.setPrefix(
            "Window: "
        )

        self.smoothing_seconds_spinbox.setSuffix(
            " s"
        )

        self.smoothing_seconds_spinbox.setEnabled(
            False
        )

        self.smoothing_seconds_spinbox.valueChanged.connect(
            self.handle_smoothing_settings_changed
        )

        layout.addWidget(
            self.smoothing_checkbox
        )

        layout.addWidget(
            self.smoothing_seconds_spinbox
        )

        return group

    def _create_plot_options_group(
            self) -> QGroupBox:

        group = QGroupBox(
            "Plot options"
        )

        layout = QVBoxLayout(group)

        self.raw_values_checkbox.setChecked(False)
        self.raw_values_checkbox.setEnabled(False)
        self.raw_values_checkbox.setToolTip(
            "Displays the original samples with gaps "
            "where Motive data was missing. Raw mode "
            "takes precedence over smoothing."
        )

        self.raw_values_checkbox.stateChanged.connect(
            self.handle_raw_values_changed
        )

        layout.addWidget(
            self.raw_values_checkbox
        )

        return group

    def _create_axis_scale_group(
            self) -> QGroupBox:

        group = QGroupBox(
            "Vertical scaling"
        )

        layout = QVBoxLayout(group)

        axis_scale_controls: tuple[
            tuple[str, SignalDataType],
            ...
        ] = (
            ("Position scale", "position"),
            ("Euler scale", "euler"),
            ("Quaternion scale", "quaternion")
        )

        for axis_label, data_type in (
                axis_scale_controls):

            row_layout = QHBoxLayout()

            scale_spinbox = QDoubleSpinBox()
            scale_spinbox.setMinimum(0.10)
            scale_spinbox.setMaximum(100.00)
            scale_spinbox.setSingleStep(0.10)
            scale_spinbox.setDecimals(2)
            scale_spinbox.setValue(1.00)
            scale_spinbox.setSuffix("x")
            scale_spinbox.setKeyboardTracking(False)
            scale_spinbox.setEnabled(False)

            scale_spinbox.valueChanged.connect(
                partial(
                    self.set_axis_scale,
                    data_type
                )
            )

            self.axis_scale_spinboxes[data_type] = (
                scale_spinbox
            )

            row_layout.addWidget(
                QLabel(axis_label),
                stretch=1
            )

            row_layout.addWidget(
                scale_spinbox
            )

            layout.addLayout(
                row_layout
            )

        return group

    def _create_plot_axes(self) -> None:
        position_viewbox: ViewBox = (
            self.plot_item.getViewBox()
        )

        plot_scene: QGraphicsScene = require_not_none(
            QGraphicsView.scene(self.plot_widget),
            "The PlotWidget is not attached "
            "to a graphics scene."
        )

        position_axis: AxisItem = (
            self.plot_item.getAxis("left")
        )

        position_axis.setLabel(
            "Position",
            units="m"
        )

        self.plot_item.showAxis("right")

        euler_axis: AxisItem = (
            self.plot_item.getAxis("right")
        )

        euler_axis.setLabel(
            "Euler angle",
            units="deg"
        )

        euler_viewbox = ViewBox()

        plot_scene.addItem(
            euler_viewbox
        )

        euler_axis.linkToView(
            euler_viewbox
        )

        euler_viewbox.setXLink(
            position_viewbox
        )

        quaternion_axis = AxisItem(
            orientation="right"
        )

        quaternion_axis.setLabel(
            "Quaternion"
        )

        plot_layout = QGraphicsWidget.layout(
            self.plot_item
        )

        if not isinstance(
                plot_layout,
                QGraphicsGridLayout
        ):
            raise RuntimeError(
                "The PlotItem does not contain "
                "a QGraphicsGridLayout."
            )

        plot_layout.addItem(
            quaternion_axis,
            2,
            3
        )

        quaternion_viewbox = ViewBox()

        plot_scene.addItem(
            quaternion_viewbox
        )

        quaternion_axis.linkToView(
            quaternion_viewbox
        )

        quaternion_viewbox.setXLink(
            position_viewbox
        )

        self.viewboxes_by_data_type = {
            "position": position_viewbox,
            "euler": euler_viewbox,
            "quaternion": quaternion_viewbox
        }

        self.axes_by_data_type = {
            "position": position_axis,
            "euler": euler_axis,
            "quaternion": quaternion_axis
        }

        position_viewbox.sigResized.connect(
            self.update_linked_viewboxes
        )

        self.update_linked_viewboxes()

    def update_linked_viewboxes(
        self,
        _source_viewbox: ViewBox | None = None
    ) -> None:

        position_viewbox = (
            self.viewboxes_by_data_type["position"]
        )

        plot_geometry = (
            position_viewbox.sceneBoundingRect()
        )

        linked_data_types: tuple[
            SignalDataType,
            ...
        ] = (
            "euler",
            "quaternion"
        )

        for data_type in linked_data_types:
            viewbox = (
                self.viewboxes_by_data_type[data_type]
            )

            viewbox.setGeometry(
                plot_geometry
            )

            viewbox.linkedViewChanged(
                position_viewbox,
                ViewBox.XAxis
            )

    def load_csv(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Motive CSV",
            "",
            "CSV files (*.csv);;All files (*)"
        )

        if not file_path:
            return

        try:
            session = load_motive_rigid_body_csv(
                file_path
            )

        except Exception as exc:
            self.status_label.setText(
                f"Error loading CSV: {exc}"
            )
            return

        self.set_session(
            session,
            source_file_path=file_path
        )

    def set_session(
        self,
        session: TrackingSession,
        source_file_path: str | None = None
    ) -> None:

        self.clear_plot_curves()

        self.session = session
        self.source_file_path = source_file_path
        self.signal_selections.clear()

        self.smoothed_positions_by_body.clear()
        self.smoothed_quaternions_by_body.clear()
        self.smoothed_euler_by_body.clear()

        self.populate_signal_tree()
        self._set_session_x_range()

        self.signal_tree.setEnabled(True)
        self.raw_values_checkbox.setEnabled(True)
        self.update_plot_button.setEnabled(True)

        self._update_smoothing_control_states()

        if (
            self.smoothing_checkbox.isChecked()
            and not self.raw_values_checkbox.isChecked()
        ):
            self.update_smoothed_signal_data()

        self._update_status_label()

    def _set_session_x_range(self) -> None:
        session = self.session

        if (
            session is None
            or len(session.time) == 0
        ):
            return

        start_time = float(
            session.time[0]
        )

        end_time = float(
            session.time[-1]
        )

        if end_time <= start_time:
            end_time = start_time + 1.0

        position_viewbox = (
            self.viewboxes_by_data_type["position"]
        )

        position_viewbox.setXRange(
            start_time,
            end_time,
            padding=0.0
        )

    def _update_status_label(self) -> None:
        session = self.session

        if session is None:
            self.status_label.setText(
                "No CSV loaded."
            )
            return

        if len(session.time) == 0:
            duration_seconds = 0.0

        else:
            duration_seconds = float(
                session.time[-1]
            )

        if self.source_file_path is None:
            source_text = (
                "Session supplied externally"
            )

        else:
            source_text = (
                self.source_file_path
            )

        self.status_label.setText(
            f"{source_text}\n"
            f"{len(session.bodies)} rigid bodies | "
            f"{duration_seconds:.3f} s | "
            f"source rotation: "
            f"{session.source_rotation_encoding}"
        )

    def _update_smoothing_control_states(self) -> None:
        session_loaded = self.session is not None
        raw_mode = self.raw_values_checkbox.isChecked()

        self.smoothing_checkbox.setEnabled(
            session_loaded and not raw_mode
        )

        self.smoothing_seconds_spinbox.setEnabled(
            session_loaded
            and not raw_mode
            and self.smoothing_checkbox.isChecked()
        )

    def update_smoothed_signal_data(self) -> None:
        session = self.session

        if session is None:
            return

        smoothing_seconds = (
            self.smoothing_seconds_spinbox.value()
        )

        self.smoothed_positions_by_body.clear()
        self.smoothed_quaternions_by_body.clear()
        self.smoothed_euler_by_body.clear()

        for body_name, body in (
                session.bodies.items()):

            positions = np.column_stack(
                [
                    body.position_x,
                    body.position_y,
                    body.position_z
                ]
            )

            quaternions = np.column_stack(
                [
                    body.rotation_x,
                    body.rotation_y,
                    body.rotation_z,
                    body.rotation_w
                ]
            )

            (
                smoothed_positions,
                smoothed_quaternions
            ) = smooth_tracking_positions_and_rotations(
                time_s=session.time,
                positions=positions,
                rotations=quaternions,
                smoothing_seconds=smoothing_seconds
            )

            smoothed_euler = (
                quaternion_xyzw_to_xyz_degrees(
                    smoothed_quaternions
                )
            )

            self.smoothed_positions_by_body[
                body_name
            ] = smoothed_positions

            self.smoothed_quaternions_by_body[
                body_name
            ] = smoothed_quaternions

            self.smoothed_euler_by_body[
                body_name
            ] = smoothed_euler

    def handle_smoothing_settings_changed(
        self,
        _value: int | float | None = None
    ) -> None:

        self._update_smoothing_control_states()

        if self.session is None:
            return

        if self.raw_values_checkbox.isChecked():
            return

        if self.smoothing_checkbox.isChecked():
            self.update_smoothed_signal_data()

        else:
            self.smoothed_positions_by_body.clear()
            self.smoothed_quaternions_by_body.clear()
            self.smoothed_euler_by_body.clear()

        self.update_plot()

    def handle_raw_values_changed(
        self,
        _state: int | None = None
    ) -> None:

        self._update_smoothing_control_states()

        if self.session is None:
            return

        if (
            not self.raw_values_checkbox.isChecked()
            and self.smoothing_checkbox.isChecked()
        ):
            self.update_smoothed_signal_data()

        self.update_plot()

    def force_update_plot(self) -> None:
        if self.session is None:
            self.status_label.setText(
                "Load a CSV before updating the plot."
            )
            return

        self.rebuild_signal_selections()

        if (
            self.smoothing_checkbox.isChecked()
            and not self.raw_values_checkbox.isChecked()
        ):
            self.update_smoothed_signal_data()

        self.update_plot()
        self._update_status_label()

    def populate_signal_tree(self) -> None:
        self.updating_signal_tree = True

        try:
            self.signal_tree.clear()

            if self.session is None:
                return

            all_bodies_item = QTreeWidgetItem(
                ["All rigid bodies"]
            )

            self.signal_tree.addTopLevelItem(
                all_bodies_item
            )

            for signal_label in SIGNAL_DEFINITIONS:
                signal_item = QTreeWidgetItem(
                    [signal_label]
                )

                signal_item.setFlags(
                    signal_item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                )

                signal_item.setCheckState(
                    0,
                    Qt.CheckState.Unchecked
                )

                signal_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    ("all", signal_label)
                )

                all_bodies_item.addChild(
                    signal_item
                )

            for body_name in self.session.bodies:
                body_item = QTreeWidgetItem(
                    [body_name]
                )

                self.signal_tree.addTopLevelItem(
                    body_item
                )

                for signal_label in SIGNAL_DEFINITIONS:
                    signal_item = QTreeWidgetItem(
                        [signal_label]
                    )

                    signal_item.setFlags(
                        signal_item.flags()
                        | Qt.ItemFlag.ItemIsUserCheckable
                    )

                    signal_item.setCheckState(
                        0,
                        Qt.CheckState.Unchecked
                    )

                    signal_item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        (body_name, signal_label)
                    )

                    body_item.addChild(
                        signal_item
                    )

            all_bodies_item.setExpanded(True)

        finally:
            self.updating_signal_tree = False

    def handle_signal_tree_changed(
        self,
        item: QTreeWidgetItem,
        column: int
    ) -> None:

        if self.updating_signal_tree:
            return

        if column != 0:
            return

        item_data = item.data(
            0,
            Qt.ItemDataRole.UserRole
        )

        if item_data is None:
            return

        body_name, signal_label = item_data

        self.updating_signal_tree = True

        try:
            if body_name == "all":
                target_state = (
                    item.checkState(0)
                )

                for body_index in range(
                        1,
                        self.signal_tree.topLevelItemCount()
                ):
                    body_item = (
                        self.signal_tree.topLevelItem(
                            body_index
                        )
                    )

                    if body_item is None:
                        continue

                    for signal_index in range(
                            body_item.childCount()
                    ):
                        signal_item = body_item.child(
                            signal_index
                        )

                        if signal_item is None:
                            continue

                        signal_data = signal_item.data(
                            0,
                            Qt.ItemDataRole.UserRole
                        )

                        if signal_data is None:
                            continue

                        (
                            _,
                            child_signal_label
                        ) = signal_data

                        if (
                            child_signal_label
                            == signal_label
                        ):
                            signal_item.setCheckState(
                                0,
                                target_state
                            )
                            break

            else:
                self.update_all_bodies_signal_state(
                    signal_label
                )

        finally:
            self.updating_signal_tree = False

        self.rebuild_signal_selections()
        self.update_plot()

    def update_all_bodies_signal_state(
        self,
        signal_label: str
    ) -> None:

        if (
            self.signal_tree.topLevelItemCount()
            == 0
        ):
            return

        checked_count = 0

        body_count = (
            self.signal_tree.topLevelItemCount()
            - 1
        )

        for body_index in range(
                1,
                self.signal_tree.topLevelItemCount()
        ):
            body_item = (
                self.signal_tree.topLevelItem(
                    body_index
                )
            )

            if body_item is None:
                continue

            for signal_index in range(
                    body_item.childCount()
            ):
                signal_item = body_item.child(
                    signal_index
                )

                if signal_item is None:
                    continue

                signal_data = signal_item.data(
                    0,
                    Qt.ItemDataRole.UserRole
                )

                if signal_data is None:
                    continue

                (
                    _,
                    child_signal_label
                ) = signal_data

                if (
                    child_signal_label
                    != signal_label
                ):
                    continue

                if (
                    signal_item.checkState(0)
                    == Qt.CheckState.Checked
                ):
                    checked_count += 1

                break

        if checked_count == 0:
            aggregate_state = (
                Qt.CheckState.Unchecked
            )

        elif checked_count == body_count:
            aggregate_state = (
                Qt.CheckState.Checked
            )

        else:
            aggregate_state = (
                Qt.CheckState.PartiallyChecked
            )

        all_bodies_item = (
            self.signal_tree.topLevelItem(0)
        )

        if all_bodies_item is None:
            return

        for signal_index in range(
                all_bodies_item.childCount()
        ):
            signal_item = all_bodies_item.child(
                signal_index
            )

            if signal_item is None:
                continue

            signal_data = signal_item.data(
                0,
                Qt.ItemDataRole.UserRole
            )

            if signal_data is None:
                continue

            (
                _,
                child_signal_label
            ) = signal_data

            if (
                child_signal_label
                == signal_label
            ):
                signal_item.setCheckState(
                    0,
                    aggregate_state
                )
                break

    def rebuild_signal_selections(self) -> None:
        selections: list[
            PlotSignalSelection
        ] = []

        for body_index in range(
                1,
                self.signal_tree.topLevelItemCount()
        ):
            body_item = (
                self.signal_tree.topLevelItem(
                    body_index
                )
            )

            if body_item is None:
                continue

            for signal_index in range(
                    body_item.childCount()
            ):
                signal_item = body_item.child(
                    signal_index
                )

                if signal_item is None:
                    continue

                if (
                    signal_item.checkState(0)
                    != Qt.CheckState.Checked
                ):
                    continue

                signal_data = signal_item.data(
                    0,
                    Qt.ItemDataRole.UserRole
                )

                if signal_data is None:
                    continue

                (
                    body_name,
                    signal_label
                ) = signal_data

                selections.append(
                    PlotSignalSelection(
                        body_name=body_name,
                        signal_label=signal_label
                    )
                )

        self.signal_selections = selections

    def update_plot(self) -> None:
        self.clear_plot_curves()

        session = self.session

        if session is None:
            return

        values_by_data_type: dict[
            SignalDataType,
            list[np.ndarray]
        ] = {
            "position": [],
            "euler": [],
            "quaternion": []
        }

        for curve_index, selection in enumerate(
                self.signal_selections):

            signal_definition = SIGNAL_DEFINITIONS[
                selection.signal_label
            ]

            data_type = signal_definition[
                "data_type"
            ]

            values = self.get_signal_values(
                selection
            )

            values_by_data_type[
                data_type
            ].append(values)

            curve_name = (
                f"{selection.body_name} - "
                f"{selection.signal_label}"
            )

            curve = PlotDataItem(
                x=session.time,
                y=values,
                pen=pg.mkPen(
                    color=color_for_curve(
                        curve_index
                    ),
                    width=2
                ),
                name=curve_name,
                connect="finite"
            )

            viewbox = (
                self.viewboxes_by_data_type[
                    data_type
                ]
            )

            viewbox.addItem(
                curve
            )

            self.legend.addItem(
                curve,
                curve_name
            )

            self.curves_by_data_type[
                data_type
            ].append(curve)

        self.update_base_y_ranges(
            values_by_data_type
        )

    def clear_plot_curves(self) -> None:
        for data_type, curves in (
                self.curves_by_data_type.items()):

            viewbox = (
                self.viewboxes_by_data_type[
                    data_type
                ]
            )

            for curve in curves:
                viewbox.removeItem(
                    curve
                )

                self.legend.removeItem(
                    curve
                )

            curves.clear()

            self.base_y_ranges_by_data_type[
                data_type
            ] = None

            scale_spinbox = (
                self.axis_scale_spinboxes[
                    data_type
                ]
            )

            scale_spinbox.setEnabled(False)

    def get_signal_values(
        self,
        selection: PlotSignalSelection
    ) -> np.ndarray:

        session = self.session

        if session is None:
            raise RuntimeError(
                "A tracking session must be assigned "
                "before retrieving signal values."
            )

        if (
            selection.body_name
            not in session.bodies
        ):
            raise KeyError(
                f"Rigid body "
                f"{selection.body_name!r} "
                "does not exist in the current session."
            )

        if (
            selection.signal_label
            not in SIGNAL_DEFINITIONS
        ):
            raise KeyError(
                f"Unknown signal: "
                f"{selection.signal_label!r}."
            )

        signal_definition = SIGNAL_DEFINITIONS[
            selection.signal_label
        ]

        data_type = signal_definition[
            "data_type"
        ]

        signal_index = signal_definition[
            "index"
        ]

        body_name = selection.body_name
        body = session.bodies[body_name]

        if self.raw_values_checkbox.isChecked():
            return self.get_pre_interpolation_signal_values(
                body,
                data_type,
                signal_index
            )

        if self.smoothing_checkbox.isChecked():
            if (
                body_name
                not in self.smoothed_positions_by_body
            ):
                self.update_smoothed_signal_data()

            if data_type == "position":
                return (
                    self.smoothed_positions_by_body[
                        body_name
                    ][:, signal_index]
                )

            if data_type == "euler":
                return (
                    self.smoothed_euler_by_body[
                        body_name
                    ][:, signal_index]
                )

            return (
                self.smoothed_quaternions_by_body[
                    body_name
                ][:, signal_index]
            )

        return self.get_interpolated_signal_values(
            body,
            data_type,
            signal_index
        )

    def get_interpolated_signal_values(
        self,
        body: RigidBodyData,
        data_type: SignalDataType,
        signal_index: int
    ) -> np.ndarray:

        if data_type == "position":
            signals = (
                body.position_x,
                body.position_y,
                body.position_z
            )

        elif data_type == "euler":
            signals = (
                body.rotation_xyz_x,
                body.rotation_xyz_y,
                body.rotation_xyz_z
            )

        elif data_type == "quaternion":
            signals = (
                body.rotation_x,
                body.rotation_y,
                body.rotation_z,
                body.rotation_w
            )

        else:
            raise ValueError(
                f"Unsupported signal data type: "
                f"{data_type!r}."
            )

        return signals[signal_index]

    def get_pre_interpolation_signal_values(
        self,
        body: RigidBodyData,
        data_type: SignalDataType,
        signal_index: int
    ) -> np.ndarray:

        if data_type == "position":
            signals = (
                body.pre_interpolation_position_x,
                body.pre_interpolation_position_y,
                body.pre_interpolation_position_z
            )

        elif data_type == "euler":
            signals = (
                body.pre_interpolation_rotation_xyz_x,
                body.pre_interpolation_rotation_xyz_y,
                body.pre_interpolation_rotation_xyz_z
            )

        elif data_type == "quaternion":
            signals = (
                body.pre_interpolation_rotation_x,
                body.pre_interpolation_rotation_y,
                body.pre_interpolation_rotation_z,
                body.pre_interpolation_rotation_w
            )

        else:
            raise ValueError(
                f"Unsupported signal data type: "
                f"{data_type!r}."
            )

        return signals[signal_index]

    def update_base_y_ranges(
        self,
        values_by_data_type: dict[
            SignalDataType,
            list[np.ndarray]
        ]
    ) -> None:

        for data_type, signal_arrays in (
                values_by_data_type.items()):

            finite_minimums: list[float] = []
            finite_maximums: list[float] = []

            for values in signal_arrays:
                finite_values = values[
                    np.isfinite(values)
                ]

                if finite_values.size == 0:
                    continue

                finite_minimums.append(
                    float(
                        np.min(finite_values)
                    )
                )

                finite_maximums.append(
                    float(
                        np.max(finite_values)
                    )
                )

            scale_spinbox = (
                self.axis_scale_spinboxes[
                    data_type
                ]
            )

            if not finite_minimums:
                self.base_y_ranges_by_data_type[
                    data_type
                ] = None

                scale_spinbox.setEnabled(False)
                continue

            data_minimum = min(
                finite_minimums
            )

            data_maximum = max(
                finite_maximums
            )

            range_center = (
                data_minimum + data_maximum
            ) / 2.0

            range_half_span = (
                data_maximum - data_minimum
            ) / 2.0

            if range_half_span <= 0.0:
                range_half_span = max(
                    abs(range_center) * 0.05,
                    0.05
                )

            else:
                range_half_span *= 1.05

            self.base_y_ranges_by_data_type[
                data_type
            ] = (
                range_center - range_half_span,
                range_center + range_half_span
            )

            scale_spinbox.setEnabled(True)

            self.set_axis_scale(
                data_type,
                scale_spinbox.value()
            )

    def set_axis_scale(
        self,
        data_type: SignalDataType,
        scale: float
    ) -> None:

        if scale <= 0.0:
            raise ValueError(
                "Axis scale must be greater than zero."
            )

        base_range = (
            self.base_y_ranges_by_data_type[
                data_type
            ]
        )

        if base_range is None:
            return

        base_minimum, base_maximum = (
            base_range
        )

        range_center = (
            base_minimum + base_maximum
        ) / 2.0

        base_half_span = (
            base_maximum - base_minimum
        ) / 2.0

        scaled_half_span = (
            base_half_span / scale
        )

        viewbox = (
            self.viewboxes_by_data_type[
                data_type
            ]
        )

        viewbox.setYRange(
            range_center - scaled_half_span,
            range_center + scaled_half_span,
            padding=0.0
        )

WorkspaceType = Literal[
    "signals",
    "recorded_3d",
    "live",
    "export"
]


class RenderSettingsWidget(QGroupBox):

    def __init__(
        self,
        title: str,
        note_text: str,
        include_ssaa: bool = False
    ) -> None:
        super().__init__(title)

        self.resolution_combobox = QComboBox()
        self.resolution_combobox.addItems(
            PLAYBACK_RESOLUTION_OPTIONS
        )
        self.resolution_combobox.setCurrentText(
            "Current widget size"
        )

        self.fps_combobox = QComboBox()
        self.fps_combobox.addItems(
            ["15", "30", "60", "120"]
        )
        self.fps_combobox.setCurrentText("30")

        self.ssaa_combobox: QComboBox | None = None

        self.note_label = QLabel(note_text)
        self.note_label.setWordWrap(True)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Resolution"))
        layout.addWidget(self.resolution_combobox)

        layout.addWidget(QLabel("Frame rate"))
        layout.addWidget(self.fps_combobox)

        if include_ssaa:
            self.ssaa_combobox = QComboBox()
            self.ssaa_combobox.addItems(SSAA_OPTIONS)
            self.ssaa_combobox.setCurrentText("1x")

            layout.addWidget(QLabel("SSAA"))
            layout.addWidget(self.ssaa_combobox)

        layout.addWidget(self.note_label)

    def fps(self) -> int:
        return int(
            self.fps_combobox.currentText()
        )

    def ssaa_factor(self) -> int:
        if self.ssaa_combobox is None:
            return 1

        return int(
            self.ssaa_combobox.currentText().removesuffix(
                "x"
            )
        )


class Recorded3DPlaybackTab(QWidget):

    def __init__(
        self,
        msaa_samples: int = DEFAULT_PLAYBACK_MSAA_SAMPLES
    ) -> None:
        super().__init__()

        self.requested_msaa_samples = msaa_samples
        self.actual_msaa_samples: int | None = None

        self.session: TrackingSession | None = None
        self.source_file_path: str | None = None

        self.body_checkboxes: dict[
            str,
            QCheckBox
        ] = {}

        self.display_positions: dict[
            str,
            np.ndarray
        ] = {}

        self.display_rotations: dict[
            str,
            np.ndarray
        ] = {}

        self.smoothed_display_positions: dict[
            str,
            np.ndarray
        ] = {}

        self.smoothed_display_rotations: dict[
            str,
            np.ndarray
        ] = {}

        self.body_display_settings: dict[
            str,
            BodyDisplaySettings
        ] = {}

        self.mesh_items_by_body: dict[
            str,
            gl.GLMeshItem
        ] = {}

        self.base_vertices_by_body: dict[
            str,
            np.ndarray
        ] = {}

        self.body_label_items_by_body: dict[
            str,
            GLTextItem
        ] = {}

        self.axis_label_items: list[GLTextItem] = []

        self.room_bounds: RoomBounds | None = None
        self.room_visual_items: list[GLGraphicsItem] = []
        self.room_visual_warning: str | None = None
        self.body_label_warning: str | None = None
        self.axis_tick_font = create_text_font(8)
        self.axis_title_font = create_text_font(9, bold=True)
        self.body_label_font = create_text_font(7)

        self.current_time_s = 0.0
        self.current_frame_idx = 0

        self.playback_speed = 1.0
        self.playback_start_wall_time_s = 0.0
        self.playback_start_data_time_s = 0.0

        self.playback_timer = QTimer(self)
        self.playback_timer.timeout.connect(
            self.advance_3d_time
        )

        self.load_button = QPushButton(
            "Load Motive CSV"
        )

        self.status_label = QLabel(
            "No CSV loaded."
        )
        self.status_label.setWordWrap(True)

        self.body_group = QGroupBox(
            "Rigid bodies"
        )
        self.body_layout = QVBoxLayout(
            self.body_group
        )
        self.body_group.setEnabled(False)

        self.smoothing_checkbox = QCheckBox(
            "Apply smoothing"
        )

        self.smoothing_seconds_spinbox = (
            QDoubleSpinBox()
        )

        self.time_slider = QSlider(
            Qt.Orientation.Horizontal
        )

        self.time_label = QLabel(
            "Time: 0.000 s | Frame: 0"
        )

        self.playback_speed_spinbox = (
            QDoubleSpinBox()
        )

        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")

        self.render_settings = RenderSettingsWidget(
            "Playback and preview settings",
            "Frame rate controls interactive playback. "
            "A fixed resolution changes the actual preview "
            "widget size; larger previews can be scrolled."
        )

        self.view_3d_widget = create_gl_view_widget(
            self.requested_msaa_samples
        )

        self.grid_3d = create_default_3d_grid()
        self.view_3d_widget.addItem(self.grid_3d)
        self.room_visual_items.append(self.grid_3d)

        self.preview_scroll_area = QScrollArea()
        self.preview_scroll_area.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.preview_scroll_area.setStyleSheet(
            "QScrollArea { background-color: white; }"
            "QScrollArea > QWidget > QWidget "
            "{ background-color: white; }"
        )
        self.preview_scroll_area.viewport().setStyleSheet(
            "background-color: white;"
        )
        self.preview_scroll_area.setWidgetResizable(True)
        self.preview_scroll_area.setWidget(
            self.view_3d_widget
        )

        self._build_layout()
        self._connect_signals()

    def _build_layout(self) -> None:
        settings_container = QWidget()
        settings_layout = QVBoxLayout(
            settings_container
        )
        settings_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop
        )

        settings_layout.addWidget(
            self._create_data_source_group()
        )

        settings_layout.addWidget(
            self.body_group
        )

        settings_layout.addWidget(
            self._create_smoothing_group()
        )

        settings_layout.addWidget(
            self._create_playback_group()
        )

        settings_layout.addWidget(
            self.render_settings
        )

        settings_layout.addStretch()

        settings_scroll_area = QScrollArea()
        settings_scroll_area.setWidgetResizable(True)
        settings_scroll_area.setMinimumWidth(340)
        settings_scroll_area.setWidget(
            settings_container
        )

        layout = QHBoxLayout(self)
        layout.addWidget(settings_scroll_area)
        layout.addWidget(
            self.preview_scroll_area,
            stretch=1
        )

    def _create_data_source_group(
        self
    ) -> QGroupBox:
        group = QGroupBox("Data source")
        layout = QVBoxLayout(group)
        layout.addWidget(self.load_button)
        layout.addWidget(self.status_label)
        return group

    def _create_smoothing_group(
        self
    ) -> QGroupBox:
        group = QGroupBox("3D smoothing")
        group.setEnabled(False)
        self.smoothing_group = group

        layout = QVBoxLayout(group)

        self.smoothing_seconds_spinbox.setMinimum(
            0.00
        )
        self.smoothing_seconds_spinbox.setMaximum(
            5.00
        )
        self.smoothing_seconds_spinbox.setSingleStep(
            0.05
        )
        self.smoothing_seconds_spinbox.setDecimals(2)
        self.smoothing_seconds_spinbox.setValue(0.25)
        self.smoothing_seconds_spinbox.setPrefix(
            "Window: "
        )
        self.smoothing_seconds_spinbox.setSuffix(
            " s"
        )
        self.smoothing_seconds_spinbox.setEnabled(
            False
        )

        layout.addWidget(self.smoothing_checkbox)
        layout.addWidget(
            self.smoothing_seconds_spinbox
        )

        return group

    def _create_playback_group(
        self
    ) -> QGroupBox:
        group = QGroupBox("3D playback")
        group.setEnabled(False)
        self.playback_group = group

        layout = QVBoxLayout(group)

        self.time_slider.setMinimum(0)
        self.time_slider.setMaximum(0)

        self.playback_speed_spinbox.setMinimum(0.25)
        self.playback_speed_spinbox.setMaximum(5.00)
        self.playback_speed_spinbox.setSingleStep(
            0.25
        )
        self.playback_speed_spinbox.setValue(1.00)
        self.playback_speed_spinbox.setDecimals(2)
        self.playback_speed_spinbox.setPrefix(
            "Speed: "
        )
        self.playback_speed_spinbox.setSuffix("x")

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.play_button)
        button_layout.addWidget(self.pause_button)

        layout.addWidget(self.time_label)
        layout.addWidget(self.time_slider)
        layout.addWidget(
            self.playback_speed_spinbox
        )
        layout.addLayout(button_layout)

        return group

    def _connect_signals(self) -> None:
        self.load_button.clicked.connect(
            self.load_csv
        )

        self.smoothing_checkbox.stateChanged.connect(
            self.handle_smoothing_settings_changed
        )

        self.smoothing_seconds_spinbox.valueChanged.connect(
            self.handle_smoothing_settings_changed
        )

        self.time_slider.valueChanged.connect(
            self.set_3d_time_from_slider
        )

        self.playback_speed_spinbox.valueChanged.connect(
            self.set_playback_speed
        )

        self.play_button.clicked.connect(
            self.play_3d
        )

        self.pause_button.clicked.connect(
            self.pause_3d
        )

        self.render_settings.fps_combobox.currentTextChanged.connect(
            self.set_render_fps_cap
        )

        self.render_settings.resolution_combobox.currentTextChanged.connect(
            self.handle_render_settings_changed
        )



    def load_csv(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Motive CSV",
            "",
            "CSV files (*.csv);;All files (*)"
        )

        if not file_path:
            return

        try:
            session = load_motive_rigid_body_csv(
                file_path
            )

        except Exception as exc:
            self.status_label.setText(
                f"Error loading CSV: {exc}"
            )
            return

        self.set_session(
            session,
            source_file_path=file_path
        )

    def set_session(
        self,
        session: TrackingSession,
        source_file_path: str | None = None
    ) -> None:
        self.pause_3d()
        self.clear_3d_meshes()
        self.clear_room_visuals()
        self.clear_body_checkboxes()

        self.room_visual_warning = None
        self.body_label_warning = None

        self.session = session
        self.source_file_path = source_file_path

        self.display_positions.clear()
        self.display_rotations.clear()
        self.smoothed_display_positions.clear()
        self.smoothed_display_rotations.clear()
        self.body_display_settings.clear()

        for body_index, body_name in enumerate(
                session.bodies):
            self.body_display_settings[body_name] = {
                "shape": "tetra",
                "length": 0.09,
                "width": 0.065,
                "height": 0.025,
                "color": color_for_curve(body_index)
            }

        self.populate_body_checkboxes()
        self.rebuild_body_geometry_cache()

        for body_name, body in session.bodies.items():
            self.display_positions[body_name] = (
                motive_positions_to_display(
                    body.position_x,
                    body.position_y,
                    body.position_z
                )
            )

            self.display_rotations[body_name] = (
                np.column_stack(
                    [
                        body.rotation_x,
                        body.rotation_y,
                        body.rotation_z,
                        body.rotation_w
                    ]
                )
            )

        self.update_room_from_loaded_data()
        self.rebuild_room_visuals()
        self.frame_camera_to_room()

        if self.smoothing_checkbox.isChecked():
            self.update_smoothed_tracking_data()

        sample_count = len(session.time)

        if sample_count == 0:
            duration_s = 0.0
        else:
            duration_s = float(session.time[-1])

        duration_ms = int(
            round(duration_s * 1000.0)
        )

        self.time_slider.blockSignals(True)
        self.time_slider.setMaximum(duration_ms)
        self.time_slider.setValue(0)
        self.time_slider.blockSignals(False)

        self.current_time_s = 0.0
        self.current_frame_idx = 0

        self.body_group.setEnabled(True)
        self.smoothing_group.setEnabled(True)
        self.playback_group.setEnabled(
            sample_count > 0
        )

        self.smoothing_seconds_spinbox.setEnabled(
            self.smoothing_checkbox.isChecked()
        )

        if sample_count > 0:
            self.set_3d_time(
                0.0,
                update_slider=True
            )
        else:
            self.time_label.setText(
                "Time: 0.000 s | Frame: --"
            )

        source_text = (
            source_file_path
            if source_file_path is not None
            else "Session supplied externally"
        )

        room_text = ""

        if self.room_bounds is not None:
            room_text = (
                "\nRoom bounds: "
                f"X {self.room_bounds.x_min:g} to "
                f"{self.room_bounds.x_max:g} m | "
                f"Y {self.room_bounds.y_min:g} to "
                f"{self.room_bounds.y_max:g} m | "
                f"Z {self.room_bounds.z_min:g} to "
                f"{self.room_bounds.z_max:g} m"
            )

        if self.room_visual_warning is not None:
            room_text += (
                "\nRoom visual warning: "
                f"{self.room_visual_warning}"
            )

        if self.body_label_warning is not None:
            room_text += (
                "\nBody label warning: "
                f"{self.body_label_warning}"
            )

        self.status_label.setText(
            f"{source_text}\n"
            f"{len(session.bodies)} rigid bodies | "
            f"{duration_s:.3f} s"
            f"{room_text}"
        )

    def clear_body_checkboxes(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self.body_checkboxes.clear()

    def populate_body_checkboxes(self) -> None:
        session = self.session

        if session is None:
            return

        self.clear_body_checkboxes()

        for body_name in session.bodies:
            checkbox = QCheckBox(body_name)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(
                self.handle_body_selection_changed
            )

            self.body_checkboxes[body_name] = (
                checkbox
            )

            self.body_layout.addWidget(checkbox)

    def selected_body_names(self) -> list[str]:
        selected_names: list[str] = []

        for body_name, checkbox in (
                self.body_checkboxes.items()):
            if checkbox.isChecked():
                selected_names.append(body_name)

        return selected_names

    def handle_body_selection_changed(
        self,
        _state: int | None = None
    ) -> None:
        self.update_3d_view()

    def update_smoothed_tracking_data(self) -> None:
        session = self.session

        if session is None:
            return

        smoothing_seconds = (
            self.smoothing_seconds_spinbox.value()
        )

        self.smoothed_display_positions.clear()
        self.smoothed_display_rotations.clear()

        for body_name in self.display_positions:
            positions = self.display_positions[body_name]
            rotations = self.display_rotations[body_name]

            (
                smoothed_positions,
                smoothed_rotations
            ) = smooth_tracking_positions_and_rotations(
                time_s=session.time,
                positions=positions,
                rotations=rotations,
                smoothing_seconds=smoothing_seconds
            )

            self.smoothed_display_positions[
                body_name
            ] = smoothed_positions

            self.smoothed_display_rotations[
                body_name
            ] = smoothed_rotations

    def handle_smoothing_settings_changed(
        self,
        _value: int | float | None = None
    ) -> None:
        smoothing_enabled = (
            self.smoothing_checkbox.isChecked()
        )

        self.smoothing_seconds_spinbox.setEnabled(
            smoothing_enabled
        )

        if self.session is None:
            return

        if smoothing_enabled:
            self.update_smoothed_tracking_data()

        else:
            self.smoothed_display_positions.clear()
            self.smoothed_display_rotations.clear()

        self.update_3d_view()

    def get_active_positions(
        self,
        body_name: str
    ) -> np.ndarray:
        if self.smoothing_checkbox.isChecked():
            if (
                body_name
                not in self.smoothed_display_positions
            ):
                self.update_smoothed_tracking_data()

            return self.smoothed_display_positions[
                body_name
            ]

        return self.display_positions[body_name]

    def get_active_rotations(
        self,
        body_name: str
    ) -> np.ndarray:
        if self.smoothing_checkbox.isChecked():
            if (
                body_name
                not in self.smoothed_display_rotations
            ):
                self.update_smoothed_tracking_data()

            return self.smoothed_display_rotations[
                body_name
            ]

        return self.display_rotations[body_name]

    def clear_3d_meshes(self) -> None:
        for mesh_item in (
                self.mesh_items_by_body.values()):
            self.view_3d_widget.removeItem(mesh_item)

        self.mesh_items_by_body.clear()

        for label_item in (
                self.body_label_items_by_body.values()):
            self.view_3d_widget.removeItem(label_item)

        self.body_label_items_by_body.clear()
        self.base_vertices_by_body.clear()

    def clear_room_visuals(self) -> None:
        for room_item in self.room_visual_items:
            self.view_3d_widget.removeItem(room_item)

        self.room_visual_items.clear()

        for label_item in self.axis_label_items:
            self.view_3d_widget.removeItem(label_item)

        self.axis_label_items.clear()

    def add_room_visual_item(
        self,
        room_item: GLGraphicsItem
    ) -> None:
        self.view_3d_widget.addItem(room_item)
        self.room_visual_items.append(room_item)

    def create_gl_text_item(
        self,
        position: tuple[float, float, float],
        text: str,
        font: QFont,
        alignment: Qt.AlignmentFlag,
        warning_kind: Literal["room", "body"]
    ) -> GLTextItem | None:
        try:
            text_item = GLTextItem(
                pos=np.asarray(
                    position,
                    dtype=float
                ),
                color=QColor(25, 25, 25, 255),
                text=text,
                font=font,
                alignment=alignment,
                glOptions="translucent"
            )

            text_item.setDepthValue(1000)
            self.view_3d_widget.addItem(text_item)
            return text_item

        except Exception as exc:
            warning_text = (
                f"Unable to create {warning_kind} label "
                f"{text!r}: {exc}"
            )

            if warning_kind == "room":
                self.room_visual_warning = warning_text
            else:
                self.body_label_warning = warning_text

            return None

    def add_room_text_item(
        self,
        position: tuple[float, float, float],
        text: str,
        font: QFont
    ) -> None:
        text_item = self.create_gl_text_item(
            position=position,
            text=text,
            font=font,
            alignment=(
                Qt.AlignmentFlag.AlignHCenter
                | Qt.AlignmentFlag.AlignVCenter
            ),
            warning_kind="room"
        )

        if text_item is not None:
            self.axis_label_items.append(text_item)

    def update_room_from_loaded_data(self) -> None:
        maximum_body_dimension = 0.10

        for settings in self.body_display_settings.values():
            maximum_body_dimension = max(
                maximum_body_dimension,
                settings["length"],
                settings["width"],
                settings["height"]
            )

        self.room_bounds = calculate_room_bounds(
            self.display_positions,
            minimum_padding=maximum_body_dimension
        )

    def rebuild_room_visuals(self) -> None:
        self.clear_room_visuals()

        bounds = self.room_bounds

        if bounds is None:
            self.grid_3d = create_default_3d_grid()
            self.add_room_visual_item(self.grid_3d)
            return

        x_span, y_span, z_span = bounds.spans()

        grid_color = (145, 145, 145, 80)

        floor_grid = gl.GLGridItem()
        floor_grid.setSize(
            x=x_span,
            y=y_span
        )
        floor_grid.setSpacing(
            x=bounds.x_tick,
            y=bounds.y_tick
        )
        floor_grid.setColor(grid_color)
        floor_grid.translate(
            float((bounds.x_min + bounds.x_max) / 2.0),
            float((bounds.y_min + bounds.y_max) / 2.0),
            float(bounds.z_min)
        )

        self.grid_3d = floor_grid
        self.add_room_visual_item(floor_grid)

        xz_grid = gl.GLGridItem()
        xz_grid.setSize(
            x=x_span,
            y=z_span
        )
        xz_grid.setSpacing(
            x=bounds.x_tick,
            y=bounds.z_tick
        )
        xz_grid.setColor(grid_color)
        xz_grid.rotate(
            90.0,
            1.0,
            0.0,
            0.0
        )
        xz_grid.translate(
            float((bounds.x_min + bounds.x_max) / 2.0),
            float(bounds.y_min),
            float((bounds.z_min + bounds.z_max) / 2.0)
        )
        self.add_room_visual_item(xz_grid)

        yz_grid = gl.GLGridItem()
        yz_grid.setSize(
            x=z_span,
            y=y_span
        )
        yz_grid.setSpacing(
            x=bounds.z_tick,
            y=bounds.y_tick
        )
        yz_grid.setColor(grid_color)
        yz_grid.rotate(
            90.0,
            0.0,
            1.0,
            0.0
        )
        yz_grid.translate(
            float(bounds.x_min),
            float((bounds.y_min + bounds.y_max) / 2.0),
            float((bounds.z_min + bounds.z_max) / 2.0)
        )
        self.add_room_visual_item(yz_grid)

        axis_color = (0.22, 0.22, 0.22, 1.0)

        x_axis_y = bounds.y_min
        x_axis_z = bounds.z_min
        y_axis_x = bounds.x_min
        y_axis_z = bounds.z_min
        z_axis_x = bounds.x_min
        z_axis_y = bounds.y_min

        axis_segments = (
            np.asarray(
                [
                    [bounds.x_min, x_axis_y, x_axis_z],
                    [bounds.x_max, x_axis_y, x_axis_z]
                ],
                dtype=np.float32
            ),
            np.asarray(
                [
                    [y_axis_x, bounds.y_min, y_axis_z],
                    [y_axis_x, bounds.y_max, y_axis_z]
                ],
                dtype=np.float32
            ),
            np.asarray(
                [
                    [z_axis_x, z_axis_y, bounds.z_min],
                    [z_axis_x, z_axis_y, bounds.z_max]
                ],
                dtype=np.float32
            )
        )

        for axis_segment in axis_segments:
            axis_item = gl.GLLinePlotItem(
                pos=axis_segment,
                color=axis_color,
                width=3.0,
                antialias=True,
                mode="line_strip"
            )
            axis_item.setGLOptions(
                {
                    "glDisable": [GL.GL_DEPTH_TEST],
                    "glEnable": [GL.GL_BLEND],
                    "glBlendFunc": (
                        GL.GL_SRC_ALPHA,
                        GL.GL_ONE_MINUS_SRC_ALPHA
                    )
                }
            )
            axis_item.setDepthValue(100)
            self.add_room_visual_item(axis_item)

        x_ticks = axis_tick_values(
            bounds.x_min,
            bounds.x_max,
            bounds.x_tick
        )
        y_ticks = axis_tick_values(
            bounds.y_min,
            bounds.y_max,
            bounds.y_tick
        )
        z_ticks = axis_tick_values(
            bounds.z_min,
            bounds.z_max,
            bounds.z_tick
        )

        x_tick_length = max(
            y_span * 0.015,
            bounds.y_tick * 0.15
        )
        y_tick_length = max(
            x_span * 0.015,
            bounds.x_tick * 0.15
        )
        z_tick_length = max(
            x_span * 0.015,
            bounds.x_tick * 0.15
        )

        tick_segments: list[list[float]] = []

        for tick_value in x_ticks:
            tick_segments.extend(
                [
                    [tick_value, x_axis_y, x_axis_z],
                    [
                        tick_value,
                        x_axis_y + x_tick_length,
                        x_axis_z
                    ]
                ]
            )

        for tick_value in y_ticks:
            tick_segments.extend(
                [
                    [y_axis_x, tick_value, y_axis_z],
                    [
                        y_axis_x + y_tick_length,
                        tick_value,
                        y_axis_z
                    ]
                ]
            )

        for tick_value in z_ticks:
            tick_segments.extend(
                [
                    [z_axis_x, z_axis_y, tick_value],
                    [
                        z_axis_x + z_tick_length,
                        z_axis_y,
                        tick_value
                    ]
                ]
            )

        if tick_segments:
            tick_item = gl.GLLinePlotItem(
                pos=np.asarray(
                    tick_segments,
                    dtype=np.float32
                ),
                color=axis_color,
                width=2.0,
                antialias=True,
                mode="lines"
            )
            tick_item.setGLOptions(
                {
                    "glDisable": [GL.GL_DEPTH_TEST],
                    "glEnable": [GL.GL_BLEND],
                    "glBlendFunc": (
                        GL.GL_SRC_ALPHA,
                        GL.GL_ONE_MINUS_SRC_ALPHA
                    )
                }
            )
            tick_item.setDepthValue(101)
            self.add_room_visual_item(tick_item)

        x_text_offset = max(
            y_span * 0.025,
            bounds.y_tick * 0.25
        )
        y_text_offset = max(
            x_span * 0.025,
            bounds.x_tick * 0.25
        )
        z_text_offset = max(
            x_span * 0.025,
            bounds.x_tick * 0.25
        )

        for tick_value in x_ticks:
            self.add_room_text_item(
                position=(
                    float(tick_value),
                    float(x_axis_y - x_text_offset),
                    float(x_axis_z)
                ),
                text=format_axis_tick(
                    float(tick_value),
                    bounds.x_tick
                ),
                font=self.axis_tick_font
            )

        for tick_value in y_ticks:
            self.add_room_text_item(
                position=(
                    float(y_axis_x - y_text_offset),
                    float(tick_value),
                    float(y_axis_z)
                ),
                text=format_axis_tick(
                    float(tick_value),
                    bounds.y_tick
                ),
                font=self.axis_tick_font
            )

        for tick_value in z_ticks:
            self.add_room_text_item(
                position=(
                    float(z_axis_x - z_text_offset),
                    float(z_axis_y),
                    float(tick_value)
                ),
                text=format_axis_tick(
                    float(tick_value),
                    bounds.z_tick
                ),
                font=self.axis_tick_font
            )

        axis_titles = (
            (
                (
                    float(bounds.x_max + bounds.x_tick * 0.4),
                    float(x_axis_y),
                    float(x_axis_z)
                ),
                "X (m)"
            ),
            (
                (
                    float(y_axis_x),
                    float(bounds.y_max + bounds.y_tick * 0.4),
                    float(y_axis_z)
                ),
                "Y (m)"
            ),
            (
                (
                    float(z_axis_x),
                    float(z_axis_y),
                    float(bounds.z_max + bounds.z_tick * 0.4)
                ),
                "Z (m)"
            )
        )

        for title_position, title_text in axis_titles:
            self.add_room_text_item(
                position=title_position,
                text=title_text,
                font=self.axis_title_font
            )

    def frame_camera_to_room(self) -> None:
        bounds = self.room_bounds

        if bounds is None:
            return

        x_span, y_span, z_span = bounds.spans()
        diagonal = math.sqrt(
            x_span * x_span
            + y_span * y_span
            + z_span * z_span
        )

        self.view_3d_widget.setCameraPosition(
            pos=bounds.center_vector(),
            distance=max(diagonal * 1.35, 1.0),
            elevation=25.0,
            azimuth=45.0
        )

    def update_body_label_entry(
        self,
        body_name: str,
        position_display: np.ndarray
    ) -> None:
        label_position = np.asarray(
            position_display,
            dtype=float
        ).copy()

        settings = self.body_display_settings[
            body_name
        ]

        maximum_body_dimension = max(
            settings["length"],
            settings["width"],
            settings["height"]
        )

        label_position[2] += max(
            maximum_body_dimension * 0.75,
            0.03
        )

        label_position_tuple = (
            float(label_position[0]),
            float(label_position[1]),
            float(label_position[2])
        )

        label_item = self.body_label_items_by_body.get(
            body_name
        )

        if label_item is None:
            label_item = self.create_gl_text_item(
                position=label_position_tuple,
                text=body_name,
                font=self.body_label_font,
                alignment=(
                    Qt.AlignmentFlag.AlignHCenter
                    | Qt.AlignmentFlag.AlignBottom
                ),
                warning_kind="body"
            )

            if label_item is not None:
                self.body_label_items_by_body[
                    body_name
                ] = label_item

            return

        try:
            label_item.setData(
                pos=np.asarray(
                    label_position_tuple,
                    dtype=float
                )
            )

        except Exception as exc:
            self.body_label_warning = (
                f"Unable to update body label "
                f"{body_name!r}: {exc}"
            )

    def remove_body_label(
        self,
        body_name: str
    ) -> None:
        label_item = self.body_label_items_by_body.pop(
            body_name,
            None
        )

        if label_item is not None:
            self.view_3d_widget.removeItem(label_item)

    def rebuild_body_geometry_cache(self) -> None:
        self.base_vertices_by_body.clear()

        for body_name, settings in (
                self.body_display_settings.items()):
            self.base_vertices_by_body[body_name] = (
                create_body_vertices(
                    shape=settings["shape"],
                    length=settings["length"],
                    width=settings["width"],
                    height=settings["height"]
                )
            )

    def update_body_mesh_for_frame(
        self,
        body_name: str,
        frame_idx: int
    ) -> None:
        positions = self.get_active_positions(
            body_name
        )

        rotations = self.get_active_rotations(
            body_name
        )

        position_display = positions[frame_idx]
        rotation_display = rotations[frame_idx]

        settings = self.body_display_settings[
            body_name
        ]

        base_vertices = self.base_vertices_by_body[
            body_name
        ]

        transformed_vertices = transform_body_vertices(
            base_vertices=base_vertices,
            position_transform=position_display,
            qx=rotation_display[0],
            qy=rotation_display[1],
            qz=rotation_display[2],
            qw=rotation_display[3]
        )

        if body_name not in self.mesh_items_by_body:
            mesh_item = make_body_mesh_item(
                vertices=transformed_vertices,
                color=settings["color"],
                shape=settings["shape"]
            )

            self.view_3d_widget.addItem(mesh_item)
            self.mesh_items_by_body[body_name] = (
                mesh_item
            )

        else:
            mesh_item = self.mesh_items_by_body[
                body_name
            ]

            update_body_mesh_item(
                mesh_item=mesh_item,
                vertices=transformed_vertices,
                shape=settings["shape"]
            )

        self.update_body_label_entry(
            body_name,
            position_display
        )

    def update_3d_view(self) -> None:
        session = self.session

        if session is None or len(session.time) == 0:
            return

        selected_bodies = self.selected_body_names()
        selected_body_set = set(selected_bodies)

        for body_name in list(
                self.mesh_items_by_body.keys()):
            if body_name not in selected_body_set:
                mesh_item = self.mesh_items_by_body.pop(
                    body_name
                )

                self.view_3d_widget.removeItem(
                    mesh_item
                )

                self.remove_body_label(
                    body_name
                )

        for body_name in list(
                self.body_label_items_by_body.keys()):
            if body_name not in selected_body_set:
                self.remove_body_label(
                    body_name
                )

        if not selected_bodies:
            self.time_label.setText(
                f"Time: {self.current_time_s:.3f} s | "
                "Frame: --"
            )
            return

        frame_idx = min(
            self.current_frame_idx,
            len(session.time) - 1
        )

        for body_name in selected_bodies:
            self.update_body_mesh_for_frame(
                body_name=body_name,
                frame_idx=frame_idx
            )

        sample_time_s = float(
            session.time[frame_idx]
        )

        frame_number = int(
            session.frames[frame_idx]
        )

        self.time_label.setText(
            f"Time: {self.current_time_s:.3f} s | "
            f"Sample: {sample_time_s:.3f} s | "
            f"Frame: {frame_number}"
        )

    def frame_idx_from_time(
        self,
        time_s: float
    ) -> int:
        session = self.session

        if session is None or len(session.time) == 0:
            return 0

        times = session.time

        right_idx = int(
            np.searchsorted(
                times,
                time_s,
                side="left"
            )
        )

        if right_idx <= 0:
            return 0

        if right_idx >= len(times):
            return len(times) - 1

        left_idx = right_idx - 1

        left_error = abs(
            time_s - times[left_idx]
        )

        right_error = abs(
            times[right_idx] - time_s
        )

        if left_error <= right_error:
            return left_idx

        return right_idx

    def set_3d_time(
        self,
        time_s: float,
        update_slider: bool = True
    ) -> None:
        session = self.session

        if session is None or len(session.time) == 0:
            return

        duration_s = float(session.time[-1])

        if duration_s <= 0.0:
            self.current_time_s = 0.0
            self.current_frame_idx = 0
            self.update_3d_view()
            return

        self.current_time_s = max(
            0.0,
            min(time_s, duration_s)
        )

        self.current_frame_idx = (
            self.frame_idx_from_time(
                self.current_time_s
            )
        )

        if update_slider:
            slider_time_ms = int(
                round(
                    self.current_time_s * 1000.0
                )
            )

            self.time_slider.blockSignals(True)
            self.time_slider.setValue(
                slider_time_ms
            )
            self.time_slider.blockSignals(False)

        self.update_3d_view()

    def set_3d_time_from_slider(
        self,
        slider_time_ms: int
    ) -> None:
        time_s = slider_time_ms / 1000.0

        self.set_3d_time(
            time_s,
            update_slider=False
        )

        if self.playback_timer.isActive():
            self.playback_start_wall_time_s = (
                time.perf_counter()
            )

            self.playback_start_data_time_s = (
                self.current_time_s
            )

    def play_3d(self) -> None:
        session = self.session

        if session is None or len(session.time) == 0:
            self.status_label.setText(
                "Load a CSV before playback."
            )
            return

        self.playback_speed = (
            self.playback_speed_spinbox.value()
        )

        self.playback_start_wall_time_s = (
            time.perf_counter()
        )

        self.playback_start_data_time_s = (
            self.current_time_s
        )

        timer_interval_ms = int(
            round(
                1000.0
                / self.render_settings.fps()
            )
        )

        self.playback_timer.start(
            timer_interval_ms
        )

    def pause_3d(self) -> None:
        self.playback_timer.stop()

    def advance_3d_time(self) -> None:
        session = self.session

        if session is None or len(session.time) == 0:
            return

        duration_s = float(session.time[-1])

        if duration_s <= 0.0:
            return

        elapsed_wall_time_s = (
            time.perf_counter()
            - self.playback_start_wall_time_s
        )

        target_time_s = (
            self.playback_start_data_time_s
            + elapsed_wall_time_s
            * self.playback_speed
        )

        if target_time_s > duration_s:
            target_time_s = (
                target_time_s % duration_s
            )

            self.playback_start_wall_time_s = (
                time.perf_counter()
            )

            self.playback_start_data_time_s = (
                target_time_s
            )

        self.set_3d_time(
            target_time_s,
            update_slider=True
        )

    def set_playback_speed(
        self,
        speed: float
    ) -> None:
        self.playback_speed = speed

        if self.playback_timer.isActive():
            self.playback_start_wall_time_s = (
                time.perf_counter()
            )

            self.playback_start_data_time_s = (
                self.current_time_s
            )

    def set_render_fps_cap(
        self,
        _fps_text: str
    ) -> None:
        if not self.playback_timer.isActive():
            return

        timer_interval_ms = int(
            round(
                1000.0
                / self.render_settings.fps()
            )
        )

        self.playback_start_wall_time_s = (
            time.perf_counter()
        )

        self.playback_start_data_time_s = (
            self.current_time_s
        )

        self.playback_timer.start(
            timer_interval_ms
        )

    def handle_render_settings_changed(
        self,
        _value: str | None = None
    ) -> None:
        self.apply_preview_resolution()

    def apply_preview_resolution(self) -> None:
        resolution_text = (
            self.render_settings.resolution_combobox.currentText()
        )

        resolution = parse_resolution_option(
            resolution_text
        )

        if resolution is None:
            self.preview_scroll_area.setWidgetResizable(True)
            self.view_3d_widget.setMinimumSize(0, 0)
            self.view_3d_widget.setMaximumSize(
                16777215,
                16777215
            )
            self.view_3d_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding
            )

            self.render_settings.note_label.setText(
                "The preview follows the available tab size. "
                f"Global preview MSAA request: "
                f"{self.requested_msaa_samples}x."
            )
            return

        width, height = resolution

        self.preview_scroll_area.setWidgetResizable(False)
        self.view_3d_widget.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed
        )
        self.view_3d_widget.setFixedSize(
            width,
            height
        )

        center_scroll_area_on_widget(
            self.preview_scroll_area
        )

        QTimer.singleShot(
            0,
            partial(
                center_scroll_area_on_widget,
                self.preview_scroll_area
            )
        )

        QTimer.singleShot(
            50,
            partial(
                center_scroll_area_on_widget,
                self.preview_scroll_area
            )
        )

        self.render_settings.note_label.setText(
            f"Preview framebuffer size requested: "
            f"{width} x {height}. Scrollbars appear when "
            "the preview is larger than the tab. "
            f"Global preview MSAA request: "
            f"{self.requested_msaa_samples}x."
        )

    def set_global_msaa_samples(
        self,
        msaa_samples: int
    ) -> None:
        if msaa_samples == self.requested_msaa_samples:
            return

        was_playing = self.playback_timer.isActive()
        self.pause_3d()

        old_view = self.view_3d_widget
        old_options = dict(old_view.opts)

        self.requested_msaa_samples = msaa_samples
        self.actual_msaa_samples = None

        self.mesh_items_by_body.clear()
        self.body_label_items_by_body.clear()
        self.axis_label_items.clear()
        self.room_visual_items.clear()
        self.room_visual_warning = None
        self.body_label_warning = None

        detached_widget = self.preview_scroll_area.takeWidget()

        self.view_3d_widget = create_gl_view_widget(
            msaa_samples
        )

        self.view_3d_widget.opts["fov"] = old_options.get(
            "fov",
            self.view_3d_widget.opts["fov"]
        )

        self.view_3d_widget.setCameraPosition(
            pos=old_options.get("center"),
            distance=old_options.get("distance"),
            elevation=old_options.get("elevation"),
            azimuth=old_options.get("azimuth")
        )

        self.preview_scroll_area.setWidget(
            self.view_3d_widget
        )

        self.rebuild_room_visuals()
        self.apply_preview_resolution()
        self.update_3d_view()

        if detached_widget is not None:
            detached_widget.deleteLater()
        elif old_view is not None:
            old_view.deleteLater()

        if was_playing:
            self.play_3d()

    def read_actual_msaa_samples(self) -> int | None:
        self.actual_msaa_samples = (
            read_gl_framebuffer_samples(
                self.view_3d_widget
            )
        )

        return self.actual_msaa_samples

    def shutdown(self) -> None:
        self.pause_3d()


class LivePlaybackTab(QWidget):

    def __init__(
        self,
        msaa_samples: int = DEFAULT_PLAYBACK_MSAA_SAMPLES
    ) -> None:
        super().__init__()

        self.requested_msaa_samples = msaa_samples
        self.actual_msaa_samples: int | None = None

        self.live_worker: object | None = None
        self.latest_positions_by_body: dict[
            str,
            np.ndarray
        ] = {}
        self.latest_rotations_by_body: dict[
            str,
            np.ndarray
        ] = {}

        self.status_label = QLabel(
            "Live transport is not implemented yet."
        )
        self.status_label.setWordWrap(True)

        self.bind_address_lineedit = QLineEdit(
            "0.0.0.0"
        )

        self.data_port_spinbox = QSpinBox()
        self.data_port_spinbox.setMinimum(1)
        self.data_port_spinbox.setMaximum(65535)
        self.data_port_spinbox.setValue(1511)

        self.start_button = QPushButton(
            "Start live stream"
        )
        self.start_button.setEnabled(False)

        self.stop_button = QPushButton(
            "Stop live stream"
        )
        self.stop_button.setEnabled(False)

        self.record_checkbox = QCheckBox(
            "Record incoming data"
        )
        self.record_checkbox.setEnabled(False)

        self.smoothing_checkbox = QCheckBox(
            "Apply live smoothing"
        )

        self.smoothing_seconds_spinbox = (
            QDoubleSpinBox()
        )

        self.render_settings = RenderSettingsWidget(
            "Live preview and output settings",
            "Resolution changes the live preview widget "
            "size now. Frame-rate output will be connected "
            "when the live receiver and recorder are added."
        )

        self.view_3d_widget = create_gl_view_widget(
            self.requested_msaa_samples
        )

        self.grid_3d = create_default_3d_grid()
        self.view_3d_widget.addItem(self.grid_3d)

        self.preview_scroll_area = QScrollArea()
        self.preview_scroll_area.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.preview_scroll_area.setStyleSheet(
            "QScrollArea { background-color: white; }"
            "QScrollArea > QWidget > QWidget "
            "{ background-color: white; }"
        )
        self.preview_scroll_area.viewport().setStyleSheet(
            "background-color: white;"
        )
        self.preview_scroll_area.setWidgetResizable(True)
        self.preview_scroll_area.setWidget(
            self.view_3d_widget
        )

        self._build_layout()
        self._connect_signals()

    def _build_layout(self) -> None:
        settings_container = QWidget()
        settings_layout = QVBoxLayout(
            settings_container
        )
        settings_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop
        )

        settings_layout.addWidget(
            self._create_connection_group()
        )

        settings_layout.addWidget(
            self._create_smoothing_group()
        )

        settings_layout.addWidget(
            self.render_settings
        )

        settings_layout.addStretch()

        settings_scroll_area = QScrollArea()
        settings_scroll_area.setWidgetResizable(True)
        settings_scroll_area.setMinimumWidth(340)
        settings_scroll_area.setWidget(
            settings_container
        )

        layout = QHBoxLayout(self)
        layout.addWidget(settings_scroll_area)
        layout.addWidget(
            self.preview_scroll_area,
            stretch=1
        )

    def _create_connection_group(
        self
    ) -> QGroupBox:
        group = QGroupBox("Live connection")
        layout = QVBoxLayout(group)

        layout.addWidget(QLabel("Bind address"))
        layout.addWidget(
            self.bind_address_lineedit
        )

        layout.addWidget(QLabel("Data port"))
        layout.addWidget(
            self.data_port_spinbox
        )

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)

        layout.addLayout(button_layout)
        layout.addWidget(self.record_checkbox)
        layout.addWidget(self.status_label)

        return group

    def _create_smoothing_group(
        self
    ) -> QGroupBox:
        group = QGroupBox("Live smoothing")
        layout = QVBoxLayout(group)

        self.smoothing_seconds_spinbox.setMinimum(
            0.00
        )
        self.smoothing_seconds_spinbox.setMaximum(
            5.00
        )
        self.smoothing_seconds_spinbox.setSingleStep(
            0.05
        )
        self.smoothing_seconds_spinbox.setDecimals(2)
        self.smoothing_seconds_spinbox.setValue(0.25)
        self.smoothing_seconds_spinbox.setPrefix(
            "Window: "
        )
        self.smoothing_seconds_spinbox.setSuffix(
            " s"
        )
        self.smoothing_seconds_spinbox.setEnabled(
            False
        )

        layout.addWidget(self.smoothing_checkbox)
        layout.addWidget(
            self.smoothing_seconds_spinbox
        )

        return group

    def _connect_signals(self) -> None:
        self.smoothing_checkbox.stateChanged.connect(
            self.handle_smoothing_setting_changed
        )

        self.render_settings.resolution_combobox.currentTextChanged.connect(
            self.handle_render_setting_changed
        )

        self.render_settings.fps_combobox.currentTextChanged.connect(
            self.handle_render_setting_changed
        )



    def handle_smoothing_setting_changed(
        self,
        _state: int | None = None
    ) -> None:
        self.smoothing_seconds_spinbox.setEnabled(
            self.smoothing_checkbox.isChecked()
        )

    def handle_render_setting_changed(
        self,
        _value: str | None = None
    ) -> None:
        self.apply_preview_resolution()

    def apply_preview_resolution(self) -> None:
        resolution_text = (
            self.render_settings.resolution_combobox.currentText()
        )

        resolution = parse_resolution_option(
            resolution_text
        )

        if resolution is None:
            self.preview_scroll_area.setWidgetResizable(True)
            self.view_3d_widget.setMinimumSize(0, 0)
            self.view_3d_widget.setMaximumSize(
                16777215,
                16777215
            )
            self.view_3d_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding
            )

            self.render_settings.note_label.setText(
                "The live preview follows the available "
                "tab size. The live transport is not "
                "connected yet. "
                f"Global preview MSAA request: "
                f"{self.requested_msaa_samples}x."
            )
            return

        width, height = resolution

        self.preview_scroll_area.setWidgetResizable(False)
        self.view_3d_widget.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed
        )
        self.view_3d_widget.setFixedSize(
            width,
            height
        )

        center_scroll_area_on_widget(
            self.preview_scroll_area
        )

        QTimer.singleShot(
            0,
            partial(
                center_scroll_area_on_widget,
                self.preview_scroll_area
            )
        )

        QTimer.singleShot(
            50,
            partial(
                center_scroll_area_on_widget,
                self.preview_scroll_area
            )
        )

        self.render_settings.note_label.setText(
            f"Live preview framebuffer size requested: "
            f"{width} x {height}. Scrollbars appear when "
            "the preview is larger than the tab. The live "
            "transport is not connected yet. "
            f"Global preview MSAA request: "
            f"{self.requested_msaa_samples}x."
        )

    def set_global_msaa_samples(
        self,
        msaa_samples: int
    ) -> None:
        if msaa_samples == self.requested_msaa_samples:
            return

        old_view = self.view_3d_widget
        old_options = dict(old_view.opts)

        self.requested_msaa_samples = msaa_samples
        self.actual_msaa_samples = None

        detached_widget = self.preview_scroll_area.takeWidget()

        self.view_3d_widget = create_gl_view_widget(
            msaa_samples
        )

        self.view_3d_widget.opts["fov"] = old_options.get(
            "fov",
            self.view_3d_widget.opts["fov"]
        )

        self.view_3d_widget.setCameraPosition(
            pos=old_options.get("center"),
            distance=old_options.get("distance"),
            elevation=old_options.get("elevation"),
            azimuth=old_options.get("azimuth")
        )

        self.grid_3d = create_default_3d_grid()
        self.view_3d_widget.addItem(self.grid_3d)
        self.preview_scroll_area.setWidget(
            self.view_3d_widget
        )
        self.apply_preview_resolution()

        if detached_widget is not None:
            detached_widget.deleteLater()
        elif old_view is not None:
            old_view.deleteLater()

    def read_actual_msaa_samples(self) -> int | None:
        self.actual_msaa_samples = (
            read_gl_framebuffer_samples(
                self.view_3d_widget
            )
        )

        return self.actual_msaa_samples

    def shutdown(self) -> None:
        self.live_worker = None


class ExportTab(QWidget):

    def __init__(self) -> None:
        super().__init__()

        self.session: TrackingSession | None = None
        self.source_file_path: str | None = None
        self.output_file_path: str | None = None
        self.export_worker: object | None = None

        self.load_button = QPushButton(
            "Load Motive CSV"
        )

        self.source_status_label = QLabel(
            "No source CSV loaded."
        )
        self.source_status_label.setWordWrap(True)

        self.output_button = QPushButton(
            "Select output file"
        )

        self.output_status_label = QLabel(
            "No output file selected."
        )
        self.output_status_label.setWordWrap(True)

        self.smoothing_checkbox = QCheckBox(
            "Apply export smoothing"
        )

        self.smoothing_seconds_spinbox = (
            QDoubleSpinBox()
        )

        self.render_settings = RenderSettingsWidget(
            "Export render settings",
            "These settings belong only to this Export "
            "tab and will be passed to the offscreen "
            "renderer and encoder when they are added.",
            include_ssaa=True
        )
        self.render_settings.fps_combobox.setCurrentText(
            "60"
        )

        export_ssaa_combobox = (
            self.render_settings.ssaa_combobox
        )

        if export_ssaa_combobox is None:
            raise RuntimeError(
                "The Export render settings did not "
                "create an SSAA control."
            )

        export_ssaa_combobox.setCurrentText(
            "2x"
        )

        self.export_button = QPushButton(
            "Export video"
        )
        self.export_button.setEnabled(False)

        self.preview_label = QLabel(
            "Export preview and progress will appear here."
        )
        self.preview_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.preview_label.setWordWrap(True)

        self._build_layout()
        self._connect_signals()

    def _build_layout(self) -> None:
        settings_container = QWidget()
        settings_layout = QVBoxLayout(
            settings_container
        )
        settings_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop
        )

        settings_layout.addWidget(
            self._create_source_group()
        )

        settings_layout.addWidget(
            self._create_output_group()
        )

        settings_layout.addWidget(
            self._create_smoothing_group()
        )

        settings_layout.addWidget(
            self.render_settings
        )

        settings_layout.addWidget(
            self.export_button
        )

        settings_layout.addStretch()

        settings_scroll_area = QScrollArea()
        settings_scroll_area.setWidgetResizable(True)
        settings_scroll_area.setMinimumWidth(340)
        settings_scroll_area.setWidget(
            settings_container
        )

        layout = QHBoxLayout(self)
        layout.addWidget(settings_scroll_area)
        layout.addWidget(
            self.preview_label,
            stretch=1
        )

    def _create_source_group(
        self
    ) -> QGroupBox:
        group = QGroupBox("Export source")
        layout = QVBoxLayout(group)
        layout.addWidget(self.load_button)
        layout.addWidget(
            self.source_status_label
        )
        return group

    def _create_output_group(
        self
    ) -> QGroupBox:
        group = QGroupBox("Output file")
        layout = QVBoxLayout(group)
        layout.addWidget(self.output_button)
        layout.addWidget(
            self.output_status_label
        )
        return group

    def _create_smoothing_group(
        self
    ) -> QGroupBox:
        group = QGroupBox("Export smoothing")
        layout = QVBoxLayout(group)

        self.smoothing_seconds_spinbox.setMinimum(
            0.00
        )
        self.smoothing_seconds_spinbox.setMaximum(
            5.00
        )
        self.smoothing_seconds_spinbox.setSingleStep(
            0.05
        )
        self.smoothing_seconds_spinbox.setDecimals(2)
        self.smoothing_seconds_spinbox.setValue(0.25)
        self.smoothing_seconds_spinbox.setPrefix(
            "Window: "
        )
        self.smoothing_seconds_spinbox.setSuffix(
            " s"
        )
        self.smoothing_seconds_spinbox.setEnabled(
            False
        )

        layout.addWidget(self.smoothing_checkbox)
        layout.addWidget(
            self.smoothing_seconds_spinbox
        )

        return group

    def _connect_signals(self) -> None:
        self.load_button.clicked.connect(
            self.load_source_csv
        )

        self.output_button.clicked.connect(
            self.select_output_file
        )

        self.smoothing_checkbox.stateChanged.connect(
            self.handle_smoothing_setting_changed
        )

        self.export_button.clicked.connect(
            self.start_export
        )

    def load_source_csv(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Motive CSV",
            "",
            "CSV files (*.csv);;All files (*)"
        )

        if not file_path:
            return

        try:
            session = load_motive_rigid_body_csv(
                file_path
            )

        except Exception as exc:
            self.source_status_label.setText(
                f"Error loading CSV: {exc}"
            )
            return

        self.set_session(
            session,
            source_file_path=file_path
        )

    def set_session(
        self,
        session: TrackingSession,
        source_file_path: str | None = None
    ) -> None:
        self.session = session
        self.source_file_path = source_file_path

        if len(session.time) == 0:
            duration_s = 0.0
        else:
            duration_s = float(session.time[-1])

        source_text = (
            source_file_path
            if source_file_path is not None
            else "Session supplied externally"
        )

        self.source_status_label.setText(
            f"{source_text}\n"
            f"{len(session.bodies)} rigid bodies | "
            f"{duration_s:.3f} s"
        )

        self._update_export_button()

    def select_output_file(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Select export file",
            "",
            "MP4 video (*.mp4);;All files (*)"
        )

        if not file_path:
            return

        self.output_file_path = file_path
        self.output_status_label.setText(file_path)
        self._update_export_button()

    def handle_smoothing_setting_changed(
        self,
        _state: int | None = None
    ) -> None:
        self.smoothing_seconds_spinbox.setEnabled(
            self.smoothing_checkbox.isChecked()
        )

    def _update_export_button(self) -> None:
        self.export_button.setEnabled(
            self.session is not None
            and self.output_file_path is not None
        )

    def start_export(self) -> None:
        if (
            self.session is None
            or self.output_file_path is None
        ):
            return

        self.preview_label.setText(
            "The export workspace is configured, but "
            "offscreen rendering and video encoding are "
            "not implemented yet."
        )

    def shutdown(self) -> None:
        self.export_worker = None


class WorkspaceMainWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle(
            "OptiTrack Motion Workspace"
        )
        self.resize(1500, 900)

        self.global_msaa_samples = (
            DEFAULT_PLAYBACK_MSAA_SAMPLES
        )

        self.workspace_counts: dict[
            WorkspaceType,
            int
        ] = {
            "signals": 0,
            "recorded_3d": 0,
            "live": 0,
            "export": 0
        }

        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setTabsClosable(True)
        self.workspace_tabs.setMovable(True)
        self.workspace_tabs.setDocumentMode(True)
        self.workspace_tabs.tabCloseRequested.connect(
            self.close_workspace_tab
        )
        self.workspace_tabs.currentChanged.connect(
            self.handle_current_workspace_changed
        )

        self.setCentralWidget(
            self.workspace_tabs
        )

        self._create_workspace_toolbar()
        self.create_workspace("signals")

    def _create_workspace_toolbar(self) -> None:
        toolbar = QToolBar("Workspaces")
        toolbar.setMovable(False)

        self.addToolBar(
            Qt.ToolBarArea.TopToolBarArea,
            toolbar
        )

        new_tab_button = QToolButton()
        new_tab_button.setText("New tab")
        new_tab_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )

        new_tab_menu = QMenu(new_tab_button)

        signals_action = new_tab_menu.addAction(
            "Signals plot"
        )
        signals_action.triggered.connect(
            partial(
                self.create_workspace,
                "signals"
            )
        )

        recorded_3d_action = new_tab_menu.addAction(
            "Recorded 3D playback"
        )
        recorded_3d_action.triggered.connect(
            partial(
                self.create_workspace,
                "recorded_3d"
            )
        )

        live_action = new_tab_menu.addAction(
            "Live playback"
        )
        live_action.triggered.connect(
            partial(
                self.create_workspace,
                "live"
            )
        )

        export_action = new_tab_menu.addAction(
            "Video export"
        )
        export_action.triggered.connect(
            partial(
                self.create_workspace,
                "export"
            )
        )

        new_tab_button.setMenu(new_tab_menu)
        toolbar.addWidget(new_tab_button)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Preview MSAA"))

        self.global_msaa_combobox = QComboBox()
        self.global_msaa_combobox.addItems(
            MSAA_OPTIONS
        )
        self.global_msaa_combobox.setCurrentText(
            f"{self.global_msaa_samples}x"
        )
        self.global_msaa_combobox.currentTextChanged.connect(
            self.handle_global_msaa_changed
        )
        toolbar.addWidget(
            self.global_msaa_combobox
        )

        self.global_msaa_status_label = QLabel(
            "Requested 4x; actual pending"
        )
        self.global_msaa_status_label.setMinimumWidth(
            230
        )
        toolbar.addWidget(
            self.global_msaa_status_label
        )

        toolbar.addSeparator()

        close_tab_button = QPushButton(
            "Close current tab"
        )
        close_tab_button.clicked.connect(
            self.close_current_workspace
        )
        toolbar.addWidget(close_tab_button)

    def create_workspace(
        self,
        workspace_type: WorkspaceType,
        _checked: bool | None = None
    ) -> None:
        self.workspace_counts[workspace_type] += 1
        workspace_number = self.workspace_counts[
            workspace_type
        ]

        if workspace_type == "signals":
            workspace = SignalPlotTab()
            base_title = "Signals"

        elif workspace_type == "recorded_3d":
            workspace = Recorded3DPlaybackTab(
                self.global_msaa_samples
            )
            base_title = "Recorded 3D"

        elif workspace_type == "live":
            workspace = LivePlaybackTab(
                self.global_msaa_samples
            )
            base_title = "Live"

        elif workspace_type == "export":
            workspace = ExportTab()
            base_title = "Export"

        else:
            raise ValueError(
                f"Unsupported workspace type: "
                f"{workspace_type!r}"
            )

        tab_title = (
            f"{base_title} {workspace_number}"
        )

        tab_index = self.workspace_tabs.addTab(
            workspace,
            tab_title
        )

        self.workspace_tabs.setCurrentIndex(
            tab_index
        )

        QTimer.singleShot(
            250,
            self.verify_global_msaa
        )

    def handle_global_msaa_changed(
        self,
        msaa_text: str
    ) -> None:
        if msaa_text == "Off":
            requested_samples = 0
        else:
            requested_samples = int(
                msaa_text.removesuffix("x")
            )

        self.global_msaa_samples = requested_samples
        configure_default_opengl_format(
            requested_samples
        )

        self.global_msaa_status_label.setText(
            f"Applying {requested_samples}x; "
            "actual pending"
        )

        for tab_index in range(
                self.workspace_tabs.count()
        ):
            workspace = self.workspace_tabs.widget(
                tab_index
            )

            if isinstance(
                workspace,
                Recorded3DPlaybackTab
            ):
                workspace.set_global_msaa_samples(
                    requested_samples
                )

            elif isinstance(
                workspace,
                LivePlaybackTab
            ):
                workspace.set_global_msaa_samples(
                    requested_samples
                )

        QTimer.singleShot(
            250,
            self.verify_global_msaa
        )
        QTimer.singleShot(
            1000,
            self.verify_global_msaa
        )

    def handle_current_workspace_changed(
        self,
        _tab_index: int
    ) -> None:
        QTimer.singleShot(
            250,
            self.verify_global_msaa
        )

    def verify_global_msaa(self) -> None:
        actual_values: list[int] = []
        pending_count = 0
        preview_count = 0

        for tab_index in range(
                self.workspace_tabs.count()
        ):
            workspace = self.workspace_tabs.widget(
                tab_index
            )

            if isinstance(
                workspace,
                Recorded3DPlaybackTab
            ):
                preview_count += 1
                actual_samples = (
                    workspace.read_actual_msaa_samples()
                )

            elif isinstance(
                workspace,
                LivePlaybackTab
            ):
                preview_count += 1
                actual_samples = (
                    workspace.read_actual_msaa_samples()
                )

            else:
                continue

            if actual_samples is None:
                pending_count += 1
            else:
                actual_values.append(actual_samples)

        requested = self.global_msaa_samples
        requested_text = (
            "Off"
            if requested == 0
            else f"{requested}x"
        )

        if preview_count == 0:
            self.global_msaa_status_label.setText(
                f"Requested {requested_text}; "
                "no 3D preview open"
            )
            return

        if not actual_values:
            self.global_msaa_status_label.setText(
                f"Requested {requested_text}; "
                "actual pending"
            )
            return

        unique_actual_values = sorted(
            set(actual_values)
        )
        actual_text = ", ".join(
            "Off" if value == 0 else f"{value}x"
            for value in unique_actual_values
        )

        mismatch = any(
            value != requested
            for value in actual_values
        )

        if mismatch:
            status_text = (
                f"Warning: requested {requested_text}; "
                f"actual {actual_text}"
            )
        else:
            status_text = (
                f"Requested {requested_text}; "
                f"actual {actual_text}"
            )

        if pending_count:
            status_text += (
                f"; {pending_count} preview(s) pending"
            )

        self.global_msaa_status_label.setText(
            status_text
        )

    def close_current_workspace(self) -> None:
        current_index = (
            self.workspace_tabs.currentIndex()
        )

        if current_index < 0:
            return

        self.close_workspace_tab(
            current_index
        )

    def close_workspace_tab(
        self,
        tab_index: int
    ) -> None:
        workspace = self.workspace_tabs.widget(
            tab_index
        )

        if workspace is None:
            return

        self.workspace_tabs.removeTab(tab_index)
        self._shutdown_workspace(workspace)
        workspace.deleteLater()

    def _shutdown_workspace(
        self,
        workspace: QWidget
    ) -> None:
        if isinstance(
            workspace,
            Recorded3DPlaybackTab
        ):
            workspace.shutdown()

        elif isinstance(
            workspace,
            LivePlaybackTab
        ):
            workspace.shutdown()

        elif isinstance(
            workspace,
            ExportTab
        ):
            workspace.shutdown()

    def closeEvent(
        self,
        event: QCloseEvent
    ) -> None:
        for tab_index in range(
            self.workspace_tabs.count() - 1,
            -1,
            -1
        ):
            workspace = self.workspace_tabs.widget(
                tab_index
            )

            if workspace is not None:
                self._shutdown_workspace(workspace)

        super().closeEvent(event)


def main() -> None:
    configure_default_opengl_format(
        DEFAULT_PLAYBACK_MSAA_SAMPLES
    )

    app = QApplication(sys.argv)

    window = WorkspaceMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
