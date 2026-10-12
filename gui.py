import html
import os
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

import core

COLS = ["Image", "Post", "Sell", "Compete", "Use", "Theme", "Edit", "Judge", "New name"]
C_USE, C_THEME, C_EDIT, C_JUDGE, C_NEW = 4, 5, 6, 7, 8
THUMB = 64
NO_SELECTION_TEXT = "Select an image to see details."


def load_pixmap(path: Path, size: int) -> QPixmap:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    native = reader.size()
    if native.isValid():
        native.scale(size, size, Qt.KeepAspectRatio)
        reader.setScaledSize(native)
    img = reader.read()
    return QPixmap() if img.isNull() else QPixmap.fromImage(img)


class Worker(QThread):
    result = Signal(int, dict)
    failed = Signal(int, str)

    def __init__(self, images, key, grader, judge, bars, max_side):
        super().__init__()
        self.images, self.key, self.grader, self.judge, self.bars, self.max_side = images, key, grader, judge, bars, max_side
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for i, path in enumerate(self.images):
            if self._stop:
                break
            try:
                g = core.evaluate(path, self.key, self.grader, self.judge, self.max_side)
                g["use"] = core.best_use(g, self.bars)
                self.result.emit(i, g)
            except Exception as e:
                self.failed.emit(i, str(e))


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Rater - Hack Club AI")
        self.resize(1350, 760)
        self.folder = None
        self.images, self.grades, self.taken = [], {}, set()
        self.worker = None
        self._last_scan = None
        self._build()

    def _build(self):
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Choose a folder with images...")
        self.folder_edit.editingFinished.connect(lambda: self.scan())
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse)
        self.recursive = QCheckBox("Subfolders")
        self.recursive.toggled.connect(lambda _: self.scan())
        self.include_renamed = QCheckBox("Re-rate already renamed")
        self.include_renamed.toggled.connect(lambda _: self.scan())

        self.key_edit = QLineEdit(os.environ.get("HACKCLUB_API_KEY", ""))
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("Hack Club AI API key (or set HACKCLUB_API_KEY)")

        self.grader_box = QComboBox()
        self.grader_box.setEditable(True)
        self.grader_box.addItem(core.DEFAULT_MODEL)
        self.judge_box = QComboBox()
        self.judge_box.setEditable(True)
        self.judge_box.addItem(core.JUDGE_MODEL)
        self.use_judge = QCheckBox("Use judge")
        self.use_judge.setChecked(True)
        self.use_judge.toggled.connect(self.judge_box.setEnabled)

        self.bar_spins = {}
        bar_row = QHBoxLayout()
        for code, label in (("1", "Post"), ("2", "Sell"), ("3", "Compete")):
            spin = QSpinBox()
            spin.setRange(1, 10)
            spin.setValue(core.WORTH_BARS[code])
            spin.setToolTip(f"{label} score needed to count as 'worth it'. If no score reaches its bar, the number is 0.")
            self.bar_spins[code] = spin
            bar_row.addWidget(QLabel(f"{label} >="))
            bar_row.addWidget(spin)

        self.max_side = QSpinBox()
        self.max_side.setRange(512, 4096)
        self.max_side.setSingleStep(128)
        self.max_side.setValue(core.MAX_SIDE)
        self.max_side.setSuffix(" px")
        self.max_side.setToolTip("Longest side of the image sent to the AI (1920 = 1080p). Never upscaled.")

        self.run_btn = QPushButton("Rate images")
        self.run_btn.clicked.connect(self.toggle_run)
        self.apply_btn = QPushButton("Apply renames")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply)
        self.undo_btn = QPushButton("Undo from log...")
        self.undo_btn.clicked.connect(self.undo)
        legend_btn = QPushButton("Legend")
        legend_btn.clicked.connect(lambda: QMessageBox.information(self, "Filename legend", core.legend_text()))
        self.progress = QProgressBar()
        self.status = QLabel("Pick a folder to begin.")

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setIconSize(QSize(THUMB, THUMB))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(THUMB + 8)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.show_detail)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(300, 240)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.detail = QLabel(NO_SELECTION_TEXT)
        self.detail.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.detail.setTextFormat(Qt.RichText)

        side = QVBoxLayout()
        side.addWidget(self.preview, 3)
        side.addWidget(self.detail, 3)
        side_w = QWidget()
        side_w.setLayout(side)
        split = QSplitter()
        split.addWidget(self.table)
        split.addWidget(side_w)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)

        row1 = QHBoxLayout()
        row1.addWidget(self.folder_edit, 1)
        row1.addWidget(self.browse_btn)
        row1.addWidget(self.recursive)
        row1.addWidget(self.include_renamed)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("API key"))
        row2.addWidget(self.key_edit, 1)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Grader"))
        row3.addWidget(self.grader_box, 1)
        row3.addWidget(self.use_judge)
        row3.addWidget(self.judge_box, 1)
        row3.addWidget(QLabel("  Worth bars:"))
        row3.addLayout(bar_row)
        row3.addWidget(QLabel("  Max side:"))
        row3.addWidget(self.max_side)
        row4 = QHBoxLayout()
        for w in (self.run_btn, self.apply_btn, self.undo_btn, legend_btn):
            row4.addWidget(w)
        row4.addWidget(self.progress, 1)

        layout = QVBoxLayout(self)
        for r in (row1, row2, row3, row4):
            layout.addLayout(r)
        layout.addWidget(split, 1)
        layout.addWidget(self.status)

    def _set_busy(self, busy: bool):
        for w in (self.folder_edit, self.browse_btn, self.recursive, self.include_renamed, self.key_edit, self.grader_box, self.judge_box, self.use_judge, self.undo_btn, self.max_side, *self.bar_spins.values()):
            w.setEnabled(not busy)
        if not busy:
            self.judge_box.setEnabled(self.use_judge.isChecked())
        self.run_btn.setText("Stop" if busy else "Rate images")

    def browse(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choose image folder", str(self.folder or Path.home()))
        if chosen:
            self.folder_edit.setText(chosen)
            self.scan()

    def scan(self, force: bool = False):
        if self.worker:
            return
        text = self.folder_edit.text().strip()
        key = (text, self.recursive.isChecked(), self.include_renamed.isChecked())
        if key == self._last_scan and not force:
            return
        self._last_scan = key

        self.table.setRowCount(0)
        self.images, self.grades, self.taken = [], {}, set()
        self.apply_btn.setEnabled(False)
        self.preview.clear()
        self.detail.setText(NO_SELECTION_TEXT)
        self.progress.setValue(0)

        folder = Path(text).expanduser() if text else None
        if not folder or not folder.is_dir():
            self.folder = None
            self.status.setText("Pick a folder to begin.")
            return

        self.folder = folder
        self.images = core.find_images(folder, self.recursive.isChecked(), skip_named=not self.include_renamed.isChecked())
        self.table.setRowCount(len(self.images))
        for i, p in enumerate(self.images):
            item = QTableWidgetItem(p.name)
            item.setIcon(QIcon(load_pixmap(p, THUMB)))
            self.table.setItem(i, 0, item)
            for c in range(1, len(COLS)):
                self.table.setItem(i, c, QTableWidgetItem(""))
        self.status.setText(f"{len(self.images)} image(s) found." if self.images else "No images found (already-renamed files are skipped unless you tick Re-rate).")

    def toggle_run(self):
        if self.worker:
            self.worker.stop()
            self.status.setText("Stopping after the current image...")
        else:
            self.start()

    def start(self):
        key = self.key_edit.text().strip()
        if not self.images:
            QMessageBox.warning(self, "No images", "Choose a folder that contains images first.")
            return
        if not key:
            QMessageBox.warning(self, "API key needed", "Paste your Hack Club AI API key (from ai.hackclub.com).")
            return

        self.grades, self.taken = {}, set()
        for r in range(self.table.rowCount()):
            for c in range(1, len(COLS)):
                item = self.table.item(r, c)
                item.setText("")
                item.setToolTip("")
                item.setBackground(QBrush())
        self.progress.setRange(0, len(self.images))
        self.progress.setValue(0)
        self.apply_btn.setEnabled(False)
        self._set_busy(True)

        grader = self.grader_box.currentText().strip() or core.DEFAULT_MODEL
        judge = (self.judge_box.currentText().strip() or core.JUDGE_MODEL) if self.use_judge.isChecked() else None
        bars = {code: spin.value() for code, spin in self.bar_spins.items()}
        self.worker = Worker(list(self.images), key, grader, judge, bars, self.max_side.value())
        self.worker.result.connect(self.on_result)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()
        self.status.setText("Rating...")

    def _cell(self, row, col, text, score=None):
        item = self.table.item(row, col)
        item.setText(str(text))
        if score is None:
            return
        item.setTextAlignment(Qt.AlignCenter)
        if score >= 8:
            item.setBackground(QBrush(QColor(60, 170, 90, 110)))
        elif score <= 3:
            item.setBackground(QBrush(QColor(200, 70, 70, 110)))

    def on_result(self, i, g):
        path = self.images[i]
        new = core.plan_new_name(path, core.base_name(g["use"], g), self.taken)
        g.update(original=path, new=new, applied="no")
        self.grades[i] = g
        self._cell(i, 1, g["post"], g["post"])
        self._cell(i, 2, g["sell"], g["sell"])
        self._cell(i, 3, g["compete"], g["compete"])
        self._cell(i, C_USE, g["use"])
        self.table.item(i, C_USE).setTextAlignment(Qt.AlignCenter)
        self._cell(i, C_THEME, f"{g['theme']} - {core.THEMES[g['theme']][0]}")
        self._cell(i, C_EDIT, f"{g['edit']} - {core.EDITS[g['edit']][1]}")
        self._cell(i, C_JUDGE, g["agreement"])
        judge_item = self.table.item(i, C_JUDGE)
        judge_item.setToolTip(g["judge_error"] or g["correction"])
        if g["agreement"] == "overruled":
            judge_item.setBackground(QBrush(QColor(230, 150, 40, 120)))
        elif g["agreement"] == "judge failed":
            judge_item.setBackground(QBrush(QColor(200, 70, 70, 120)))
        self._cell(i, C_NEW, new.name)
        self.progress.setValue(self.progress.value() + 1)
        self.status.setText(f"Rated {self.progress.value()}/{len(self.images)}")
        rows = self.table.selectionModel().selectedRows()
        if rows and rows[0].row() == i:
            self.show_detail()

    def on_failed(self, i, message):
        self._cell(i, C_NEW, "failed (hover for details)")
        self.table.item(i, C_NEW).setToolTip(message)
        self.progress.setValue(self.progress.value() + 1)

    def on_finished(self):
        self.worker = None
        self._set_busy(False)
        self.apply_btn.setEnabled(bool(self.grades))
        failed_judge = sum(1 for g in self.grades.values() if g["agreement"] == "judge failed")
        extra = f" {failed_judge} had no judge verdict (judge failed)." if failed_judge else ""
        self.status.setText(f"Done: {len(self.grades)} of {len(self.images)} rated.{extra} Review the table, then press Apply renames.")

    def show_detail(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        i = rows[0].row()
        pix = load_pixmap(self.images[i], 900)
        if not pix.isNull():
            self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        g = self.grades.get(i)
        if not g:
            self.detail.setText("Not rated yet.")
            return

        esc = html.escape
        first = g.get("first")
        parts = [f"<b>{esc(g['new'].name)}</b>", f"Final: Post {g['post']} &middot; Sell {g['sell']} &middot; Compete {g['compete']}"]
        if first:
            parts.append(f"<span style='color:gray'>First reviewer: {first['post']} / {first['sell']} / {first['compete']} ({esc(core.THEMES[first['theme']][0])})</span>")
        parts += [
            f"<b>Best use:</b> {esc(core.USES[g['use']])}",
            f"<b>Theme:</b> {esc(core.THEMES[g['theme']][0])}",
            f"<b>Edit ({esc(g['edit'])}):</b> {esc(core.EDITS[g['edit']][1])}" + (f" &mdash; {esc(g['edit_note'])}" if g["edit_note"] else ""),
        ]
        if g["strength"]:
            parts.append(f"<b>Strength:</b> {esc(g['strength'])}")
        if g["agreement"] not in ("-", "agree"):
            parts.append(f"<b>Judge ({esc(g['agreement'])}):</b> {esc(g['judge_error'] or g['correction'] or '-')}")
        if g["reason"]:
            parts.append(f"<i>{esc(g['reason'])}</i>")
        self.detail.setText("<br>".join(parts))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.table.selectionModel() and self.table.selectionModel().selectedRows():
            self.show_detail()

    def apply(self):
        rows = [self.grades[i] for i in sorted(self.grades)]
        if not rows:
            return
        answer = QMessageBox.question(self, "Rename files?", f"Rename {len(rows)} file(s) in\n{self.folder}\n\nA log is saved so you can undo this.")
        if answer != QMessageBox.Yes:
            return

        core.apply_renames(rows)
        log = self.folder / f"ratings_{datetime.now():%Y%m%d_%H%M%S}.csv"
        core.write_log(rows, log)
        done = 0
        for i, g in self.grades.items():
            if g["applied"] == "yes":
                self.images[i] = g["new"]
                self.table.item(i, 0).setText(g["new"].name)
                self._cell(i, C_NEW, "renamed")
                done += 1
        self.apply_btn.setEnabled(False)
        self.status.setText(f"Renamed {done} file(s). Log: {log.name}")

    def undo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a ratings log", str(self.folder or Path.home()), "CSV files (*.csv)")
        if not path:
            return
        QMessageBox.information(self, "Undo", f"Restored {core.undo(path)} file(s).")
        self.scan(force=True)

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
            self.worker.wait(5000)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    win = Window()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()