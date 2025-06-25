import datetime
import os
import pickle
import threading
import time
import urllib.request
from queue import Queue

import cv2
import mysql.connector
import pyttsx3
from PIL._tkinter_finder import tk
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone

from attendance import AttendanceSystem
from pin_utils import generate_pin
from report_gui import AttendanceReportGUI

# ==================== INITIALIZATION ====================

# Speech engine setup
speech_queue = Queue()
speech_engine = pyttsx3.init()
speech_active = True
voices = speech_engine.getProperty('voices')
speech_engine.setProperty('voice', voices[1].id)  # Female voice


def speech_worker():
    """Background thread for speech synthesis"""
    while True:
        text = speech_queue.get()
        if text is None:  # Termination signal
            break
        if speech_active:
            try:
                speech_engine.say(text)
                speech_engine.runAndWait()
            except Exception as e:
                print(f"Speech error: {e}")
        speech_queue.task_done()


speech_thread = threading.Thread(target=speech_worker, daemon=True)
speech_thread.start()


def speak(text):
    """Add text to speech queue"""
    if speech_active:
        speech_queue.put(text)


# Database connection with reconnect logic
def get_db_connection():
    """Get database connection with retry and timeout settings"""
    config = {
        'host': 'localhost',
        'user': 'root',
        'password': '',
        'database': 'face_recognition',
        'autocommit': True,
        'connect_timeout': 30,  # Increased timeout
        'pool_size': 5,  # Connection pooling
        'pool_name': 'attendance_pool'
    }

    try:
        db = mysql.connector.connect(**config)
        print("✅ Database connected")
        return db
    except mysql.connector.Error as err:
        print(f"❌ Database error: {err}")
        return None


db = get_db_connection()
if db is None:
    exit()

cursor = db.cursor(buffered=True)

