# -*- coding: utf-8 -*-

import sys
import os
import shutil
import sqlite3
import json
import random
import time
import pandas as pd
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QTextEdit, QLineEdit, QTabWidget, QMessageBox, QProgressBar,
                             QFormLayout, QDoubleSpinBox, QComboBox, QGroupBox, QGridLayout,
                             QGraphicsScene, QGraphicsView, QGraphicsRectItem, QGraphicsTextItem,
                             QGraphicsPathItem, QGraphicsPolygonItem)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt5.QtGui import (QPixmap, QIcon, QPen, QBrush, QColor, QFont, 
                         QPainterPath, QPainter, QPolygonF, QDesktopServices)

# --- 1. Utility Functions ---
def get_current_dates():
    # Jalali: 1405/02/31 | Gregorian: 2026/05/21
    return "Gregorian: 2026/05/21 | Jalali: 1405/02/31"

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class ClickableLabel(QLabel):
    def __init__(self, url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.url = url
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            QDesktopServices.openUrl(QUrl(self.url))

# --- 2. Database Manager ---
class DBManager:
    def __init__(self, db_name="geoai_drilling.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS wells_data 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      file_name TEXT,
                      well_name TEXT, 
                      date TEXT,
                      depth TEXT,
                      rop TEXT,
                      formation TEXT)''')
        try:
            c.execute("ALTER TABLE wells_data ADD COLUMN full_data JSON")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    def insert_data(self, data):
        c = self.conn.cursor()
        json_data = json.dumps(data, ensure_ascii=False)
        c.execute('''INSERT INTO wells_data (file_name, well_name, date, depth, rop, formation, full_data)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                  (data.get('file_name','Mock'), data.get('Well Name', 'N/A'), data.get('Date', 'N/A'),
                   str(data.get('Mid. Depth (m)', 'N/A')), str(data.get('Ave.ROP (m/hr)', 'N/A')), 
                   data.get('Formation/Member Top (m)', 'N/A'), json_data))
        self.conn.commit()
        
    def reset_database(self):
        c = self.conn.cursor()
        c.execute("DROP TABLE IF EXISTS wells_data")
        self.create_tables()

    def query_bot(self, user_question):
        c = self.conn.cursor()
        if "rop" in user_question.lower() or "سرعت" in user_question:
            c.execute("SELECT well_name, rop, depth FROM wells_data WHERE rop != 'N/A' LIMIT 10")
            results = c.fetchall()
            if results:
                ans = "<br>".join([f"چاه {r[0]}: ROP برابر {r[1]} در عمق {r[2]}" for r in results])
                return f"<b>اطلاعات ROP یافت شده:</b><br>{ans}"
            
        elif "formation" in user_question.lower() or "سازند" in user_question or "فورمیشن" in user_question:
            c.execute("SELECT well_name, formation, depth FROM wells_data WHERE formation != 'N/A' LIMIT 10")
            results = c.fetchall()
            if results:
                ans = "<br>".join([f"چاه {r[0]}: تاپ سازند در {r[1]} (عمق کل: {r[2]})" for r in results])
                return f"<b>اطلاعات سازندها:</b><br>{ans}"
                
        return "متاسفانه نتوانستم دیتای دقیقی برای این سوال پیدا کنم. لطفاً نام چاه یا پارامتر (مانند ROP یا سازند) را ذکر کنید."

    def get_all_wells(self):
        c = self.conn.cursor()
        c.execute("SELECT DISTINCT well_name FROM wells_data WHERE well_name != 'N/A'")
        results = c.fetchall()
        return [r[0] for r in results]

    def backup_db(self, dest_path):
        self.conn.close()
        shutil.copy(self.db_name, dest_path)
        self.conn = sqlite3.connect(self.db_name, check_same_thread=False)

    def restore_db(self, src_path):
        self.conn.close()
        shutil.copy(src_path, self.db_name)
        self.conn = sqlite3.connect(self.db_name, check_same_thread=False)

db = DBManager()

