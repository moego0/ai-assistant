import sys
import os
import time
import threading
import speech_recognition as sr
import pyttsx3
from gtts import gTTS
import google.generativeai as genai
import math
import serial
import serial.tools.list_ports
import json
import subprocess
import pyautogui
import ctypes
import cv2
from PIL import Image
import io
from datetime import datetime
from dotenv import load_dotenv
import pvporcupine
import pyaudio
import struct
import numpy as np
import webrtcvad
import collections
from array import array
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, 
                           QVBoxLayout, QLabel, QScrollArea, QFrame,
                           QHBoxLayout, QLineEdit, QPushButton, QComboBox,
                           QMessageBox, QDialog, QGridLayout, QListWidget,
                           QListWidgetItem, QStackedWidget, QFileDialog,
                           QGraphicsOpacityEffect, QGraphicsDropShadowEffect,
                           QProgressBar, QSizePolicy, QFormLayout)
from PyQt6.QtCore import (Qt, QPropertyAnimation, QPoint, pyqtSignal, QObject, QTimer, QSize, QEasingCurve, 
                         QParallelAnimationGroup, QSequentialAnimationGroup,
                         pyqtProperty, QRect, QMetaObject, Q_ARG)
from PyQt6.QtGui import (QPainter, QColor, QPainterPath, QLinearGradient,
                        QPalette, QBrush, QRadialGradient, QPen, 
                        QFontDatabase, QFont, QImage, QPixmap)
import random
import re
import pygame

# Load environment variables
load_dotenv()

def initialize_gemini(api_key):
    """Initialize Gemini AI with proper error handling"""
    global gemini_initialized
    try:
        if not api_key or not isinstance(api_key, str) or len(api_key.strip()) == 0:
            print("Notice: Gemini API key not provided - running in limited mode")
            gemini_initialized = False
            return False
        
        # Clean the API key (remove whitespace and quotes)
        clean_key = api_key.strip().strip('"\'')
        genai.configure(api_key=clean_key)
        gemini_initialized = True
        return True
    except Exception as e:
        print(f"Error initializing Gemini AI: {str(e)}")
        gemini_initialized = False
        return False

def is_gemini_initialized():
    """Check if Gemini AI is initialized with valid API key"""
    global gemini_initialized
    return gemini_initialized

# Initialize global state
gemini_initialized = False
# Initialize with empty key first (will be configured from settings)
initialize_gemini("")

def apply_shadow(widget):
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(10)
    shadow.setOffset(0, 3)
    shadow.setColor(QColor(0, 0, 0, 120))
    widget.setGraphicsEffect(shadow)

class SignalEmitter(QObject):
    status_changed = pyqtSignal(str)
    animation_trigger = pyqtSignal(str)
    new_message = pyqtSignal(str, bool)  # message, is_user

class VADManager:
    def __init__(self, aggressiveness=3, sample_rate=16000, frame_duration=30, signal_emitter=None):
        print("Initializing WebRTC Voice Activity Detection...")
        try:
            self.vad = webrtcvad.Vad(aggressiveness)
            self.sample_rate = sample_rate
            self.frame_duration = frame_duration  # in milliseconds
            self.frame_size = int(sample_rate * frame_duration / 1000)  # samples per frame
            self.ring_buffer = collections.deque(maxlen=8)  # Buffer for voice frames
            self.triggered = False
            self.voiced_frames = []
            self.signal_emitter = signal_emitter
            
            print(f"WebRTC VAD initialized successfully (Aggressiveness Level: {aggressiveness})")
            print("Noise reduction is now active and ready")
            if self.signal_emitter:
                self.signal_emitter.status_changed.emit("✓ Noise reduction active")
                self.signal_emitter.new_message.emit("Noise reduction system is now active and ready", False)
        except Exception as e:
            print(f"Error initializing WebRTC VAD: {str(e)}")
            if self.signal_emitter:
                self.signal_emitter.status_changed.emit("⚠ Noise reduction failed")
                self.signal_emitter.new_message.emit(f"Could not initialize noise reduction: {str(e)}", False)
            raise

    def process_audio(self, audio_chunk):
        """Process audio chunk and determine if speech is present"""
        try:
            is_speech = self.vad.is_speech(audio_chunk, self.sample_rate)
            
            if not self.triggered:
                self.ring_buffer.append((audio_chunk, is_speech))
                num_voiced = len([f for f, speech in self.ring_buffer if speech])
                
                # Start collecting audio when enough voiced frames are detected
                if num_voiced > 0.5 * self.ring_buffer.maxlen:
                    self.triggered = True
                    self.voiced_frames = [f[0] for f in self.ring_buffer]
                    self.ring_buffer.clear()
                    return True, self.voiced_frames
            else:
                # Keep collecting audio until enough silence is detected
                self.voiced_frames.append(audio_chunk)
                self.ring_buffer.append((audio_chunk, is_speech))
                num_unvoiced = len([f for f, speech in self.ring_buffer if not speech])
                
                if num_unvoiced > 0.9 * self.ring_buffer.maxlen:
                    self.triggered = False
                    return False, self.voiced_frames
            
            return None, []
        except Exception as e:
            print(f"Error processing audio in VAD: {str(e)}")
            if self.signal_emitter:
                self.signal_emitter.status_changed.emit("⚠ Noise reduction error")
            return None, []

    def reset(self):
        """Reset the VAD state"""
        self.triggered = False
        self.ring_buffer.clear()
        self.voiced_frames = []
        if self.signal_emitter:
            self.signal_emitter.status_changed.emit("✓ Noise reduction active")

class BluetoothManager:
    def __init__(self):
        self.serial_port = None
        self.is_connected = False

    def get_available_ports(self):
        return [port.device for port in serial.tools.list_ports.comports()]

    def connect(self, port, baud_rate=9600):
        try:
            self.serial_port = serial.Serial(port, baud_rate, timeout=1)
            self.is_connected = True
            return True
        except serial.SerialException as e:
            print(f"Error connecting to port {port}: {str(e)}")
            self.is_connected = False
            return False

    def disconnect(self):
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            self.is_connected = False

    def send_data(self, data):
        if self.is_connected and self.serial_port:
            try:
                self.serial_port.write(data.encode())
                return True
            except serial.SerialException as e:
                print(f"Error sending data: {str(e)}")
                return False
        return False

class BluetoothControl(QFrame):
    def __init__(self, bluetooth_manager, parent=None):
        super().__init__(parent)
        self.bluetooth_manager = bluetooth_manager
        self.setup_ui()

    def setup_ui(self):
        # Main layout without margins
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # Create a glass-effect container
        container = QFrame(self)
        container.setObjectName("bluetoothContainer")
        container.setStyleSheet("""
            QFrame#bluetoothContainer {
                background: rgba(44, 62, 80, 0.3);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 10px;
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(15, 15, 15, 15)
        container_layout.setSpacing(15)
        
        # Port selection area
        port_frame = QFrame()
        port_frame.setObjectName("portFrame")
        port_frame.setStyleSheet("""
            QFrame#portFrame {
                background: rgba(44, 62, 80, 0.4);
                border-radius: 8px;
            }
        """)
        port_layout = QHBoxLayout(port_frame)
        port_layout.setContentsMargins(10, 10, 10, 10)
        port_layout.setSpacing(8)
        
        # Port dropdown with fixed width
        self.port_combo = QComboBox()
        self.port_combo.setFixedWidth(120)  # Fixed width for combo box
        self.refresh_ports()
        
        # Refresh button with fixed size
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(32, 32)
        refresh_btn.clicked.connect(self.refresh_ports)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: rgba(52, 73, 94, 0.6);
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 14px;
            }
            QPushButton:hover {
                background: rgba(52, 73, 94, 0.8);
            }
            QPushButton:pressed {
                background: rgba(44, 62, 80, 0.8);
            }
        """)
        
        # Connect button with fixed width
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setFixedSize(90, 32)
        self.connect_btn.clicked.connect(self.toggle_connection)

        # Add widgets to port layout with proper spacing
        port_layout.addWidget(self.port_combo)
        port_layout.addWidget(refresh_btn)
        port_layout.addStretch(1)  # Add stretch to push connect button to the right
        port_layout.addWidget(self.connect_btn)
        
        # Status area
        status_frame = QFrame()
        status_frame.setObjectName("statusFrame")
        status_frame.setStyleSheet("""
            QFrame#statusFrame {
                background: rgba(44, 62, 80, 0.3);
                border: 1px solid rgba(231, 76, 60, 0.3);
                border-radius: 5px;
            }
        """)
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(10, 10, 10, 10)
        
        self.status_label = QLabel("Not Connected")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.status_label)

        # Add widgets to container
        container_layout.addWidget(port_frame)
        container_layout.addWidget(status_frame)
        container_layout.addStretch()

        # Add container to main layout
        layout.addWidget(container)
        
        # Apply styles after layout setup
        self._apply_styles()
        
    def _apply_styles(self):
        # Port combo style
        self.port_combo.setStyleSheet("""
            QComboBox {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
                    fx:0.45, fy:0.45,
                    stop:0 rgba(52, 73, 94, 0.8),
                    stop:1 rgba(44, 62, 80, 0.8));
                color: white;
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 16px;
                padding: 5px 15px;
                min-height: 32px;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border: none;
            }
            QComboBox:hover {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
                    fx:0.45, fy:0.45,
                    stop:0 rgba(52, 152, 219, 0.8),
                    stop:1 rgba(41, 128, 185, 0.8));
                border: 1px solid rgba(52, 152, 219, 0.5);
            }
            QComboBox QAbstractItemView {
                background: rgba(44, 62, 80, 0.95);
                color: white;
                selection-background-color: rgba(52, 152, 219, 0.6);
                selection-color: white;
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 8px;
            }
        """)
        
        # Apply shadow to combo box
        apply_shadow(self.port_combo)
        
        # Status label style
        self.status_label.setStyleSheet("""
            QLabel {
                color: #e74c3c;
                font-size: 14px;
                background: transparent;
            }
        """)
        
        # Connect button style
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
                    fx:0.45, fy:0.45,
                    stop:0 rgba(46, 204, 113, 0.95),
                    stop:1 rgba(39, 174, 96, 0.95));
                color: white;
                border: none;
                border-radius: 16px;
                font-weight: bold;
                padding: 6px 15px;
            }
            QPushButton:hover {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
                    fx:0.45, fy:0.45,
                    stop:0 rgba(39, 174, 96, 0.95),
                    stop:1 rgba(46, 204, 113, 0.95));
            }
            QPushButton:pressed {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
                    fx:0.45, fy:0.45,
                    stop:0 rgba(39, 174, 96, 1),
                    stop:1 rgba(46, 204, 113, 1));
                padding: 7px 14px 5px 16px;
            }
        """)
        
        # Apply shadow to connect button
        apply_shadow(self.connect_btn)

    def refresh_ports(self):
        current_port = self.port_combo.currentText()
        self.port_combo.clear()
        ports = self.bluetooth_manager.get_available_ports()
        self.port_combo.addItems(ports)
        if current_port in ports:
            self.port_combo.setCurrentText(current_port)

    def toggle_connection(self):
        if not self.bluetooth_manager.is_connected:
            port = self.port_combo.currentText()
            if port:
                if self.bluetooth_manager.connect(port):
                    self.status_label.setText("Connected")
                    self.status_label.setStyleSheet("""
                        QLabel {
                            color: #2ecc71;
                            font-size: 14px;
                            background: transparent;
                        }
                    """)
                    self.connect_btn.setText("Disconnect")
                    self.connect_btn.setStyleSheet("""
                        QPushButton {
                            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 rgba(192, 57, 43, 0.8),
                                stop:1 rgba(231, 76, 60, 0.8));
                            color: white;
                            border: none;
                            border-radius: 5px;
                            padding: 5px 15px;
                            font-weight: bold;
                        }
                        QPushButton:hover {
                            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 rgba(231, 76, 60, 0.8),
                                stop:1 rgba(192, 57, 43, 0.8));
                        }
                        QPushButton:pressed {
                            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 rgba(192, 57, 43, 0.9),
                                stop:1 rgba(231, 76, 60, 0.9));
                        }
                    """)
                else:
                    QMessageBox.warning(self, "Connection Error", 
                                      "Failed to connect to the selected port.")
        else:
            self.bluetooth_manager.disconnect()
            self.status_label.setText("Not Connected")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #e74c3c;
                    font-size: 14px;
                    background: transparent;
                }
            """)
            self.connect_btn.setText("Connect")
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba(39, 174, 96, 0.8),
                        stop:1 rgba(46, 204, 113, 0.8));
                    color: white;
                    border: none;
                    border-radius: 5px;
                    padding: 5px 15px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba(46, 204, 113, 0.8),
                        stop:1 rgba(39, 174, 96, 0.8));
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba(39, 174, 96, 0.9),
                        stop:1 rgba(46, 204, 113, 0.9));
                }
            """)

class ChatBubble(QFrame):
    def __init__(self, text, is_user=False, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        self.setObjectName("userBubble" if is_user else "assistantBubble")
        
        # Add fade-in effect
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0)
        
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(150)  # Faster animation
        self.fade_animation.setStartValue(0)
        self.fade_animation.setEndValue(1)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Add slide-in effect
        self.slide_animation = QPropertyAnimation(self, b"geometry")
        self.slide_animation.setDuration(150)  # Faster animation
        self.slide_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Combine animations
        self.animation_group = QParallelAnimationGroup()
        self.animation_group.addAnimation(self.fade_animation)
        self.animation_group.addAnimation(self.slide_animation)
        
        # Setup UI
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(0)  # Reduce spacing
        
        message = QLabel(text)
        message.setWordWrap(True)
        message.setStyleSheet("""
            QLabel {
                color: #ffffff;
                background: transparent;
                font-size: 14px;
                line-height: 1.4;
            }
        """)
        layout.addWidget(message)
        
        # Style the bubble with glass effect
        self.setStyleSheet(f"""
            QFrame#userBubble {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(41, 128, 185, 0.8),
                    stop:1 rgba(52, 152, 219, 0.8));
                border-radius: 15px;
                border: 1px solid rgba(52, 152, 219, 0.3);
                margin-left: 50px;
                margin-right: 10px;
            }}
            QFrame#assistantBubble {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(44, 62, 80, 0.6),
                    stop:1 rgba(52, 73, 94, 0.6));
                border-radius: 15px;
                border: 1px solid rgba(52, 152, 219, 0.3);
                margin-left: 10px;
                margin-right: 50px;
            }}
        """)

    def showEvent(self, event):
        super().showEvent(event)
        # Setup slide animation
        start_geo = self.geometry()
        if self.is_user:
            start_geo.moveRight(start_geo.right() + 50)
        else:
            start_geo.moveLeft(start_geo.left() - 50)
        
        self.slide_animation.setStartValue(start_geo)
        self.slide_animation.setEndValue(self.geometry())
        
        # Start animation group
        self.animation_group.start()

class ChatArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Smooth scroll animation
        self.scroll_animation = QPropertyAnimation(self.verticalScrollBar(), b"value")
        self.scroll_animation.setDuration(200)  # Faster scrolling
        self.scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Setup UI
        self.setup_ui()

    def setup_ui(self):
        # Main widget setup
        main_widget = QWidget()
        main_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a1a2e,
                    stop:0.5 #16213e,
                    stop:1 #1a1a2e);
                border-radius: 15px;
            }
        """)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)
        
        # Chat container
        self.container = QWidget()
        self.container.setStyleSheet("background-color: transparent;")
        self.layout = QVBoxLayout(self.container)
        self.layout.setSpacing(10)
        self.layout.addStretch()
        
        # Input area with glass effect
        input_container = QWidget()
        input_container.setObjectName("inputContainer")
        input_container.setStyleSheet("""
            QWidget#inputContainer {
                background: rgba(44, 62, 80, 0.6);
                border-radius: 20px;
                border: 1px solid rgba(52, 152, 219, 0.3);
            }
        """)
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(10, 10, 10, 10)
        input_layout.setSpacing(10)
        
        # Text input with glass effect
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Type a message or command...")
        self.text_input.setStyleSheet("""
            QLineEdit {
                background: rgba(44, 62, 80, 0.6);
                color: white;
                border: 2px solid rgba(52, 152, 219, 0.3);
                border-radius: 20px;
                padding: 10px 15px;
                font-size: 14px;
                selection-background-color: rgba(52, 152, 219, 0.5);
            }
            QLineEdit:focus {
                background: rgba(52, 73, 94, 0.6);
                border: 2px solid rgba(52, 152, 219, 0.8);
            }
        """)
        self.text_input.setMinimumHeight(40)
        
        # Send button with glass effect
        self.send_button = QPushButton("Send")
        self.send_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(41, 128, 185, 0.8),
                    stop:1 rgba(52, 152, 219, 0.8));
                color: white;
                border: none;
                border-radius: 20px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(52, 152, 219, 0.8),
                    stop:1 rgba(41, 128, 185, 0.8));
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(36, 117, 168, 0.8),
                    stop:1 rgba(41, 128, 185, 0.8));
            }
        """)
        self.send_button.setFixedHeight(40)
        
        input_layout.addWidget(self.text_input)
        input_layout.addWidget(self.send_button)
        
        # Add everything to main layout
        main_layout.addWidget(self.container)
        main_layout.addWidget(input_container)
        
        self.setWidget(main_widget)
        
        # Set scrollbar style
        self.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: rgba(26, 26, 46, 0.6);
                width: 10px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(52, 152, 219, 0.4);
                min-height: 30px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(52, 152, 219, 0.6);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

    def add_message(self, text, is_user=False):
        bubble = ChatBubble(text, is_user)
        self.layout.insertWidget(self.layout.count() - 1, bubble)
        
        # Animate scroll to bottom
        QTimer.singleShot(50, self._scroll_to_bottom)  # Small delay to ensure widget is properly laid out

    def _scroll_to_bottom(self):
        target_value = self.verticalScrollBar().maximum()
        current_value = self.verticalScrollBar().value()
        
        # Only animate if we're not already at the bottom
        if current_value != target_value:
            self.scroll_animation.setStartValue(current_value)
            self.scroll_animation.setEndValue(target_value)
            self.scroll_animation.start()
        
    def process_command(self, text):
        """Process commands from text input"""
        if text.strip():
            self.add_message(text, True)
            if hasattr(self, 'process_command_callback') and self.process_command_callback:
                self.process_command_callback(text)
            self.text_input.clear()
            # Return focus to input for next message
            self.text_input.setFocus()

    def set_command_processor(self, callback):
        """Set the callback for processing commands and connect signals"""
        self.process_command_callback = callback
        
        # Disconnect any existing connections first
        try:
            self.send_button.clicked.disconnect()
            self.text_input.returnPressed.disconnect()
        except:
            pass  # No existing connections
            
        # Connect signals
        self.send_button.clicked.connect(lambda: self.process_command(self.text_input.text()))
        self.text_input.returnPressed.connect(lambda: self.process_command(self.text_input.text()))

class DynamicIsland(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Fixed size - no more dynamic width changes
        self.setFixedSize(300, 60)
        self.status = "idle"
        self.wave_offset = 0
        self.wave_timer = QTimer()
        self.wave_timer.timeout.connect(self.update_wave)
        self.wave_timer.start(30)  # Update more frequently for smoother animation
        self.wave_points = []
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent;")
        
        # Pre-calculate wave points with higher density
        self.precalculate_wave_points()
        
    def precalculate_wave_points(self):
        self.wave_points = []
        # Increase density of points for smoother waves
        for x in range(0, self.width(), 2):
            self.wave_points.append(x)
            
    def update_wave(self):
        self.wave_offset += 0.15  # Slower wave movement
        if self.wave_offset > 2 * math.pi:
            self.wave_offset = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Create pill shape path
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), self.height()//2, self.height()//2)
        
        # Create gradient with glass effect
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        
        if self.status == "listening":
            gradient.setColorAt(0, QColor(41, 128, 185, 230))  # Increased opacity
            gradient.setColorAt(0.5, QColor(52, 152, 219, 230))
            gradient.setColorAt(1, QColor(41, 128, 185, 230))
        elif self.status == "speaking":
            gradient.setColorAt(0, QColor(39, 174, 96, 230))
            gradient.setColorAt(0.5, QColor(46, 204, 113, 230))
            gradient.setColorAt(1, QColor(39, 174, 96, 230))
        else:
            gradient.setColorAt(0, QColor(44, 62, 80, 200))
            gradient.setColorAt(0.5, QColor(52, 73, 94, 200))
            gradient.setColorAt(1, QColor(44, 62, 80, 200))
            
        # Fill background with glass effect
        painter.fillPath(path, gradient)
        
        # Add subtle border with animation
        if self.status in ["listening", "speaking"]:
            glow_color = QColor(52, 152, 219, 150) if self.status == "listening" else QColor(46, 204, 113, 150)
            painter.setPen(QPen(glow_color, 2))
        else:
            painter.setPen(QPen(QColor(52, 152, 219, 100), 1))
        painter.drawPath(path)
        
        # Draw wave animation if listening or speaking
        if self.status in ["listening", "speaking"]:
            painter.setClipPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            
            # Different wave colors for different states
            if self.status == "listening":
                wave_color = QColor(255, 255, 255, 50)
            else:  # speaking
                wave_color = QColor(255, 255, 255, 60)
            
            wave_height = 15  # Slightly reduced height for subtler effect
            
            for i in range(3):  # Three waves for better performance
                points = []
                offset = self.wave_offset + i * math.pi / 3
                
                # Improved wave calculation
                for x in self.wave_points:
                    # Combined sine waves for more organic movement
                    y = (math.sin(x * 0.03 + offset) * 0.6 + 
                         math.sin(x * 0.02 - offset * 1.5) * 0.4) * wave_height
                    points.append(QPoint(x, int(self.height()/2 + y)))
                
                wave_path = QPainterPath()
                wave_path.moveTo(0, self.height())
                
                # Create smooth wave path
                if points:
                    wave_path.moveTo(points[0].x(), points[0].y())
                    for i in range(1, len(points) - 2, 2):
                        wave_path.quadTo(
                            points[i].x(), points[i].y(),
                            (points[i].x() + points[i + 1].x()) / 2,
                            (points[i].y() + points[i + 1].y()) / 2
                        )
                
                wave_path.lineTo(self.width(), self.height())
                wave_path.lineTo(0, self.height())
                
                painter.fillPath(wave_path, wave_color)

    def animate(self, status):
        """Update status without size animation"""
        if status == self.status:
            return
        
        self.status = status
        
        # Start or stop wave animation based on status
        if status in ["listening", "speaking"]:
            if not self.wave_timer.isActive():
                self.wave_timer.start(30)
        else:
            if self.wave_timer.isActive():
                self.wave_timer.stop()
        
        self.update()  # Trigger repaint

class DeviceConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Device")
        self.setModal(True)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QLabel {
                color: white;
            }
            QLineEdit {
                background-color: #2c3e50;
                color: white;
                border: 1px solid #34495e;
                border-radius: 5px;
                padding: 5px;
            }
            QPushButton {
                background-color: #2980b9;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
            }
            QPushButton:hover {
                background-color: #3498db;
            }
        """)
        self.setup_ui()

    def setup_ui(self):
        layout = QGridLayout(self)
        
        # Device Name
        layout.addWidget(QLabel("Device Name:"), 0, 0)
        self.name_input = QLineEdit()
        layout.addWidget(self.name_input, 0, 1)
        
        # On Command
        layout.addWidget(QLabel("Voice Command (ON):"), 1, 0)
        self.on_command_input = QLineEdit()
        layout.addWidget(self.on_command_input, 1, 1)
        
        # Off Command
        layout.addWidget(QLabel("Voice Command (OFF):"), 2, 0)
        self.off_command_input = QLineEdit()
        layout.addWidget(self.off_command_input, 2, 1)
        
        # Bluetooth Signal (ON)
        layout.addWidget(QLabel("Bluetooth Signal (ON):"), 3, 0)
        self.on_signal_input = QLineEdit()
        layout.addWidget(self.on_signal_input, 3, 1)
        
        # Bluetooth Signal (OFF)
        layout.addWidget(QLabel("Bluetooth Signal (OFF):"), 4, 0)
        self.off_signal_input = QLineEdit()
        layout.addWidget(self.off_signal_input, 4, 1)
        
        # Buttons
        button_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout, 5, 0, 1, 2)

    def get_device_data(self):
        return {
            "name": self.name_input.text(),
            "on_command": self.on_command_input.text(),
            "off_command": self.off_command_input.text(),
            "on_signal": self.on_signal_input.text(),
            "off_signal": self.off_signal_input.text()
        }

