from __future__ import annotations

import io
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QObject, QPoint, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QImage
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from config import APP_DIR, APP_NAME, load_config, save_config

# Prevent silent crashes under pythonw.exe where stdout/stderr are None
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _install_exception_guard() -> None:
    log_path = APP_DIR / "app_error.log"

    def _log_exc(exc_type, exc_value, exc_tb) -> None:  # noqa: ANN001
        try:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"[{stamp}]\n{msg}\n")
        except Exception:
            pass

    sys.excepthook = _log_exc
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: _log_exc(args.exc_type, args.exc_value, args.exc_traceback)
from ocr_translator import FreeTranslator, LocalOCREngine
from ui_widgets import (
    ExpandedTranslatePanel,
    FloatingTranslateOrb,
    clamp_window_to_desktop,
    create_app_icon,
    extract_image_path_from_mime,
)

SINGLE_INSTANCE_KEY = "antigravity_cn_floating_translator_v1"


def qimage_to_pil(qimg: QImage) -> Image.Image:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    qimg.save(buf, "PNG")
    raw = bytes(buf.data())
    buf.close()
    return Image.open(io.BytesIO(raw)).convert("RGB")


class OCRPreloadThread(QThread):
    loaded = Signal()

    def __init__(self, ocr: LocalOCREngine) -> None:
        super().__init__()
        self._ocr = ocr

    def run(self) -> None:
        try:
            self._ocr.load()
            self.loaded.emit()
        except Exception:
            pass


class TranslateJobThread(QThread):
    status_update = Signal(str)
    finished_result = Signal(str, str, str, int)  # (source_text, translated_text, direction, job_id)
    failed = Signal(str, int)

    def __init__(
        self,
        ocr: LocalOCREngine,
        translator: FreeTranslator,
        job_id: int,
        auto_swap: bool,
        text: Optional[str] = None,
        image: Optional[Image.Image] = None,
    ) -> None:
        super().__init__()
        self._ocr = ocr
        self._translator = translator
        self._job_id = job_id
        self._auto_swap = auto_swap
        self._text = text
        self._image = image

    def run(self) -> None:
        try:
            source_text = (self._text or "").strip()
            if self._image is not None:
                self.status_update.emit("正在识别图片中的文字…")
                source_text = self._ocr.extract_text(self._image)
                if not source_text:
                    self.failed.emit("未在图片中识别到文字", self._job_id)
                    return

            self.status_update.emit("正在翻译为中文…")
            translated, direction = self._translator.translate(
                source_text,
                auto_swap_zh_en=self._auto_swap,
            )
            self.finished_result.emit(source_text, translated, direction, self._job_id)
        except Exception as exc:
            self.failed.emit(str(exc), self._job_id)


