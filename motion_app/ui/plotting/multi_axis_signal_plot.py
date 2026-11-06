from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from pyqtgraph.graphicsItems.AxisItem import AxisItem
from pyqtgraph.graphicsItems.PlotDataItem import PlotDataItem
from pyqtgraph.graphicsItems.PlotItem.PlotItem import PlotItem
from pyqtgraph.graphicsItems.ViewBox.ViewBox import ViewBox
from PySide6.QtWidgets import QGraphicsGridLayout, QGraphicsScene, QGraphicsView, QGraphicsWidget, QWidget, QVBoxLayout

from motion_app.core.app_types import CurveSpec, SignalDataType


class MultiAxisSignalPlot(QWidget):
    """Reusable PyQtGraph plot with position, Euler, and quaternion Y axes."""

    def __init__(self) -> None:
        super().__init__()
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("w")
        plot_item = self.plot_widget.getPlotItem()
        if plot_item is None:
            raise RuntimeError("The PlotWidget did not create a PlotItem.")
        self.plot_item: PlotItem = plot_item
        self.plot_item.showGrid(x=True, y=True)
        self.plot_item.setLabel("bottom", "Time", units="s")
        self.legend = self.plot_item.addLegend()
        self.viewboxes: dict[SignalDataType, ViewBox] = {}
        self.curves: dict[SignalDataType, list[PlotDataItem]] = {"position": [], "euler": [], "quaternion": []}
        self.base_ranges: dict[SignalDataType, tuple[float, float] | None] = {
            "position": None, "euler": None, "quaternion": None
        }
        self.scale_factors: dict[SignalDataType, float] = {"position": 1.0, "euler": 1.0, "quaternion": 1.0}
        self._create_axes()
        QVBoxLayout(self).addWidget(self.plot_widget)

    def _create_axes(self) -> None:
        position_viewbox = self.plot_item.getViewBox()
        position_axis = self.plot_item.getAxis("left")
        position_axis.setLabel("Position", units="m")

        self.plot_item.showAxis("right")
        euler_axis = self.plot_item.getAxis("right")
        euler_axis.setLabel("Euler angle", units="deg")
        euler_viewbox = ViewBox()

        scene: QGraphicsScene | None = QGraphicsView.scene(self.plot_widget)
        if scene is None:
            raise RuntimeError("The PlotWidget is not attached to a graphics scene.")
        scene.addItem(euler_viewbox)
        euler_axis.linkToView(euler_viewbox)
        euler_viewbox.setXLink(position_viewbox)

        quaternion_axis = AxisItem(orientation="right")
        quaternion_axis.setLabel("Quaternion")
        plot_layout = QGraphicsWidget.layout(self.plot_item)
        if not isinstance(plot_layout, QGraphicsGridLayout):
            raise RuntimeError("The PlotItem does not contain a QGraphicsGridLayout.")
        plot_layout.addItem(quaternion_axis, 2, 3)
        quaternion_viewbox = ViewBox()
        scene.addItem(quaternion_viewbox)
        quaternion_axis.linkToView(quaternion_viewbox)
        quaternion_viewbox.setXLink(position_viewbox)

        self.viewboxes = {
            "position": position_viewbox,
            "euler": euler_viewbox,
            "quaternion": quaternion_viewbox,
        }
        position_viewbox.sigResized.connect(self._sync_viewboxes)
        self._sync_viewboxes()

    def _sync_viewboxes(self, _source: ViewBox | None = None) -> None:
        primary = self.viewboxes["position"]
        geometry = primary.sceneBoundingRect()
        for data_type in ("euler", "quaternion"):
            viewbox = self.viewboxes[data_type]
            viewbox.setGeometry(geometry)
            viewbox.linkedViewChanged(primary, ViewBox.XAxis)

    def set_x_range(self, start_time: float, end_time: float) -> None:
        if end_time <= start_time:
            end_time = start_time + 1.0
        self.viewboxes["position"].setXRange(start_time, end_time, padding=0.0)

    def set_curves(self, specs: list[CurveSpec]) -> None:
        self.clear()
        values_by_type: dict[SignalDataType, list[np.ndarray]] = {
            "position": [], "euler": [], "quaternion": []
        }
        for spec in specs:
            curve = PlotDataItem(
                x=spec.x,
                y=spec.y,
                pen=pg.mkPen(color=spec.color, width=2),
                name=spec.name,
                connect="finite",
            )
            self.viewboxes[spec.data_type].addItem(curve)
            self.legend.addItem(curve, spec.name)
            self.curves[spec.data_type].append(curve)
            values_by_type[spec.data_type].append(spec.y)
        self._calculate_ranges(values_by_type)

    def clear(self) -> None:
        for data_type, curves in self.curves.items():
            viewbox = self.viewboxes[data_type]
            for curve in curves:
                viewbox.removeItem(curve)
                self.legend.removeItem(curve)
            curves.clear()
            self.base_ranges[data_type] = None

    def has_data(self, data_type: SignalDataType) -> bool:
        return self.base_ranges[data_type] is not None

    def set_axis_scale(self, data_type: SignalDataType, scale: float) -> None:
        if scale <= 0:
            raise ValueError("Axis scale must be greater than zero.")
        self.scale_factors[data_type] = float(scale)
        base_range = self.base_ranges[data_type]
        if base_range is None:
            return
        low, high = base_range
        center = (low + high) / 2.0
        half_span = (high - low) / 2.0 / scale
        self.viewboxes[data_type].setYRange(center - half_span, center + half_span, padding=0.0)

    def _calculate_ranges(self, values_by_type: dict[SignalDataType, list[np.ndarray]]) -> None:
        for data_type, arrays in values_by_type.items():
            finite_arrays = [np.asarray(values)[np.isfinite(values)] for values in arrays]
            finite_arrays = [values for values in finite_arrays if values.size]
            if not finite_arrays:
                self.base_ranges[data_type] = None
                continue
            minimum = min(float(np.min(values)) for values in finite_arrays)
            maximum = max(float(np.max(values)) for values in finite_arrays)
            center = (minimum + maximum) / 2.0
            half_span = (maximum - minimum) / 2.0
            half_span = max(abs(center) * 0.05, 0.05) if half_span <= 0 else half_span * 1.05
            self.base_ranges[data_type] = center - half_span, center + half_span
            self.set_axis_scale(data_type, self.scale_factors[data_type])