class DeviceManager(QFrame):
    def __init__(self, bluetooth_manager, parent=None):
        super().__init__(parent)
        self.bluetooth_manager = bluetooth_manager
        self.devices = {}
        self.load_devices()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # Create a glass-effect container
        container = QFrame(self)
        container.setObjectName("deviceContainer")
        container.setStyleSheet("""
            QFrame#deviceContainer {
                background: rgba(44, 62, 80, 0.3);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 10px;
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(15, 15, 15, 15)
        container_layout.setSpacing(15)

        # Header with Add Device button
        header_layout = QHBoxLayout()
        header = QLabel("Devices")
        header.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        header_layout.addWidget(header)
        
        # Add Device button
        add_btn = QPushButton("Add Device")
        add_btn.clicked.connect(self.add_device)
        add_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(39, 174, 96, 0.8),
                    stop:1 rgba(46, 204, 113, 0.8));
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(46, 204, 113, 0.8),
                    stop:1 rgba(39, 174, 96, 0.8));
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(39, 174, 96, 0.9),
                    stop:1 rgba(46, 204, 113, 0.9));
            }
        """)
        header_layout.addWidget(add_btn)
        container_layout.addLayout(header_layout)

        # Devices list with glass effect
        self.device_list = QListWidget()
        self.device_list.setStyleSheet("""
            QListWidget {
                background: rgba(44, 62, 80, 0.4);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 8px;
                color: white;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid rgba(52, 152, 219, 0.2);
            }
            QListWidget::item:selected {
                background: rgba(52, 152, 219, 0.4);
            }
            QListWidget::item:hover {
                background: rgba(52, 73, 94, 0.4);
            }
        """)
        container_layout.addWidget(self.device_list)

        # Device details widget with glass effect
        self.details_widget = QWidget()
        self.details_widget.setObjectName("detailsWidget")
        self.details_widget.setStyleSheet("""
            QWidget#detailsWidget {
                background: rgba(44, 62, 80, 0.4);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 8px;
            }
        """)
        details_layout = QVBoxLayout(self.details_widget)
        details_layout.setContentsMargins(15, 15, 15, 15)
        details_layout.setSpacing(10)
        
        # Device info labels
        self.name_label = QLabel()
        self.commands_label = QLabel()
        self.signals_label = QLabel()
        for label in [self.name_label, self.commands_label, self.signals_label]:
            label.setStyleSheet("""
                QLabel {
                    color: white;
                    padding: 5px;
                    background: rgba(44, 62, 80, 0.3);
                    border-radius: 5px;
                }
            """)
            label.setWordWrap(True)
            details_layout.addWidget(label)
        
        # Delete button
        delete_btn = QPushButton("Delete Device")
        delete_btn.clicked.connect(self.delete_selected_device)
        delete_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(192, 57, 43, 0.8),
                    stop:1 rgba(231, 76, 60, 0.8));
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-size: 13px;
                font-weight: bold;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(231, 76, 60, 0.8),
                    stop:1 rgba(192, 57, 43, 0.8));
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(192, 57, 43, 0.9),
                    stop:1 rgba(231, 76, 60, 0.9));
            }
        """)
        details_layout.addWidget(delete_btn)
        
        container_layout.addWidget(self.details_widget)
        self.details_widget.hide()

        # Connect selection signal
        self.device_list.itemSelectionChanged.connect(self.show_device_details)
        
        # Add container to main layout
        layout.addWidget(container)
        
        self.update_device_list()

    def show_device_details(self):
        selected_items = self.device_list.selectedItems()
        if selected_items:
            device_name = selected_items[0].text()
            device = self.devices[device_name]
            
            self.name_label.setText(f"Device: {device_name}")
            self.commands_label.setText(
                f"Commands:\n"
                f"ON: {device['on_command']}\n"
                f"OFF: {device['off_command']}"
            )
            self.signals_label.setText(
                f"Bluetooth Signals:\n"
                f"ON: {device['on_signal']}\n"
                f"OFF: {device['off_signal']}"
            )
            self.details_widget.show()
        else:
            self.details_widget.hide()

    def delete_selected_device(self):
        selected_items = self.device_list.selectedItems()
        if selected_items:
            device_name = selected_items[0].text()
            reply = QMessageBox.question(
                self, 
                'Delete Device',
                f'Are you sure you want to delete "{device_name}"?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                del self.devices[device_name]
                self.save_devices()
                self.update_device_list()
                self.details_widget.hide()

    def update_device_list(self):
        self.device_list.clear()
        for name in self.devices.keys():
            item = QListWidgetItem(name)
            self.device_list.addItem(item)

    def add_device(self):
        dialog = DeviceConfigDialog(self)
        if dialog.exec():
            device_data = dialog.get_device_data()
            self.devices[device_data["name"]] = {
                "on_command": device_data["on_command"].lower(),
                "off_command": device_data["off_command"].lower(),
                "on_signal": device_data["on_signal"],
                "off_signal": device_data["off_signal"]
            }
            self.save_devices()
            self.update_device_list()

    def load_devices(self):
        try:
            with open('devices.json', 'r') as f:
                self.devices = json.load(f)
        except FileNotFoundError:
            self.devices = {}

    def save_devices(self):
        with open('devices.json', 'w') as f:
            json.dump(self.devices, f, indent=4)

    def process_command(self, command):
        command = command.lower()
        for device_name, device_data in self.devices.items():
            # Only check for exact matches or very close matches to device commands
            if (device_data["on_command"] == command or 
                device_data["off_command"] == command or
                f"turn {device_data['on_command']}" == command or
                f"turn {device_data['off_command']}" == command):
                
                if self.bluetooth_manager.is_connected:
                    # Send the Bluetooth signal
                    if device_data["on_command"] in command:
                        success = self.bluetooth_manager.send_data(device_data["on_signal"])
                        if success:
                            return f"Turning on {device_name}"
                        else:
                            return f"Failed to send signal to {device_name}"
                    else:
                        success = self.bluetooth_manager.send_data(device_data["off_signal"])
                        if success:
                            return f"Turning off {device_name}"
                        else:
                            return f"Failed to send signal to {device_name}"
                else:
                    return "Please connect to Bluetooth device first"
        return None  # Return None if no device command matched

class AppConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Application")
        self.setModal(True)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QLabel {
                color: white;
            }
            QLineEdit {
                background-color: #2c3e50;
                color: white;
                border: 1px solid #34495e;
                border-radius: 5px;
                padding: 5px;
            }
            QPushButton {
                background-color: #2980b9;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
            }
            QPushButton:hover {
                background-color: #3498db;
            }
        """)
        self.setup_ui()

    def setup_ui(self):
        layout = QGridLayout(self)
        
        # App Name
        layout.addWidget(QLabel("App Name:"), 0, 0)
        self.name_input = QLineEdit()
        layout.addWidget(self.name_input, 0, 1)
        
        # Voice Command
        layout.addWidget(QLabel("Voice Command:"), 1, 0)
        self.command_input = QLineEdit()
        layout.addWidget(self.command_input, 1, 1)
        
        # App Path
        layout.addWidget(QLabel("App Path:"), 2, 0)
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        path_layout.addWidget(self.path_input)
        
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_file)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout, 2, 1)
        
        # Buttons
        button_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout, 3, 0, 1, 2)

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Application",
            "",
            "Applications (*.exe);;All Files (*.*)"
        )
        if file_path:
            self.path_input.setText(file_path)

    def get_app_data(self):
        return {
            "name": self.name_input.text(),
            "command": self.command_input.text().lower(),
            "path": self.path_input.text()
        }

