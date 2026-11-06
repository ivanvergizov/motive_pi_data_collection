"""Shared visual constants for every PyVista/VTK 3D view."""

REFERENCE_DPI = 72.0
REFERENCE_VIEWPORT_HEIGHT_DIP = 1080.0

# Text sizes are defined for a 1080-DIP-tall viewport.  Interactive views scale
# them with the persistent Qt scene widget, not the replaceable VTK interactor,
# so rebuilding the renderer for AA cannot temporarily shrink the labels.
# The render-window DPI then converts those logical sizes to physical pixels.
AXIS_TEXT_HEIGHT_DIP_AT_REFERENCE = 12.0
BODY_LABEL_FONT_SIZE_PT_AT_REFERENCE = 15.0
BODY_LABEL_OFFSET_DIP_AT_REFERENCE = 6.0
AXIS_LABEL_OFFSET_DIP_AT_REFERENCE = 20.0
AXIS_TITLE_OFFSET_DIP_AT_REFERENCE = 20.0

AXIS_COLOR = (0.30, 0.30, 0.30)
GRID_COLOR = (0.68, 0.68, 0.68)

DEFAULT_CAMERA_VIEW_ANGLE = 30.0

# Move the default camera and focal point downward together by this fraction of
# the room height.  The camera direction and perspective stay unchanged while
# the room appears slightly higher in the viewport.
ROOM_VERTICAL_CAMERA_SHIFT_FRACTION = 1.0 / 8.0
