import datetime
import threading
import time
import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
import face_recognition
import numpy as np
from tensorflow import timestamp

from emergency_leave import handle_emergency_leave


class AttendanceSystem:
    MODE_READY = 0  # 1.png - Ready state
    MODE_PROCESSING = 1  # 2.png - Face detected, processing
    MODE_SUCCESS = 2  # 3.png - Attendance marked successfully
    MODE_ALREADY_MARKED = 3  # 4.png - Attendance already marked

    def __init__(self, db_connection, cursor, encode_list_known, student_ids, speech_queue):
        self.db = db_connection
        self.cursor = cursor
        self.encodeListKnown = encode_list_known
        self.studentIds = student_ids
        self._current_student = None
        self.speech_queue = speech_queue
        self._last_spoken = {}
        self.shown_emergency_dialogs = set()
        self.emergency_dialog_shown = False
        self.face_detection_active = False
        self.last_face_detected_time = 0
        self.MIN_PROCESSING_TIME = 1.5
        self.face_detection_timeout = 2.0
        self._last_spoken_already_marked = {}

        # State variables
        self.mode = self.MODE_READY
        self.face_detected = False
        self.last_face_time = 0
        self.processing_start = 0
        self.student_details = None
        self.current_student_id = None
        self.success_display_start = 0
        self.in_success_display = False
        self.in_already_marked_display = False

    def _clear_student_details(self):
        """Clear current student details"""
        self.student_details = None
        self.current_student_id = None

    # In attendance.py, modify the process_face method:
    def process_face(self, imgSmallRGB):
        current_time = time.time()

        try:
            # 1. Face Detection
            faceCurFrame = face_recognition.face_locations(imgSmallRGB)

            # Early exit if no faces detected
            if not faceCurFrame:
                if self.face_detection_active and current_time - self.last_face_detected_time > self.face_detection_timeout:
                    self.face_detection_active = False
                    self._clear_student_details()
                    self.mode = self.MODE_READY  # Reset to ready state
                    print("Face lost - resetting to ready state")
                return

            # Face detected - update tracking
            self.face_detection_active = True
            self.last_face_detected_time = current_time

            # 2. Face Encoding
            encodeCurFrame = face_recognition.face_encodings(imgSmallRGB, faceCurFrame)

            # Skip if no encodings generated
            if not encodeCurFrame:
                return

            # 3. Face Matching
            matches = face_recognition.compare_faces(self.encodeListKnown, encodeCurFrame[0])
            faceDis = face_recognition.face_distance(self.encodeListKnown, encodeCurFrame[0])

            # Critical protection against empty sequences
            if len(faceDis) == 0 or len(matches) == 0:
                return

            # 4. Find Best Match
            matchIndex = np.argmin(faceDis)
            minDistance = faceDis[matchIndex]

            # 5. Recognition Threshold Check
            if matches[matchIndex] and minDistance < 0.6:
                student_id = self.studentIds[matchIndex]

                # Only update if new student or no current details
                if student_id != self.current_student_id or not self.student_details:
                    self.current_student_id = student_id
                    self._get_student_details(student_id)

                    if self.student_details:
                        # Only announce detection if not done recently (2-second cooldown)
                        if not hasattr(self, 'last_detection_time') or current_time - self.last_detection_time > 2.0:
                            self.speak(f"Detected {self.student_details[1]}")
                            self.last_detection_time = current_time

                        self.last_face_time = current_time
                        self.face_detected = True
                        self.mode = self.MODE_PROCESSING  # Switch to processing state
                        self.processing_start = current_time

                # Process attendance
                if self.student_details and (current_time - self.processing_start >= 1.0 or
                                             student_id == self.current_student_id):
                    self._process_attendance(student_id)

            else:
                # No valid match found
                if current_time - self.last_face_time > 2:
                    self.mode = self.MODE_READY  # Reset to ready state
                    self._clear_student_details()

        except Exception as e:
            print(f"Face processing error: {str(e)}")
            # Reset to ready state on any error
            self.mode = self.MODE_READY
            self._clear_student_details()

    # Also update the update_mode_display method:
    def update_mode_display(self):
        """Handle mode timing and transitions"""
        current_time = time.time()

        # Reset if face is lost during processing
        if (self.mode == self.MODE_PROCESSING and
                current_time - self.last_face_detected_time > self.face_detection_timeout):
            self.mode = self.MODE_READY
            self._clear_student_details()
            return self.mode

        # Processing mode timeout
        if self.mode == self.MODE_PROCESSING:
            if current_time - self.processing_start > 3.5:
                self.mode = self.MODE_READY

        # Already marked mode timeout
        elif self.mode == self.MODE_ALREADY_MARKED:
            if current_time - self.processing_start > 3.5:
                self.mode = self.MODE_READY

        # Success mode timeout
        elif self.mode == self.MODE_SUCCESS:
            if current_time - self.success_display_start > 4:
                self.mode = self.MODE_READY
                self.in_success_display = False

        return self.mode

    def _get_student_details(self, student_id):
        """Fetch and store student details for display"""
        try:
            self.cursor.execute("""
                SELECT student_id, name, major, section, total_attendance 
                FROM students WHERE student_id = %s
            """, (student_id,))
            self.student_details = self.cursor.fetchone()
        except Exception as e:
            print(f"Error fetching student details: {e}")
            self.student_details = None

    def get_student_details(self):
        """Return student details for display during processing"""
        if self.student_details:
            return (
                self.student_details[0],  # student_id
                self.student_details[2],  # major
                self.student_details[4]  # total_attendance
            )
        return None

    def _process_attendance(self, student_id):
        """Process attendance with single emergency leave prompt"""
        current_time = time.time()
        processing_time = current_time - self.processing_start

        # Ensure minimum processing time has elapsed
        if processing_time < self.MIN_PROCESSING_TIME:
            return  # Stay in processing mode

        if not self.face_detection_active or not self.student_details:
            self.mode = self.MODE_READY
            self._clear_student_details()
            return

        try:
            now = datetime.datetime.now()
            today = now.date()

            # Get today's attendance records
            self.cursor.execute("""
                SELECT timestamp, is_emergency_leave, daily_status 
                FROM attendance_log 
                WHERE student_id = %s AND DATE(timestamp) = %s
                ORDER BY timestamp
            """, (student_id, today))
            records = self.cursor.fetchall()

            # Reset emergency dialog flag if new student detected
            if not hasattr(self, '_current_student') or self._current_student != student_id:
                self.emergency_dialog_shown = False
                self._current_student = student_id

            # CASE 1: No attendance yet (first mark)
            if len(records) == 0:
                self._mark_attendance(student_id, now, daily_status='pending')  # Modified
                self.speak(f"{self.student_details[1]}, first attendance marked")
                self.show_success_screen()

                # Show emergency leave option once (after a delay)
                if not self.emergency_dialog_shown:
                    self.emergency_dialog_shown = True
                    threading.Timer(3.0, self._show_emergency_leave_prompt, [student_id]).start()

            # CASE 2: One attendance (second mark possible)
            elif len(records) == 1:
                first_record_time = records[0][0]
                hours_passed = (now - first_record_time).total_seconds() / 3600

                if hours_passed >= 6:  # Valid interval for second attendance
                    # Mark second attendance
                    self._mark_attendance(student_id, now, daily_status='pending')  # Modified

                    # Update BOTH records to 'present' status only now
                    self.cursor.execute("""
                        UPDATE attendance_log 
                        SET daily_status = 'present'
                        WHERE student_id = %s AND DATE(timestamp) = %s
                    """, (student_id, today))

                    # Update attendance count
                    self.cursor.execute("""
                        UPDATE students 
                        SET total_attendance = total_attendance + 1
                        WHERE student_id = %s
                    """, (student_id,))

                    self.db.commit()
                    self.speak(f"{self.student_details[1]}, attendance complete")
                    self.show_success_screen()
                else:
                    # Show marked screen (already done once)
                    if not hasattr(self, '_last_spoken') or self._last_spoken.get(student_id) != today:
                        self.speak("Attendance marked once today")
                        self._last_spoken = {student_id: today}
                    self.show_success_screen()

                    # Show emergency leave option once (after a delay)
                    if not self.emergency_dialog_shown:
                        self.emergency_dialog_shown = True
                        threading.Timer(3.0, self._show_emergency_leave_prompt, [student_id]).start()

            # CASE 3: Both attendances done
            else:
                # Show already marked screen
                if not hasattr(self, '_last_spoken_already_marked') or self._last_spoken_already_marked.get(
                        student_id) != today:
                    self.speak("Attendance already completed today")
                    self._last_spoken_already_marked = {student_id: today}
                self.show_already_marked_screen()
                self._clear_student_details()  # Clear details when already marked

        except Exception as e:
            print(f"Attendance error: {e}")
            self.speak("Error processing attendance")
            self.show_already_marked_screen()
            self._clear_student_details()


    def _update_daily_status(self, student_id, date):
        """Update daily status for all records of a student on a given date"""
        try:
            # Update all records to 'present'
            self.cursor.execute("""
                UPDATE attendance_log 
                SET daily_status = 'present'
                WHERE student_id = %s AND DATE(timestamp) = %s
            """, (student_id, date))

            # Update attendance count in students table
            self.cursor.execute("""
                UPDATE students 
                SET total_attendance = total_attendance + 1
                WHERE student_id = %s
            """, (student_id,))

            self.db.commit()
            # Refresh student details to show updated count
            self._get_student_details(student_id)
        except Exception as e:
            print(f"Error updating daily status: {e}")
            self.db.rollback()

    # Update show_success_screen and show_already_marked_screen:
    def show_success_screen(self):
        """Show success screen after minimum processing time"""
        self.mode = self.MODE_SUCCESS
        self.success_display_start = time.time()
        self.in_success_display = True

    def show_already_marked_screen(self):
        """Show already marked screen after minimum processing time"""
        self.mode = self.MODE_ALREADY_MARKED
        self.processing_start = time.time()  # Reset timer for display
        self.in_already_marked_display = True

    def _show_emergency_leave_prompt(self, student_id):
        """Show emergency leave dialog once"""
        if self.mode == self.MODE_SUCCESS and student_id not in self.shown_emergency_dialogs:
            student_name = self.student_details[1] if self.student_details else "Student"

            approved = handle_emergency_leave(
                self.cursor,
                self.db,
                student_id,
                student_name,
                self.speak
            )

            if approved:
                self.speak("Emergency leave approved")
                self.show_success_screen()

            # Mark this student as having seen the dialog
            self.shown_emergency_dialogs.add(student_id)

    def _mark_attendance(self, student_id, timestamp, is_emergency=False, daily_status='pending'):
        """Mark attendance for a student"""
        try:
            # Fetch the latest student_name
            self.cursor.execute("SELECT name FROM students WHERE student_id = %s", (student_id,))
            latest_name = self.cursor.fetchone()[0]

            # Insert attendance record
            self.cursor.execute("""
                INSERT INTO attendance_log 
                (student_id, student_name, timestamp, is_emergency_leave, daily_status)
                VALUES (%s, %s, %s, %s, %s)
            """, (student_id, latest_name, timestamp, 'yes' if is_emergency else 'no', daily_status))

            # Update last_attendance in students table
            self.cursor.execute("""
                UPDATE students 
                SET last_attendance = %s
                WHERE student_id = %s
            """, (timestamp, student_id))

            self.db.commit()
        except Exception as e:
            print(f"Error marking attendance: {e}")
            self.db.rollback()
            raise

    def _check_attendance_complete(self, student_id, date):
        """Check if attendance is complete for a given date"""
        self.cursor.execute("""
            SELECT COUNT(*) FROM attendance_log 
            WHERE student_id = %s AND DATE(timestamp) = %s
            AND daily_status = 'present'
        """, (student_id, date))
        return self.cursor.fetchone()[0] >= 2

    def _update_attendance_count(self, student_id):
        """Immediately update attendance count after first mark"""
        try:
            self.cursor.execute("""
                UPDATE students 
                SET total_attendance = total_attendance + 1
                WHERE student_id = %s
            """, (student_id,))
            self.db.commit()
            # Refresh student details to show updated count
            self._get_student_details(student_id)
        except Exception as e:
            print(f"Error updating attendance count: {e}")
            self.db.rollback()

    def update_daily_attendance_status(self, student_id, date):
        """Update daily status when attendance is complete"""
        try:
            # Get all records for today
            self.cursor.execute("""
                SELECT id, is_emergency_leave, daily_status
                FROM attendance_log 
                WHERE student_id = %s AND DATE(timestamp) = %s
                ORDER BY timestamp
            """, (student_id, date))
            records = self.cursor.fetchall()

            if len(records) >= 2:  # Enough records to complete attendance
                # Update all records to 'present'
                self.cursor.execute("""
                    UPDATE attendance_log 
                    SET daily_status = 'present'
                    WHERE student_id = %s AND DATE(timestamp) = %s
                """, (student_id, date))

                # Update last_attendance in students table
                self.cursor.execute("""
                    UPDATE students 
                    SET last_attendance = %s
                    WHERE student_id = %s
                """, (datetime.datetime.now(), student_id))

                self.db.commit()
                return True
            return False
        except Exception as e:
            print(f"Error updating daily status: {e}")
            self.db.rollback()
            return False

    def show_success_screen(self):
        self.mode = self.MODE_SUCCESS
        self.success_display_start = time.time()
        self.in_success_display = True

    def show_already_marked_screen(self):
        self.mode = self.MODE_ALREADY_MARKED
        self.processing_start = time.time()
        self.in_already_marked_display = True

    def update_mode_display(self):
        """Handle mode timing and transitions"""
        current_time = time.time()

        # Reset if face is lost during processing
        if (self.mode == self.MODE_PROCESSING and
                current_time - self.last_face_detected_time > self.face_detection_timeout):
            self.mode = self.MODE_READY
            self._clear_student_details()
            return self.mode

        # Existing mode transition logic...
        if self.mode == self.MODE_PROCESSING:
            if current_time - self.processing_start > 3.5:
                self.mode = self.MODE_READY

        elif self.mode == self.MODE_ALREADY_MARKED:
            if current_time - self.processing_start > 3.5:
                self.mode = self.MODE_READY

        elif self.mode == self.MODE_SUCCESS:
            if current_time - self.success_display_start > 4:
                self.mode = self.MODE_READY
                self.in_success_display = False

        return self.mode

    def get_student_details(self):
        """Return student details for display during processing"""
        if self.mode == self.MODE_PROCESSING and self.student_details:
            return (
                self.student_details[0],  # student_id
                self.student_details[1],  # name
                self.student_details[2],  # major
                self.student_details[4]  # total_attendance
            )
        return None

    def generate_monthly_report(self, year_month=None):
        """Generate monthly attendance report for all students"""
        if year_month is None:
            year_month = datetime.datetime.now().strftime("%Y-%m")

        try:
            # First get all students
            self.cursor.execute("SELECT student_id FROM students")
            students = [x[0] for x in self.cursor.fetchall()]

            for student_id in students:
                # Calculate attendance stats for the month
                self.cursor.execute("""
                    SELECT 
                        COUNT(*) as total_days,
                        SUM(CASE WHEN daily_status = 'present' THEN 1 ELSE 0 END) as present_days,
                        SUM(CASE WHEN daily_status = 'absent' THEN 1 ELSE 0 END) as absent_days,
                        SUM(CASE WHEN is_emergency_leave = 'yes' THEN 1 ELSE 0 END) as emergency_leaves
                    FROM attendance_log
                    WHERE student_id = %s 
                    AND DATE_FORMAT(timestamp, '%Y-%m') = %s
                """, (student_id, year_month))

                stats = self.cursor.fetchone()
                total_days = stats[0] if stats[0] else 0
                present_days = stats[1] if stats[1] else 0
                absent_days = stats[2] if stats[2] else 0
                emergency_leaves = stats[3] if stats[3] else 0

                # Calculate percentage (avoid division by zero)
                percentage = 0.0
                if total_days > 0:
                    percentage = (present_days / total_days) * 100

                # Insert or update report
                self.cursor.execute("""
                    INSERT INTO attendance_report 
                    (student_id, month_year, total_days, present_days, absent_days, emergency_leaves, attendance_percentage)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        total_days = VALUES(total_days),
                        present_days = VALUES(present_days),
                        absent_days = VALUES(absent_days),
                        emergency_leaves = VALUES(emergency_leaves),
                        attendance_percentage = VALUES(attendance_percentage)
                """, (student_id, year_month, total_days, present_days, absent_days, emergency_leaves, percentage))

            self.db.commit()
            return True

        except Exception as e:
            print(f"Error generating monthly report: {e}")
            self.db.rollback()
            return False

    def get_section_report(self, section, month_year):
        """Get report data for a section"""
        try:
            self.cursor.execute("""
                SELECT s.student_id, s.name, s.section,
                       r.present_days, r.absent_days, 
                       r.emergency_leaves, r.attendance_percentage
                FROM students s
                LEFT JOIN attendance_report r ON s.student_id = r.student_id
                WHERE s.section = %s AND r.month_year = %s
                ORDER BY s.student_id
            """, (section, month_year))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Database error: {e}")
            return None

    def get_student_monthly_report(self, student_id, month_year):
        """Get detailed attendance for a specific student and month"""
        try:
            # Get summary
            self.cursor.execute("""
                SELECT student_id, month_year, total_days, present_days,
                       absent_days, emergency_leaves, attendance_percentage
                FROM attendance_report
                WHERE student_id = %s AND month_year = %s
            """, (student_id, month_year))
            summary = self.cursor.fetchone()

            # Get daily records
            self.cursor.execute("""
                SELECT DATE(timestamp), daily_status, is_emergency_leave
                FROM attendance_log
                WHERE student_id = %s AND DATE_FORMAT(timestamp, '%Y-%m') = %s
                ORDER BY timestamp
            """, (student_id, month_year))
            daily_records = self.cursor.fetchall()

            # Generate remarks
            remarks = ""
            if summary and summary[5] > 3:  # More than 3 emergency leaves
                remarks = "Excessive emergency leaves"
            elif summary and summary[6] < 75:  # Less than 75% attendance
                remarks = "Low attendance percentage"

            return summary, daily_records, remarks
        except Exception as e:
            print(f"Error getting student report: {e}")
            return None, None, ""

    def speak(self, text):
        """Add text to speech queue"""
        self.speech_queue.put(text)

    def mark_absent_students(self):
        """Mark students absent at end of day if they didn't complete attendance by 5 PM"""
        today = datetime.date.today()
        now = datetime.datetime.now()
        print(f"⏰ [DEBUG] Running at {now} (Nepal Time)")

        try:
            # Check if we already ran today
            self.cursor.execute("""
                SELECT 1 FROM attendance_log 
                WHERE DATE(timestamp) = %s 
                AND daily_status = 'absent'
                LIMIT 1
            """, (today,))
            if self.cursor.fetchone():
                print("Already marked absent today")
                return False

            # Get all active students
            self.cursor.execute("SELECT student_id FROM students")
            all_students = [x[0] for x in self.cursor.fetchall()]
            print(f"Total students: {len(all_students)}")

            # Get students who completed attendance (must have 2 records with 'present' status)
            self.cursor.execute("""
                SELECT student_id, COUNT(*) as count 
                FROM attendance_log 
                WHERE DATE(timestamp) = %s 
                AND daily_status = 'present'
                GROUP BY student_id
                HAVING count >= 2
            """, (today,))
            completed_students = [x[0] for x in self.cursor.fetchall()]
            print(f"Completed attendance students: {len(completed_students)}")

            # Mark all other students as absent
            absent_count = 0
            for student_id in all_students:
                if student_id not in completed_students:
                    try:
                        # Update all existing records to 'absent'
                        self.cursor.execute("""
                            UPDATE attendance_log 
                            SET daily_status = 'absent'
                            WHERE student_id = %s 
                            AND DATE(timestamp) = %s
                        """, (student_id, today))

                        # If no records exist for today, create one
                        if self.cursor.rowcount == 0:
                            self.cursor.execute("""
                                INSERT INTO attendance_log 
                                (student_id, student_name, timestamp, daily_status)
                                VALUES (%s, (SELECT name FROM students WHERE student_id = %s), %s, 'absent')
                            """, (student_id, student_id, now))

                        # Update last_attendance
                        self.cursor.execute("""
                            UPDATE students 
                            SET last_attendance = %s
                            WHERE student_id = %s
                        """, (now, student_id))

                        absent_count += 1
                        print(f"Marked {student_id} as absent")
                    except Exception as e:
                        print(f"Error marking {student_id} as absent: {e}")
                        continue

            self.db.commit()
            print(f"Marked {absent_count} students as absent for {today}")
            return True

        except Exception as e:
            self.db.rollback()
            print(f"Error marking absent: {e}")
            return False