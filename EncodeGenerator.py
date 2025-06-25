import face_recognition
import cv2
import os
import pickle
import mysql.connector

# Database connection
db = mysql.connector.connect(
    host='localhost',
    user='root',
    password='',
    database='face_recognition'
)
cursor = db.cursor()

# Get all students with photos
cursor.execute("SELECT student_id, photo FROM students WHERE photo IS NOT NULL")
students = cursor.fetchall()

encodeList = []
studentIds = []

for student in students:
    student_id, photo_blob = student

    # Save blob to temporary file
    with open(f"temp_{student_id}.jpg", 'wb') as f:
        f.write(photo_blob)

    # Load image and generate encoding
    img = cv2.imread(f"temp_{student_id}.jpg")
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    face_encodings = face_recognition.face_encodings(img)

    if face_encodings:  # If face found
        encodeList.append(face_encodings[0])
        studentIds.append(student_id)
        print(f"✅ Generated encoding for {student_id}")
    else:
        print(f"❌ No face found for {student_id}")

    # Clean up temp file
    os.remove(f"temp_{student_id}.jpg")

# Save encodings
with open("EncodeFile.p", 'wb') as f:
    pickle.dump([encodeList, studentIds], f)

print(f"\n🎉 Successfully encoded {len(studentIds)} students")
print("Student IDs:", studentIds)

cursor.close()
db.close()