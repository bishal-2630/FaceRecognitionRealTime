import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, time

import mysql

from attendance import AttendanceSystem


class AttendanceReportGUI:
    def __init__(self, db_connection, cursor, attendance_system=None):
        self.db = db_connection
        self.cursor = cursor
        self.attendance_system = attendance_system or AttendanceSystem(
            db_connection,
            cursor,
            [],
            [],
            None
        )

        # Create root window
        self.root = tk.Tk()
        self.root.title("Attendance Reporting System")
        self.root.geometry("1000x700")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._create_widgets()
        self._populate_months()

    def on_close(self):
        """Proper cleanup on window close"""
        if hasattr(self, 'root'):
            self.root.quit()
            self.root.destroy()

    def _create_widgets(self):
        # Main notebook for different report types
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Section Report Tab
        self.section_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.section_frame, text="Section Report")
        self._create_section_report_tab()

        # Student Report Tab
        self.student_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.student_frame, text="Student Report")
        self._create_student_report_tab()

    def _create_section_report_tab(self):
        # Section selection
        ttk.Label(self.section_frame, text="Select Section:").grid(row=0, column=0, padx=5, pady=5)
        self.section_var = tk.StringVar()
        self.section_combo = ttk.Combobox(self.section_frame, textvariable=self.section_var, values=["A", "B"])
        self.section_combo.grid(row=0, column=1, padx=5, pady=5)
        self.section_combo.current(0)

        # Month selection
        ttk.Label(self.section_frame, text="Select Month:").grid(row=0, column=2, padx=5, pady=5)
        self.month_var = tk.StringVar()
        self.month_combo = ttk.Combobox(self.section_frame, textvariable=self.month_var)
        self.month_combo.grid(row=0, column=3, padx=5, pady=5)
        self._populate_months()

        # Generate button
        ttk.Button(self.section_frame, text="Generate Report", command=self.generate_section_report).grid(
            row=0, column=4, padx=5, pady=5)

        # Report treeview
        self.section_tree = ttk.Treeview(self.section_frame, columns=(
            "student_id", "name", "section", "present", "absent", "emergency", "percentage", "remarks"
        ), show="headings")

        self.section_tree.heading("student_id", text="Student ID")
        self.section_tree.heading("name", text="Name")
        self.section_tree.heading("section", text="Section")
        self.section_tree.heading("present", text="Present Days")
        self.section_tree.heading("absent", text="Absent Days")
        self.section_tree.heading("emergency", text="Emergency Leaves")
        self.section_tree.heading("percentage", text="Percentage")
        self.section_tree.heading("remarks", text="Remarks")

        self.section_tree.column("student_id", width=100)
        self.section_tree.column("name", width=150)
        self.section_tree.column("section", width=70)
        self.section_tree.column("present", width=80)
        self.section_tree.column("absent", width=80)
        self.section_tree.column("emergency", width=100)
        self.section_tree.column("percentage", width=80)
        self.section_tree.column("remarks", width=200)

        self.section_tree.grid(row=1, column=0, columnspan=5, padx=5, pady=5, sticky="nsew")

        # Scrollbar
        scrollbar = ttk.Scrollbar(self.section_frame, orient="vertical", command=self.section_tree.yview)
        scrollbar.grid(row=1, column=5, sticky="ns")
        self.section_tree.configure(yscrollcommand=scrollbar.set)

    def _create_student_report_tab(self):
        # Initialize variables first
        self.student_id_var = tk.StringVar()
        self.student_month_var = tk.StringVar()

        # Student ID entry
        ttk.Label(self.student_frame, text="Student ID:").grid(row=0, column=0, padx=5, pady=5)
        ttk.Entry(self.student_frame, textvariable=self.student_id_var).grid(row=0, column=1, padx=5, pady=5)

        # Month selection
        ttk.Label(self.student_frame, text="Select Month:").grid(row=0, column=2, padx=5, pady=5)
        self.student_month_combo = ttk.Combobox(self.student_frame, textvariable=self.student_month_var)
        self.student_month_combo.grid(row=0, column=3, padx=5, pady=5)
        self._populate_months()

        # Generate button
        ttk.Button(self.student_frame, text="Generate Report", command=self.generate_student_report).grid(
            row=0, column=4, padx=5, pady=5)

        # Summary frame
        summary_frame = ttk.LabelFrame(self.student_frame, text="Summary")
        summary_frame.grid(row=1, column=0, columnspan=5, padx=5, pady=5, sticky="ew")

        ttk.Label(summary_frame, text="Total Days:").grid(row=0, column=0, padx=5, pady=5)
        self.total_days_label = ttk.Label(summary_frame, text="")
        self.total_days_label.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(summary_frame, text="Present Days:").grid(row=0, column=2, padx=5, pady=5)
        self.present_days_label = ttk.Label(summary_frame, text="")
        self.present_days_label.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(summary_frame, text="Absent Days:").grid(row=0, column=4, padx=5, pady=5)
        self.absent_days_label = ttk.Label(summary_frame, text="")
        self.absent_days_label.grid(row=0, column=5, padx=5, pady=5)

        ttk.Label(summary_frame, text="Emergency Leaves:").grid(row=1, column=0, padx=5, pady=5)
        self.emergency_label = ttk.Label(summary_frame, text="")
        self.emergency_label.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(summary_frame, text="Attendance Percentage:").grid(row=1, column=2, padx=5, pady=5)
        self.percentage_label = ttk.Label(summary_frame, text="")
        self.percentage_label.grid(row=1, column=3, padx=5, pady=5)

        ttk.Label(summary_frame, text="Remarks:").grid(row=1, column=4, padx=5, pady=5)
        self.remarks_label = ttk.Label(summary_frame, text="", foreground="red")
        self.remarks_label.grid(row=1, column=5, padx=5, pady=5)

        # Daily records treeview
        self.daily_tree = ttk.Treeview(self.student_frame, columns=(
            "date", "status", "emergency"
        ), show="headings")

        self.daily_tree.heading("date", text="Date")
        self.daily_tree.heading("status", text="Status")
        self.daily_tree.heading("emergency", text="Emergency Leave")

        self.daily_tree.column("date", width=150)
        self.daily_tree.column("status", width=100)
        self.daily_tree.column("emergency", width=100)

        self.daily_tree.grid(row=2, column=0, columnspan=5, padx=5, pady=5, sticky="nsew")

        # Scrollbar
        scrollbar = ttk.Scrollbar(self.student_frame, orient="vertical", command=self.daily_tree.yview)
        scrollbar.grid(row=2, column=5, sticky="ns")
        self.daily_tree.configure(yscrollcommand=scrollbar.set)

    def _populate_months(self):
        """Populate month selection comboboxes with available months"""
        try:
            self.cursor.execute("""
                SELECT DISTINCT DATE_FORMAT(timestamp, '%Y-%m') as month_year
                FROM attendance_log
                ORDER BY month_year DESC
            """)
            months = [row[0] for row in self.cursor.fetchall()]

            if not months:
                current_month = datetime.now().strftime("%Y-%m")
                months = [current_month]

            # Safely set values for both comboboxes
            if hasattr(self, 'month_combo'):
                self.month_combo['values'] = months
                if months:
                    self.month_combo.current(0)

            if hasattr(self, 'student_month_combo'):
                self.student_month_combo['values'] = months
                if months:
                    self.student_month_combo.current(0)

        except Exception as e:
            print(f"Error populating months: {e}")
            messagebox.showerror("Error", "Could not load month data")

    def generate_section_report(self):
        try:
            # Verify connection
            if not self.db.is_connected():
                self.db.reconnect(attempts=3, delay=1)

            section = self.section_var.get()
            month = self.month_var.get()

            if not all([section, month]):
                raise ValueError("Please select both section and month")

            # Clear previous data
            self.section_tree.delete(*self.section_tree.get_children())

            # Execute with retry logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.cursor.execute("""
                        SELECT s.student_id, s.name, s.section,
                               IFNULL(r.present_days, 0), IFNULL(r.absent_days, 0),
                               IFNULL(r.emergency_leaves, 0), IFNULL(r.attendance_percentage, 0)
                        FROM students s
                        LEFT JOIN attendance_report r ON s.student_id = r.student_id 
                            AND r.month_year = %s
                        WHERE s.section = %s
                        ORDER BY s.student_id
                    """, (month, section))

                    for row in self.cursor.fetchall():
                        remarks = "Good" if row[6] >= 75 else "Needs improvement"
                        self.section_tree.insert("", "end", values=(
                            row[0], row[1], row[2], row[3], row[4], row[5],
                            f"{row[6]:.2f}%", remarks
                        ))
                    break  # Success - exit retry loop

                except mysql.connector.Error as err:
                    if attempt == max_retries - 1:
                        raise
                    print(f"⚠️ Retry {attempt + 1} for report generation")
                    time.sleep(1)
                    self.db.reconnect()

        except Exception as e:
            messagebox.showerror("Report Error",
                                 f"Error processing attendance:\n{str(e)}\n\n"
                                 "Please try again or check server connection")

    def generate_student_report(self):
        student_id = self.student_id_var.get().strip()
        month = self.student_month_var.get()

        if not student_id or not month:
            messagebox.showwarning("Input Error", "Please enter student ID and select month")
            return

        # Clear previous data
        for item in self.daily_tree.get_children():
            self.daily_tree.delete(item)

        # Get report data using the new method
        summary, daily_records, remarks = self.attendance_system.get_student_monthly_report(student_id, month)

        if not summary or not daily_records:
            messagebox.showinfo("No Data", f"No attendance data found for student {student_id} in {month}")
            return

        # Update summary labels
        self.total_days_label.config(text=str(summary[2]))
        self.present_days_label.config(text=str(summary[3]))
        self.absent_days_label.config(text=str(summary[4]))
        self.emergency_label.config(text=str(summary[5]))
        self.percentage_label.config(text=f"{summary[6]:.2f}%")
        self.remarks_label.config(text=remarks)

        # Populate daily records
        for record in daily_records:
            self.daily_tree.insert("", "end", values=(
                record[0], record[1], "Yes" if record[2] == "yes" else "No"
            ))