class FloatingTranslateApp(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._cfg = load_config()
        self._ocr = LocalOCREngine()
        self._translator = FreeTranslator()

        self._auto_clipboard: bool = bool(self._cfg.get("auto_clipboard", False))
        self._auto_swap: bool = bool(self._cfg.get("auto_swap", False))
        self._source_text: str = ""
        self._translated_text: str = ""
        self._showing_source: bool = False
        self._job_counter: int = 0
        self._ignoring_clipboard: bool = False
        self._quitting: bool = False
        self._active_workers: list[QThread] = []

        self._icon = create_app_icon(64)
        self._app.setWindowIcon(self._icon)

        self._orb = FloatingTranslateOrb()
        self._panel = ExpandedTranslatePanel()

        self._connect_signals()
        self._setup_tray()
        self._apply_options(save=False)
        self._restore_orb_position()

        # Keep-visible guard: never vanish on Win+D, display change, or accidental close
        self._keep_alive_timer = QTimer(self)
        self._keep_alive_timer.setInterval(2500)
        self._keep_alive_timer.timeout.connect(self._ensure_visible)
        self._keep_alive_timer.start()

        self._orb.show()
        self._preload_ocr()

    def _ensure_visible(self) -> None:
        if self._quitting:
            return
        if not self._orb.isVisible() and not self._panel.isVisible():
            self._orb.show()
            self._orb.raise_()
        elif self._orb.isVisible() and self._orb.isMinimized():
            self._orb.showNormal()
            self._orb.raise_()
        elif self._panel.isVisible():
            if self._panel.isMinimized() or self._panel.isMaximized():
                self._panel.showNormal()
                self._panel.raise_()
            screen = QApplication.screenAt(self._panel.frameGeometry().center()) or QApplication.primaryScreen()
            if screen is not None:
                target_size = self._panel.compute_target_size(screen.geometry())
                if self._panel.size() != target_size:
                    self._panel.setFixedSize(target_size)
                if not self._panel._dragging:
                    clamped = clamp_window_to_desktop(self._panel.pos(), self._panel.size())
                    if clamped != self._panel.pos():
                        self._panel.move(clamped)

    def _connect_signals(self) -> None:
        self._orb.clicked.connect(self.expand_panel)
        self._orb.position_changed.connect(self._on_orb_moved)
        self._orb.reset_position_requested.connect(self.reset_orb_position)
        self._orb.auto_clipboard_toggled.connect(self._on_auto_clipboard_toggled)
        self._orb.auto_swap_toggled.connect(self._on_auto_swap_toggled)
        self._orb.quit_requested.connect(self.quit_app)

        self._panel.collapse_requested.connect(self.collapse_to_orb)
        self._panel.paste_translate_requested.connect(self.paste_and_translate)
        self._panel.pick_image_requested.connect(self.pick_and_translate_image)
        self._panel.toggle_source_view_requested.connect(self._on_toggle_source_view)
        self._panel.copy_requested.connect(self.copy_output)
        self._panel.clear_requested.connect(self.clear_all)
        self._panel.image_pasted.connect(self._translate_qimage)
        self._panel.image_file_dropped.connect(self._translate_image_file)
        self._panel.text_pasted.connect(self._translate_text)
        self._panel.translate_current_text_requested.connect(self._translate_box_text)
        self._panel.auto_clipboard_toggled.connect(self._on_auto_clipboard_toggled)
        self._panel.auto_swap_toggled.connect(self._on_auto_swap_toggled)
        self._panel.panel_moved.connect(self._on_panel_moved)

        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)

    def _setup_tray(self) -> None:
        self._tray = QSystemTrayIcon(self._icon, self)
        self._tray.setToolTip(f"{APP_NAME}（左键切换窗口）")

        menu = QMenu()
        act_expand = QAction("展开翻译窗", menu)
        act_expand.triggered.connect(self.expand_panel)
        menu.addAction(act_expand)

        act_orb = QAction("收起为悬浮图标", menu)
        act_orb.triggered.connect(self.collapse_to_orb)
        menu.addAction(act_orb)

        self._tray_auto_clip = QAction("自动监听剪贴板翻译", menu)
        self._tray_auto_clip.setCheckable(True)
        self._tray_auto_clip.setChecked(self._auto_clipboard)
        self._tray_auto_clip.triggered.connect(
            lambda _checked=False: self._on_auto_clipboard_toggled(self._tray_auto_clip.isChecked())
        )
        menu.addAction(self._tray_auto_clip)

        self._tray_auto_swap = QAction("智能中英互译", menu)
        self._tray_auto_swap.setCheckable(True)
        self._tray_auto_swap.setChecked(self._auto_swap)
        self._tray_auto_swap.triggered.connect(
            lambda _checked=False: self._on_auto_swap_toggled(self._tray_auto_swap.isChecked())
        )
        menu.addAction(self._tray_auto_swap)

        act_reset = QAction("重置默认位置", menu)
        act_reset.triggered.connect(self.reset_orb_position)
        menu.addAction(act_reset)

        menu.addSeparator()

        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _apply_options(self, save: bool = True) -> None:
        self._orb.set_options(self._auto_clipboard, self._auto_swap)
        self._panel.set_options(self._auto_clipboard, self._auto_swap)
        self._tray_auto_clip.setChecked(self._auto_clipboard)
        self._tray_auto_swap.setChecked(self._auto_swap)
        if save:
            self._cfg["auto_clipboard"] = self._auto_clipboard
            self._cfg["auto_swap"] = self._auto_swap
            save_config(self._cfg)

    def _on_auto_clipboard_toggled(self, enabled: bool) -> None:
        self._auto_clipboard = bool(enabled)
        self._apply_options(save=True)
        if self._auto_clipboard:
            self._panel.show_status("已开启自动监听剪贴板", "#10B981")
        else:
            self._panel.show_status("就绪 · 粘贴文字或图片即可翻译", "#10B981")

    def _on_auto_swap_toggled(self, enabled: bool) -> None:
        self._auto_swap = bool(enabled)
        self._apply_options(save=True)

    def _preload_ocr(self) -> None:
        worker = OCRPreloadThread(self._ocr)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._active_workers.append(worker)
        worker.start()

    def _cleanup_worker(self, worker: QThread) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        worker.deleteLater()

    def _default_orb_pos(self) -> QPoint:
        screen = QApplication.primaryScreen()
        if screen is None:
            return QPoint(1200, 620)
        avail = screen.availableGeometry()
        # Stack cleanly above the voice-to-text orb on the right side
        x = avail.right() - self._orb.width() - 32
        y = avail.bottom() - self._orb.height() - 170
        return QPoint(x, y)

    def _restore_orb_position(self) -> None:
        x = self._cfg.get("orb_x")
        y = self._cfg.get("orb_y")
        if isinstance(x, int) and isinstance(y, int):
            pos = clamp_window_to_desktop(QPoint(x, y), self._orb.size())
        else:
            pos = self._default_orb_pos()
        self._orb.move(pos)

    def reset_orb_position(self) -> None:
        pos = self._default_orb_pos()
        self._orb.move(pos)
        self._on_orb_moved(pos.x(), pos.y())
        if self._panel.isVisible():
            self.collapse_to_orb()
        self._orb.show()
        self._orb.raise_()

    def _on_orb_moved(self, x: int, y: int) -> None:
        self._cfg["orb_x"] = x
        self._cfg["orb_y"] = y
        save_config(self._cfg)

    def _on_panel_moved(self, x: int, y: int) -> None:
        orb_pos = QPoint(
            x + self._panel.width() - self._orb.width() - 6,
            y + 6,
        )
        clamped = clamp_window_to_desktop(orb_pos, self._orb.size())
        self._orb.move(clamped)
        self._on_orb_moved(clamped.x(), clamped.y())

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self._panel.isVisible():
                self.collapse_to_orb()
            else:
                self.expand_panel()

    def bring_to_front(self) -> None:
        if self._panel.isVisible():
            self._panel.raise_()
            self._panel.activateWindow()
        else:
            self.expand_panel()

    def expand_panel(self) -> None:
        orb_center = self._orb.frameGeometry().center()
        screen = QApplication.screenAt(orb_center) or QApplication.primaryScreen()
        screen_geo = screen.geometry() if screen else self._orb.geometry()
        target_size = self._panel.compute_target_size(screen_geo)
        self._panel.setFixedSize(target_size)

        avail = screen.availableGeometry() if screen else screen_geo
        if orb_center.x() > avail.center().x():
            px = self._orb.frameGeometry().right() - target_size.width() + 8
        else:
            px = self._orb.frameGeometry().left() - 8

        if orb_center.y() > avail.center().y():
            py = self._orb.frameGeometry().bottom() - target_size.height() + 8
        else:
            py = self._orb.frameGeometry().top() - 8

        panel_pos = clamp_window_to_desktop(QPoint(px, py), target_size)
        self._panel.move(panel_pos)

        self._orb.hide()
        self._panel.showNormal()
        self._panel.raise_()
        self._panel.activateWindow()

    def collapse_to_orb(self) -> None:
        self._panel.hide()
        self._orb.show()
        self._orb.raise_()

    def _on_clipboard_changed(self) -> None:
        if not self._auto_clipboard or self._ignoring_clipboard:
            return
        if not self._panel.isVisible():
            return
        self.paste_and_translate(fallback_to_box=False)

    def paste_and_translate(self, fallback_to_box: bool = True) -> None:
        cb = QApplication.clipboard()
        mime = cb.mimeData()
        if mime is not None:
            img_path = extract_image_path_from_mime(mime)
            if img_path:
                self._translate_image_file(img_path)
                return
            if mime.hasImage():
                qimg = cb.image()
                if not qimg.isNull():
                    self._translate_qimage(qimg)
                    return
            if mime.hasText():
                text = cb.text().strip()
                if text and text != self._translated_text.strip():
                    self._translate_text(text)
                    return

        if fallback_to_box:
            box_text = self._panel.get_text().strip()
            if box_text:
                self._translate_text(box_text)
            else:
                self._panel.show_error("剪贴板里没有可翻译的文字或图片")

    def pick_and_translate_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            None,
            "选择要识别并翻译的图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)",
        )
        if path:
            self._translate_image_file(path)

    def _translate_box_text(self) -> None:
        text = self._panel.get_text().strip()
        if text:
            self._translate_text(text)

    def _translate_image_file(self, path_str: str) -> None:
        try:
            pil_img = Image.open(Path(path_str)).convert("RGB")
        except Exception as exc:
            self._panel.show_error(f"无法读取图片：{exc}")
            return
        self._start_job(image=pil_img)

    def _translate_qimage(self, qimg: QImage) -> None:
        try:
            pil_img = qimage_to_pil(qimg)
        except Exception as exc:
            self._panel.show_error(f"无法解析剪贴板图片：{exc}")
            return
        self._start_job(image=pil_img)

    def _translate_text(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        self._start_job(text=clean)

    def _start_job(
        self,
        text: Optional[str] = None,
        image: Optional[Image.Image] = None,
    ) -> None:
        self._job_counter += 1
        job_id = self._job_counter
        self._orb.set_busy(True)
        init_msg = "正在识别图片文字…" if image is not None else "正在翻译为中文…"
        self._panel.set_busy(True, init_msg)
        self._panel.set_source_view_checked(False)

        worker = TranslateJobThread(
            ocr=self._ocr,
            translator=self._translator,
            job_id=job_id,
            auto_swap=self._auto_swap,
            text=text,
            image=image,
        )
        worker.status_update.connect(lambda msg, jid=job_id: self._on_job_status(msg, jid))
        worker.finished_result.connect(self._on_job_finished)
        worker.failed.connect(self._on_job_failed)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._active_workers.append(worker)
        worker.start()

    def _on_job_status(self, msg: str, job_id: int) -> None:
        if job_id == self._job_counter:
            self._panel.show_status(msg, "#F59E0B")

    def _on_job_finished(
        self,
        source_text: str,
        translated_text: str,
        direction: str,
        job_id: int,
    ) -> None:
        if job_id != self._job_counter:
            return
        self._source_text = source_text
        self._translated_text = translated_text
        self._showing_source = False
        self._panel.set_source_view_checked(False)
        self._panel.set_text(translated_text)
        self._orb.set_busy(False)
        self._panel.set_busy(False, f"{direction} 翻译完成 · 可直接复制")

    def _on_job_failed(self, err: str, job_id: int) -> None:
        if job_id != self._job_counter:
            return
        self._orb.set_busy(False)
        self._panel.set_busy(False)
        self._panel.show_error(err)

    def _on_toggle_source_view(self, show_source: bool) -> None:
        self._showing_source = show_source
        if show_source:
            if self._source_text:
                self._panel.set_text(self._source_text)
                self._panel.show_status("正在查看原文（可编辑后按 Ctrl+Enter 重译）", "#38BDF8")
            else:
                self._panel.show_status("当前暂无原文记录", "#94A3B8")
        else:
            if self._translated_text:
                self._panel.set_text(self._translated_text)
                self._panel.show_status("译文已显示 · 可直接复制", "#10B981")

    def copy_output(self) -> None:
        text = self._panel.get_text().strip()
        if not text:
            self._panel.show_error("当前没有可复制的内容")
            return
        self._ignoring_clipboard = True
        try:
            QApplication.clipboard().setText(text)
        finally:
            self._ignoring_clipboard = False
        self._panel.flash_copied()

    def clear_all(self) -> None:
        self._source_text = ""
        self._translated_text = ""
        self._panel.set_source_view_checked(False)
        self._panel.set_text("")
        self._panel.show_status("就绪 · 粘贴文字或图片即可翻译", "#10B981")

    def quit_app(self) -> None:
        self._quitting = True
        self._keep_alive_timer.stop()
        self._orb.allow_close()
        self._panel.allow_close()
        self._orb.close()
        self._panel.close()
        self._tray.hide()
        self._app.quit()


def main() -> int:
    _install_exception_guard()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    probe = QLocalSocket()
    probe.connectToServer(SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(200):
        probe.write(b"RAISE")
        probe.flush()
        probe.waitForBytesWritten(200)
        probe.disconnectFromServer()
        return 0

    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_KEY)

    controller = FloatingTranslateApp(app)

    def _on_new_instance() -> None:
        sock = server.nextPendingConnection()
        if sock is not None:
            sock.readyRead.connect(lambda: sock.readAll())
            sock.close()
        controller.bring_to_front()

    server.newConnection.connect(_on_new_instance)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
