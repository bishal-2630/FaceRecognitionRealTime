# pin_utils.py
import random
import tkinter as tk
from tkinter import simpledialog, messagebox
import pyttsx3


def generate_pin():
    """Generate random 4-digit PIN"""
    return str(random.randint(1000, 9999))


def verify_pin(cursor, db, student_id, speak_func=None):
    """Handle PIN verification with attempt count display"""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    try:
        # Get current PIN and attempts at start
        cursor.execute("SELECT pin, pin_attempts FROM students WHERE student_id = %s", (student_id,))
        result = cursor.fetchone()
        if not result:
            if speak_func:
                speak_func("Student not found")
            root.destroy()
            return False

        correct_pin, attempts = result
        remaining_attempts = 3 - attempts

        while remaining_attempts > 0:
            # Show remaining attempts in dialog
            pin = simpledialog.askstring(
                "PIN Verification",
                f"Enter your 4-digit PIN ({remaining_attempts} {'attempt' if remaining_attempts == 1 else 'attempts'} left):",
                parent=root,
                show='*'
            )

            if not pin:  # User cancelled
                if speak_func:
                    speak_func("PIN entry cancelled")
                root.destroy()
                return False

            if pin == correct_pin:
                # Generate new PIN and reset attempts
                new_pin = generate_pin()
                cursor.execute("""
                    UPDATE students 
                    SET pin = %s, pin_attempts = 0 
                    WHERE student_id = %s
                """, (new_pin, student_id))
                db.commit()
                if speak_func:
                    speak_func("PIN verified successfully")
                root.destroy()
                return True
            else:
                # Increment attempts on failure
                cursor.execute("""
                    UPDATE students 
                    SET pin_attempts = pin_attempts + 1 
                    WHERE student_id = %s
                """, (student_id,))
                db.commit()
                remaining_attempts -= 1
                if speak_func:
                    speak_func("Incorrect PIN")

        # After 3 failed attempts - generate new PIN
        new_pin = generate_pin()
        cursor.execute("""
            UPDATE students 
            SET pin = %s, pin_attempts = 0 
            WHERE student_id = %s
        """, (new_pin, student_id))
        db.commit()

        messagebox.showwarning(
            "PIN Reset",
            "Maximum attempts reached. New PIN generated.",
            parent=root
        )
        if speak_func:
            speak_func("Maximum attempts reached. New PIN generated.")
        root.destroy()
        return False

    except Exception as e:
        print(f"Error during PIN verification: {e}")
        db.rollback()
        root.destroy()
        return False