# Create tables if not exists
try:
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        student_id VARCHAR(20) PRIMARY KEY,
        name VARCHAR(100),
        major VARCHAR(100),
        starting_year INT,
        section VARCHAR(10),
        total_attendance INT,
        year INT,
        last_attendance DATETIME,
        photo LONGBLOB,
        pin VARCHAR(4) DEFAULT '0000',
        emergency_leave_count INT DEFAULT 0,
        pin_attempts INT DEFAULT 0
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance_log (
        log_id INT AUTO_INCREMENT PRIMARY KEY,
        student_id VARCHAR(20),
        timestamp DATETIME,
        is_emergency_leave ENUM('yes', 'no') DEFAULT 'no',
        daily_status VARCHAR(20) DEFAULT 'pending',
        FOREIGN KEY (student_id) REFERENCES students(student_id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance_report (
        report_id INT AUTO_INCREMENT PRIMARY KEY,
        student_id VARCHAR(20),
        month_year VARCHAR(7),
        total_days INT DEFAULT 0,
        present_days INT DEFAULT 0,
        absent_days INT DEFAULT 0,
        emergency_leaves INT DEFAULT 0,
        attendance_percentage DECIMAL(5,2) DEFAULT 0.00,
        FOREIGN KEY (student_id) REFERENCES students(student_id),
        UNIQUE KEY student_month (student_id, month_year)
    )""")

    # Ensure all students have valid PINs
    cursor.execute("SELECT student_id FROM students WHERE pin = '0000' OR pin IS NULL")
    students_without_pins = cursor.fetchall()
    for student in students_without_pins:
        new_pin = generate_pin()
        cursor.execute("UPDATE students SET pin = %s WHERE student_id = %s",
                       (new_pin, student[0]))

    db.commit()
except mysql.connector.Error as err:
    print(f"❌ Database setup error: {err}")
    exit()

# Load face encodings
print("🔍 Loading face encodings...")
try:
    with open("EncodeFile.p", 'rb') as f:
        encodeListKnown, studentIds = pickle.load(f)
    print(f"✅ Loaded {len(studentIds)} student profiles")
    print(f"📝 Student IDs: {studentIds}")
except Exception as e:
    print(f"❌ Error loading encodings: {e}")
    exit()

# Initialize attendance system
attendance_system = AttendanceSystem(
    db_connection=db,
    cursor=cursor,
    encode_list_known=encodeListKnown,
    student_ids=studentIds,
    speech_queue=speech_queue
)

# Set scheduler to Nepal time
nepal_time = timezone('Asia/Kathmandu')
print(f"🕒 Current Nepal Time: {datetime.datetime.now(nepal_time)}")

scheduler = BackgroundScheduler(timezone=nepal_time)
scheduler.add_job(
    attendance_system.mark_absent_students,
    'cron',
    hour=17,
    minute=0
)
scheduler.add_job(
    attendance_system.generate_monthly_report,
    'cron',
    day='last',
    hour=23,
    minute=59
)
scheduler.start()

# Video capture setup
cap = cv2.VideoCapture(0)
cap.set(3, 640)  # Width
cap.set(4, 480)  # Height

# Motion detector
fgbg = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=16, detectShadows=False)
motion_detected = False
last_motion_time = 0
motion_timeout = 5

# Face detector
try:
    prototxt_path = "deploy.prototxt"
    model_path = "res10_300x300_ssd_iter_140000.caffemodel"

    if not os.path.exists(prototxt_path):
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt",
            prototxt_path
        )

    if not os.path.exists(model_path):
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel",
            model_path
        )

    face_net = cv2.dnn.readNetFromCaffe(prototxt_path, model_path)
    USE_DNN = True
except Exception as e:
    print(f"⚠️ Using Haar Cascade instead: {e}")
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    USE_DNN = False

# Interface images
imgBackground = cv2.imread('Resources/background.png')
imgModeList = [
    cv2.resize(cv2.imread('Resources/Modes/1.png'), (273, 430)),  # Ready
    cv2.resize(cv2.imread('Resources/Modes/2.png'), (273, 430)),  # Processing
    cv2.resize(cv2.imread('Resources/Modes/3.png'), (273, 430)),  # Success
    cv2.resize(cv2.imread('Resources/Modes/4.png'), (273, 430))  # Already marked
]


def show_report_gui():
    """Thread-safe GUI launcher"""
    if not hasattr(show_report_gui, '_window') or not tk._default_root:
        gui = AttendanceReportGUI(db, cursor, attendance_system)
        show_report_gui._window = gui
        try:
            gui.root.mainloop()
        except Exception as e:
            print(f"GUI error: {e}")
        finally:
            if hasattr(show_report_gui, '_window'):
                del show_report_gui._window


# ==================== MAIN PROCESSING LOOP ====================
last_frame_time = time.time()
frame_interval = 0.033  # Target ~30 FPS

while True:
    try:
        current_time = time.time()
        if current_time - last_frame_time < frame_interval:
            time.sleep(0.001)
            continue

        last_frame_time = current_time

        # Verify database connection
        if not db.is_connected():
            db = get_db_connection()
            if not db:
                time.sleep(1)
                continue

        success, img = cap.read()
        if not success:
            continue

        img = cv2.flip(img, 1)

        # Motion detection
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        fgmask = fgbg.apply(gray)
        motion_pixels = cv2.countNonZero(fgmask)

        if motion_pixels > 500:
            motion_detected = True
            last_motion_time = current_time

        # Face detection and processing
        if motion_detected or (current_time - last_motion_time < motion_timeout):
            if USE_DNN:
                blob = cv2.dnn.blobFromImage(cv2.resize(img, (400, 400)), 1.0, (400, 400), (104.0, 177.0, 123.0))
                face_net.setInput(blob)
                detections = face_net.forward()
                face_found = detections.shape[2] > 0
            else:
                faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(100, 100))
                face_found = len(faces) > 0

            if face_found:
                imgSmall = cv2.resize(img, (0, 0), None, 0.25, 0.25)
                imgSmallRGB = cv2.cvtColor(imgSmall, cv2.COLOR_BGR2RGB)
                attendance_system.process_face(imgSmallRGB)

        # Update display
        imgBackground[113:113 + 305, 40:40 + 410] = cv2.resize(img, (410, 305))
        current_mode = attendance_system.update_mode_display()
        imgBackground[22:22 + 430, 528:528 + 273] = imgModeList[current_mode]

        # Show student details if processing
        if current_mode == AttendanceSystem.MODE_PROCESSING:
            if (details := attendance_system.get_student_details()):
                cv2.putText(imgBackground, details[0], (658, 330),
                            cv2.FONT_HERSHEY_COMPLEX, 0.5, (0, 0, 0), 1)

                cv2.putText(imgBackground, str(details[3]), (562, 77),  # Total attendance
                            cv2.FONT_HERSHEY_COMPLEX, 0.6, (0, 0, 0), 1)
                cv2.putText(imgBackground, details[2], (660, 367),  # Major
                            cv2.FONT_HERSHEY_COMPLEX, 0.4, (0, 0, 0), 1)

        # Key checks
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('r'):
            import threading

            threading.Thread(target=show_report_gui, daemon=True).start()

        cv2.imshow('Face Attendance', imgBackground)

    except KeyboardInterrupt:
        print("\n🛑 Keyboard interrupt received")
        break
    except Exception as e:
        print(f"🔥 Main loop error: {e}")
        continue

# ==================== CLEANUP ====================
print("\n🛑 Shutting down system...")

# Close report GUI if open
if hasattr(show_report_gui, '_window') and show_report_gui._window:
    show_report_gui._window.on_close()

cap.release()
cv2.destroyAllWindows()
scheduler.shutdown()
cursor.close()
db.close()
speech_queue.put(None)
speech_thread.join()
print("✅ System shutdown complete")