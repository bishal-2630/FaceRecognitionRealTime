import mysql.connector
import os
from datetime import datetime
import time


def create_database_and_tables():
    """Create database and tables if they don't exist"""
    temp_connection = None
    temp_cursor = None
    try:
        # Connect without specifying database with increased timeout
        temp_connection = mysql.connector.connect(
            host='localhost',
            user='root',
            password='',
            connection_timeout=30
        )
        temp_cursor = temp_connection.cursor()

        # Create database if not exists
        temp_cursor.execute("CREATE DATABASE IF NOT EXISTS face_recognition")
        print("Database 'face_recognition' created or already exists")

        # Connect to the database
        temp_cursor.execute("USE face_recognition")

        # Create students table
        temp_cursor.execute("""
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
        )
        """)

        # Create attendance_log table
        temp_cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            student_id VARCHAR(20),
            student_name VARCHAR(100),
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_emergency_leave ENUM('yes', 'no') DEFAULT 'no',
            daily_status VARCHAR(20) DEFAULT 'pending',
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
        """)

        temp_connection.commit()
        print("Tables created successfully")
        return True

    except mysql.connector.Error as err:
        print(f"Error creating database/tables: {err}")
        return False
    finally:
        if temp_cursor:
            temp_cursor.close()
        if temp_connection and temp_connection.is_connected():
            temp_connection.close()


def verify_database_content(connection):
    """Verify that data exists in the database"""
    cursor = None
    try:
        if not connection.is_connected():
            print("Database connection is not active")
            return

        cursor = connection.cursor()

        # Check students table
        cursor.execute("SELECT COUNT(*) FROM students")
        student_count = cursor.fetchone()[0]
        print(f"Found {student_count} students in database")

        # Check attendance_log table
        cursor.execute("SELECT COUNT(*) FROM attendance_log")
        log_count = cursor.fetchone()[0]
        print(f"Found {log_count} attendance records in database")

        # List all students
        cursor.execute("SELECT student_id, name FROM students")
        students = cursor.fetchall()
        print("\nCurrent students in database:")
        for student in students:
            print(f"ID: {student[0]}, Name: {student[1]}")

    except mysql.connector.Error as err:
        print(f"Error verifying database content: {err}")
    finally:
        if cursor:
            cursor.close()


def get_db_connection():
    """Get database connection with retry logic"""
    max_retries = 3
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            connection = mysql.connector.connect(
                host='localhost',
                user='root',
                password='',
                database='face_recognition',
                connection_timeout=30
            )
            return connection
        except mysql.connector.Error as err:
            print(f"Attempt {attempt + 1} failed: {err}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            raise


def convert_to_binary(filename):
    """Convert digital data to binary format"""
    try:
        with open(filename, 'rb') as file:
            return file.read()
    except Exception as e:
        print(f"Error reading image file {filename}: {e}")
        return None


def process_student_batch(connection, student_data, student_ids, start_idx, end_idx):
    """Process a batch of students with enhanced error handling and image optimization"""
    cursor = None
    processed_count = 0
    try:
        cursor = connection.cursor()

        for i in range(start_idx, end_idx):
            student_id = student_ids[i]
            data = student_data[student_id]

            try:
                # Initialize variables
                image_file = os.path.join('images', f"{student_id}.jpg")
                photo_blob = None

                # Image handling with compression
                if os.path.exists(image_file):
                    try:
                        # Check file size first
                        file_size = os.path.getsize(image_file)
                        if file_size > 10 * 1024 * 1024:  # 10MB hard limit
                            print(f"⚠️ Skipping large image for {student_id} ({file_size / 1024 / 1024:.2f} MB)")
                            photo_blob = None
                        else:
                            # Compress image if needed
                            with open(image_file, 'rb') as f:
                                original_blob = f.read()

                            # Only compress if > 2MB
                            if len(original_blob) > 2 * 1024 * 1024:
                                from PIL import Image
                                import io

                                img = Image.open(io.BytesIO(original_blob))
                                img_io = io.BytesIO()

                                # Convert to JPEG if not already
                                if img.format != 'JPEG':
                                    img = img.convert('RGB')

                                # Save with 85% quality
                                img.save(img_io, 'JPEG', quality=85)
                                photo_blob = img_io.getvalue()
                                print(
                                    f"📐 Compressed image for {student_id} (original: {len(original_blob) / 1024:.1f}KB -> compressed: {len(photo_blob) / 1024:.1f}KB)")
                            else:
                                photo_blob = original_blob
                    except Exception as img_error:
                        print(f"🖼️ Image processing error for {student_id}: {img_error}")
                        photo_blob = None
                else:
                    print(f"📷 No image found for {student_id}")

                # Database operation with retry logic
                max_retries = 2
                for attempt in range(max_retries):
                    try:
                        cursor.execute("""
                            INSERT INTO students (
                                student_id, name, major, starting_year, 
                                section, total_attendance, year, last_attendance, photo,
                                pin, emergency_leave_count, pin_attempts
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                name = VALUES(name),
                                major = VALUES(major),
                                section = VALUES(section),
                                photo = VALUES(photo),
                                last_attendance = VALUES(last_attendance)
                        """, (
                            student_id, data["name"], data["major"], data["starting_year"],
                            data["section"], data["total_attendance"], data["year"],
                            data["last_attendance"], photo_blob,
                            data.get("pin", "0000"),  # Default PIN if not specified
                            data.get("emergency_leave_count", 0),
                            data.get("pin_attempts", 0)
                        ))

                        # Insert attendance log with current student name
                        cursor.execute("""
                            INSERT INTO attendance_log 
                            (student_id, student_name, timestamp)
                            VALUES (%s, %s, %s)
                        """, (student_id, data["name"], datetime.now()))

                        processed_count += 1
                        print(f"✅ Success: {student_id} ({processed_count}/{end_idx - start_idx})")
                        break  # Success - exit retry loop

                    except mysql.connector.Error as err:
                        if attempt == max_retries - 1:  # Last attempt failed
                            raise
                        print(f"⚠️ Retry {attempt + 1} for {student_id}: {err}")
                        time.sleep(1)  # Wait before retry
                        continue

            except mysql.connector.Error as err:
                print(f"❌ Database error on {student_id}: {err}")
                connection.rollback()
                continue
            except Exception as e:
                print(f"⚠️ Unexpected error on {student_id}: {e}")
                connection.rollback()
                continue

        connection.commit()
        print(f"🎉 Batch completed. Success: {processed_count}, Failed: {(end_idx - start_idx) - processed_count}")
        return processed_count > 0  # Return True if at least one succeeded

    except Exception as e:
        print(f"🔥 Fatal batch error: {e}")
        connection.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        # Ensure connection is alive
        try:
            if connection.is_connected():
                connection.ping(reconnect=True, attempts=3, delay=5)
        except:
            pass


def main():
    # Create database and tables first
    if not create_database_and_tables():
        exit()

    connection = None
    try:
        connection = get_db_connection()
        print("\nSuccessfully connected to database")

        # Verify current content before making changes
        verify_database_content(connection)

        # Updated student data
        student_data = {
            "1": {
                "name": "Bishal",
                "major": " Science",
                "starting_year": 2018,
                "section": "A",
                "total_attendance": 9,
                "year": 4,
                "last_attendance": "2023-09-01 00:34:00"
            },
            "2": {
                "name": "Lionel Messi",
                "major": "Sports ",
                "starting_year": 2018,
                "section": "B",
                "total_attendance": 10,
                "year": 3,
                "last_attendance": "2023-09-01 01:23:00"
            },
            "3": {
                "name": "Elon Musk",
                "major": " Engineering",
                "starting_year": 2018,
                "section": "A",
                "total_attendance": 6,
                "year": 4,
                "last_attendance": "2023-09-01 00:20:00"
            },

            "4": {
                "name": "Zayn Malik",
                "major": "Music",
                "starting_year": 2016,
                "section": "B",
                "total_attendance": 0,
                "year": 4,
                "last_attendance": "2023-09-01 00:20:00"
            },


        }

        # Process students in smaller batches
        batch_size = 2  # Process 2 students at a time
        student_ids = list(student_data.keys())

        for i in range(0, len(student_ids), batch_size):
            end_idx = min(i + batch_size, len(student_ids))
            print(f"\nProcessing batch {i // batch_size + 1}/{(len(student_ids) - 1) // batch_size + 1}")

            success = process_student_batch(
                connection,
                student_data,
                student_ids,
                i,
                end_idx
            )

            if not success:
                # Try to reconnect if batch failed
                connection = get_db_connection()

            # Small delay between batches
            time.sleep(1)

        # Final verification
        verify_database_content(connection)

    except mysql.connector.Error as err:
        print(f"Failed to connect to database: {err}")
    finally:
        if connection and connection.is_connected():
            connection.close()


if __name__ == "__main__":
    main()