class AppsManager(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.apps = {}
        self.load_apps()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)

        # Header
        header_layout = QHBoxLayout()
        header = QLabel("Applications")
        header.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        header_layout.addWidget(header)
        
        # Add App button
        add_btn = QPushButton("Add App")
        add_btn.clicked.connect(self.add_app)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
        """)
        header_layout.addWidget(add_btn)
        layout.addLayout(header_layout)

        # Apps list
        self.app_list = QListWidget()
        self.app_list.setStyleSheet("""
            QListWidget {
                background-color: #2c3e50;
                border: 1px solid #34495e;
                border-radius: 5px;
                color: white;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #34495e;
            }
            QListWidget::item:selected {
                background-color: #3498db;
            }
            QListWidget::item:hover {
                background-color: #34495e;
            }
        """)
        layout.addWidget(self.app_list)

        # App details widget
        self.details_widget = QWidget()
        details_layout = QVBoxLayout(self.details_widget)
        details_layout.setContentsMargins(0, 10, 0, 0)
        
        # App info labels
        self.name_label = QLabel()
        self.command_label = QLabel()
        self.path_label = QLabel()
        for label in [self.name_label, self.command_label, self.path_label]:
            label.setStyleSheet("color: white; padding: 5px;")
            label.setWordWrap(True)
            details_layout.addWidget(label)
        
        # Delete button
        delete_btn = QPushButton("Delete App")
        delete_btn.clicked.connect(self.delete_selected_app)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #c0392b;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-size: 13px;
                margin-top: 10px;
            }
            QPushButton:hover {
                background-color: #e74c3c;
            }
        """)
        details_layout.addWidget(delete_btn)
        
        layout.addWidget(self.details_widget)
        self.details_widget.hide()

        # Connect selection signal
        self.app_list.itemSelectionChanged.connect(self.show_app_details)
        
        self.update_app_list()

    def show_app_details(self):
        selected_items = self.app_list.selectedItems()
        if selected_items:
            app_name = selected_items[0].text()
            app = self.apps[app_name]
            
            self.name_label.setText(f"App: {app_name}")
            self.command_label.setText(f"Voice Command: {app['command']}")
            self.path_label.setText(f"Path: {app['path']}")
            self.details_widget.show()
        else:
            self.details_widget.hide()

    def delete_selected_app(self):
        selected_items = self.app_list.selectedItems()
        if selected_items:
            app_name = selected_items[0].text()
            reply = QMessageBox.question(
                self, 
                'Delete Application',
                f'Are you sure you want to delete "{app_name}"?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                del self.apps[app_name]
                self.save_apps()
                self.update_app_list()
                self.details_widget.hide()

    def update_app_list(self):
        self.app_list.clear()
        for name in self.apps.keys():
            item = QListWidgetItem(name)
            self.app_list.addItem(item)

    def add_app(self):
        dialog = AppConfigDialog(self)
        if dialog.exec():
            app_data = dialog.get_app_data()
            self.apps[app_data["name"]] = {
                "command": app_data["command"].lower(),
                "path": app_data["path"]
            }
            self.save_apps()
            self.update_app_list()

    def load_apps(self):
        try:
            with open('apps.json', 'r') as f:
                self.apps = json.load(f)
        except FileNotFoundError:
            self.apps = {}

    def save_apps(self):
        with open('apps.json', 'w') as f:
            json.dump(self.apps, f, indent=4)

    def process_command(self, command):
        command = command.lower().strip()
        for app_name, app_data in self.apps.items():
            # Split command into words for more precise matching
            command_words = command.split()
            app_command_words = app_data["command"].lower().strip().split()
            
            # Check if the app's command words appear in sequence in the user's command
            if self._check_sequence_match(command_words, app_command_words):
                try:
                    subprocess.Popen(app_data["path"])
                    return f"Opening {app_name}"
                except Exception as e:
                    return f"Failed to open {app_name}: {str(e)}"
        return None

    def _check_sequence_match(self, command_words, app_command_words):
        """
        Check if app_command_words appear in sequence within command_words
        Example: 
        command_words = ["please", "open", "chrome", "browser"]
        app_command_words = ["open", "chrome"]
        Would return True because "open chrome" appears in sequence
        """
        if not app_command_words:
            return False
            
        # Find the first word of the app command in the user's command
        try:
            start_idx = command_words.index(app_command_words[0])
        except ValueError:
            return False
            
        # Check if the remaining words match in sequence
        for i, word in enumerate(app_command_words[1:], 1):
            next_idx = start_idx + i
            if next_idx >= len(command_words) or command_words[next_idx] != word:
                return False
                
        return True

class Sidebar(QFrame):
    def __init__(self, bluetooth_manager, parent=None):
        super().__init__(parent)
        self.setFixedWidth(0)  # Start collapsed
        self.expanded_width = 520  # Width for camera display
        self.is_expanded = False
        self.animation = None
        
        # Set up the sidebar position
        self.setVisible(True)
        self.setMinimumWidth(0)
        
        # Set background and border styles
        self.setStyleSheet("""
            QFrame {
                background: qradialgradient(cx:0.5, cy:0.5, radius:1.5,
                    fx:0.5, fy:0.5,
                    stop:0 rgba(26, 26, 46, 0.97),
                    stop:0.6 rgba(22, 33, 62, 0.97),
                    stop:1 rgba(26, 26, 46, 0.97));
                border-top-right-radius: 35px;
                border-bottom-right-radius: 35px;
                border-right: 2px solid rgba(52, 152, 219, 0.3);
                border-top: 2px solid rgba(52, 152, 219, 0.2);
                border-bottom: 2px solid rgba(52, 152, 219, 0.2);
            }
        """)
        
        # Create main layout with proper spacing
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Create content widget with proper padding
        self.content = QWidget()
        self.content.setObjectName("sidebarContent")
        self.content.setStyleSheet("background: transparent;")
        
        # Content layout with increased padding
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(20, 20, 20, 20)
        self.content_layout.setSpacing(15)
        
        self.setup_ui(bluetooth_manager)
        
        # Add content to main layout
        self.main_layout.addWidget(self.content)
        
        # Initially hide content but keep frame visible
        self.content.setVisible(False)
        
    def toggle(self):
        if self.animation and self.animation.state() == QPropertyAnimation.State.Running:
            return
            
        if self.is_expanded:
            self.contract()
        else:
            self.expand()
            
    def expand(self):
        print("Debug: Expanding sidebar")  # Debug log
        if self.animation and self.animation.state() == QPropertyAnimation.State.Running:
            return
            
        if not self.is_expanded:
            # Get main window instance
            main_window = None
            current = self
            while current:
                if isinstance(current, MainWindow):
                    main_window = current
                    break
                current = current.parent()
            
            if self.animation:
                self.animation.stop()
                self.animation.deleteLater()
                
            self.animation = QPropertyAnimation(self, b"minimumWidth")
            self.animation.setDuration(300)
            self.animation.setStartValue(self.width())
            self.animation.setEndValue(self.expanded_width)
            self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.animation.finished.connect(self._on_expand_finished)
            
            # Show the sidebar before animation
            self.show()
            self.raise_()
            
            # Ensure content is visible
            self.content.show()
            self.stack.show()
            
            # Start animation
            self.animation.start()
            print("Debug: Sidebar expansion started")  # Debug log
    
    def contract(self):
        if self.animation:
            self.animation.stop()
            self.animation.deleteLater()
            
        self.animation = QPropertyAnimation(self, b"minimumWidth")
        self.animation.setDuration(300)
        self.animation.setStartValue(self.width())
        self.animation.setEndValue(0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._on_contract_finished)
        self.animation.start()
        
    def _on_expand_finished(self):
        self.is_expanded = True
        self.animation = None
        
    def _on_contract_finished(self):
        self.is_expanded = False
        self.animation = None

    def setup_ui(self, bluetooth_manager):
        # Header
        header = QLabel("Settings")
        header.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.95);
                font-size: 20px;
                font-weight: bold;
                padding: 15px 5px;
            }
        """)
        self.content_layout.addWidget(header)
        
        # Tab buttons container
        tab_container = QFrame()
        tab_container.setObjectName("tabContainer")
        tab_container.setFixedHeight(40)  # Adjusted height
        tab_container.setStyleSheet("""
            QFrame#tabContainer {
                background: rgba(44, 62, 80, 0.4);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 20px;
                padding: 2px;
            }
        """)
        
        # Tab layout with proper spacing
        tab_layout = QHBoxLayout(tab_container)
        tab_layout.setContentsMargins(4, 2, 4, 2)
        tab_layout.setSpacing(4)
        
        # Create tab buttons with improved styling
        buttons_data = [
            ("Bluetooth", "🔵", "Control Bluetooth connections"),
            ("Devices", "🔌", "Manage connected devices"),
            ("Apps", "📱", "Configure voice-activated apps"),
            ("Camera", "📷", "Camera analysis settings"),
            ("Code", "💻", "Generate and edit code"),
            ("Settings", "⚙️", "Configure API keys and models")
        ]
        
        self.buttons = {}
        for name, icon, tooltip in buttons_data:
            btn = QPushButton(f"{icon} {name}")
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setFixedHeight(32)  # Adjusted height
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(44, 62, 80, 0.6);
                    color: rgba(255, 255, 255, 0.85);
                    border: none;
                    border-radius: 16px;
                    padding: 4px 8px;
                    font-size: 11px;
                    font-weight: bold;
                    text-align: left;
                    margin: 0px;
                }
                QPushButton:checked {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba(52, 152, 219, 0.9),
                        stop:1 rgba(41, 128, 185, 0.9));
                    color: white;
                }
                QPushButton:hover:!checked {
                    background: rgba(52, 73, 94, 0.8);
                }
                QPushButton:pressed {
                    padding-top: 5px;
                    padding-bottom: 3px;
                }
            """)
            
            # Add drop shadow effect
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(6)
            shadow.setOffset(0, 1)
            shadow.setColor(QColor(0, 0, 0, 30))
            btn.setGraphicsEffect(shadow)
            
            tab_layout.addWidget(btn)
            self.buttons[name.lower()] = btn
        
        self.content_layout.addWidget(tab_container)
        
        # Stacked widget for different pages
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")
        
        # Add pages
        self.bluetooth_page = BluetoothControl(bluetooth_manager)
        self.stack.addWidget(self.bluetooth_page)
        
        self.device_page = DeviceManager(bluetooth_manager)
        self.stack.addWidget(self.device_page)
        
        self.apps_page = AppsManager()
        self.stack.addWidget(self.apps_page)
        
        # Create camera page with signal emitter from main window
        self.camera_page = CameraAnalyzer()
        if self.parent() and hasattr(self.parent(), 'signal_emitter'):
            self.camera_page.signal_emitter = self.parent().signal_emitter
        self.stack.addWidget(self.camera_page)
        
        # Add code generator page
        self.code_page = CodeGeneratorManager()
        self.stack.addWidget(self.code_page)

        # Add settings page
        self.settings_page = SettingsManager()
        self.stack.addWidget(self.settings_page)
        
        self.content_layout.addWidget(self.stack)
        
        # Connect buttons
        self.buttons['bluetooth'].clicked.connect(lambda: self.switch_page(0))
        self.buttons['devices'].clicked.connect(lambda: self.switch_page(1))
        self.buttons['apps'].clicked.connect(lambda: self.switch_page(2))
        self.buttons['camera'].clicked.connect(lambda: self.switch_page(3))
        self.buttons['code'].clicked.connect(lambda: self.switch_page(4))
        self.buttons['settings'].clicked.connect(lambda: self.switch_page(5))
        
        # Set initial state
        self.buttons['bluetooth'].setChecked(True)
        self.stack.setCurrentIndex(0)
    
    def switch_page(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate([self.buttons['bluetooth'], 
                               self.buttons['devices'], 
                               self.buttons['apps'], 
                               self.buttons['camera'],
                               self.buttons['code'],
                               self.buttons['settings']]):
            btn.setChecked(i == index)

class AnimatedButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setMinimumHeight(40)
        self._animation = QPropertyAnimation(self, b"geometry")
        self._animation.setDuration(100)
        self._base_stylesheet = ""
        self._hover_stylesheet = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event):
        self._animation.setEndValue(self.geometry().adjusted(-2, -2, 2, 2))
        self._animation.start()
        if self._hover_stylesheet:
            self.setStyleSheet(self._hover_stylesheet)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animation.setEndValue(self.geometry().adjusted(2, 2, -2, -2))
        self._animation.start()
        if self._base_stylesheet:
            self.setStyleSheet(self._base_stylesheet)
        super().leaveEvent(event)

    def setStyleSheets(self, base, hover):
        self._base_stylesheet = base
        self._hover_stylesheet = hover
        self.setStyleSheet(base)

class FadeInWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0)
        
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(500)
        self.fade_animation.setStartValue(0)
        self.fade_animation.setEndValue(1)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def showEvent(self, event):
        super().showEvent(event)
        self.fade_animation.start()

class GlowingLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._glow_radius = 0
        self._glow_color = QColor(52, 152, 219)
        
        self.glow_animation = QPropertyAnimation(self, b"glow_radius")
        self.glow_animation.setDuration(1500)
        self.glow_animation.setLoopCount(-1)
        self.glow_animation.setStartValue(0)
        self.glow_animation.setEndValue(10)
        self.glow_animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        
        # Set background to be transparent
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent; color: white;")

    def setGlowColor(self, color):
        self._glow_color = color
        self.update()

    def getGlowRadius(self):
        return self._glow_radius

    def setGlowRadius(self, radius):
        self._glow_radius = radius
        self.update()

    glow_radius = pyqtProperty(float, getGlowRadius, setGlowRadius)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw glow effect
        if self._glow_radius > 0:
            glow = self._glow_color
            for i in range(int(self._glow_radius)):
                alpha = int(127 * (1 - i / self._glow_radius))
                glow.setAlpha(alpha)
                painter.setPen(QPen(glow, i, Qt.PenStyle.SolidLine))
                painter.drawRoundedRect(self.rect().adjusted(i, i, -i, -i), 10, 10)

        # Draw the text
        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.drawText(self.rect(), self.alignment(), self.text())

