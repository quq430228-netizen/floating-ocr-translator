from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QMimeData,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def paint_translate_glyph(painter: QPainter, center: QPointF, scale: float, color: QColor) -> None:
    """Draw a crisp bilingual '译' emblem centered at `center`."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(max(12, int(round(20 * scale))))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(color)
    rect = QRectF(center.x() - 18 * scale, center.y() - 18 * scale, 36 * scale, 36 * scale)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "译")
    painter.restore()


def create_app_icon(size: int = 64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    rect = QRectF(3, 3, size - 6, size - 6)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#10B981"))
    grad.setColorAt(1.0, QColor("#0F766E"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawEllipse(rect)

    paint_translate_glyph(painter, rect.center(), scale=size / 44.0, color=QColor("#FFFFFF"))
    painter.end()
    return QIcon(pixmap)


def create_image_button_icon(color: str = "#CBD5E1", size: int = 18) -> QIcon:
    """Draw a clean vector picture/gallery icon."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    c = QColor(color)
    pen = QPen(c, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    frame = QRectF(2.2, 3.0, size - 4.4, size - 6.0)
    painter.drawRoundedRect(frame, 2.5, 2.5)

    # Tiny sun dot
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(c)
    painter.drawEllipse(QPointF(size * 0.34, size * 0.42), 1.4, 1.4)

    # Mountain silhouette
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(frame.left() + 1.5, frame.bottom() - 1.5)
    path.lineTo(frame.left() + frame.width() * 0.42, frame.top() + frame.height() * 0.52)
    path.lineTo(frame.left() + frame.width() * 0.62, frame.top() + frame.height() * 0.72)
    path.lineTo(frame.left() + frame.width() * 0.78, frame.top() + frame.height() * 0.46)
    path.lineTo(frame.right() - 1.5, frame.bottom() - 1.5)
    painter.drawPath(path)

    painter.end()
    return QIcon(pixmap)


def create_paste_button_icon(color: str = "#FFFFFF", size: int = 16) -> QIcon:
    """Draw a clean vector clipboard/spark icon for the paste-translate CTA."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    c = QColor(color)
    pen = QPen(c, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    board = QRectF(3.0, 3.2, size - 6.0, size - 4.8)
    painter.drawRoundedRect(board, 2.2, 2.2)

    clip = QRectF(size * 0.33, 1.6, size * 0.34, 2.8)
    painter.setBrush(c)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(clip, 1.2, 1.2)

    painter.setPen(pen)
    painter.drawLine(QPointF(5.5, size * 0.55), QPointF(size - 5.5, size * 0.55))
    painter.drawLine(QPointF(5.5, size * 0.75), QPointF(size - 7.0, size * 0.75))

    painter.end()
    return QIcon(pixmap)


def clamp_window_to_desktop(pos: QPoint, size: QSize) -> QPoint:
    center = QPoint(pos.x() + size.width() // 2, pos.y() + size.height() // 2)
    screen = QApplication.screenAt(center) or QApplication.primaryScreen()
    if screen is None:
        return pos
    avail = screen.availableGeometry()
    x = max(avail.left(), min(pos.x(), avail.right() - size.width() + 1))
    y = max(avail.top(), min(pos.y(), avail.bottom() - size.height() + 1))
    return QPoint(x, y)


def extract_image_path_from_mime(mime: QMimeData) -> Optional[str]:
    if mime.hasUrls():
        for url in mime.urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.suffix.lower() in IMAGE_EXTS and p.exists():
                    return str(p)
    return None


class ElidedLabel(QLabel):
    """Single-line label that elides overflow with '…' instead of widening its parent window."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None, shrink_only: bool = False) -> None:
        super().__init__(parent)
        self._full_text = text or ""
        h_policy = QSizePolicy.Policy.Maximum if shrink_only else QSizePolicy.Policy.Ignored
        self.setSizePolicy(h_policy, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self._sync_tooltip()

    def text(self) -> str:
        return self._full_text

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text or ""
        self._sync_tooltip()
        self.updateGeometry()
        self.update()

    def _single_line_text(self) -> str:
        return " ".join(self._full_text.splitlines()).strip()

    def _sync_tooltip(self) -> None:
        display = self._single_line_text()
        if not display:
            self.setToolTip("")
            return
        avail = self.contentsRect().width()
        if (avail > 0 and self.fontMetrics().horizontalAdvance(display) > avail) or "\n" in self._full_text:
            self.setToolTip(self._full_text)
        else:
            self.setToolTip("")

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, max(16, self.fontMetrics().height() + 2))

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self.fontMetrics()
        display = self._single_line_text()
        return QSize(fm.horizontalAdvance(display) + 2, max(18, fm.height() + 2))

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        self._sync_tooltip()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        rect = self.contentsRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        elided = self.fontMetrics().elidedText(
            self._single_line_text(),
            Qt.TextElideMode.ElideRight,
            rect.width(),
        )
        self.style().drawItemText(
            painter,
            rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine),
            self.palette(),
            self.isEnabled(),
            elided,
            self.foregroundRole(),
        )