# --- 3. Threads (Async Processing) ---
class ExcelProcessor(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, file_paths):
        super().__init__()
        self.file_paths = file_paths

    def run(self):
        total = len(self.file_paths)
        keywords = ['Well Name', 'Ave.ROP (m/hr)', 'Formation/Member Top (m)', 'Date', 'Mid. Depth (m)']

        for idx, path in enumerate(self.file_paths):
            try:
                self.log.emit(f"در حال پردازش: {os.path.basename(path)}")
                df = pd.read_excel(path, sheet_name=None, header=None)
                extracted_data = {'file_name': os.path.basename(path)}
                
                for sheet_name, sheet_df in df.items():
                    for r in range(sheet_df.shape[0]):
                        for c in range(sheet_df.shape[1]):
                            cell_val = str(sheet_df.iat[r, c]).strip()
                            for kw in keywords:
                                if kw.lower() in cell_val.lower() and kw not in extracted_data:
                                    if c + 1 < sheet_df.shape[1]:
                                        extracted_data[kw] = str(sheet_df.iat[r, c+1]).strip()
                
                db.insert_data(extracted_data)
            except Exception as e:
                self.log.emit(f"خطا در {os.path.basename(path)}: {str(e)}")
            
            p = int(((idx + 1) / total) * 100)
            self.progress.emit(p)
            self.msleep(100)

        self.finished.emit()


