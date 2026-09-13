# SPDX-License-Identifier: MIT
"""Crop and magnify a region of a PNG so a screenshot can be inspected."""
import sys

from PySide6.QtGui import QImage, QGuiApplication

app = QGuiApplication([])
src, dst, x, y, w, h = sys.argv[1], sys.argv[2], *[int(v) for v in sys.argv[3:7]]
scale = float(sys.argv[7]) if len(sys.argv) > 7 else 3.0
img = QImage(src)
print("source", img.width(), img.height())
crop = img.copy(x, y, w, h)
out = crop.scaled(int(w * scale), int(h * scale))
out.save(dst)
print("wrote", dst, out.width(), out.height())