class SmartTranslateEdit(QPlainTextEdit):
    """QPlainTextEdit that intercepts Ctrl+V for images/text and supports Drag & Drop."""

    image_pasted = Signal(QImage)
    image_file_dropped = Signal(str)
    text_pasted = Signal(str)
    translate_shortcut_pressed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        if source.hasImage() or extract_image_path_from_mime(source) is not None:
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        img_path = extract_image_path_from_mime(source)
        if img_path:
            self.image_file_dropped.emit(img_path)
            return
        if source.hasImage():
            img = source.imageData()
            if isinstance(img, QPixmap) and not img.isNull():
                self.image_pasted.emit(img.toImage())
                return
            if isinstance(img, QImage) and not img.isNull():
                self.image_pasted.emit(img)
                return
        if source.hasText():
            text = source.text().strip()
            if text:
                self.text_pasted.emit(text)
                return
        super().insertFromMimeData(source)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime.hasImage() or extract_image_path_from_mime(mime) or mime.hasText():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        img_path = extract_image_path_from_mime(mime)
        if img_path:
            self.image_file_dropped.emit(img_path)
            event.acceptProposedAction()
            return
        if mime.hasImage():
            img = mime.imageData()
            if isinstance(img, QPixmap) and not img.isNull():
                self.image_pasted.emit(img.toImage())
                event.acceptProposedAction()
                return
            if isinstance(img, QImage) and not img.isNull():
                self.image_pasted.emit(img)
                event.acceptProposedAction()
                return
        if mime.hasText():
            text = mime.text().strip()
            if text:
                self.text_pasted.emit(text)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001, N802
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            self.translate_shortcut_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class FloatingTranslateOrb(QWidget):
    """Collapsed circular translate floating icon — draggable anywhere, click to expand."""

    clicked = Signal()
    position_changed = Signal(int, int)
    reset_position_requested = Signal()
    auto_clipboard_toggled = Signal(bool)
    auto_swap_toggled = Signal(bool)
    quit_requested = Signal()

    ORB_DIAMETER = 54
    CANVAS_SIZE = 74

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(self.CANVAS_SIZE, self.CANVAS_SIZE)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("点击展开翻译悬浮窗 · 按住拖动位置")

        self._hovered = False
        self._pressed = False
        self._busy = False
        self._auto_clipboard = False
        self._auto_swap = False
        self._dragging = False
        self._allow_close = False
        self._press_global = QPoint()
        self._drag_offset = QPoint()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.update()

    def set_options(self, auto_clipboard: bool, auto_swap: bool) -> None:
        self._auto_clipboard = auto_clipboard
        self._auto_swap = auto_swap

    def enterEvent(self, event) -> None:  # noqa: ANN001, N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001, N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._dragging = False
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = self._press_global - self.frameGeometry().topLeft()
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._pressed and (event.buttons() & Qt.MouseButton.LeftButton):
            cur = event.globalPosition().toPoint()
            if not self._dragging and (cur - self._press_global).manhattanLength() >= 6:
                self._dragging = True
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            if self._dragging:
                target = clamp_window_to_desktop(cur - self._drag_offset, self.size())
                self.move(target)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            was_dragging = self._dragging
            self._pressed = False
            self._dragging = False
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.update()
            if was_dragging:
                self.position_changed.emit(self.x(), self.y())
            else:
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #1A2232;
                color: #F1F5F9;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 10px;
                padding: 5px;
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
            }
            QMenu::item {
                padding: 6px 16px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #0D9488;
                color: #FFFFFF;
            }
            """
        )
        act_open = QAction("展开翻译窗", menu)
        act_open.triggered.connect(self.clicked.emit)
        menu.addAction(act_open)

        act_auto = QAction("自动监听剪贴板翻译", menu)
        act_auto.setCheckable(True)
        act_auto.setChecked(self._auto_clipboard)
        act_auto.triggered.connect(
            lambda _checked=False, a=act_auto: self.auto_clipboard_toggled.emit(a.isChecked())
        )
        menu.addAction(act_auto)

        act_swap = QAction("智能中英互译", menu)
        act_swap.setCheckable(True)
        act_swap.setChecked(self._auto_swap)
        act_swap.triggered.connect(
            lambda _checked=False, a=act_swap: self.auto_swap_toggled.emit(a.isChecked())
        )
        menu.addAction(act_swap)

        act_reset = QAction("重置默认位置", menu)
        act_reset.triggered.connect(self.reset_position_requested.emit)
        menu.addAction(act_reset)

        menu.addSeparator()

        act_quit = QAction("退出程序", menu)
        act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(act_quit)

        menu.exec(global_pos)

    def allow_close(self) -> None:
        self._allow_close = True

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        if not self._allow_close:
            event.ignore()
            self.show()
            return
        super().closeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        r = self.ORB_DIAMETER / 2.0

        # Soft painted elevation shadow
        shadow_grad = QRadialGradient(QPointF(cx, cy + 3.0), r + 9.0)
        shadow_grad.setColorAt(0.0, QColor(0, 0, 0, 125))
        shadow_grad.setColorAt(0.68, QColor(0, 0, 0, 55))
        shadow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow_grad)
        painter.drawEllipse(QPointF(cx, cy + 3.0), r + 9.0, r + 9.0)

        # Main circular orb
        orb_rect = QRectF(cx - r, cy - r, self.ORB_DIAMETER, self.ORB_DIAMETER)
        grad = QLinearGradient(orb_rect.topLeft(), orb_rect.bottomRight())
        if self._busy:
            grad.setColorAt(0.0, QColor("#F59E0B"))
            grad.setColorAt(1.0, QColor("#D97706"))
        elif self._pressed:
            grad.setColorAt(0.0, QColor("#0D9488"))
            grad.setColorAt(1.0, QColor("#115E59"))
        elif self._hovered:
            grad.setColorAt(0.0, QColor("#34D399"))
            grad.setColorAt(1.0, QColor("#0D9488"))
        else:
            grad.setColorAt(0.0, QColor("#10B981"))
            grad.setColorAt(1.0, QColor("#0F766E"))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawEllipse(orb_rect)

        rim_alpha = 115 if self._hovered else 72
        painter.setPen(QPen(QColor(255, 255, 255, rim_alpha), 1.3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(orb_rect.adjusted(0.8, 0.8, -0.8, -0.8))

        paint_translate_glyph(painter, QPointF(cx, cy), scale=1.12, color=QColor("#FFFFFF"))


class ExpandedTranslatePanel(QWidget):
    """Expanded rounded-rectangle translator card occupying ~1/16 of the screen."""

    collapse_requested = Signal()
    paste_translate_requested = Signal()
    pick_image_requested = Signal()
    toggle_source_view_requested = Signal(bool)
    copy_requested = Signal()
    clear_requested = Signal()
    image_pasted = Signal(QImage)
    image_file_dropped = Signal(str)
    text_pasted = Signal(str)
    translate_current_text_requested = Signal()
    auto_clipboard_toggled = Signal(bool)
    auto_swap_toggled = Signal(bool)
    panel_moved = Signal(int, int)

    SHADOW_MARGIN = 12
    CORNER_RADIUS = 18

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)

        self._dragging = False
        self._allow_close = False
        self._drag_offset = QPoint()
        self._busy = False
        self._showing_source = False
        self._auto_clipboard = False
        self._auto_swap = False

        self._img_icon = create_image_button_icon("#CBD5E1", 16)
        self._paste_icon = create_paste_button_icon("#FFFFFF", 16)

        self._copy_feedback_timer = QTimer(self)
        self._copy_feedback_timer.setSingleShot(True)
        self._copy_feedback_timer.setInterval(1800)
        self._copy_feedback_timer.timeout.connect(self._reset_copy_button)

        self._build_ui()
        self._apply_styles()

        screen = QApplication.primaryScreen()
        if screen is not None:
            self.setFixedSize(self.compute_target_size(screen.geometry()))

    def compute_target_size(self, screen_geo: QRect) -> QSize:
        card_w = max(390, min(560, int(round(screen_geo.width() / 4.0))))
        card_h = max(236, min(340, int(round(screen_geo.height() / 4.0))))
        return QSize(card_w + self.SHADOW_MARGIN * 2, card_h + self.SHADOW_MARGIN * 2)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        m = self.SHADOW_MARGIN
        outer.setContentsMargins(m + 14, m + 11, m + 14, m + 13)
        outer.setSpacing(10)

        # Top header bar (draggable)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self._status_dot = QLabel()
        self._status_dot.setFixedSize(9, 9)
        self._status_dot.setObjectName("statusDot")

        self._status_label = ElidedLabel("就绪 · 粘贴文字或图片即可翻译")
        self._status_label.setObjectName("statusLabel")

        self._pick_img_btn = QPushButton()
        self._pick_img_btn.setObjectName("iconBtn")
        self._pick_img_btn.setIcon(self._img_icon)
        self._pick_img_btn.setIconSize(QSize(16, 16))
        self._pick_img_btn.setFixedSize(28, 28)
        self._pick_img_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._pick_img_btn.setToolTip("选择本地图片识别并翻译（也支持直接拖入或 Ctrl+V 粘贴截图）")
        self._pick_img_btn.clicked.connect(self.pick_image_requested.emit)

        self._source_btn = QPushButton("原")
        self._source_btn.setObjectName("sourceBtn")
        self._source_btn.setCheckable(True)
        self._source_btn.setFixedSize(28, 28)
        self._source_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._source_btn.setToolTip("切换查看原文 / 译文")
        self._source_btn.toggled.connect(self._on_source_toggled)

        self._collapse_btn = QPushButton("—")
        self._collapse_btn.setObjectName("iconBtn")
        self._collapse_btn.setFixedSize(28, 28)
        self._collapse_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._collapse_btn.setToolTip("收起为圆形翻译图标 (Esc)")
        self._collapse_btn.clicked.connect(self.collapse_requested.emit)

        header.addWidget(self._status_dot)
        header.addWidget(self._status_label, 1)
        header.addWidget(self._pick_img_btn)
        header.addWidget(self._source_btn)
        header.addWidget(self._collapse_btn)
        outer.addLayout(header)

        # Smart text & image drop/paste area
        self._text_edit = SmartTranslateEdit()
        self._text_edit.setObjectName("transcriptEdit")
        self._text_edit.setPlaceholderText(
            "复制英文文字或截图后，点下方「粘贴翻译」、按 Ctrl+V，或直接拖入图片…"
        )
        self._text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._text_edit.image_pasted.connect(self.image_pasted.emit)
        self._text_edit.image_file_dropped.connect(self.image_file_dropped.emit)
        self._text_edit.text_pasted.connect(self.text_pasted.emit)
        self._text_edit.translate_shortcut_pressed.connect(self.translate_current_text_requested.emit)
        outer.addWidget(self._text_edit, 1)

        # Ergonomic bottom action bar: [复制 (~50%)] [粘贴翻译] [清空]
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        self._copy_btn = QPushButton("复制")
        self._copy_btn.setObjectName("copyBtn")
        self._copy_btn.setFixedHeight(38)
        self._copy_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._copy_btn.clicked.connect(self.copy_requested.emit)

        self._paste_btn = QPushButton(" 粘贴翻译")
        self._paste_btn.setObjectName("pasteBtn")
        self._paste_btn.setIcon(self._paste_icon)
        self._paste_btn.setIconSize(QSize(15, 15))
        self._paste_btn.setFixedHeight(38)
        self._paste_btn.setMinimumWidth(116)
        self._paste_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._paste_btn.setToolTip("读取剪贴板中的英文文字或截图并翻译为中文")
        self._paste_btn.clicked.connect(self.paste_translate_requested.emit)

        self._clear_btn = QPushButton("清空")
        self._clear_btn.setObjectName("clearBtn")
        self._clear_btn.setFixedHeight(38)
        self._clear_btn.setFixedWidth(56)
        self._clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._clear_btn.clicked.connect(self.clear_requested.emit)

        actions.addWidget(self._copy_btn, 5)
        actions.addWidget(self._paste_btn, 4)
        actions.addWidget(self._clear_btn, 0)
        outer.addLayout(actions)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
            }
            #statusLabel {
                color: #CBD5E1;
                font-size: 12.5px;
                font-weight: 500;
            }
            #iconBtn, #sourceBtn {
                background-color: rgba(255, 255, 255, 0.06);
                color: #CBD5E1;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                font-size: 12.5px;
                font-weight: 600;
            }
            #iconBtn:hover, #sourceBtn:hover {
                background-color: rgba(255, 255, 255, 0.14);
                color: #FFFFFF;
            }
            #iconBtn:pressed, #sourceBtn:pressed {
                background-color: rgba(255, 255, 255, 0.2);
            }
            #sourceBtn:checked {
                background-color: rgba(16, 185, 129, 0.26);
                border: 1px solid rgba(52, 211, 153, 0.65);
                color: #A7F3D0;
            }
            #transcriptEdit {
                background-color: rgba(9, 13, 21, 215);
                color: #F8FAFC;
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 12px;
                padding: 9px 11px;
                font-size: 14.5px;
                selection-background-color: #0D9488;
                selection-color: #FFFFFF;
            }
            #transcriptEdit:focus {
                border: 1px solid rgba(52, 211, 153, 0.55);
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 4px 1px 4px 1px;
            }
            QScrollBar::handle:vertical {
                background: rgba(148, 163, 184, 0.35);
                border-radius: 3px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(148, 163, 184, 0.6);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            #pasteBtn {
                background-color: #0D9488;
                color: #FFFFFF;
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 600;
                padding: 0 12px;
            }
            #pasteBtn:hover {
                background-color: #14B8A6;
            }
            #pasteBtn:pressed {
                background-color: #0F766E;
            }
            #pasteBtn:disabled {
                background-color: #334155;
                color: #94A3B8;
            }
            #copyBtn {
                background-color: #243044;
                color: #F8FAFC;
                border: 1px solid rgba(255, 255, 255, 0.11);
                border-radius: 10px;
                font-size: 13.5px;
                font-weight: 600;
                padding: 0 14px;
            }
            #copyBtn:hover {
                background-color: #30405A;
            }
            #copyBtn:pressed {
                background-color: #1E293B;
            }
            #copyBtn[copied="true"] {
                background-color: #059669;
                border-color: #10B981;
                color: #FFFFFF;
            }
            #clearBtn {
                background-color: rgba(255, 255, 255, 0.05);
                color: #94A3B8;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                font-size: 13px;
                padding: 0 10px;
            }
            #clearBtn:hover {
                background-color: rgba(255, 255, 255, 0.12);
                color: #E2E8F0;
            }
            """
        )
        self._set_dot_color("#10B981")

    def _set_dot_color(self, hex_color: str) -> None:
        self._status_dot.setStyleSheet(
            f"background-color: {hex_color}; border-radius: 4px;"
        )

    def set_options(self, auto_clipboard: bool, auto_swap: bool) -> None:
        self._auto_clipboard = auto_clipboard
        self._auto_swap = auto_swap

    def _on_source_toggled(self, checked: bool) -> None:
        self._showing_source = checked
        self.toggle_source_view_requested.emit(checked)

    def set_source_view_checked(self, checked: bool) -> None:
        self._showing_source = checked
        self._source_btn.blockSignals(True)
        self._source_btn.setChecked(checked)
        self._source_btn.blockSignals(False)

    def set_busy(self, busy: bool, status_text: str = "") -> None:
        self._busy = busy
        self._paste_btn.setEnabled(not busy)
        self._pick_img_btn.setEnabled(not busy)
        if busy:
            self._set_dot_color("#F59E0B")
            self._status_label.setText(status_text or "正在处理…")
            self._paste_btn.setIcon(QIcon())
            self._paste_btn.setText("翻译中…")
        else:
            self._set_dot_color("#10B981")
            if status_text:
                self._status_label.setText(status_text)
            self._paste_btn.setIcon(self._paste_icon)
            self._paste_btn.setIconSize(QSize(15, 15))
            self._paste_btn.setText(" 粘贴翻译")

    def show_status(self, message: str, color: str = "#10B981") -> None:
        self._set_dot_color(color)
        self._status_label.setText(message)

    def show_error(self, message: str) -> None:
        self._set_dot_color("#EF4444")
        self._status_label.setText(message)

    def set_text(self, text: str) -> None:
        self._text_edit.setPlainText(text)
        cursor = self._text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self._text_edit.setTextCursor(cursor)

    def get_text(self) -> str:
        return self._text_edit.toPlainText()

    def flash_copied(self) -> None:
        self._copy_btn.setText("✓ 已复制")
        self._copy_btn.setProperty("copied", "true")
        self._copy_btn.style().unpolish(self._copy_btn)
        self._copy_btn.style().polish(self._copy_btn)
        self._copy_feedback_timer.start()

    def _reset_copy_button(self) -> None:
        self._copy_btn.setText("复制")
        self._copy_btn.setProperty("copied", "false")
        self._copy_btn.style().unpolish(self._copy_btn)
        self._copy_btn.style().polish(self._copy_btn)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime.hasImage() or extract_image_path_from_mime(mime) or mime.hasText():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        img_path = extract_image_path_from_mime(mime)
        if img_path:
            self.image_file_dropped.emit(img_path)
            event.acceptProposedAction()
            return
        if mime.hasImage():
            img = mime.imageData()
            if isinstance(img, QPixmap) and not img.isNull():
                self.image_pasted.emit(img.toImage())
                event.acceptProposedAction()
                return
            if isinstance(img, QImage) and not img.isNull():
                self.image_pasted.emit(img)
                event.acceptProposedAction()
                return
        if mime.hasText():
            text = mime.text().strip()
            if text:
                self.text_pasted.emit(text)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def allow_close(self) -> None:
        self._allow_close = True

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        if not self._allow_close:
            event.ignore()
            self.collapse_requested.emit()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.key() == Qt.Key.Key_Escape:
            self.collapse_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_V and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.paste_translate_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_panel_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #1A2232;
                color: #F1F5F9;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 10px;
                padding: 5px;
                font-family: "Microsoft YaHei UI";
                font-size: 12.5px;
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #0D9488;
                color: #FFFFFF;
            }
            """
        )
        act_auto = QAction("自动监听剪贴板翻译", menu)
        act_auto.setCheckable(True)
        act_auto.setChecked(self._auto_clipboard)
        act_auto.triggered.connect(
            lambda _checked=False, a=act_auto: self.auto_clipboard_toggled.emit(a.isChecked())
        )
        menu.addAction(act_auto)

        act_swap = QAction("智能中英互译", menu)
        act_swap.setCheckable(True)
        act_swap.setChecked(self._auto_swap)
        act_swap.triggered.connect(
            lambda _checked=False, a=act_swap: self.auto_swap_toggled.emit(a.isChecked())
        )
        menu.addAction(act_swap)

        menu.exec(global_pos)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() == Qt.MouseButton.RightButton:
            self._show_panel_context_menu(event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            target = clamp_window_to_desktop(
                event.globalPosition().toPoint() - self._drag_offset,
                self.size(),
            )
            self.move(target)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.panel_moved.emit(self.x(), self.y())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        m = self.SHADOW_MARGIN
        card_rect = QRectF(m, m, self.width() - m * 2, self.height() - m * 2)

        for i, alpha in enumerate((10, 18, 28, 42)):
            spread = (4 - i) * 1.8
            shadow_rect = card_rect.adjusted(-spread, -spread + 1.2, spread, spread + 2.2)
            path = QPainterPath()
            path.addRoundedRect(
                shadow_rect,
                self.CORNER_RADIUS + spread * 0.45,
                self.CORNER_RADIUS + spread * 0.45,
            )
            painter.fillPath(path, QColor(0, 0, 0, alpha))

        card_path = QPainterPath()
        card_path.addRoundedRect(card_rect, self.CORNER_RADIUS, self.CORNER_RADIUS)
        bg_grad = QLinearGradient(card_rect.topLeft(), card_rect.bottomRight())
        bg_grad.setColorAt(0.0, QColor(24, 31, 45, 248))
        bg_grad.setColorAt(1.0, QColor(17, 22, 33, 250))
        painter.fillPath(card_path, QBrush(bg_grad))

        painter.setPen(QPen(QColor(255, 255, 255, 30), 1.1))
        painter.drawPath(card_path)
