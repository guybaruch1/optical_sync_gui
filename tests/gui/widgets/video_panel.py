"""Displays a live numpy frame (grayscale IR or BGR RGB) as a QLabel."""

import cv2
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel


class VideoPanel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScaledContents(True)

    def set_frame(self, image):
        if image.ndim == 2:
            height, width = image.shape
            qimage = QImage(image.data, width, height, width, QImage.Format_Grayscale8)
        else:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            height, width, _ = rgb.shape
            qimage = QImage(rgb.data, width, height, 3 * width, QImage.Format_RGB888)
        self.setPixmap(QPixmap.fromImage(qimage.copy()))