class ClickableImageLabel(QLabel):
    """A QLabel that emits a signal when clicked, with the click coordinates"""
    clicked = pyqtSignal(object)  # Signal that will pass the click event

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.selection_start = None
        self.current_selection = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 240)  # Minimum reasonable size
        self.original_pixmap = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def setPixmap(self, pixmap):
        """Override setPixmap to store original and update display"""
        self.original_pixmap = pixmap
        self.updatePixmap()

    def resizeEvent(self, event):
        """Handle resize events by updating the displayed pixmap"""
        super().resizeEvent(event)
        self.updatePixmap()

    def updatePixmap(self):
        """Update the displayed pixmap with proper aspect ratio and letterboxing/pillarboxing"""
        if not self.original_pixmap:
            return

        # Get the widget size
        widget_size = self.size()
        if widget_size.width() <= 0 or widget_size.height() <= 0:
            return

        # Get the original image size
        img_size = self.original_pixmap.size()
        if img_size.width() <= 0 or img_size.height() <= 0:
            return

        # Calculate aspect ratios
        widget_ratio = widget_size.width() / widget_size.height()
        img_ratio = img_size.width() / img_size.height()

        # Calculate the target size maintaining aspect ratio
        if widget_ratio > img_ratio:
            # Widget is wider than image - fit to height
            target_height = widget_size.height()
            target_width = int(target_height * img_ratio)
        else:
            # Widget is taller than image - fit to width
            target_width = widget_size.width()
            target_height = int(target_width / img_ratio)

        # Create a black background pixmap
        background = QPixmap(widget_size)
        background.fill(QColor(0, 0, 0))

        # Scale the image
        scaled_pixmap = self.original_pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        # Create a painter to draw on the background
        painter = QPainter(background)
        
        # Calculate position to center the scaled image
        x = (widget_size.width() - target_width) // 2
        y = (widget_size.height() - target_height) // 2
        
        # Draw the scaled image centered on the background
        painter.drawPixmap(x, y, scaled_pixmap)
        painter.end()

        # Set the composite pixmap to the label
        super().setPixmap(background)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selection_start = event.pos()
            self.current_selection = None
            self.clicked.emit(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self.selection_start:
            # Update the current selection
            self.current_selection = QRect(
                self.selection_start,
                event.pos()
            ).normalized()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.current_selection:
            # Handle the selection if needed
            self.selection_start = None
            self.current_selection = None
            self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.current_selection:
            painter = QPainter(self)
            painter.setPen(QPen(QColor(52, 152, 219), 2))
            painter.drawRect(self.current_selection)

class CameraAnalyzer(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.camera = None
        self.is_capturing = False
        self.capture_thread = None
        self.frame_lock = threading.Lock()
        self.current_frame = None
        self.last_analyzed_frame = None
        self.last_analysis_time = 0
        self.analysis_cooldown = 2  # Seconds between analyses
        self.model = None  # Initialize model as None
        
        # Get signal emitter from main window
        self.signal_emitter = None
        self.main_window = None
        
        # Find main window and signal emitter
        current = self
        while current:
            if isinstance(current, MainWindow):
                self.main_window = current
                self.signal_emitter = current.signal_emitter
                break
            current = current.parent()
            
        if not self.signal_emitter and parent:
            if hasattr(parent, 'signal_emitter'):
                self.signal_emitter = parent.signal_emitter
            else:
                print("Debug: Creating new signal emitter for CameraAnalyzer")
                self.signal_emitter = SignalEmitter()
        
        # Initialize Gemini model with API key from settings
        self.initialize_gemini_model()

    def initialize_gemini_model(self):
        """Initialize or reinitialize the Gemini model with current settings"""
        try:
            # Get API key from settings
            api_key = None
            settings_found = False
            
            # Try to get settings from main window first
            if self.main_window and hasattr(self.main_window, 'settings'):
                print("Debug: Found main window settings")
                settings_found = True
                api_key = self.main_window.settings.get('gemini_api_key', '').strip()
                print(f"Debug: API key from main window settings length: {len(api_key) if api_key else 0}")
            
            # If no main window settings, try to get from parent's parent
            if not api_key and self.parent() and hasattr(self.parent(), 'parent'):
                print("Debug: Trying to get settings from parent's parent")
                main_window = self.parent().parent()
                if isinstance(main_window, MainWindow) and hasattr(main_window, 'settings'):
                    settings_found = True
                    api_key = main_window.settings.get('gemini_api_key', '').strip()
                    print(f"Debug: API key from parent settings length: {len(api_key) if api_key else 0}")
            
            # If still no API key, try to load directly from settings file
            if not api_key:
                print("Debug: Trying to load settings directly from file")
                try:
                    if os.path.exists('settings.json'):
                        with open('settings.json', 'r') as f:
                            settings = json.load(f)
                            settings_found = True
                            api_key = settings.get('gemini_api_key', '').strip()
                            print(f"Debug: API key from settings file length: {len(api_key) if api_key else 0}")
                except Exception as e:
                    print(f"Debug: Error loading settings file: {str(e)}")
            
            if not settings_found:
                print("Debug: No settings source found")
                self.model = None
                return False
            
            if not api_key:
                print("Debug: API key is empty or not found in settings")
                self.model = None
                return False
            
            print("Debug: Configuring Gemini with API key")
            # Configure Gemini with API key
            genai.configure(api_key=api_key)
            
            # Hardcode model to gemini-1.5-flash
            model_name = 'gemini-1.5-flash'
            print(f"Debug: Creating model instance with {model_name}")
            
            # Create model instance with hardcoded configuration
            self.model = genai.GenerativeModel(
                model_name=model_name,
                generation_config={
                    "temperature": 0.4,
                    "top_p": 1,
                    "top_k": 32,
                    "max_output_tokens": 1024,
                },
                safety_settings=[
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ]
            )
            print("Debug: Gemini model initialized successfully with gemini-1.5-flash")
            return True
        except Exception as e:
            print(f"Debug: Error initializing Gemini model: {str(e)}")
            self.model = None
            return False

    def emit_message(self, text, is_user=False):
        """Helper method to emit messages to chat"""
        if self.signal_emitter:
            self.signal_emitter.new_message.emit(text, is_user)
        elif self.parent() and hasattr(self.parent(), 'signal_emitter'):
            self.parent().signal_emitter.new_message.emit(text, is_user)
        else:
            print(f"Debug: Could not emit message: {text}")

    def speak_text(self, text):
        """Helper method to speak text"""
        try:
            # First try to get the speak method from the main window
            main_window = None
            current = self
            while current:
                if isinstance(current, MainWindow):
                    main_window = current
                    break
                current = current.parent()
            
            if main_window and hasattr(main_window, 'speak'):
                main_window.speak(text)
            elif self.parent() and hasattr(self.parent(), 'speak'):
                self.parent().speak(text)
            else:
                print(f"Debug: Could not find speak method in any parent")
                # Try to find MainWindow instance in the widget hierarchy
                main_window = QApplication.instance().activeWindow()
                if isinstance(main_window, MainWindow):
                    main_window.speak(text)
                else:
                    print(f"Debug: Could not speak text: {text}")
        except Exception as e:
            print(f"Debug: Error in speak_text: {str(e)}")

    def analyze_image(self, image, prompt_text):
        """Analyze an image using Gemini"""
        try:
            if not is_gemini_initialized():
                error_msg = "⚠️ API key not configured. Please add your Gemini API key in Settings to use image analysis."
                self.emit_message(error_msg, False)
                self.status_label.setText("API key required")
                return
                
            self.progress_bar.setRange(0, 0)  # Indeterminate progress
            self.progress_bar.show()
            self.status_label.setText("Analyzing image...")
            print("Debug: Starting image analysis")
            
            # Ensure the image is in a format Gemini can handle
            if not isinstance(image, Image.Image):
                raise ValueError("Invalid image format")
            
            # Resize image if it's too large
            max_size = 768  # Reduced max size to help with API reliability
            if max(image.size) > max_size:
                print(f"Debug: Resizing image from {image.size} to fit within {max_size}x{max_size}")
                ratio = max_size / max(image.size)
                new_size = tuple(int(dim * ratio) for dim in image.size)
                image = image.resize(new_size, Image.Resampling.LANCZOS)
            
            # Convert image to RGB if it isn't already
            if image.mode != 'RGB':
                print("Debug: Converting image to RGB")
                image = image.convert('RGB')
            
            print("Debug: Preparing to call Gemini API for general description")
            # First, get a general description
            try:
                description_prompt = [
                    "Describe what you see in this image in a natural, conversational way.",
                    "Focus on the main elements and interesting details.",
                    "Be concise but informative."
                ]
                
                # Set a timeout for the API call
                print("Debug: Making first API call")
                description_response = self.model.generate_content(
                    ["\n".join(description_prompt), image],
                    generation_config={
                        "temperature": 0.4,
                        "top_p": 1,
                        "top_k": 32,
                        "max_output_tokens": 512,
                    }
                )
                print("Debug: Received response from first API call")
                
                if not description_response:
                    raise ValueError("No response received from Gemini API")
                
                # Get the text from the response
                description_text = description_response.text if hasattr(description_response, 'text') else str(description_response)
                print(f"Debug: Description text length: {len(description_text)}")
                print(f"Debug: Description text content: {description_text}")  # Added debug print
                
                if not description_text.strip():
                    raise ValueError("Empty response from Gemini API")
                
            except Exception as e:
                print(f"Debug - Error in general description: {str(e)}")
                raise
            
            # Handle specific question if provided
            combined_response = ""
            speak_text = ""
            
            try:
                if prompt_text != "What do you see in this image?":
                    print("Debug: Making second API call for specific question")
                    specific_response = self.model.generate_content(
                        [prompt_text, image],
                        generation_config={
                            "temperature": 0.4,
                            "top_p": 1,
                            "top_k": 32,
                            "max_output_tokens": 512,
                        }
                    )
                    print("Debug: Received response from second API call")
                    
                    specific_text = specific_response.text if hasattr(specific_response, 'text') else str(specific_response)
                    print(f"Debug: Specific response text length: {len(specific_text)}")
                    print(f"Debug: Specific response content: {specific_text}")  # Added debug print
                    
                    if not specific_text.strip():
                        raise ValueError("Empty response for specific question")
                        
                    combined_response = f"Here's what I see:\n\n{description_text}\n\nAnswering your specific question:\n{specific_text}"
                    speak_text = f"Let me tell you what I see, and then answer your question. {description_text} Now, to answer your specific question: {specific_text}"
                else:
                    combined_response = f"Here's what I see:\n\n{description_text}"
                    speak_text = f"Let me tell you what I see. {description_text}"
            
            except Exception as e:
                print(f"Debug - Error in specific question: {str(e)}")
                # Fall back to just the general description
                combined_response = f"Here's what I see:\n\n{description_text}"
                speak_text = f"Let me tell you what I see. {description_text}"
            
            print("Debug: Preparing to emit response")
            print(f"Debug: Combined response: {combined_response}")  # Added debug print
            
            # Store the analyzed frame
            with self.frame_lock:
                if self.current_frame is not None:
                    self.last_analyzed_frame = self.current_frame.copy()
            self.last_analysis_time = time.time()
            
            # Use helper methods to emit message and speak
            self.emit_message(combined_response, False)
            self.speak_text(speak_text)
            
            self.status_label.setText("Analysis complete")
            print("Debug: Analysis complete")
            
        except Exception as e:
            error_msg = f"Error analyzing image: {str(e)}"
            print(f"Debug - Critical error in analyze_image: {error_msg}")
            self.status_label.setText("Analysis failed")
            
            # Use helper methods for error feedback
            error_response = (
                f"I encountered an error while analyzing the image: {error_msg}\n\n"
                "This might be due to:\n"
                "1. Network connectivity issues\n"
                "2. API rate limiting\n"
                "3. Image format or size issues\n"
                "Please try again in a moment."
            )
            self.emit_message(error_response, False)
            self.speak_text("Sorry, I encountered an error while analyzing the image. Please try again in a moment.")
            raise
        finally:
            self.progress_bar.hide()
            self.progress_bar.setRange(0, 100)
            QApplication.processEvents()  # Ensure UI updates

    def setup_ui(self):
        print("Debug: Setting up camera UI")  # Debug log
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # Create a glass-effect container
        container = QFrame(self)
        container.setObjectName("cameraContainer")
        container.setStyleSheet("""
            QFrame#cameraContainer {
                background: rgba(44, 62, 80, 0.3);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 10px;
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(15, 15, 15, 15)
        container_layout.setSpacing(15)

        # Create camera container with no margins or padding
        camera_container = QWidget()
        camera_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        camera_container.setMinimumSize(480, 360)
        camera_container.setMaximumSize(800, 600)
        camera_container.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
                border-radius: 0px;
                padding: 0px;
                margin: 0px;
            }
        """)
        
        # Camera label with no margins or padding
        self.camera_label = ClickableImageLabel()
        self.camera_label.clicked.connect(self.handle_image_click)
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setStyleSheet("""
            QLabel {
                background: rgba(0, 0, 0, 0.3);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 5px;
                padding: 0px;
                margin: 0px;
            }
        """)
        
        # Ensure camera label is visible
        self.camera_label.show()
        print("Debug: Camera label created and shown")  # Debug log

        # Create layout with zero margins
        camera_layout = QVBoxLayout(camera_container)
        camera_layout.setContentsMargins(0, 0, 0, 0)
        camera_layout.setSpacing(0)
        camera_layout.addWidget(self.camera_label)

        # Add camera container to main layout
        container_layout.addWidget(camera_container, 0, Qt.AlignmentFlag.AlignHCenter)
        
        # Add minimal spacing between camera and controls
        container_layout.addSpacing(5)

        # Create controls container with proper spacing
        controls_container = QFrame()
        controls_container.setObjectName("controlsContainer")
        controls_container.setFixedHeight(70)  # Increased height for better spacing
        controls_container.setMinimumWidth(480)
        controls_container.setMaximumWidth(800)
        controls_container.setStyleSheet("""
            QFrame#controlsContainer {
                background: rgba(44, 62, 80, 0.4);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 15px;
                margin: 5px;
            }
        """)

        # Controls layout with proper spacing
        controls_layout = QHBoxLayout(controls_container)
        controls_layout.setContentsMargins(15, 5, 15, 5)  # Adjusted margins
        controls_layout.setSpacing(15)  # Adjusted spacing between buttons

        # Create buttons with consistent sizing
        self.camera_btn = QPushButton("start Camera")
        self.analyze_btn = QPushButton("Analyze")
        self.upload_btn = QPushButton("Upload")

        # Set fixed size for all buttons
        button_size = QSize(130, 45)  # Increased button size
        for btn in [self.camera_btn, self.analyze_btn, self.upload_btn]:
            btn.setFixedSize(button_size)
            btn.setFont(QFont("", 11, QFont.Weight.Bold))  # Increased font size and made bold

        # Style the camera button
        self.camera_btn.setStyleSheet("""
            QPushButton {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8, fx:0.45, fy:0.45,
                    stop:0 rgba(39, 174, 96, 0.9),
                    stop:1 rgba(46, 204, 113, 0.9));
                color: white;
                border: none;
                border-radius: 22px;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8, fx:0.45, fy:0.45,
                    stop:0 rgba(46, 204, 113, 0.9),
                    stop:1 rgba(39, 174, 96, 0.9));
            }
            QPushButton:pressed {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8, fx:0.45, fy:0.45,
                    stop:0 rgba(39, 174, 96, 1),
                    stop:1 rgba(46, 204, 113, 1));
                padding-top: 11px;
                padding-bottom: 9px;
            }
        """)
        
        # Style the analyze button
        self.analyze_btn.setStyleSheet("""
            QPushButton {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8, fx:0.45, fy:0.45,
                    stop:0 rgba(52, 152, 219, 0.9),
                    stop:1 rgba(41, 128, 185, 0.9));
                color: white;
                border: none;
                border-radius: 22px;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8, fx:0.45, fy:0.45,
                    stop:0 rgba(41, 128, 185, 0.9),
                    stop:1 rgba(52, 152, 219, 0.9));
            }
            QPushButton:pressed {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8, fx:0.45, fy:0.45,
                    stop:0 rgba(41, 128, 185, 1),
                    stop:1 rgba(52, 152, 219, 1));
                padding-top: 11px;
                padding-bottom: 9px;
            }
            QPushButton:disabled {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8, fx:0.45, fy:0.45,
                    stop:0 rgba(44, 62, 80, 0.5),
                    stop:1 rgba(52, 73, 94, 0.5));
                color: rgba(255, 255, 255, 0.5);
            }
        """)
        
        # Style the upload button
        self.upload_btn.setStyleSheet("""
            QPushButton {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8, fx:0.45, fy:0.45,
                    stop:0 rgba(142, 68, 173, 0.9),
                    stop:1 rgba(155, 89, 182, 0.9));
                color: white;
                border: none;
                border-radius: 22px;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8, fx:0.45, fy:0.45,
                    stop:0 rgba(155, 89, 182, 0.9),
                    stop:1 rgba(142, 68, 173, 0.9));
            }
            QPushButton:pressed {
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8, fx:0.45, fy:0.45,
                    stop:0 rgba(142, 68, 173, 1),
                    stop:1 rgba(155, 89, 182, 1));
                padding-top: 11px;
                padding-bottom: 9px;
            }
        """)

        # Add drop shadows to buttons
        for btn in [self.camera_btn, self.analyze_btn, self.upload_btn]:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(20)  # Increased blur radius
            shadow.setOffset(0, 4)    # Slightly increased offset
            shadow.setColor(QColor(0, 0, 0, 100))  # Increased opacity
            btn.setGraphicsEffect(shadow)

        # Add buttons to layout with proper centering
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.camera_btn)
        controls_layout.addWidget(self.analyze_btn)
        controls_layout.addWidget(self.upload_btn)
        controls_layout.addStretch(1)

        # Connect button signals
        self.camera_btn.clicked.connect(self.toggle_camera)
        self.analyze_btn.clicked.connect(lambda: self.analyze_current_view())
        self.analyze_btn.setEnabled(False)
        self.upload_btn.clicked.connect(self.upload_image)

        # Add controls to main layout with proper alignment
        container_layout.addWidget(controls_container, 0, Qt.AlignmentFlag.AlignHCenter)

        # Status area with glass effect
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Camera inactive")
        self.status_label.setStyleSheet("""
            QLabel {
                color: white;
                padding: 5px 10px;
                background: rgba(44, 62, 80, 0.4);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 10px;
            }
        """)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(100)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 5px;
                text-align: center;
                background: rgba(44, 62, 80, 0.3);
                max-height: 12px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(52, 152, 219, 0.8),
                    stop:1 rgba(41, 128, 185, 0.8));
                border-radius: 4px;
            }
        """)
        self.progress_bar.hide()
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.progress_bar)
        status_layout.addStretch()
        container_layout.addLayout(status_layout)

        layout.addWidget(container)

    def handle_image_click(self, event):
        """Handle clicks on the image for object selection"""
        if not self.current_frame is None:
            # Get click coordinates relative to the image
            pos = event.pos()
            label_size = self.camera_label.size()
            pixmap_size = self.camera_label.pixmap().size()
            
            # Calculate scaling factors
            scale_x = pixmap_size.width() / label_size.width()
            scale_y = pixmap_size.height() / label_size.height()
            
            # Calculate actual coordinates in the image
            x = int(pos.x() * scale_x)
            y = int(pos.y() * scale_y)
            
            # Create a region of interest around the click
            roi_size = 100  # Size of the region to analyze
            x1 = max(0, x - roi_size//2)
            y1 = max(0, y - roi_size//2)
            x2 = min(pixmap_size.width(), x + roi_size//2)
            y2 = min(pixmap_size.height(), y + roi_size//2)
            
            # Analyze the specific region
            self.analyze_current_view(f"What is in the region I clicked at coordinates ({x}, {y})?")

    def upload_image(self):
        """Handle image upload from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*.*)"
        )
        
        if file_path:
            try:
                # Load and display the image
                image = cv2.imread(file_path)
                if image is not None:
                    # Convert BGR to RGB
                    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    with self.frame_lock:
                        self.current_frame = image
                    
                    # Update display
                    self._update_display(image)
                    self.analyze_btn.setEnabled(True)
                    self.status_label.setText("Image loaded")
                else:
                    QMessageBox.warning(self, "Error", "Could not load image")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Error loading image: {str(e)}")

    def _update_display(self, frame):
        """Update the display with the current frame"""
        if frame is not None:
            try:
                # Convert frame to RGB QImage
                h, w, ch = frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                
                # Get the size of the label
                label_size = self.camera_label.size()
                
                if label_size.width() <= 0 or label_size.height() <= 0:
                    return
                
                # Calculate scaling while preserving aspect ratio
                image_ratio = w / h
                label_ratio = label_size.width() / label_size.height()
                
                # Scale image to fill the label completely
                if image_ratio > label_ratio:
                    # Image is wider than label - scale to height
                    target_height = label_size.height()
                    target_width = int(target_height * image_ratio)
                else:
                    # Image is taller than label - scale to width
                    target_width = label_size.width()
                    target_height = int(target_width / image_ratio)
                
                # Scale the image
                scaled_image = qt_image.scaled(
                    target_width,
                    target_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # Create a black background image
                result = QImage(label_size, QImage.Format.Format_RGB888)
                result.fill(QColor(0, 0, 0))
                
                # Calculate position to center the scaled image
                x = (label_size.width() - scaled_image.width()) // 2
                y = (label_size.height() - scaled_image.height()) // 2
                
                # Draw the scaled image onto the background
                painter = QPainter(result)
                painter.drawImage(x, y, scaled_image)
                painter.end()
                
                # Convert to pixmap and set to label
                pixmap = QPixmap.fromImage(result)
                self.camera_label.setPixmap(pixmap)
                
            except Exception as e:
                print(f"Error updating display: {str(e)}")
                self.camera_label.clear()

    def process_command(self, command):
        """Process camera-related voice commands"""
        command = command.lower().strip()
        
        # Camera opening commands
        camera_open_triggers = [
            "what am i looking at",
            "open camera and tell me about",  # Base phrase
            "open camera and tell me",        # Partial match
            "open camera",                    # Basic command
            "show me what you see",
            "take a look at this"
        ]
        
        # Camera analysis commands
        analysis_triggers = [
            "what is this",
            "what do you see",
            "analyze this",
            "describe what you see",
            "tell me what this is"
        ]
        
        # Camera closing commands
        camera_close_triggers = [
            "close camera",
            "stop camera",
            "turn off camera"
        ]
        
        # Handle specific object queries
        specific_object_patterns = [
            "is there a",
            "do you see a",
            "do you see any",
            "can you see a",
            "can you see any",
            "where is the",
            "where are the",
            "find the",
            "locate the"
        ]
        
        # Check for camera opening commands first - using startswith for better matching
        if any(command.startswith(trigger) for trigger in camera_open_triggers):
            print("Debug: Processing camera open command")  # Debug log
            
            # Get the main window and sidebar
            main_window = None
            current = self
            while current:
                if isinstance(current, MainWindow):
                    main_window = current
                    break
                current = current.parent()
            
            if main_window and hasattr(main_window, 'sidebar'):
                print("Debug: Found main window and sidebar")  # Debug log
                # Switch to camera page and expand sidebar
                main_window.sidebar.switch_page(3)  # Camera page index
                main_window.sidebar.expand()
                QApplication.processEvents()  # Process pending events
            
            if not self.is_capturing:
                self.start_camera()
                return "Okay, opening the camera. Show me what you want me to analyze."
            else:
                return "Camera is already active. What would you like me to look at?"
        
        # Check for specific object queries
        elif any(pattern in command for pattern in specific_object_patterns):
            if not self.is_capturing:
                return "Please let me open the camera first. Say 'open camera' or 'what am I looking at'"
            
            # Check cooldown
            current_time = time.time()
            if current_time - self.last_analysis_time < self.analysis_cooldown:
                return "Please wait a moment before requesting another analysis."
            
            # Pass the specific query to the analyzer
            self.analyze_current_view(command)
            return "Let me look for that..."
        
        # Handle general camera analysis
        elif any(trigger in command for trigger in analysis_triggers):
            if not self.is_capturing:
                return "Please let me open the camera first. Say 'open camera' or 'what am I looking at'"
            
            # Check cooldown
            current_time = time.time()
            if current_time - self.last_analysis_time < self.analysis_cooldown:
                return "Please wait a moment before requesting another analysis."
            
            self.analyze_current_view()
            return "Let me take a look at that..."
        
        # Handle camera closing
        elif any(trigger in command for trigger in camera_close_triggers):
            if self.is_capturing:
                self.stop_camera()
                return "Closing camera."
            else:
                return "Camera is already closed."
        
        return None  # Return None if not a camera command

    def start_camera(self):
        print("Debug: Starting camera")  # Debug log
        if self.camera is None:
            try:
                print("Debug: Initializing camera")  # Debug log
                self.camera = cv2.VideoCapture(0)
                if not self.camera.isOpened():
                    print("Debug: Failed to open camera")  # Debug log
                    QMessageBox.warning(self, "Error", "Could not open camera")
                    return
                print("Debug: Camera opened successfully")  # Debug log
            except Exception as e:
                print(f"Debug: Error initializing camera: {str(e)}")  # Debug log
                QMessageBox.warning(self, "Error", f"Could not initialize camera: {str(e)}")
                return

        self.is_capturing = True
        self.camera_btn.setText("Stop Camera")
        self.analyze_btn.setEnabled(True)
        self.status_label.setText("Camera active")
        
        print("Debug: Starting capture thread")  # Debug log
        self.capture_thread = threading.Thread(target=self.update_frame, daemon=True)
        self.capture_thread.start()
        print("Debug: Camera started successfully")  # Debug log

    def stop_camera(self):
        self.is_capturing = False
        if self.camera:
            self.camera.release()
            self.camera = None
        
        self.camera_btn.setText("Start Camera")
        self.analyze_btn.setEnabled(False)  # Fixed: changed from capture_btn to analyze_btn
        self.status_label.setText("Camera inactive")
        
        # Clear the camera view
        self.camera_label.clear()
        self.current_frame = None

    def toggle_camera(self):
        if not self.is_capturing:
            self.start_camera()
        else:
            self.stop_camera()

    def update_frame(self):
        print("Debug: Starting camera frame update thread")  # Debug log
        while self.is_capturing:
            try:
                if not self.camera:
                    print("Debug: Camera not initialized")  # Debug log
                    break
                    
                ret, frame = self.camera.read()
                if ret:
                    # Store current frame
                    with self.frame_lock:
                        self.current_frame = frame.copy()
                    
                    # Convert frame to RGB for display
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_frame.shape
                    bytes_per_line = ch * w
                    
                    # Convert to QImage
                    qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                    
                    # Check if widget still exists
                    if self.camera_label and not self.camera_label.isVisible():
                        print("Debug: Camera label no longer visible")  # Debug log
                        break
                        
                    # Scale to fit label while maintaining aspect ratio
                    scaled_image = qt_image.scaled(self.camera_label.size(), 
                                                 Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
                    
                    # Update label with new image
                    self.camera_label.setPixmap(QPixmap.fromImage(scaled_image))
                else:
                    print("Debug: Failed to read frame from camera")  # Debug log
                
                time.sleep(0.03)  # Limit to ~30 fps
                
            except RuntimeError:
                print("Debug: Widget deleted, stopping camera thread")  # Debug log
                # Widget has been deleted, stop the thread
                break
            except Exception as e:
                print(f"Debug: Camera error: {str(e)}")  # Debug log
                break
        
        print("Debug: Camera frame update thread stopping")  # Debug log
        self.is_capturing = False
        if self.camera:
            self.camera.release()
            self.camera = None

    def analyze_current_view(self, custom_prompt=None):
        """Analyze the current view from camera or uploaded image"""
        print("Debug: Starting analyze_current_view")  # Debug log
        try:
            # Check if model is initialized
            if not self.model:
                if not self.initialize_gemini_model():
                    error_msg = "Gemini API key not configured. Please add your API key in settings."
                    print("Debug: " + error_msg)
                    self.status_label.setText("API key missing")
                    self.emit_message(error_msg, False)
                    self.speak_text("Please configure your Gemini API key in settings before using image analysis.")
                    return

            if self.current_frame is None:
                print("Debug: No current frame available")  # Debug log
                message = "No image available. Please start the camera or upload an image."
                self.status_label.setText("No image available")
                self.emit_message(message, False)
                self.speak_text(message)
                return

            # Check cooldown period
            current_time = time.time()
            if current_time - self.last_analysis_time < self.analysis_cooldown:
                print("Debug: Analysis cooldown in effect")  # Debug log
                message = "Please wait a moment before requesting another analysis."
                self.status_label.setText(message)
                self.emit_message(message, False)
                self.speak_text(message)
                return

            print("Debug: Processing frame for analysis")  # Debug log
            self.status_label.setText("Processing image...")
            self.progress_bar.setRange(0, 0)  # Show indeterminate progress
            self.progress_bar.show()
            
            with self.frame_lock:
                frame_to_analyze = self.current_frame.copy()
            
            print("Debug: Converting frame to RGB")  # Debug log
            # Convert frame to RGB
            if len(frame_to_analyze.shape) == 3:  # Color image
                rgb_frame = cv2.cvtColor(frame_to_analyze, cv2.COLOR_BGR2RGB)
            else:  # Grayscale image
                rgb_frame = cv2.cvtColor(frame_to_analyze, cv2.COLOR_GRAY2RGB)
                
            print("Debug: Converting to PIL Image")  # Debug log
            pil_image = Image.fromarray(rgb_frame)
            
            # Save debug image
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"capture_{timestamp}.jpg"
            print(f"Debug: Saving debug image as {filename}")  # Debug log
            cv2.imwrite(filename, frame_to_analyze)
            
            # Prepare the prompt based on the query type
            if custom_prompt:
                # Handle specific object queries
                if "is there" in custom_prompt.lower() or "do you see" in custom_prompt.lower():
                    prompt = f"{custom_prompt} Please focus specifically on finding and describing this object in the image."
                elif "where is" in custom_prompt.lower():
                    prompt = f"{custom_prompt} Please describe the location of this object in the image, using terms like 'top', 'bottom', 'left', 'right', 'center', etc."
                else:
                    prompt = custom_prompt
            else:
                prompt = [
                    "Describe what you see in this image.",
                    "Focus on the main objects and their locations.",
                    "If there are multiple objects, describe their spatial relationships.",
                    "If you see any text, read it.",
                    "Be natural and conversational in your response."
                ]
                prompt = "\n".join(prompt)
            
            print(f"Debug: Sending to Gemini with prompt: {prompt}")  # Debug log
            # Call Gemini for analysis
            response = self.model.generate_content(
                [prompt, pil_image],
                generation_config={
                    "temperature": 0.4,
                    "top_p": 1,
                    "top_k": 32,
                    "max_output_tokens": 1024,
                }
            )
            
            print("Debug: Received response from Gemini")  # Debug log
            if not response or not hasattr(response, 'text'):
                raise ValueError("No response received from Gemini API")
            
            response_text = response.text.strip()
            if not response_text:
                raise ValueError("Empty response from Gemini API")
            
            print(f"Debug: Response text: {response_text}")  # Debug log
            
            # Store the analyzed frame
            with self.frame_lock:
                self.last_analyzed_frame = self.current_frame.copy()
            self.last_analysis_time = time.time()
            
            # Emit and speak the response
            self.emit_message(response_text, False)
            self.speak_text(response_text)
            self.status_label.setText("Analysis complete")
            print("Debug: Analysis complete and response emitted")  # Debug log

        except Exception as e:
            error_msg = f"Error during analysis: {str(e)}"
            print(f"Debug - Error in analyze_current_view: {error_msg}")  # Debug log
            self.status_label.setText("Analysis failed")
            
            # Use helper methods for error feedback - only emit one error message
            error_response = (
                f"I encountered an error while analyzing the image: {error_msg}\n\n"
                "This might be due to:\n"
                "1. Network connectivity issues\n"
                "2. API rate limiting\n"
                "3. Image format or size issues\n"
                "Please try again in a moment."
            )
            self.emit_message(error_response, False)
            self.speak_text("Sorry, I encountered an error while analyzing the image. Please try again in a moment.")
            
        finally:
            self.progress_bar.hide()
            self.progress_bar.setRange(0, 100)
            # Reset animation state
            if hasattr(self.parent(), 'signal_emitter'):
                self.parent().signal_emitter.animation_trigger.emit("idle")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Initialize variables
        self.is_suspended = False
        self.is_speaking = False
        self.speech_queue = []
        self.speech_lock = threading.Lock()
        self.speech_event = threading.Event()
        self.stop_speech = threading.Event()
        self.stop_wake_word = threading.Event()
        self._welcome_shown = False
        self.settings = {}
        
        # Window dragging variables
        self.old_pos = None
        self.start_resize = False
        self.edge = None
        self.start_pos = None
        self.start_geometry = None
        self.arabic_tts_engine = None
        self.resize_margin = 5  # Add resize margin for window resizing
        
        # Load settings
        self.load_settings()
        
        # Create signal emitter
        self.signal_emitter = SignalEmitter()
        
        # Create main widget and layout
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QHBoxLayout(self.main_widget)  # Changed to horizontal layout
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Create content widget
        self.content_widget = QWidget()
        self.content_widget.setObjectName("mainContent")
        
        # Create content layout
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        
        # Create bluetooth manager
        self.bluetooth_manager = BluetoothManager()
        
        # Create sidebar
        self.sidebar = Sidebar(self.bluetooth_manager, self)
        
        # Add sidebar and content to main layout
        self.main_layout.addWidget(self.sidebar)
        self.main_layout.addWidget(self.content_widget)
        
        # Initialize UI
        self.initUI()
        
        # Initialize speech components and start threads
        self.initialize_speech_components()
        self.start_threads()
        
        # Schedule welcome message
        QTimer.singleShot(2000, self._show_welcome)

    def _show_welcome(self):
        """Show welcome message when app starts"""
        if not self._welcome_shown:  # Only show welcome message if not shown before
            welcome_msg = "Hi, your assistant is ready!"
            self.signal_emitter.new_message.emit(welcome_msg, False)
            self.speak(welcome_msg)
            self._welcome_shown = True

    def initUI(self):
        self.setWindowTitle('AI Assistant')
        # Set minimum and default size
        self.setMinimumSize(1024, 768)  # Increased minimum size
        self.resize(1280, 800)  # Set default size
        
        # Create main background frame
        background_frame = QFrame(self.content_widget)
        background_frame.setObjectName("mainBackground")
        background_frame.setStyleSheet("""
            QFrame#mainBackground {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a1a2e,
                    stop:0.5 #16213e,
                    stop:1 #1a1a2e);
                border-radius: 20px;
                border: 2px solid #2c3e50;
                margin: 0px;
                padding: 0px;
            }
        """)
        
        # Create layout for background frame
        bg_layout = QVBoxLayout(background_frame)
        bg_layout.setContentsMargins(15, 15, 15, 15)
        bg_layout.setSpacing(10)
        
        # Add background frame to content layout with negative left margin
        self.content_layout.addWidget(background_frame)
        self.content_layout.setContentsMargins(-20, 0, 0, 0)
        
        # Welcome message - using the correct method name
        QTimer.singleShot(1000, self._show_welcome)
        
        # Top controls with animations
        top_controls = QHBoxLayout()
        top_controls.setSpacing(10)
        
        # Window control buttons
        window_controls = QHBoxLayout()
        window_controls.setSpacing(8)
        
        # Increased button sizes
        button_size = 28
        close_btn = QPushButton("×")
        maximize_btn = QPushButton("□")
        minimize_btn = QPushButton("−")
        
        for btn in [close_btn, maximize_btn, minimize_btn]:
            btn.setFixedSize(button_size, button_size)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(44, 62, 80, 0.8);
                    color: white;
                    border: none;
                    border-radius: {button_size//2}px;
                    font-size: 18px;
                    font-weight: bold;
                    margin: 0px 2px;
                }}
                QPushButton:hover {{
                    background: rgba(52, 73, 94, 0.9);
                }}
                QPushButton:pressed {{
                    background: rgba(44, 62, 80, 1);
                    padding-top: 1px;
                }}
            """)
            apply_shadow(btn)
        
        # Special hover color for close button
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(44, 62, 80, 0.8);
                color: white;
                border: none;
                border-radius: {button_size//2}px;
                font-size: 18px;
                font-weight: bold;
                margin: 0px 2px;
            }}
            QPushButton:hover {{
                background: rgba(231, 76, 60, 0.9);
            }}
            QPushButton:pressed {{
                background: rgba(192, 57, 43, 1);
                padding-top: 1px;
            }}
        """)
        
        close_btn.clicked.connect(self.close)
        maximize_btn.clicked.connect(self.toggle_maximize)
        minimize_btn.clicked.connect(self.showMinimized)
        
        window_controls.addWidget(minimize_btn)
        window_controls.addWidget(maximize_btn)
        window_controls.addWidget(close_btn)
        window_controls.addStretch()
        
        # Animated menu button with increased spacing
        menu_btn = AnimatedButton("☰")
        menu_btn.setFixedSize(48, 48)  # Increased size
        
        # Animated suspend button with increased spacing
        self.suspend_btn = AnimatedButton("🎤")
        self.suspend_btn.setFixedSize(48, 48)  # Increased size
        self.suspend_btn.setCheckable(True)

        # Define button styles
        style = f"""
            QPushButton {{
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
                    fx:0.45, fy:0.45,
                    stop:0 rgba(52, 73, 94, 0.95),
                    stop:1 rgba(44, 62, 80, 0.95));
                color: white;
                border: none;
                border-radius: {button_size // 2}px;
                font-size: 20px;
                padding-bottom: 2px;
                margin: 0 5px;
            }}
            QPushButton:hover {{
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
                    fx:0.45, fy:0.45,
                    stop:0 rgba(52, 152, 219, 0.95),
                    stop:1 rgba(41, 128, 185, 0.95));
            }}
            QPushButton:pressed {{
                padding-top: 1px;
                padding-bottom: 1px;
            }}
        """

        checked_style = f"""
            QPushButton {{
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
                    fx:0.45, fy:0.45,
                    stop:0 rgba(46, 204, 113, 0.95),
                    stop:1 rgba(39, 174, 96, 0.95));
                color: white;
                border: none;
                border-radius: {button_size // 2}px;
                font-size: 20px;
                padding-bottom: 2px;
                margin: 0 5px;
            }}
            QPushButton:checked {{
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
                    fx:0.45, fy:0.45,
                    stop:0 rgba(231, 76, 60, 0.95),
                    stop:1 rgba(192, 57, 43, 0.95));
            }}
            QPushButton:hover:!checked {{
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
                    fx:0.45, fy:0.45,
                    stop:0 rgba(39, 174, 96, 1),
                    stop:1 rgba(46, 204, 113, 1));
            }}
        """

        # Apply styles and shadows
        menu_btn.setStyleSheets(style, style)
        self.suspend_btn.setStyleSheets(checked_style, checked_style)
        
        # Apply drop shadows using QGraphicsDropShadowEffect
        apply_shadow(menu_btn)
        apply_shadow(self.suspend_btn)

        menu_btn.clicked.connect(self.sidebar.toggle)
        self.suspend_btn.clicked.connect(self.toggle_suspension)
        
        top_controls.addLayout(window_controls)
        top_controls.addStretch()
        top_controls.addWidget(menu_btn)
        top_controls.addWidget(self.suspend_btn)
        bg_layout.addLayout(top_controls)
        
        # Glowing status label
        self.status_label = GlowingLabel("Waiting for 'computer'...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.glow_animation.start()
        bg_layout.addWidget(self.status_label)
        
        # Dynamic Island with enhanced animations
        self.dynamic_island = DynamicIsland()
        bg_layout.addWidget(self.dynamic_island, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Connect animation trigger signal to dynamic island
        self.signal_emitter.animation_trigger.connect(self.dynamic_island.animate)
        
        # Chat area with smooth scrolling
        self.chat_area = ChatArea()
        bg_layout.addWidget(self.chat_area)
        
        # Connect chat area command processor
        self.chat_area.set_command_processor(self.process_text_command)
        
        # Connect signal emitter to chat area
        self.signal_emitter.new_message.connect(self.chat_area.add_message)
        
        # Set window style
        self.setStyleSheet("""
            QMainWindow {
                background: transparent;
            }
        """)

    def initialize_speech_components(self):
        """Initialize speech recognition and TTS components"""
        print("\nInitializing speech components...")
        
        # Clean up any existing resources
        if hasattr(self, 'porcupine'):
            try:
                self.porcupine.delete()
            except:
                pass
            self.porcupine = None
            
        if hasattr(self, 'audio'):
            try:
                self.audio.terminate()
            except:
                pass
            self.audio = None
            
        if hasattr(self, 'wake_word_stream'):
            try:
                self.wake_word_stream.stop_stream()
                self.wake_word_stream.close()
            except:
                pass
            self.wake_word_stream = None
        
        # Initialize speech recognition
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.energy_threshold = 100
        self.recognizer.dynamic_energy_adjustment_damping = 0.15
        self.recognizer.dynamic_energy_ratio = 1.5
        self.recognizer.pause_threshold = 0.8
        self.recognizer.phrase_threshold = 0.3
        self.recognizer.non_speaking_duration = 0.5
        
        # Initialize VAD with status messages
        print("\nSetting up noise reduction...")
        try:
            vad_level = self.settings.get('vad_aggressiveness', 1)
            self.vad_manager = VADManager(aggressiveness=vad_level, signal_emitter=self.signal_emitter)
            print("Voice activity detection system is ready")
        except Exception as e:
            print(f"Warning: Could not initialize noise reduction: {str(e)}")
            print("Falling back to standard voice detection")
            self.vad_manager = None
            self.signal_emitter.status_changed.emit("⚠ Using basic voice detection")
            self.signal_emitter.new_message.emit("Noise reduction not available - using basic voice detection", False)
        
        self.initialize_tts_engine()
        
        # Initialize wake word detection
        print("\nInitializing wake word detection...")
        try:
            # Initialize Porcupine with key from settings
            porcupine_key = self.settings.get('porcupine_key', '')
            if not porcupine_key:
                print("No Porcupine key found in settings")
                self.signal_emitter.new_message.emit("Please add your Porcupine key in settings to enable wake word detection", False)
                self.signal_emitter.status_changed.emit("⚠ No wake word key")
                self.porcupine = None
                return

            # Initialize Porcupine with the only supported wake word
            self.porcupine = pvporcupine.create(
                access_key=porcupine_key,
                keywords=['computer']
            )
            
            # Initialize PyAudio
            self.audio = pyaudio.PyAudio()
            
            # Test audio input devices
            input_device_info = None
            for i in range(self.audio.get_device_count()):
                device_info = self.audio.get_device_info_by_index(i)
                if device_info['maxInputChannels'] > 0:
                    print(f"Found input device: {device_info['name']}")
                    input_device_info = device_info
                    break
            
            if not input_device_info:
                raise Exception("No input device found")
                
            print(f"Using audio device: {input_device_info['name']}")
            print("Wake word detection initialized successfully")
            print("Wake word set to 'computer'")
            
            # Set initial status
            if hasattr(self, 'status_label'):
                if self.vad_manager:
                    self.status_label.setText("Waiting for 'Computer' (Noise reduction active)")
                else:
                    self.status_label.setText("Waiting for 'Computer'")
                    
            # Send initial message without changing status
            self.signal_emitter.new_message.emit("Wake word detection is active. Say 'Computer' to start.", False)
            
            # Store the base status message for later use
            self.base_status = "Waiting for 'Computer' (Noise reduction active)" if self.vad_manager else "Waiting for 'Computer'"
            
        except Exception as e:
            print(f"Error initializing wake word detection: {str(e)}")
            self.porcupine = None
            self.signal_emitter.status_changed.emit("⚠ Wake word detection failed")
            self.signal_emitter.new_message.emit(f"Could not initialize wake word detection: {str(e)}", False)

    def start_threads(self):
        """Start all background threads"""
        print("\nStarting background threads...")
        
        # Initialize stop flags
        self.stop_wake_word = threading.Event()
        self.stop_speech = threading.Event()
        
        # Start speech processing thread
        self.speech_thread = threading.Thread(target=self.speech_worker, daemon=True)
        self.speech_thread.start()
        print("Speech processing thread started")
        
        # Check API key and initialize Gemini
        api_key = self.settings.get('gemini_api_key', '').strip()
        if api_key:
            if initialize_gemini(api_key):
                print("API key validated, starting voice features...")
                # Initialize speech components if needed
                if not hasattr(self, 'recognizer'):
                    self.initialize_speech_components()
                
                # Start appropriate listening thread based on wake word availability
                if self.porcupine:
                    print("Starting wake word detection thread...")
                    # Stop any existing wake word thread
                    if hasattr(self, 'wake_word_thread') and self.wake_word_thread and self.wake_word_thread.is_alive():
                        self.stop_wake_word.set()
                        self.wake_word_thread.join(timeout=1)
                    # Reset stop flag and start new thread
                    self.stop_wake_word.clear()
                    self.wake_word_thread = threading.Thread(target=self.wake_word_listener, daemon=True)
                    self.wake_word_thread.start()
                    print("Wake word detection thread started")
                else:
                    print("Starting fallback listening thread...")
                    # Stop any existing listening thread
                    if hasattr(self, 'listening_thread') and self.listening_thread and self.listening_thread.is_alive():
                        self.stop_wake_word.set()
                        self.listening_thread.join(timeout=1)
                    # Reset stop flag and start new thread
                    self.stop_wake_word.clear()
                    self.listening_thread = threading.Thread(target=self.background_listening, daemon=True)
                    self.listening_thread.start()
                    print("Fallback listening thread started")
                
                self.signal_emitter.new_message.emit("✓ Voice features are now enabled and ready to use.", False)
                if hasattr(self, 'status_label'):
                    if self.vad_manager:
                        self.status_label.setText("Waiting for 'Computer' (Noise reduction active)")
                    else:
                        self.status_label.setText("Waiting for 'Computer'")
            else:
                print("Voice features disabled - invalid API key")
                self.signal_emitter.new_message.emit("⚠️ Voice features are disabled. The provided API key appears to be invalid.", False)
        else:
            print("Voice features disabled - no API key configured")
            self.signal_emitter.new_message.emit("⚠️ Voice features are disabled. Please configure your API key in Settings to enable all features.", False)
            
        print("All background threads initialized")

    def speech_worker(self):
        """Dedicated thread for handling speech output"""
        while True:
            try:
                self.speech_event.wait()  # Wait for speech to be queued
                
                with self.speech_lock:
                    if self.speech_queue:
                        speech_type, content = self.speech_queue.pop(0)
                    else:
                        self.speech_event.clear()
                        # Reset to idle when queue is empty
                        try:
                            if not self.is_suspended:
                                self.signal_emitter.animation_trigger.emit("idle")
                        except:
                            pass
                        continue
                
                if not self.is_suspended and not self.stop_speech.is_set():
                    self.is_speaking = True
                    try:
                        self.signal_emitter.animation_trigger.emit("speaking")
                    except:
                        pass
                        
                    try:
                        if speech_type == 'file':
                            # Play MP3 file using system default player
                            if sys.platform == 'win32':
                                # Use absolute path and quotes to handle spaces
                                abs_path = os.path.abspath(content)
                                os.system(f'powershell -c "(New-Object Media.SoundPlayer \'{abs_path}\').PlaySync()"')
                            elif sys.platform == 'darwin':
                                os.system(f'afplay {content}')
                            else:
                                os.system(f'mpg123 {content}')
                            # Clean up temp file
                            try:
                                os.remove(content)
                            except:
                                pass
                        else:
                            self.engine.say(content)
                            self.engine.runAndWait()
                    except Exception as e:
                        print(f"Error in speech output: {str(e)}")
                    finally:
                        self.is_speaking = False
                        
                        # Reset to idle after speaking
                        if not self.speech_queue:
                            try:
                                if not self.is_suspended:
                                    self.signal_emitter.animation_trigger.emit("idle")
                            except:
                                pass
            except Exception as e:
                print(f"Error in speech worker: {str(e)}")
                time.sleep(0.1)  # Prevent tight loop on error

    def wake_word_listener(self):
        """Background thread for wake word detection using Porcupine"""
        try:
            self.wake_word_stream = self.audio.open(
                rate=self.porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.porcupine.frame_length,
                stream_callback=None
            )
            
            # Get speech language from settings
            speech_language = self.settings.get('speech_language', 'en-US')
            
            while not self.stop_wake_word.is_set():
                if self.is_suspended:
                    time.sleep(0.1)
                    continue
                
                try:
                    pcm = self.wake_word_stream.read(self.porcupine.frame_length, exception_on_overflow=False)
                    pcm = struct.unpack_from("h" * self.porcupine.frame_length, pcm)
                    
                    result = self.porcupine.process(pcm)
                    if result >= 0:  # Wake word detected
                        print("Wake word detected!")
                        
                        # Get current language setting
                        speech_language = self.settings.get('speech_language', 'en-US')
                        
                        # Set recognition language based on settings
                        if speech_language == 'ar-SA':
                            recognition_language = 'ar-AR'
                        elif speech_language == 'bilingual':
                            # In bilingual mode, we'll try both languages
                            recognition_language = 'bilingual'
                        else:
                            recognition_language = 'en-US'
                        # Stop current speech if any
                        self.stop_speaking()
                        
                        # Update UI and play acknowledgment based on language
                        if recognition_language == 'ar-AR':
                            self.status_label.setText("جاري الاستماع...")
                            self.speak("نعم؟")
                        elif recognition_language == 'bilingual':
                            self.status_label.setText("Listening...")
                            self.speak("Yes? / نعم؟")
                        else:
                            self.status_label.setText("Listening...")
                            self.speak("Yes?")
                        
                        time.sleep(0.5)  # Wait for acknowledgment
                        
                        # Temporarily stop wake word detection
                        self.wake_word_stream.stop_stream()
                        
                        # Listen for command using Google Speech Recognition
                        with sr.Microphone() as source:
                            try:
                                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)
                                
                                # Get the current language setting
                                speech_language = self.settings.get('speech_language', 'en-US')
                                
                                # Try to recognize command in the appropriate language
                                if speech_language == 'bilingual':
                                    # Try both languages and use the one that gives a result
                                    try:
                                        command = self.recognizer.recognize_google(
                                            audio,
                                            language="en-US",
                                            show_all=False
                                        )
                                    except sr.UnknownValueError:
                                        command = self.recognizer.recognize_google(
                                            audio,
                                            language="ar-SA",
                                            show_all=False
                                        )
                                else:
                                    command = self.recognizer.recognize_google(
                                        audio,
                                        language=speech_language,
                                        show_all=False
                                    )
                                
                                print(f"Received command: {command}")
                                self.signal_emitter.animation_trigger.emit("listening")
                                
                                # Add user message to chat
                                self.signal_emitter.new_message.emit(command, True)
                                
                                # Process command through existing logic
                                self.process_text_command(command)
                            
                            except sr.UnknownValueError:
                                error_msg = "عذراً، لم أفهم ذلك" if speech_language == "ar-SA" else "Sorry, I didn't catch that. Could you please repeat?"
                                self.signal_emitter.new_message.emit(error_msg, False)
                                self.speak(error_msg)
                            except sr.RequestError as e:
                                error_msg = "عذراً، حدث خطأ في خدمة التعرف على الكلام" if speech_language == "ar-SA" else f"Sorry, there was an error with the speech recognition service: {str(e)}"
                                self.signal_emitter.new_message.emit(error_msg, False)
                                self.speak(error_msg)
                            finally:
                                # Resume wake word detection
                                self.wake_word_stream.start_stream()
                                self.signal_emitter.animation_trigger.emit("idle")
                                
                                # Reset UI state
                                if self.vad_manager:
                                    status_msg = "Waiting for 'Computer' (Noise reduction active)"
                                else:
                                    status_msg = "Waiting for 'Computer'"
                                self.status_label.setText(status_msg)
                except Exception as e:
                    print(f"Error in wake word processing: {str(e)}")
                    time.sleep(0.1)
                    continue
                    
        except Exception as e:
            print(f"Error in wake word listener: {str(e)}")
        finally:
            if self.wake_word_stream:
                self.wake_word_stream.stop_stream()
                self.wake_word_stream.close()

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def stop_speaking(self):
        """Stop any ongoing speech and clear the queue"""
        try:
            # Stop any ongoing speech
            if hasattr(self, 'engine'):
                self.engine.stop()
            
            # Stop any playing audio
            if sys.platform == 'win32':
                os.system('taskkill /F /IM wmplayer.exe 2>NUL')
            elif sys.platform == 'darwin':
                os.system('killall afplay 2>/dev/null')
            else:
                os.system('killall mpg123 2>/dev/null')
            
            # Clear the speech queue
            with self.speech_lock:
                self.speech_queue.clear()
                self.speech_event.clear()
            
            # Reset speaking state
            self.is_speaking = False
            self.signal_emitter.animation_trigger.emit("idle")
            
        except Exception as e:
            print(f"Error stopping speech: {str(e)}")

    def toggle_suspension(self):
        """Toggle voice recognition suspension"""
        self.is_suspended = self.suspend_btn.isChecked()
        
        # Get current language setting
        speech_language = self.settings.get('speech_language', 'en-US')
        
        if self.is_suspended:
            self.suspend_btn.setText("🔇")
            if speech_language == 'ar-SA':
                self.status_label.setText("المساعد متوقف")
            else:
                self.status_label.setText("Assistant is suspended")
            self.dynamic_island.animate("idle")
            self.stop_speaking()
        else:
            if self.initialize_tts_engine():
                self.suspend_btn.setText("🎤")
                if speech_language == 'ar-SA':
                    self.status_label.setText("في انتظار كلمة 'computer'...")
                    self.speak("المساعد جاهز")
                elif speech_language == 'bilingual':
                    self.status_label.setText("Waiting for 'computer' / في انتظار 'computer'...")
                    self.speak("Assistant ready / المساعد جاهز")
                else:
                    self.status_label.setText("Waiting for 'computer'...")
                    self.speak("Assistant ready")
            else:
                self.is_suspended = True
                self.suspend_btn.setChecked(True)
                if speech_language == 'ar-SA':
                    self.status_label.setText("خطأ: لم يتم تهيئة نظام الكلام. يرجى المحاولة مرة أخرى.")
                else:
                    self.status_label.setText("Error: Could not initialize speech. Please try again.")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Get the position of the mouse relative to the window
            self.edge = self.get_edge(event.position().toPoint())
            if self.edge:
                # If on an edge, start resize
                self.start_resize = True
                self.start_pos = event.globalPosition().toPoint()
                self.start_geometry = self.geometry()
            elif event.position().y() < 50:  # Top area for moving
                self.old_pos = event.globalPosition().toPoint()
            else:
                self.old_pos = None
                self.start_resize = False

    def mouseMoveEvent(self, event):
        if hasattr(self, 'start_resize') and self.start_resize:
            # Handle resizing
            delta = event.globalPosition().toPoint() - self.start_pos
            new_geometry = self.start_geometry
            
            if self.edge & Qt.Edge.LeftEdge:
                new_geometry.setLeft(new_geometry.left() + delta.x())
            if self.edge & Qt.Edge.RightEdge:
                new_geometry.setRight(new_geometry.right() + delta.x())
            if self.edge & Qt.Edge.TopEdge:
                new_geometry.setTop(new_geometry.top() + delta.y())
            if self.edge & Qt.Edge.BottomEdge:
                new_geometry.setBottom(new_geometry.bottom() + delta.y())
                
            # Ensure minimum size
            if new_geometry.width() >= self.minimumWidth() and new_geometry.height() >= self.minimumHeight():
                self.setGeometry(new_geometry)
        
        elif self.old_pos and not self.isMaximized():
            # Handle window dragging
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPosition().toPoint()
        else:
            # Update cursor based on position
            edge = self.get_edge(event.position().toPoint())
            if edge & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif edge & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif edge & (Qt.Edge.TopEdge | Qt.Edge.LeftEdge) or edge & (Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif edge & (Qt.Edge.TopEdge | Qt.Edge.RightEdge) or edge & (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self.start_resize = False
        self.old_pos = None
        self.edge = 0

    def get_edge(self, pos):
        margin = self.resize_margin
        width = self.width()
        height = self.height()
        
        # Determine which edge the cursor is near
        edge = Qt.Edge(0)
        
        if pos.x() <= margin:
            edge |= Qt.Edge.LeftEdge
        if pos.x() >= width - margin:
            edge |= Qt.Edge.RightEdge
        if pos.y() <= margin:
            edge |= Qt.Edge.TopEdge
        if pos.y() >= height - margin:
            edge |= Qt.Edge.BottomEdge
            
        return edge

    def mouseDoubleClickEvent(self, event):
        if event.position().y() < 50:  # Top area
            self.toggle_maximize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Update the sidebar width if needed
        if self.sidebar.is_expanded:
            self.sidebar.setFixedWidth(min(300, self.width() // 3))

    def initialize_tts_engine(self):
        """Initialize or reinitialize the text-to-speech engine"""
        try:
            if hasattr(self, 'engine'):
                self.engine.stop()
                del self.engine
            self.engine = pyttsx3.init()
            
            # Configure engine properties
            self.engine.setProperty('rate', 150)  # Speed of speech
            self.engine.setProperty('volume', 1.0)  # Volume level
            
            # Set voice gender based on settings
            voices = self.engine.getProperty('voices')
            voice_gender = self.settings.get('voice_gender', 'male')
            speech_language = self.settings.get('speech_language', 'en-US')
            
            # Find appropriate voice based on gender and language
            selected_voice = None
            for voice in voices:
                # Check if voice name or ID contains gender indicator and language
                voice_info = voice.name.lower() + ' ' + voice.id.lower()
                if speech_language.startswith('ar'):
                    # For Arabic, prioritize Arabic voices
                    if 'arabic' in voice_info or 'ar' in voice_info:
                        selected_voice = voice
                        break
                else:
                    # For other languages, match gender
                    if voice_gender == 'male' and ('male' in voice_info or 'david' in voice_info):
                        selected_voice = voice
                        break
                    elif voice_gender == 'female' and ('female' in voice_info or 'zira' in voice_info):
                        selected_voice = voice
                        break
            
            # If we found a matching voice, use it
            if selected_voice:
                self.engine.setProperty('voice', selected_voice.id)
            # If no matching voice found, use first available voice
            elif voices:
                self.engine.setProperty('voice', voices[0].id)
                print(f"Warning: No matching voice found for {voice_gender} gender and {speech_language} language")
            
            return True
        except Exception as e:
            print(f"Error initializing TTS engine: {str(e)}")
            return False

    def cleanup_audio_resources(self):
        """Clean up audio resources before switching between wake word and command listening"""
        if hasattr(self, 'wake_word_stream') and self.wake_word_stream:
            try:
                if self.wake_word_stream.is_active():
                    self.wake_word_stream.stop_stream()
                self.wake_word_stream.close()
                self.wake_word_stream = None
            except Exception as e:
                print(f"Error stopping wake word stream: {str(e)}")
            
        # Ensure PyAudio instance is clean
        if hasattr(self, 'audio'):
            try:
                self.audio.terminate()
                self.audio = pyaudio.PyAudio()
            except Exception as e:
                print(f"Error resetting PyAudio: {str(e)}")

    def resume_wake_word_detection(self):
        """Resume wake word detection after command processing"""
        try:
            # Clean up any existing stream
            if hasattr(self, 'wake_word_stream') and self.wake_word_stream:
                if self.wake_word_stream.is_active():
                    self.wake_word_stream.stop_stream()
                self.wake_word_stream.close()
                self.wake_word_stream = None
            
            # Ensure we have a fresh PyAudio instance
            if not hasattr(self, 'audio') or self.audio is None:
                self.audio = pyaudio.PyAudio()
            
            # Create new stream
            self.wake_word_stream = self.audio.open(
                rate=self.porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.porcupine.frame_length,
                stream_callback=None
            )
            
            # Start the stream
            self.wake_word_stream.start_stream()
            
        except Exception as e:
            print(f"Error resuming wake word detection: {str(e)}")
            # If we fail to resume, try to reinitialize everything
            try:
                self.initialize_speech_components()
            except Exception as e2:
                print(f"Error reinitializing speech components: {str(e2)}")

    def load_settings(self):
        """Load settings from file"""
        try:
            print("Debug: Starting to load settings")
            if os.path.exists('settings.json'):
                with open('settings.json', 'r') as f:
                    self.settings = json.load(f)
                print("Debug: Settings loaded from file")
                print(f"Debug: API key present: {bool(self.settings.get('gemini_api_key', '').strip())}")
            else:
                print("Debug: No settings file found, using defaults")
                self.settings = {
                    'gemini_api_key': '',
                    'gemini_model': 'gemini-2.0-flash',
                    'porcupine_key': '',
                    'voice_gender': 'male',  # Default to male voice
                    'speech_language': 'en-US',  # Default to English
                    'vad_aggressiveness': 3  # Default VAD aggressiveness
                }
        except Exception as e:
            print(f"Debug: Error loading settings: {str(e)}")
            # Initialize with default settings if loading fails
            self.settings = {
                'gemini_api_key': '',
                'gemini_model': 'gemini-2.0-flash',
                'porcupine_key': '',
                'voice_gender': 'male',
                'speech_language': 'en-US',
                'vad_aggressiveness': 3
            }

    def save_settings(self):
        """Save settings to file and update main window"""
        try:
            # Get new API keys and compare with old ones
            new_api_key = self.gemini_key_input.text().strip()
            old_api_key = self.settings.get('gemini_api_key', '')
            new_porcupine_key = self.porcupine_key_input.text().strip()
            old_porcupine_key = self.settings.get('porcupine_key', '')
            
            # Update settings from UI
            self.settings['gemini_api_key'] = new_api_key
            self.settings['gemini_model'] = self.model_selector.currentData()
            self.settings['porcupine_key'] = new_porcupine_key
            self.settings['voice_gender'] = 'male' if self.voice_gender_selector.currentText() == "Male Voice" else 'female'
            
            # Get language setting
            language_text = self.language_selector.currentText()
            if language_text == "English":
                self.settings['speech_language'] = 'en-US'
            elif language_text == "Arabic":
                self.settings['speech_language'] = 'ar-SA'
            else:  # English & Arabic
                self.settings['speech_language'] = 'bilingual'
                
            # Handle API key changes
            restart_required = False
            
            if new_api_key != old_api_key:
                if initialize_gemini(new_api_key):
                    if not old_api_key:
                        # Find the MainWindow
                        main_window = self
                        while main_window and not isinstance(main_window, MainWindow):
                            main_window = main_window.parent()
                            
                        if main_window:
                            # Stop any existing threads
                            if hasattr(main_window, 'wake_word_thread') and main_window.wake_word_thread:
                                main_window.stop_wake_word.set()
                                main_window.wake_word_thread.join(timeout=1)
                            if hasattr(main_window, 'listening_thread') and main_window.listening_thread:
                                main_window.stop_wake_word.set()
                                main_window.listening_thread.join(timeout=1)
                            
                            # Reset stop flag
                            main_window.stop_wake_word.clear()
                            
                            # Initialize speech components and start threads
                            main_window.initialize_speech_components()
                            main_window.start_threads()
                            QMessageBox.information(self, "Success", "API key configured successfully. Voice features have been enabled.")
                        else:
                            QMessageBox.information(self, "Success", "API key configured successfully. Please restart to enable voice features.")
                            restart_required = True
                    else:
                        QMessageBox.information(self, "Success", "API key updated successfully.")
                else:
                    if new_api_key:
                        QMessageBox.warning(self, "Warning", "Invalid API key. Voice features will remain disabled.")
                    else:
                        QMessageBox.warning(self, "Warning", "No API key provided. Voice features will be disabled.")
                        
            # Handle Porcupine key changes
            if new_porcupine_key != old_porcupine_key:
                if new_porcupine_key:
                    restart_required = True
                    QMessageBox.information(self, "Success", "Wake word detection will be enabled after restart.")
                else:
                    QMessageBox.warning(self, "Notice", "Wake word detection will be disabled.")
            
            # Save to file
            with open('settings.json', 'w') as f:
                json.dump(self.settings, f, indent=4)
            
            # Find the MainWindow by traversing up the widget hierarchy
            parent = self.parent()
            while parent and not isinstance(parent, QMainWindow):
                parent = parent.parent()
            
            # Update main window if found
            if parent:
                # Reinitialize TTS engine with new voice settings
                if parent.initialize_tts_engine():
                    parent.speak("Settings saved successfully")
                
                # Update Gemini model if API key is present
                if self.settings.get('gemini_api_key', '').strip():
                    if hasattr(parent, 'sidebar') and hasattr(parent.sidebar, 'camera_page'):
                        parent.sidebar.camera_page.initialize_gemini_model()
            
            if restart_required:
                response = QMessageBox.question(
                    self, 
                    "Restart Required",
                    "Some changes require a restart to take effect. Would you like to restart now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if response == QMessageBox.StandardButton.Yes:
                    QApplication.quit()
                    os.execl(sys.executable, sys.executable, *sys.argv)
            else:
                QMessageBox.information(self, "Success", "Settings saved successfully!")
                
        except Exception as e:
            print(f"Debug: Error saving settings: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to save settings: {str(e)}")

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def process_device_command(self, command):
        return self.sidebar.device_page.process_command(command)

    def process_text_command(self, command):
        """Process commands from text input"""
        try:
            # Check for camera commands first
            camera_response = self.sidebar.camera_page.process_command(command.lower())
            if camera_response:
                self.signal_emitter.new_message.emit(str(camera_response), False)
                self.speak(camera_response)
                return

            # Check for device commands
            device_response = self.process_device_command(command)
            if device_response:
                # If it is a device command, handle it
                self.signal_emitter.new_message.emit(str(device_response), False)
                self.speak(device_response)
                return

            # Check for app commands
            app_response = self.sidebar.apps_page.process_command(command)
            if app_response:
                self.signal_emitter.new_message.emit(str(app_response), False)
                self.speak(app_response)
                return
                
            # Check for code generation commands
            code_response = self.sidebar.code_page.process_command(command)
            if code_response:
                self.signal_emitter.new_message.emit(str(code_response), False)
                self.speak(code_response)
                return
                
            # If it's not a device, camera, app, or code command, process with Gemini
            try:
                self.signal_emitter.status_changed.emit("Processing your request...")
                # Configure Gemini with API key from settings
                api_key = self.settings.get('gemini_api_key', '').strip()
                if initialize_gemini(api_key):
                    # Get validated model name
                    model_name = get_valid_model_name(self.settings.get('gemini_model', 'gemini-2.0-flash'))
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(command)
                    response_text = response.text if response and hasattr(response, 'text') else "Sorry, I couldn't process that request."
                    
                    # Add assistant message to chat
                    self.signal_emitter.new_message.emit(str(response_text), False)
                    self.speak(response_text)
                else:
                    error_msg = "Gemini API key not configured. Please add your API key in settings."
                    self.signal_emitter.new_message.emit(error_msg, False)
                    self.speak(error_msg)
            except Exception as e:
                error_msg = f"Error processing with Gemini: {str(e)}"
                print(error_msg)
                self.signal_emitter.new_message.emit("Sorry, I encountered an error processing your request.", False)
                self.speak("Sorry, I encountered an error processing your request.")
            
        except Exception as e:
            print(f"Error processing text command: {str(e)}")
            self.signal_emitter.new_message.emit(f"Error: {str(e)}", False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Get the position of the mouse relative to the window
            self.edge = self.get_edge(event.position().toPoint())
            if self.edge:
                # If on an edge, start resize
                self.start_resize = True
                self.start_pos = event.globalPosition().toPoint()
                self.start_geometry = self.geometry()
            elif event.position().y() < 50:  # Top area for moving
                self.old_pos = event.globalPosition().toPoint()
            else:
                self.old_pos = None
                self.start_resize = False

    def clean_text_for_tts(self, text):
        """Clean text before sending to TTS engine by removing special characters and formatting"""
        import re
        
        # Replace common special characters and formatting
        replacements = {
            '\n': ' ',          # Replace newlines with spaces
            '\t': ' ',          # Replace tabs with spaces
            '•': '',            # Remove bullet points
            '*': '',            # Remove asterisks
            '`': '',            # Remove backticks
            '|': ',',           # Replace pipes with commas
            '_': ' ',           # Replace underscores with spaces
            '...': ',',         # Replace ellipsis with comma
            '---': ',',         # Replace em dashes with comma
            '--': ',',          # Replace en dashes with comma
            '~': '',            # Remove tildes
            '>': '',            # Remove quote markers
            '<': '',            # Remove quote markers
            '[]': '',           # Remove empty brackets
            '()': '',           # Remove empty parentheses
            '{}': '',           # Remove empty braces
        }
        
        # Apply all replacements
        for old, new in replacements.items():
            text = text.replace(old, new)
            
        # Remove multiple spaces
        text = re.sub(r'\s+', ' ', text)
        
        # Remove spaces before punctuation
        text = re.sub(r'\s+([,.!?])', r'\1', text)
        
        # Clean up multiple commas
        text = re.sub(r',\s*,', ',', text)
        
        # Remove leading/trailing whitespace
        text = text.strip()
        
        return text

    def speak(self, text):
        """Queue text for speaking after cleaning"""
        if not self.is_suspended:
            # Clean the text before queuing
            cleaned_text = self.clean_text_for_tts(text)
            
            # Check if text contains Arabic characters
            if any(ord(char) in range(0x0600, 0x06FF) for char in cleaned_text):
                def tts_worker():
                    temp_file = None
                    mixer_initialized = False
                    try:
                        import tempfile
                        import time
                        
                        # Create a temporary file with proper permissions
                        temp_dir = tempfile.gettempdir()
                        temp_file = os.path.join(temp_dir, f'arabic_speech_{int(time.time())}.mp3')
                        
                        # Use gTTS for Arabic text
                        tts = gTTS(text=cleaned_text, lang='ar')
                        tts.save(temp_file)
                        
                        # Make sure pygame is not initialized
                        try:
                            pygame.mixer.quit()
                            time.sleep(0.1)  # Give time for resources to be released
                        except:
                            pass
                            
                        # Initialize pygame with proper settings
                        try:
                            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
                            mixer_initialized = True
                            
                            pygame.mixer.music.load(temp_file)
                            self.signal_emitter.animation_trigger.emit("speaking")
                            pygame.mixer.music.play()
                            
                            # Wait for playback to complete
                            while pygame.mixer.music.get_busy():
                                pygame.time.Clock().tick(10)
                                
                        except Exception as e:
                            print(f"Pygame error: {str(e)}, falling back to system audio")
                            # Fallback to system audio player if pygame fails
                            if sys.platform == 'win32':
                                os.system(f'powershell -c "(New-Object Media.SoundPlayer \'{temp_file}\').PlaySync()"')
                            elif sys.platform == 'darwin':
                                os.system(f'afplay "{temp_file}"')
                            else:
                                os.system(f'mpg123 "{temp_file}"')
                                
                    except Exception as e:
                        print(f"TTS error: {str(e)}")
                        self.signal_emitter.animation_trigger.emit("idle")
                        
                        # Fallback to regular TTS
                        with self.speech_lock:
                            self.speech_queue.append(('text', cleaned_text))
                            self.speech_event.set()
                        
                    finally:
                        # Clean up pygame
                        if mixer_initialized:
                            try:
                                pygame.mixer.music.stop()
                                pygame.mixer.quit()
                            except:
                                pass
                                
                        # Clean up the temporary file
                        if temp_file and os.path.exists(temp_file):
                            try:
                                os.remove(temp_file)
                            except Exception as e:
                                print(f"Error removing temporary file: {str(e)}")
                        
                        self.signal_emitter.animation_trigger.emit("idle")
                
                # Start TTS generation and playback in a thread
                tts_thread = threading.Thread(target=tts_worker)
                tts_thread.daemon = True
                tts_thread.start()
            else:
                # Use pyttsx3 for non-Arabic text
                with self.speech_lock:
                    self.speech_queue.append(('text', cleaned_text))
                    self.speech_event.set()
                    
                # Trigger speaking animation
                self.signal_emitter.animation_trigger.emit("speaking")

    def stop_speaking(self):
        """Stop any ongoing speech and clear the queue"""
        try:
            # Stop any ongoing speech
            if hasattr(self, 'engine'):
                self.engine.stop()
            
            # Stop any playing audio
            if sys.platform == 'win32':
                os.system('taskkill /F /IM wmplayer.exe 2>NUL')
            elif sys.platform == 'darwin':
                os.system('killall afplay 2>/dev/null')
            else:
                os.system('killall mpg123 2>/dev/null')
            
            # Clear the speech queue
            with self.speech_lock:
                self.speech_queue.clear()
                self.speech_event.clear()
            
            # Reset speaking state
            self.is_speaking = False
            self.signal_emitter.animation_trigger.emit("idle")
            
        except Exception as e:
            print(f"Error stopping speech: {str(e)}")

    def background_listening(self):
        """Basic listening method when wake word detection is not available"""
        print("Starting basic listening mode...")
        
        while not self.stop_wake_word.is_set():
            if self.is_suspended:
                time.sleep(0.1)
                continue
                
            try:
                with sr.Microphone() as source:
                    print("Listening for commands...")
                    audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)
                    
                    try:
                        # Get current language setting
                        speech_language = self.settings.get('speech_language', 'en-US')
                        
                        # Try to recognize command in the appropriate language
                        if speech_language == 'bilingual':
                            # Try both languages and use the one that gives a result
                            try:
                                command = self.recognizer.recognize_google(
                                    audio,
                                    language="en-US",
                                    show_all=False
                                )
                            except sr.UnknownValueError:
                                command = self.recognizer.recognize_google(
                                    audio,
                                    language="ar-SA",
                                    show_all=False
                                )
                        else:
                            command = self.recognizer.recognize_google(
                                audio,
                                language=speech_language,
                                show_all=False
                            )
                        
                        print(f"Received command: {command}")
                        self.signal_emitter.animation_trigger.emit("listening")
                        
                        # Add user message to chat
                        self.signal_emitter.new_message.emit(command, True)
                        
                        # Process command through existing logic
                        self.process_text_command(command)
                        
                    except sr.UnknownValueError:
                        # No speech detected, continue listening
                        pass
                    except sr.RequestError as e:
                        error_msg = "عذراً، حدث خطأ في خدمة التعرف على الكلام" if speech_language == "ar-SA" else f"Sorry, there was an error with the speech recognition service: {str(e)}"
                        self.signal_emitter.new_message.emit(error_msg, False)
                        self.speak(error_msg)
                        time.sleep(2)  # Wait before retrying
                        
            except Exception as e:
                print(f"Error in background listening: {str(e)}")
                time.sleep(0.1)  # Prevent tight loop on error
                
        print("Background listening stopped")

class CodeGeneratorManager(QFrame):
    # Define the signals
    hide_requested = pyqtSignal()
    show_requested = pyqtSignal()
    status_update = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor_config = {}
        self.load_editor_config()
        # Initially visible
        self.is_visible = True
        self.typing_thread = None
        self.generation_thread = None
        
        # Connect signals to slots
        self.hide_requested.connect(self._do_hide, Qt.ConnectionType.QueuedConnection)
        self.show_requested.connect(self._do_show, Qt.ConnectionType.QueuedConnection)
        if parent and hasattr(parent, 'signal_emitter'):
            self.status_update.connect(parent.signal_emitter.status_changed)
        
        self.setup_ui()
        
    def _do_hide(self):
        """Actual implementation of hide, runs in main thread"""
        if self.isVisible():
            self.hide()
            self.is_visible = False
        
    def _do_show(self):
        """Actual implementation of show, runs in main thread"""
        if not self.isVisible():
            self.show()
            self.is_visible = True
        
    def hide_generator(self):
        """Thread-safe method to hide the generator"""
        if self.isVisible():
            self.hide_requested.emit()
        
    def show_generator(self):
        """Thread-safe method to show the generator"""
        if not self.isVisible():
            self.show_requested.emit()

    def update_status(self, status):
        """Thread-safe method to update status"""
        self.status_update.emit(status)

    def _generate_code_thread(self, prompt):
        """Thread function for code generation"""
        try:
            # Get the code completion
            code = self.get_code_completion(prompt)
            if isinstance(code, str) and code:
                # Generate a filename based on the prompt
                filename = self._generate_filename(prompt)
                # Start the typing simulation in a new thread
                self.typing_thread = threading.Thread(target=self.simulate_typing, args=(code, filename))
                self.typing_thread.start()
                return code
            else:
                error_msg = "Failed to generate code. Please try again."
                if hasattr(self, 'parent') and hasattr(self.parent, 'signal_emitter'):
                    self.parent.signal_emitter.new_message.emit(error_msg, False)
                return error_msg
        except Exception as e:
            error_msg = f"Error in code generation: {str(e)}"
            print(error_msg)
            if hasattr(self, 'parent') and hasattr(self.parent, 'signal_emitter'):
                self.parent.signal_emitter.new_message.emit(error_msg, False)
            if hasattr(self, 'show_generator'):
                self.show_requested.emit()
            return error_msg

    def generate_code(self, prompt):
        """Start code generation in a separate thread"""
        try:
            if self.generation_thread and self.generation_thread.is_alive():
                return "Code generation already in progress"
                
            if self.typing_thread and self.typing_thread.is_alive():
                return "Code typing already in progress"
                
            self.generation_thread = threading.Thread(target=self._generate_code_thread, args=(prompt,))
            self.generation_thread.start()
            return "Starting code generation..."
        except Exception as e:
            return f"Error starting code generation: {str(e)}"

    def _generate_filename(self, prompt):
        """Generate a filename based on the prompt"""
        # Take the first few words of the prompt
        words = prompt.split()[:3]
        # Create a safe filename
        safe_name = "_".join(word.lower() for word in words if word.isalnum())
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        return f"generated_{safe_name}_{timestamp}.py"

    def simulate_typing(self, code, filename):
        """Simulate typing the code in the editor by writing it letter by letter"""
        if not code or not isinstance(code, str):
            print("Invalid code provided")
            return False
            
        try:
            # Hide the generator before typing
            if hasattr(self, 'hide_generator'):
                self.hide_requested.emit()  # Use the signal directly
            
            # Get the editor path from config
            editor_path = self.editor_config.get('path')
            if not editor_path:
                print("Editor path not configured")
                return False

            # Ensure the file exists with initial content
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write("# Generating code...\n")
            except Exception as e:
                print(f"Error creating file: {str(e)}")
                return False

            # Small delay before opening editor
            time.sleep(0.5)
                
            # Get additional editor arguments if any
            editor_args = self.editor_config.get('args', '').split()
            cmd = [editor_path] + editor_args + [filename]

            try:
                # Open the editor with file
                process = subprocess.Popen(cmd)
            except Exception as e:
                print(f"Error opening editor: {str(e)}")
                return False
            
            # Give the editor more time to open and stabilize
            time.sleep(2)
            
            # Split code into lines and then characters
            lines = code.split('\n')
            total_chars = sum(len(line) + 1 for line in lines)  # +1 for newline
            chars_written = 0
            
            try:
                # Clear the initial content
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write("")
                
                # Write the code character by character with minimal delays
                for line in lines:
                    for char in line:
                        try:
                            # Append the character
                            with open(filename, 'a', encoding='utf-8') as f:
                                f.write(char)
                        except Exception as e:
                            print(f"Error writing character: {str(e)}")
                            continue

                        # Smaller delay to reduce VS Code refreshes
                        time.sleep(random.uniform(0.002, 0.004))
                        
                        chars_written += 1
                        # Provide progress feedback less frequently
                        if chars_written % 200 == 0:
                            progress = f"Writing code: {chars_written}/{total_chars} characters..."
                            if hasattr(self, 'parent') and hasattr(self.parent, 'signal_emitter'):
                                # Use signal emission directly
                                self.parent.signal_emitter.status_changed.emit(progress)
                    
                    # Add newline after each line
                    try:
                        with open(filename, 'a', encoding='utf-8') as f:
                            f.write('\n')
                    except Exception as e:
                        print(f"Error writing newline: {str(e)}")
                        continue
                    chars_written += 1
                
            except Exception as e:
                print(f"Error during typing simulation: {str(e)}")
            
            # Show the generator again after completion
            if hasattr(self, 'show_generator'):
                self.show_requested.emit()  # Use the signal directly
            
            return True
            
        except Exception as e:
            print(f"Error in simulate_typing: {str(e)}")
            if hasattr(self, 'show_generator'):
                self.show_requested.emit()  # Use the signal directly
            return False

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # Create a glass-effect container
        container = QFrame(self)
        container.setObjectName("codeGenContainer")
        container.setStyleSheet("""
            QFrame#codeGenContainer {
                background: rgba(44, 62, 80, 0.3);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 10px;
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(15, 15, 15, 15)
        container_layout.setSpacing(15)

        # Header with configuration button
        header_layout = QHBoxLayout()
        header = QLabel("Code Generator")
        header.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        header_layout.addWidget(header)
        
        # Configure Editor button
        config_btn = QPushButton("Configure Editor")
        config_btn.clicked.connect(self.configure_editor)
        config_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(39, 174, 96, 0.8),
                    stop:1 rgba(46, 204, 113, 0.8));
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(46, 204, 113, 0.8),
                    stop:1 rgba(39, 174, 96, 0.8));
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(39, 174, 96, 0.9),
                    stop:1 rgba(46, 204, 113, 0.9));
            }
        """)
        header_layout.addWidget(config_btn)
        container_layout.addLayout(header_layout)

        # Editor info display
        self.editor_info = QLabel()
        self.editor_info.setWordWrap(True)
        self.editor_info.setStyleSheet("""
            QLabel {
                color: white;
                background: rgba(44, 62, 80, 0.4);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 8px;
                padding: 10px;
            }
        """)
        container_layout.addWidget(self.editor_info)

        # Example commands section
        examples_frame = QFrame()
        examples_frame.setStyleSheet("""
            QFrame {
                background: rgba(44, 62, 80, 0.4);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 8px;
            }
        """)
        examples_layout = QVBoxLayout(examples_frame)
        
        examples_header = QLabel("Example Commands")
        examples_header.setStyleSheet("color: white; font-weight: bold;")
        examples_layout.addWidget(examples_header)
        
        examples = [
            "Generate code for a Python function to calculate factorial",
            "Create a simple HTML page with a header and paragraph",
            "Write a JavaScript function to sort an array",
            "Make a CSS flexbox layout",
            "Create a Python class for a basic calculator"
        ]
        
        for example in examples:
            example_label = QLabel(f"• {example}")
            example_label.setStyleSheet("color: white;")
            example_label.setWordWrap(True)
            examples_layout.addWidget(example_label)
        
        container_layout.addWidget(examples_frame)
        container_layout.addStretch()
        
        # Add container to main layout
        layout.addWidget(container)
        
        # Update editor info display
        self.update_editor_info()

    def configure_editor(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Configure Code Editor")
        dialog.setModal(True)
        dialog.setStyleSheet("""
            QDialog {
                background-color: rgba(44, 62, 80, 0.4);
                color: white;
            }
            QLabel {
                color: white;
            }
            QLineEdit, QComboBox {
                background-color: #2c3e50;
                color: white;
                border: 1px solid #34495e;
                border-radius: 5px;
                padding: 5px;
            }
            QPushButton {
                background-color: #2980b9;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
            }
            QPushButton:hover {
                background-color: #3498db;
            }
        """)

        layout = QVBoxLayout(dialog)

        # Editor selection
        editor_layout = QHBoxLayout()
        editor_label = QLabel("Editor Path:")
        self.editor_path = QLineEdit()
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(lambda: self.browse_editor(dialog))
        
        editor_layout.addWidget(editor_label)
        editor_layout.addWidget(self.editor_path)
        editor_layout.addWidget(browse_btn)
        layout.addLayout(editor_layout)

        # Arguments field
        args_layout = QHBoxLayout()
        args_label = QLabel("Command Arguments:")
        self.args_input = QLineEdit()
        self.args_input.setPlaceholderText("e.g. -n for new window")
        
        args_layout.addWidget(args_label)
        args_layout.addWidget(self.args_input)
        layout.addLayout(args_layout)

        # Load current config
        if self.editor_config:
            self.editor_path.setText(self.editor_config.get('path', ''))
            self.args_input.setText(self.editor_config.get('args', ''))

        # Buttons
        button_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        
        save_btn.clicked.connect(lambda: self.save_editor_config(dialog))
        cancel_btn.clicked.connect(dialog.reject)
        
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        dialog.exec()

    def browse_editor(self, dialog):
        file_path, _ = QFileDialog.getOpenFileName(
            dialog,
            "Select Code Editor",
            "",
            "Applications (*.exe);;All Files (*.*)"
        )
        if file_path:
            self.editor_path.setText(file_path)

    def save_editor_config(self, dialog):
        self.editor_config = {
            'path': self.editor_path.text(),
            'args': self.args_input.text()
        }
        self.save_config_to_file()
        self.update_editor_info()
        dialog.accept()

    def update_editor_info(self):
        if self.editor_config and self.editor_config.get('path'):
            editor_name = os.path.basename(self.editor_config['path'])
            args = self.editor_config.get('args', '')
            info_text = f"Current Editor: {editor_name}\nArguments: {args if args else 'None'}"
        else:
            info_text = "No editor configured. Click 'Configure Editor' to set up."
        self.editor_info.setText(info_text)

    def load_editor_config(self):
        """Load the editor configuration from the config file"""
        try:
            if os.path.exists('editor_config.json'):
                with open('editor_config.json', 'r') as f:
                    self.editor_config = json.load(f)
            else:
                self.editor_config = {'path': '', 'args': ''}
                self.save_config_to_file()
        except Exception as e:
            print(f"Error loading editor config: {str(e)}")
            self.editor_config = {'path': '', 'args': ''}

    def save_config_to_file(self):
        with open('editor_config.json', 'w') as f:
            json.dump(self.editor_config, f, indent=4)

    def get_code_completion(self, prompt):
        """Generate code based on the prompt"""
        try:
            # First check if editor is configured
            if not self.editor_config or not self.editor_config.get('path'):
                return "Please configure a code editor first in the Code Generator settings."

            # Update status
            if hasattr(self, 'parent') and hasattr(self.parent, 'signal_emitter'):
                self.parent.signal_emitter.status_changed.emit("Generating code from your request...")

            # Enhance the prompt for better code generation
            enhanced_prompt = f"""
            Please generate clean, well-documented code for the following request:
            {prompt}
            
            Provide only the code without any additional explanation or markdown formatting.
            Include necessary imports and comments for clarity.
            """

            # Get model name from settings
            model_name = 'gemini-1.5-flash'
            if self.parent() and hasattr(self.parent(), 'parent'):
                main_window = self.parent().parent()
                if isinstance(main_window, MainWindow) and hasattr(main_window, 'gemini_model'):
                    model_name = main_window.gemini_model

            # Create model instance with settings
            model = genai.GenerativeModel(model_name)
            
            # Generate code using Gemini
            response = model.generate_content(enhanced_prompt)
            if not response or not response.text:
                return "Sorry, I couldn't generate the code. Please try again."

            # Clean up the response to get just the code
            code = response.text.strip()
            if code.startswith("```") and code.endswith("```"):
                code = code[code.find("\n")+1:code.rfind("```")].strip()

            # Update status
            if hasattr(self, 'parent') and hasattr(self.parent, 'signal_emitter'):
                self.parent.signal_emitter.status_changed.emit("Code generated, preparing to write...")

            return code

        except Exception as e:
            error_msg = f"Error generating code: {str(e)}"
            print(error_msg)
            return error_msg

    def determine_file_extension(self, code, prompt):
        """Determine the appropriate file extension based on code content and prompt"""
        prompt_lower = prompt.lower()
        
        # Check prompt for language hints
        if any(lang in prompt_lower for lang in ['python', 'py']):
            return '.py'
        elif any(lang in prompt_lower for lang in ['javascript', 'js']):
            return '.js'
        elif any(lang in prompt_lower for lang in ['html']):
            return '.html'
        elif any(lang in prompt_lower for lang in ['css']):
            return '.css'
        
        # Check code content for language-specific patterns
        if 'def ' in code or 'import ' in code or 'class ' in code:
            return '.py'
        elif 'function ' in code or 'const ' in code or 'let ' in code:
            return '.js'
        elif '<html' in code or '<!DOCTYPE' in code:
            return '.html'
        elif '{' in code and (':' in code or '@media' in code):
            return '.css'
        
        # Default to Python if no clear indicators
        return '.py'

    def process_command(self, command):
        """Process code generation commands"""
        command_lower = command.lower()
        
        # Keywords that indicate a code generation request
        code_triggers = [
            "generate code for",
            "create code for",
            "write code for",
            "make code for",
            "code a",
            "generate a",
            "create a",
            "write a"
        ]
        
        # Check if this is a code generation command
        if any(trigger in command_lower for trigger in code_triggers):
            # Initial feedback
            if hasattr(self, 'parent') and hasattr(self.parent, 'signal_emitter'):
                self.parent.signal_emitter.new_message.emit("I'll help you generate that code and type it out.", False)
                if hasattr(self.parent, 'speak'):
                    self.parent.speak("I'll help you generate that code and type it out.")
            
            # Generate the code
            result = self.generate_code(command)
            
            # Final feedback
            if hasattr(self, 'parent') and hasattr(self.parent, 'speak'):
                if "error" in result.lower():
                    self.parent.speak("Sorry, there was an error generating the code.")
                else:
                    self.parent.speak("I've finished generating and typing out the code for you.")
            
            return result
            
        return None  # Not a code generation command

class SettingsManager(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = {}
        self.load_settings()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)

        # Header
        header = QLabel("Assistant Settings")
        header.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        layout.addWidget(header)

        # Settings form
        form_container = QFrame()
        form_container.setStyleSheet("""
            QFrame {
                background: rgba(44, 62, 80, 0.4);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 10px;
            }
            QLabel {
                color: white;
            }
            QLineEdit {
                background: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 5px;
                color: white;
                padding: 5px;
                margin: 2px;
            }
            QComboBox {
                background: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(52, 152, 219, 0.3);
                border-radius: 5px;
                color: white;
                padding: 5px;
                margin: 2px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: url(down_arrow.png);
                width: 12px;
                height: 12px;
            }
        """)

        form_layout = QFormLayout(form_container)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(20, 20, 20, 20)

        # Voice Settings Section
        voice_header = QLabel("Voice Settings")
        voice_header.setStyleSheet("color: white; font-weight: bold; margin-top: 10px;")
        form_layout.addRow(voice_header)

        # Voice Gender Selection
        self.voice_gender_selector = QComboBox()
        self.voice_gender_selector.addItem("Male Voice", "male")
        self.voice_gender_selector.addItem("Female Voice", "female")
        
        # Set current voice gender from settings
        current_voice = self.settings.get('voice_gender', 'male')
        self.voice_gender_selector.setCurrentText("Male Voice" if current_voice == "male" else "Female Voice")
        form_layout.addRow("Assistant Voice:", self.voice_gender_selector)

        # Language Selection
        self.language_selector = QComboBox()
        self.language_selector.addItem("English", "en-US")
        self.language_selector.addItem("Arabic", "ar-SA")
        self.language_selector.addItem("English & Arabic", "bilingual")
        
        # Set current language from settings
        current_language = self.settings.get('speech_language', 'en-US')
        if current_language == 'en-US':
            self.language_selector.setCurrentText("English")
        elif current_language == 'ar-SA':
            self.language_selector.setCurrentText("Arabic")
        else:
            self.language_selector.setCurrentText("English & Arabic")
        form_layout.addRow("Speech Language:", self.language_selector)

        # API Settings Section
        api_header = QLabel("API Settings")
        api_header.setStyleSheet("color: white; font-weight: bold; margin-top: 20px;")
        form_layout.addRow(api_header)

        # Gemini API Key
        self.gemini_key_input = QLineEdit()
        self.gemini_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key_input.setText(self.settings.get('gemini_api_key', ''))
        form_layout.addRow("Gemini API Key:", self.gemini_key_input)

        # Gemini Model Selection
        self.model_selector = QComboBox()
        available_models = [
            ('Gemini 2.0 Flash (Recommended)', 'gemini-2.0-flash'),
            ('Gemini 2.0 Flash Lite (Efficient)', 'gemini-2.0-flash-lite'),
            ('Gemini 1.5 Flash (Legacy)', 'gemini-1.5-flash'),
            ('Gemini 1.5 Pro (Legacy)', 'gemini-1.5-pro')
        ]
        for display_name, model_id in available_models:
            self.model_selector.addItem(display_name, model_id)
        
        # Set current model from settings
        current_model = self.settings.get('gemini_model', 'gemini-2.0-flash')
        for i in range(self.model_selector.count()):
            if self.model_selector.itemData(i) == current_model:
                self.model_selector.setCurrentIndex(i)
                break
                
        form_layout.addRow("Gemini Model:", self.model_selector)

        # Porcupine Key
        self.porcupine_key_input = QLineEdit()
        self.porcupine_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.porcupine_key_input.setText(self.settings.get('porcupine_key', ''))
        form_layout.addRow("Porcupine Key:", self.porcupine_key_input)

        layout.addWidget(form_container)

        # Save Button
        save_button = QPushButton("Save Settings")
        save_button.setStyleSheet("""
            QPushButton {
                background: rgba(52, 152, 219, 0.7);
                border: none;
                border-radius: 5px;
                color: white;
                padding: 8px;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: rgba(52, 152, 219, 0.9);
            }
        """)
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button)

        # Restart note
        restart_note = QLabel("App needs to restart after every change")
        restart_note.setStyleSheet("""
            QLabel {
                color: rgba(231, 76, 60, 0.9);
                font-style: italic;
                padding: 5px;
                font-size: 12px;
            }
        """)
        restart_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(restart_note)

        # Add stretch to push everything to the top
        layout.addStretch()

    def load_settings(self):
        try:
            print("Debug: Starting to load settings")
            if os.path.exists('settings.json'):
                with open('settings.json', 'r') as f:
                    self.settings = json.load(f)
                print("Debug: Settings loaded from file")
                print(f"Debug: API key present: {bool(self.settings.get('gemini_api_key', '').strip())}")
            else:
                print("Debug: No settings file found, using defaults")
                self.settings = {
                    'gemini_api_key': '',
                    'gemini_model': 'gemini-2.0-flash',
                    'porcupine_key': '',
                    'voice_gender': 'male',  # Default to male voice
                    'speech_language': 'en-US',  # Default to English
                    'vad_aggressiveness': 3  # Default VAD aggressiveness
                }
        except Exception as e:
            print(f"Debug: Error loading settings: {str(e)}")
            # Initialize with default settings if loading fails
            self.settings = {
                'gemini_api_key': '',
                'gemini_model': 'gemini-2.0-flash',
                'porcupine_key': '',
                'voice_gender': 'male',
                'speech_language': 'en-US',
                'vad_aggressiveness': 3
            }

    def save_settings(self):
        """Save settings to file and update main window"""
        try:
            # Get new API keys and compare with old ones
            new_api_key = self.gemini_key_input.text().strip()
            old_api_key = self.settings.get('gemini_api_key', '')
            new_porcupine_key = self.porcupine_key_input.text().strip()
            old_porcupine_key = self.settings.get('porcupine_key', '')
            
            # Update settings from UI
            self.settings['gemini_api_key'] = new_api_key
            self.settings['gemini_model'] = self.model_selector.currentData()
            self.settings['porcupine_key'] = new_porcupine_key
            self.settings['voice_gender'] = 'male' if self.voice_gender_selector.currentText() == "Male Voice" else 'female'
            
            # Get language setting
            language_text = self.language_selector.currentText()
            if language_text == "English":
                self.settings['speech_language'] = 'en-US'
            elif language_text == "Arabic":
                self.settings['speech_language'] = 'ar-SA'
            else:  # English & Arabic
                self.settings['speech_language'] = 'bilingual'
                
            # Handle API key changes
            restart_required = False
            
            if new_api_key != old_api_key:
                if initialize_gemini(new_api_key):
                    if not old_api_key:
                        # Find the MainWindow
                        main_window = self
                        while main_window and not isinstance(main_window, MainWindow):
                            main_window = main_window.parent()
                            
                        if main_window:
                            # Stop any existing threads
                            if hasattr(main_window, 'wake_word_thread') and main_window.wake_word_thread:
                                main_window.stop_wake_word.set()
                                main_window.wake_word_thread.join(timeout=1)
                            if hasattr(main_window, 'listening_thread') and main_window.listening_thread:
                                main_window.stop_wake_word.set()
                                main_window.listening_thread.join(timeout=1)
                            
                            # Reset stop flag
                            main_window.stop_wake_word.clear()
                            
                            # Initialize speech components and start threads
                            main_window.initialize_speech_components()
                            main_window.start_threads()
                            QMessageBox.information(self, "Success", "API key configured successfully. Voice features have been enabled.")
                        else:
                            QMessageBox.information(self, "Success", "API key configured successfully. Please restart to enable voice features.")
                            restart_required = True
                    else:
                        QMessageBox.information(self, "Success", "API key updated successfully.")
                else:
                    if new_api_key:
                        QMessageBox.warning(self, "Warning", "Invalid API key. Voice features will remain disabled.")
                    else:
                        QMessageBox.warning(self, "Warning", "No API key provided. Voice features will be disabled.")
                        
            # Handle Porcupine key changes
            if new_porcupine_key != old_porcupine_key:
                if new_porcupine_key:
                    restart_required = True
                    QMessageBox.information(self, "Success", "Wake word detection will be enabled after restart.")
                else:
                    QMessageBox.warning(self, "Notice", "Wake word detection will be disabled.")
            
            # Save to file
            with open('settings.json', 'w') as f:
                json.dump(self.settings, f, indent=4)
            
            # Find the MainWindow by traversing up the widget hierarchy
            parent = self.parent()
            while parent and not isinstance(parent, QMainWindow):
                parent = parent.parent()
            
            # Update main window if found
            if parent:
                # Reinitialize TTS engine with new voice settings
                if parent.initialize_tts_engine():
                    parent.speak("Settings saved successfully")
                
                # Update Gemini model if API key is present
                if self.settings.get('gemini_api_key', '').strip():
                    if hasattr(parent, 'sidebar') and hasattr(parent.sidebar, 'camera_page'):
                        parent.sidebar.camera_page.initialize_gemini_model()

            QMessageBox.information(self, "Success", "Settings saved successfully!")
        except Exception as e:
            print(f"Debug: Error saving settings: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to save settings: {str(e)}")

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

def get_valid_model_name(model_name):
    """Validate and return correct Gemini model name"""
    valid_models = {
        'gemini-1.5-flash': 'gemini-1.5-flash',
        'gemini-1.5-pro': 'gemini-1.5-pro',
        'gemini-2.0-flash': 'gemini-2.0-flash',
        'gemini-2.0-flash-lite': 'gemini-2.0-flash-lite'
    }
    return valid_models.get(model_name.strip().lower(), 'gemini-2.0-flash')

# Initialize with empty key first (will be configured from settings)
initialize_gemini("")

if __name__ == '__main__':
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI
    except Exception:
        pass  # Qt will handle DPI awareness by default

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec()) 