import datetime
import tkinter as tk
from tkinter import messagebox
from pin_utils import verify_pin


import datetime
import tkinter as tk
from tkinter import messagebox
from pin_utils import verify_pin


def handle_emergency_leave(cursor, db, student_id, student_name, speak_func):
    """Handle the emergency leave process"""
    # Create emergency leave prompt
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    response = messagebox.askyesno(
        "Emergency Leave",
        f"{student_name}, you've already marked attendance today.\nDo you need emergency leave?",
        parent=root
    )
    root.destroy()

    if not response:
        speak_func("Emergency leave request cancelled")
        return False

    # Verify PIN if user requested emergency leave
    if not verify_pin(cursor, db, student_id, speak_func):
        speak_func("Emergency leave denied - PIN verification failed")
        return False

    now = datetime.datetime.now()

    try:
        # Get current student name
        cursor.execute("SELECT name FROM students WHERE student_id = %s", (student_id,))
        current_name = cursor.fetchone()[0]

        # Update emergency leave count AND last_attendance AND total_attendance
        cursor.execute("""
            UPDATE students SET
            emergency_leave_count = emergency_leave_count + 1,
            last_attendance = %s,
            total_attendance = total_attendance + 1
            WHERE student_id = %s
        """, (now, student_id))

        # Record emergency leave with current student name
        cursor.execute("""
            INSERT INTO attendance_log 
            (student_id, student_name, timestamp, is_emergency_leave, daily_status)
            VALUES (%s, %s, %s, 'yes', 'present')
        """, (student_id, current_name, now))

        db.commit()
        return True

    except Exception as e:
        db.rollback()
        print(f"Emergency leave database error: {e}")
        speak_func("Error processing emergency leave")
        return False