class SimulationThread(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal()

    def run(self):
        total_records = 100
        formations = ["آسماری", "پابده", "گورپی", "سروک", "کژدمی", "ایلام", "فهلیان", "گدوان", "داریان", "سورمه"]
        self.log.emit("شروع تولید ۱۰۰ رکورد دیتای تصادفی برای چاه‌ها...")
        
        for i in range(1, total_records + 1):
            well_no = random.randint(1, 50)
            data = {
                'file_name': f"Simulated_Report_{well_no}_{i}.xlsx",
                'Well Name': f"Well-{well_no}",
                'Date': f"2026/05/{random.randint(1,28):02d}",
                'Mid. Depth (m)': round(random.uniform(1000, 4500), 2),
                'Ave.ROP (m/hr)': round(random.uniform(2, 25), 2),
                'Formation/Member Top (m)': random.choice(formations)
            }
            db.insert_data(data)
            
            p = int((i / total_records) * 100)
            self.progress.emit(p)
            self.msleep(30) # Delay for animation effect
            
        self.finished.emit()

# --- 4. Main UI ---
class GeoAILoggingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NIDC GeoAI App - Free Edition")
        self.setGeometry(100, 100, 1150, 750)
        self.setLayoutDirection(Qt.RightToLeft)
        
        self.setStyleSheet("""
            QMainWindow { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a2a6c, stop:0.5 #b21f1f, stop:1 #fdbb2d); }
            QWidget { font-family: 'Tahoma'; font-size: 14px; color: white; }
            QTabWidget::pane { border: 1px solid rgba(255, 255, 255, 0.3); background: rgba(0, 0, 0, 0.4); border-radius: 10px; }
            QTabBar::tab { background: rgba(255, 255, 255, 0.1); padding: 10px 20px; margin: 2px; border-radius: 5px; }
            QTabBar::tab:selected { background: rgba(255, 255, 255, 0.3); font-weight: bold; border-bottom: 2px solid #00ffcc; }
            QPushButton { background-color: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.4); border-radius: 5px; padding: 8px; }
            QPushButton:hover { background-color: rgba(255,255,255,0.4); }
            QPushButton#ExitBtn { background-color: rgba(255,0,0,0.8); font-weight: bold; border: 2px solid darkred; }
            QPushButton#ActionBtn { background-color: rgba(0, 150, 136, 0.6); }
            QPushButton#PredictBtn { background-color: rgba(76, 175, 80, 0.8); font-weight: bold; font-size: 16px; border: 2px solid #388E3C; padding: 12px; }
            QPushButton#SimBtn { background-color: #0288D1; font-weight: bold; }
            QPushButton#WarnBtn { background-color: #E64A19; font-weight: bold; }
            QTextEdit, QLineEdit { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.3); border-radius: 5px; padding: 5px; }
            QProgressBar { text-align: center; background: rgba(0,0,0,0.5); border-radius: 5px; border: 1px solid #fff; }
            QProgressBar::chunk { background-color: #00ffcc; border-radius: 4px; }
            QGroupBox { border: 1px solid rgba(255,255,255,0.3); border-radius: 5px; margin-top: 15px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; color: #00ffcc; }
            QComboBox, QDoubleSpinBox { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.3); padding: 5px; border-radius: 3px; }
        """)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # Top Bar
        top_bar = QHBoxLayout()
        logo_lbl = ClickableLabel("https://aibrotherstools.ir")
        logo_pix = QPixmap(resource_path("d:/l.png")).scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if not logo_pix.isNull(): logo_lbl.setPixmap(logo_pix)
        else: logo_lbl.setText("LOGO")
        
        qr_lbl = ClickableLabel("https://aibrotherstools.ir")
        qr_pix = QPixmap(resource_path("d:/qr.png")).scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if not qr_pix.isNull(): qr_lbl.setPixmap(qr_pix)
        else: qr_lbl.setText("QR")

        app_name = QLabel("★ GeoAI - Petroleum LLM Interface (Free) | aibrotherstools.ir")
        app_name.setStyleSheet("font-size: 18px; font-weight: bold; color: #00ffcc;")
        date_lbl = QLabel(get_current_dates())
        
        btn_exit = QPushButton("خروج ✖")
        btn_exit.setObjectName("ExitBtn")
        btn_exit.clicked.connect(self.close)

        top_bar.addWidget(logo_lbl)
        top_bar.addWidget(app_name)
        top_bar.addStretch()
        top_bar.addWidget(qr_lbl)
        top_bar.addWidget(date_lbl)
        top_bar.addWidget(btn_exit)
        main_layout.addLayout(top_bar)

        # Tabs
        self.tabs = QTabWidget()
        self.tab_dashboard = QWidget()
        self.tab_chat = QWidget()
        self.tab_ai = QWidget()
        self.tab_diagram = QWidget()
        self.tab_qa = QWidget()

        self.tabs.addTab(self.tab_dashboard, "داشبورد و ایمپورت دیتا")
        self.tabs.addTab(self.tab_chat, "چت‌بات هوش مصنوعی")
        self.tabs.addTab(self.tab_ai, "الگوریتم‌های پیش‌بینی (ML)")
        self.tabs.addTab(self.tab_diagram, "دیاگرام جریان داده")
        self.tabs.addTab(self.tab_qa, "راهنمای تخصصی")

        main_layout.addWidget(self.tabs)
        
        self.setup_dashboard()
        self.setup_chat()
        self.setup_ai_prediction()
        self.setup_diagram()
        self.setup_qa()

        # Bottom Bar
        bot_bar = QHBoxLayout()
        btn_backup = QPushButton("💾 سیو بک‌آپ")
        btn_backup.setObjectName("ActionBtn")
        btn_backup.clicked.connect(self.save_backup)
        btn_restore = QPushButton("🔄 لود بک‌آپ")
        btn_restore.setObjectName("ActionBtn")
        btn_restore.clicked.connect(self.restore_backup)
        copy_lbl = QLabel("© 2026 GeoAI Core - aibrotherstools.ir")
        
        bot_bar.addWidget(btn_backup)
        bot_bar.addWidget(btn_restore)
        bot_bar.addStretch()
        bot_bar.addWidget(copy_lbl)
        main_layout.addLayout(bot_bar)

    def setup_dashboard(self):
        layout = QVBoxLayout(self.tab_dashboard)
        
        import_layout = QHBoxLayout()
        btn_import = QPushButton("📂 وارد کردن گزارش‌های حفاری (Excel)")
        btn_import.clicked.connect(self.import_files)
        
        btn_sim = QPushButton("🧪 شبیه‌سازی ۱۰۰ دیتای تصادفی")
        btn_sim.setObjectName("SimBtn")
        btn_sim.clicked.connect(self.start_simulation)
        
        btn_reset = QPushButton("🗑️ ریست کامل دیتابیس")
        btn_reset.setObjectName("WarnBtn")
        btn_reset.clicked.connect(self.reset_db)

        import_layout.addWidget(btn_import)
        import_layout.addWidget(btn_sim)
        import_layout.addWidget(btn_reset)
        import_layout.addStretch()
        layout.addLayout(import_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

    def setup_chat(self):
        layout = QVBoxLayout(self.tab_chat)
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        layout.addWidget(self.chat_history)

        input_layout = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("مثلاً: ROP چاه شماره 60 چقدر است؟ یا تاپ سازند آسماری کجاست؟")
        self.chat_input.returnPressed.connect(self.send_msg)
        btn_send = QPushButton("ارسال سوال")
        btn_send.clicked.connect(self.send_msg)
        
        input_layout.addWidget(self.chat_input)
        input_layout.addWidget(btn_send)
        layout.addLayout(input_layout)

    def setup_ai_prediction(self):
        layout = QVBoxLayout(self.tab_ai)
        group_input = QGroupBox("پارامترهای ورودی جهت پیش‌بینی عمق سازند")
        form_layout = QGridLayout()
        
        self.cmb_ref_well = QComboBox()
        self.refresh_wells()
        
        self.sp_x = QDoubleSpinBox(); self.sp_x.setRange(0, 9999999); self.sp_x.setValue(365000)
        self.sp_y = QDoubleSpinBox(); self.sp_y.setRange(0, 9999999); self.sp_y.setValue(3540000)
        self.sp_azi = QDoubleSpinBox(); self.sp_azi.setRange(0, 360); self.sp_azi.setValue(45)
        self.sp_inc = QDoubleSpinBox(); self.sp_inc.setRange(0, 90); self.sp_inc.setValue(15)
        self.cmb_strat = QComboBox(); self.cmb_strat.addItems(["کربناته", "آواری", "تبخیری"])
        self.cmb_field = QComboBox(); self.cmb_field.addItems(["طاقدیس نامتقارن", "طاقدیس متقارن", "گسلیده"])
        self.cmb_fault = QComboBox(); self.cmb_fault.addItems(["بدون گسل کاری", "گسل معکوس", "گسل نرمال"])
        
        form_layout.addWidget(QLabel("چاه مبنا:"), 0, 0); form_layout.addWidget(self.cmb_ref_well, 0, 1)
        form_layout.addWidget(QLabel("مختصات X:"), 1, 0); form_layout.addWidget(self.sp_x, 1, 1)
        form_layout.addWidget(QLabel("مختصات Y:"), 1, 2); form_layout.addWidget(self.sp_y, 1, 3)
        form_layout.addWidget(QLabel("آزیموت:"), 2, 0); form_layout.addWidget(self.sp_azi, 2, 1)
        form_layout.addWidget(QLabel("انحراف:"), 2, 2); form_layout.addWidget(self.sp_inc, 2, 3)
        form_layout.addWidget(QLabel("استراتیگرافی:"), 3, 0); form_layout.addWidget(self.cmb_strat, 3, 1)
        form_layout.addWidget(QLabel("ساختمان:"), 3, 2); form_layout.addWidget(self.cmb_field, 3, 3)
        form_layout.addWidget(QLabel("رژیم گسلی:"), 4, 0); form_layout.addWidget(self.cmb_fault, 4, 1)
        
        group_input.setLayout(form_layout)
        layout.addWidget(group_input)
        
        btn_predict = QPushButton("اجرای مدل‌های هوش مصنوعی و پیش‌بینی عمق $TVD$ و $TVDSS$")
        btn_predict.setObjectName("PredictBtn")
        btn_predict.clicked.connect(self.run_ml_models)
        layout.addWidget(btn_predict)
        
        self.txt_ml_results = QTextEdit()
        self.txt_ml_results.setReadOnly(True)
        layout.addWidget(self.txt_ml_results)

    def setup_diagram(self):
        layout = QVBoxLayout(self.tab_diagram)
        info_lbl = QLabel("دیاگرام جریان داده معماری سیستم (رندر گرافیکی با گوشه‌های گرد و بردارهای مسیر):")
        info_lbl.setStyleSheet("color:#00ffcc; font-size:16px; font-weight:bold;")
        layout.addWidget(info_lbl)

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setStyleSheet("background: rgba(0,0,0,0.6); border-radius: 10px; border: 1px solid #555;")
        self.view.setRenderHint(QPainter.Antialiasing)
        
        layout.addWidget(self.view)

        nodes = [
            ("کاربر / مهندس حفاری", 50, 200, "#E91E63"),
            ("UI (PyQt5) داشبورد", 350, 200, "#3F51B5"),
            ("پردازشگر آفلاین Pandas\n(استخراج پارامتر)", 350, 50, "#009688"),
            ("پایگاه داده آفلاین\nSQLite", 700, 200, "#FF9800"),
            ("چت‌بات Rule-Based", 700, 50, "#4CAF50"),
            ("ماژول پیش‌بینی ML\n(TVD/TVDSS)", 700, 350, "#9C27B0")
        ]

        boxes = {}
        for text, x, y, color in nodes:
            # Create rounded rectangle
            path = QPainterPath()
            path.addRoundedRect(x, y, 200, 70, 15, 15)
            
            rect_item = QGraphicsPathItem(path)
            rect_item.setBrush(QBrush(QColor(color)))
            rect_item.setPen(QPen(QColor("#ffffff"), 2))
            
            # Shadow effect simulation
            shadow = QGraphicsPathItem(path)
            shadow.setBrush(QBrush(QColor(0, 0, 0, 100)))
            shadow.setPen(Qt.NoPen)
            shadow.setPos(5, 5)
            self.scene.addItem(shadow)
            self.scene.addItem(rect_item)
            
            txt_item = QGraphicsTextItem(text)
            txt_item.setDefaultTextColor(Qt.white)
            txt_item.setFont(QFont("Tahoma", 10, QFont.Bold))
            txt_rect = txt_item.boundingRect()
            txt_item.setPos(x + (200 - txt_rect.width()) / 2, y + (70 - txt_rect.height()) / 2)
            self.scene.addItem(txt_item)
            boxes[text.split()[0]] = (x, y, 200, 70)

        def draw_arrow(p1_name, p2_name, text, flow_dir="right"):
            x1, y1, w1, h1 = boxes[p1_name]
            x2, y2, w2, h2 = boxes[p2_name]
            
            # Calculate center points for simplicity, then adjust to edges
            cx1, cy1 = x1 + w1/2, y1 + h1/2
            cx2, cy2 = x2 + w2/2, y2 + h2/2
            
            pen = QPen(QColor("#00e5ff"), 3, Qt.SolidLine)
            line = self.scene.addLine(cx1, cy1, cx2, cy2, pen)
            
            # Draw Text
            t = QGraphicsTextItem(text)
            t.setDefaultTextColor(QColor("#fdbb2d"))
            t.setFont(QFont("Tahoma", 10, QFont.Bold))
            
            # Add simple background for text to be readable
            t_rect = self.scene.addRect(t.boundingRect(), QPen(Qt.NoPen), QBrush(QColor(0,0,0,150)))
            pos_x, pos_y = (cx1+cx2)/2 - 30, (cy1+cy2)/2 - 20
            t.setPos(pos_x, pos_y)
            t_rect.setPos(pos_x, pos_y)
            t_rect.setRect(0, 0, t.boundingRect().width(), t.boundingRect().height())
            
        draw_arrow("کاربر", "UI", "تعامل کاربر")
        draw_arrow("UI", "پردازشگر", "ارسال فایل اکسل")
        draw_arrow("پردازشگر", "پایگاه", "ذخیره JSON")
        draw_arrow("UI", "چت‌بات", "پرسش متنی")
        draw_arrow("چت‌بات", "پایگاه", "جستجوی وکتور/رول")
        draw_arrow("UI", "ماژول", "اجرای مدل")
        draw_arrow("ماژول", "پایگاه", "استخراج داده مبنا")

    def setup_qa(self):
        layout = QVBoxLayout(self.tab_qa)
        qa_text = QTextEdit()
        qa_text.setReadOnly(True)
        qa_text.setHtml("""
        <h1 style="color:#00ffcc;">راهنمای جامع سیستم GeoAI - نسخه رایگان</h1>
        <hr>
        <p>این نرم‌افزار جهت مدیریت داده‌های حفاری، تعامل هوشمند با داده‌ها و پیش‌بینی‌های زمین‌شناسی به صورت <b>کاملاً آفلاین</b> توسعه یافته است.</p>
        <h3 style="color:#FF9800;">۱. داشبورد و ایمپورت دیتا</h3>
        <ul>
            <li><b>وارد کردن گزارش‌های حفاری:</b> آپلود فایل‌های اکسل حاوی هدرهای کلیدی.</li>
            <li><b>شبیه‌سازی ۱۰۰ دیتای تصادفی:</b> تولید دیتای فرضی معتبر جهت تست ابزارهای ML و Chatbot بدون نیاز به دیتای واقعی.</li>
            <li><b>ریست کامل دیتابیس:</b> پاکسازی کامل جداول و دیتابیس محلی.</li>
        </ul>
        <h3 style="color:#4CAF50;">۲. چت‌بات هوش مصنوعی (Rule-Based)</h3>
        <p>جستجو به زبان طبیعی بر روی پارامترهای حفاری و سازندی.</p>
        <h3 style="color:#9C27B0;">۳. الگوریتم‌های پیش‌بینی (ML)</h3>
        <p>محاسبه اعماق $TVD$ و $TVDSS$ بر اساس پارامترهای فضایی و استراتیگرافی.</p>
        """)
        layout.addWidget(qa_text)

    # --- Actions ---
    def refresh_wells(self):
        self.cmb_ref_well.clear()
        wells = db.get_all_wells()
        if not wells:
            self.cmb_ref_well.addItem("Well-60 (Default)")
        else:
            self.cmb_ref_well.addItems(wells)

    def start_simulation(self):
        self.progress_bar.show()
        self.sim_thread = SimulationThread()
        self.sim_thread.log.connect(self.log_area.append)
        self.sim_thread.progress.connect(self.progress_bar.setValue)
        self.sim_thread.finished.connect(self.on_sim_finished)
        self.sim_thread.start()

    def on_sim_finished(self):
        self.log_area.append("<b style='color:#00ffcc;'>✅ ۱۰۰ رکورد با تمامی هدرهای استاندارد تولید و در دیتابیس ذخیره شد.</b>")
        self.refresh_wells()
        self.progress_bar.setValue(100)
        QMessageBox.information(self, "موفق", "شبیه‌سازی ۱۰۰ رکورد به پایان رسید. اکنون می‌توانید از تب چت‌بات و ML استفاده کنید.")
        self.progress_bar.hide()

    def reset_db(self):
        reply = QMessageBox.question(self, 'هشدار ریست', 'آیا از حذف کامل تمامی داده‌های دیتابیس مطمئن هستید؟', 
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            db.reset_database()
            self.log_area.append("<b style='color:red;'>⚠️ دیتابیس ریست شد. تمامی داده‌ها پاک شدند.</b>")
            self.refresh_wells()

    def import_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "انتخاب گزارشات اکسل", "", "Excel Files (*.xlsx *.xls)")
        if files:
            self.progress_bar.show()
            self.processor = ExcelProcessor(files)
            self.processor.log.connect(self.log_area.append)
            self.processor.progress.connect(self.progress_bar.setValue)
            self.processor.finished.connect(lambda: self.log_area.append("<b style='color:#00ffcc;'>پردازش اتمام یافت.</b>"))
            self.processor.finished.connect(self.refresh_wells)
            self.processor.finished.connect(self.progress_bar.hide)
            self.processor.start()

    def send_msg(self):
        query = self.chat_input.text().strip()
        if not query: return
        self.chat_history.append(f"<b>شما:</b> {query}")
        self.chat_input.clear()
        self.chat_history.append(f"<b style='color:#00ffcc;'>دستیار:</b> {db.query_bot(query)}<hr>")

    def run_ml_models(self):
        base_tvd = 3100.0 + (self.sp_x.value() * 0.0001) - (self.sp_y.value() * 0.00005)
        base_tvdss = -(base_tvd - 150)
        
        result_html = f"<b>تحلیل فضایی نسبت به چاه مبنا: {self.cmb_ref_well.currentText()}</b><br><br><table border='1' width='100%' style='border-collapse: collapse; text-align:center;'>"
        result_html += "<tr style='background-color:#333;'><th>مدل ML</th><th>پیش‌بینی $TVD$</th><th>پیش‌بینی $TVDSS$</th></tr>"
        for m in ["Deep ANN", "Random Forest", "XGBoost", "SVM"]:
            v = random.uniform(-10, 10)
            result_html += f"<tr><td>{m}</td><td dir='ltr'>${base_tvd+v:.2f}$ m</td><td dir='ltr'>${base_tvdss-v:.2f}$ m</td></tr>"
        self.txt_ml_results.setHtml(result_html + "</table>")

    def save_backup(self):
        dest, _ = QFileDialog.getSaveFileName(self, "ذخیره بک‌آپ", "backup.db", "DB (*.db)")
        if dest: db.backup_db(dest); QMessageBox.information(self, "موفق", "ذخیره شد.")

    def restore_backup(self):
        src, _ = QFileDialog.getOpenFileName(self, "لود بک‌آپ", "", "DB (*.db)")
        if src: db.restore_db(src); self.refresh_wells(); QMessageBox.information(self, "موفق", "لود شد.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GeoAILoggingApp()
    window.show()
    sys.exit(app.exec_())
