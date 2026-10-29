import os
import sys
import random
from datetime import datetime, date, timedelta
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from extensions import db
from models import (
    Department, AcademicYear, Section, User, Admin, Faculty, Student,
    Subject, FacultySubjectAssignment, Examination, Mark, AttendanceRecord,
    Question, StudentTask, StudentGoal, MotivationalQuote
)

DEPARTMENTS = [
    {"name": "Information Technology", "code": "IT"},
    {"name": "Computer Science", "code": "CS"},
    {"name": "Electronics & Communication", "code": "EC"},
    {"name": "Electrical Engineering", "code": "EE"},
    {"name": "Mechanical Engineering", "code": "ME"},
    {"name": "Civil Engineering", "code": "CE"},
]

SUBJECTS_BY_DEPT = {
    "IT": [
        {"code": "IT101", "name": "Programming in C", "semester": 1, "credits": 4},
        {"code": "IT102", "name": "Mathematics I", "semester": 1, "credits": 4},
        {"code": "IT103", "name": "Digital Logic Design", "semester": 1, "credits": 3},
        {"code": "IT104", "name": "Communication Skills", "semester": 1, "credits": 2},
        {"code": "IT201", "name": "Data Structures", "semester": 2, "credits": 4},
        {"code": "IT202", "name": "Mathematics II", "semester": 2, "credits": 4},
        {"code": "IT203", "name": "Object Oriented Programming", "semester": 2, "credits": 3},
        {"code": "IT204", "name": "Computer Organization", "semester": 2, "credits": 3},
        {"code": "IT301", "name": "Database Management Systems", "semester": 3, "credits": 4},
        {"code": "IT302", "name": "Operating Systems", "semester": 3, "credits": 4},
        {"code": "IT303", "name": "Computer Networks", "semester": 3, "credits": 4},
        {"code": "IT304", "name": "Web Technologies", "semester": 3, "credits": 3},
    ],
    "CS": [
        {"code": "CS101", "name": "Introduction to Computing", "semester": 1, "credits": 4},
        {"code": "CS102", "name": "Discrete Mathematics", "semester": 1, "credits": 4},
        {"code": "CS103", "name": "Programming Fundamentals", "semester": 1, "credits": 4},
        {"code": "CS104", "name": "Physics", "semester": 1, "credits": 3},
        {"code": "CS201", "name": "Algorithms & Complexity", "semester": 2, "credits": 4},
        {"code": "CS202", "name": "Computer Architecture", "semester": 2, "credits": 3},
        {"code": "CS203", "name": "Java Programming", "semester": 2, "credits": 3},
        {"code": "CS301", "name": "Artificial Intelligence", "semester": 3, "credits": 4},
        {"code": "CS302", "name": "Software Engineering", "semester": 3, "credits": 4},
        {"code": "CS303", "name": "Compiler Design", "semester": 3, "credits": 4},
    ],
    "EC": [
        {"code": "EC101", "name": "Basic Electronics", "semester": 1, "credits": 4},
        {"code": "EC102", "name": "Engineering Mathematics", "semester": 1, "credits": 4},
        {"code": "EC103", "name": "Circuit Theory", "semester": 1, "credits": 4},
        {"code": "EC201", "name": "Signals & Systems", "semester": 2, "credits": 4},
        {"code": "EC202", "name": "Analog Electronics", "semester": 2, "credits": 4},
        {"code": "EC203", "name": "Digital Electronics", "semester": 2, "credits": 3},
        {"code": "EC301", "name": "Communication Systems", "semester": 3, "credits": 4},
        {"code": "EC302", "name": "Microprocessors", "semester": 3, "credits": 4},
    ],
    "EE": [
        {"code": "EE101", "name": "Electrical Fundamentals", "semester": 1, "credits": 4},
        {"code": "EE102", "name": "Engineering Maths", "semester": 1, "credits": 4},
        {"code": "EE201", "name": "Electric Circuits", "semester": 2, "credits": 4},
        {"code": "EE202", "name": "Machines I", "semester": 2, "credits": 4},
        {"code": "EE301", "name": "Power Systems", "semester": 3, "credits": 4},
        {"code": "EE302", "name": "Control Systems", "semester": 3, "credits": 4},
    ],
    "ME": [
        {"code": "ME101", "name": "Engineering Mechanics", "semester": 1, "credits": 4},
        {"code": "ME102", "name": "Engineering Drawing", "semester": 1, "credits": 3},
        {"code": "ME201", "name": "Thermodynamics", "semester": 2, "credits": 4},
        {"code": "ME202", "name": "Fluid Mechanics", "semester": 2, "credits": 4},
        {"code": "ME301", "name": "Manufacturing Processes", "semester": 3, "credits": 4},
        {"code": "ME302", "name": "Machine Design", "semester": 3, "credits": 4},
    ],
    "CE": [
        {"code": "CE101", "name": "Engineering Mechanics", "semester": 1, "credits": 4},
        {"code": "CE102", "name": "Surveying", "semester": 1, "credits": 3},
        {"code": "CE201", "name": "Structural Analysis", "semester": 2, "credits": 4},
        {"code": "CE202", "name": "Soil Mechanics", "semester": 2, "credits": 4},
        {"code": "CE301", "name": "Concrete Technology", "semester": 3, "credits": 4},
        {"code": "CE302", "name": "Transportation Engineering", "semester": 3, "credits": 3},
    ],
}

FIRST_NAMES = [
    "Aarav", "Aanya", "Abhinav", "Aditi", "Aditya", "Akash", "Ananya", "Arjun",
    "Aryan", "Bhavya", "Deepak", "Divya", "Gauri", "Harsh", "Ishaan", "Kavya",
    "Kiran", "Kunal", "Lakshmi", "Manish", "Meera", "Mohit", "Neha", "Nikhil",
    "Pooja", "Pranav", "Priya", "Rahul", "Rajesh", "Riya", "Rohan", "Rohit",
    "Sahil", "Sanjay", "Shreya", "Siddharth", "Sneha", "Suresh", "Tanvi", "Varun",
    "Vidya", "Vijay", "Vinay", "Vishal", "Yash", "Zara", "Amit", "Anjali",
    "Chetan", "Dhruv"
]

LAST_NAMES = [
    "Sharma", "Patel", "Singh", "Kumar", "Gupta", "Joshi", "Mehta", "Shah",
    "Verma", "Nair", "Reddy", "Iyer", "Pillai", "Rao", "Jain", "Malhotra",
    "Srivastava", "Agarwal", "Bose", "Chatterjee", "Das", "Dey", "Ghosh",
    "Kapoor", "Khanna", "Mishra", "Mukherjee", "Pandey", "Saxena", "Tiwari"
]

FACULTY_NAMES = [
    "Dr. Ramesh Kumar", "Prof. Sunita Sharma", "Dr. Vijay Patel", "Prof. Anita Joshi",
    "Dr. Suresh Reddy", "Prof. Meena Gupta", "Dr. Anil Singh", "Prof. Rekha Nair",
    "Dr. Pradeep Verma", "Prof. Kavitha Iyer", "Dr. Mohan Rao", "Prof. Smitha Pillai",
    "Dr. Rajiv Mehta", "Prof. Usha Saxena", "Dr. Girish Jain",
]

MOTIVATIONAL_QUOTES = [
    ("Success is not final, failure is not fatal: it is the courage to continue that counts.", "Winston Churchill"),
    ("The beautiful thing about learning is that nobody can take it away from you.", "B.B. King"),
    ("Education is the most powerful weapon which you can use to change the world.", "Nelson Mandela"),
    ("The expert in anything was once a beginner.", "Helen Hayes"),
    ("It always seems impossible until it's done.", "Nelson Mandela"),
    ("Knowledge is power.", "Francis Bacon"),
    ("In the middle of every difficulty lies opportunity.", "Albert Einstein"),
    ("Don't watch the clock; do what it does. Keep going.", "Sam Levenson"),
    ("The secret of getting ahead is getting started.", "Mark Twain"),
    ("Believe you can and you're halfway there.", "Theodore Roosevelt"),
]

SAMPLE_QUESTIONS = {
    "IT": [
        {"q": "What is the time complexity of binary search?", "a": "O(log n)", "b": "O(n)", "c": "O(n²)", "d": "O(1)", "ans": "A", "topic": "Algorithms", "diff": "easy"},
        {"q": "Which data structure uses LIFO principle?", "a": "Queue", "b": "Stack", "c": "Array", "d": "Tree", "ans": "B", "topic": "Data Structures", "diff": "easy"},
        {"q": "What does SQL stand for?", "a": "Structured Query Language", "b": "Simple Query Language", "c": "Structured Quick Language", "d": "None", "ans": "A", "topic": "DBMS", "diff": "easy"},
        {"q": "Which protocol is used for web browsing?", "a": "FTP", "b": "SMTP", "c": "HTTP", "d": "TCP", "ans": "C", "topic": "Networks", "diff": "easy"},
        {"q": "What is a primary key in a database?", "a": "A key that can be null", "b": "Uniquely identifies each record", "c": "A foreign key", "d": "An index", "ans": "B", "topic": "DBMS", "diff": "medium"},
    ],
    "CS": [
        {"q": "What is the worst case complexity of QuickSort?", "a": "O(n log n)", "b": "O(n²)", "c": "O(n)", "d": "O(log n)", "ans": "B", "topic": "Algorithms", "diff": "medium"},
        {"q": "Which of the following is NOT an OOP concept?", "a": "Encapsulation", "b": "Compilation", "c": "Polymorphism", "d": "Inheritance", "ans": "B", "topic": "OOP", "diff": "easy"},
    ],
    "EC": [
        {"q": "Ohm's law states V=?", "a": "I+R", "b": "I/R", "c": "IR", "d": "I-R", "ans": "C", "topic": "Circuits", "diff": "easy"},
        {"q": "What is the unit of capacitance?", "a": "Henry", "b": "Ohm", "c": "Farad", "d": "Tesla", "ans": "C", "topic": "Electronics", "diff": "easy"},
    ],
}


def create_synthetic_data():
    app = create_app()
    with app.app_context():
        print("Creating database tables...")
        db.create_all()

        # Check if already seeded
        if User.query.filter_by(role='admin').first():
            print("Database already seeded. Skipping.")
            return

        print("Seeding database with synthetic data...")

        # Academic Year
        ay = AcademicYear(year_label="2024-25", is_current=True)
        db.session.add(ay)
        db.session.flush()

        # Admin user
        admin_user = User(unique_id="ADMIN001", role="admin")
        admin_user.set_password("ADMIN001")
        db.session.add(admin_user)
        db.session.flush()
        admin = Admin(user_id=admin_user.id, name="System Administrator",
                      email="admin@edupulse.edu")
        db.session.add(admin)

        # Departments
        dept_objects = {}
        for dept_data in DEPARTMENTS:
            dept = Department(name=dept_data["name"], code=dept_data["code"])
            db.session.add(dept)
            db.session.flush()
            dept_objects[dept_data["code"]] = dept

        # Subjects
        subject_objects = {}
        for dept_code, subjects in SUBJECTS_BY_DEPT.items():
            dept = dept_objects[dept_code]
            subject_objects[dept_code] = []
            for s in subjects:
                subj = Subject(
                    code=s["code"], name=s["name"],
                    department_id=dept.id, semester=s["semester"],
                    credits=s["credits"]
                )
                db.session.add(subj)
                db.session.flush()
                subject_objects[dept_code].append(subj)

        # Sections per department
        section_objects = {}
        for dept_code, dept in dept_objects.items():
            section_objects[dept_code] = {}
            for sem in [1, 2, 3]:
                for sec_name in ["A", "B"]:
                    sec = Section(
                        name=sec_name,
                        department_id=dept.id,
                        academic_year_id=ay.id,
                        semester=sem,
                        max_students=60
                    )
                    db.session.add(sec)
                    db.session.flush()
                    section_objects[dept_code][(sem, sec_name)] = sec

        # Faculty
        faculty_objects = []
        fac_index = 0
        for dept_code, dept in list(dept_objects.items())[:4]:  # 4 main departments get faculty
            for i in range(3):
                fname = FACULTY_NAMES[fac_index % len(FACULTY_NAMES)]
                fac_id = f"FAC{dept_code}{str(i+1).zfill(2)}"
                fac_user = User(unique_id=fac_id, role="faculty")
                fac_user.set_password(fac_id)
                db.session.add(fac_user)
                db.session.flush()
                fac = Faculty(
                    user_id=fac_user.id, faculty_id=fac_id,
                    name=fname, department_id=dept.id,
                    designation="Assistant Professor"
                )
                db.session.add(fac)
                db.session.flush()
                faculty_objects.append((dept_code, fac))
                fac_index += 1

        # Faculty Subject Assignments
        for dept_code, fac in faculty_objects:
            dept_subjects = subject_objects.get(dept_code, [])
            for subj in dept_subjects[:4]:
                for sem in [1, 2]:
                    for sec_name in ["A"]:
                        key = (subj.semester, sec_name)
                        if key in section_objects.get(dept_code, {}):
                            existing = FacultySubjectAssignment.query.filter_by(
                                faculty_id=fac.id, subject_id=subj.id,
                                section_id=section_objects[dept_code][key].id
                            ).first()
                            if not existing:
                                try:
                                    fsa = FacultySubjectAssignment(
                                        faculty_id=fac.id,
                                        subject_id=subj.id,
                                        section_id=section_objects[dept_code][key].id,
                                        academic_year_id=ay.id
                                    )
                                    db.session.add(fsa)
                                    db.session.flush()
                                except Exception:
                                    db.session.rollback()

        # Students
        student_objects = []
        roll_counter = {}
        used_names = []

        primary_dept = "IT"
        dept = dept_objects[primary_dept]

        for sem in [1, 2, 3]:
            for sec_name in ["A", "B"]:
                key = (sem, sec_name)
                section = section_objects[primary_dept][key]
                count = 12 if sem == 1 else (10 if sem == 2 else 8)

                for i in range(count):
                    first = random.choice(FIRST_NAMES)
                    last = random.choice(LAST_NAMES)
                    name = f"{first} {last}"

                    roll_key = f"{primary_dept}{sem}{sec_name}"
                    roll_counter[roll_key] = roll_counter.get(roll_key, 0) + 1
                    roll = f"{primary_dept}{23+sem}{str(roll_counter[roll_key]).zfill(3)}{sec_name}"

                    # Ensure unique roll number
                    while Student.query.filter_by(roll_number=roll).first():
                        roll_counter[roll_key] += 1
                        roll = f"{primary_dept}{23+sem}{str(roll_counter[roll_key]).zfill(3)}{sec_name}"

                    stu_user = User(unique_id=roll, role="student")
                    stu_user.set_password(roll)
                    db.session.add(stu_user)
                    db.session.flush()

                    stu = Student(
                        user_id=stu_user.id,
                        roll_number=roll,
                        name=name,
                        email=f"{roll.lower()}@student.edupulse.edu",
                        department_id=dept.id,
                        section_id=section.id,
                        academic_year_id=ay.id,
                        current_semester=sem,
                        gender=random.choice(["Male", "Female"]),
                        date_of_birth=date(2003 + sem, random.randint(1, 12), random.randint(1, 28))
                    )
                    db.session.add(stu)
                    db.session.flush()
                    student_objects.append(stu)

        # Also add a few students in CS
        cs_dept = dept_objects["CS"]
        for i in range(10):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            name = f"{first} {last}"
            roll = f"CS24{str(i+1).zfill(3)}A"
            while Student.query.filter_by(roll_number=roll).first():
                roll = f"CS24{str(i+2).zfill(3)}A"

            stu_user = User(unique_id=roll, role="student")
            stu_user.set_password(roll)
            db.session.add(stu_user)
            db.session.flush()

            cs_section = section_objects["CS"][(1, "A")]
            stu = Student(
                user_id=stu_user.id,
                roll_number=roll,
                name=name,
                email=f"{roll.lower()}@student.edupulse.edu",
                department_id=cs_dept.id,
                section_id=cs_section.id,
                academic_year_id=ay.id,
                current_semester=1,
                gender=random.choice(["Male", "Female"]),
            )
            db.session.add(stu)
            db.session.flush()
            student_objects.append(stu)

        db.session.commit()

        # Examinations & Marks
        print("Creating examination records and marks...")
        it_subjects = subject_objects["IT"]

        exam_configs = [
            {"name": "IA-1", "type": "internal", "max_marks": 30},
            {"name": "IA-2", "type": "internal", "max_marks": 30},
            {"name": "IA-3", "type": "internal", "max_marks": 30},
            {"name": "Semester Exam", "type": "semester", "max_marks": 100},
            {"name": "Assignment-1", "type": "assignment", "max_marks": 10},
        ]

        # Create examinations for IT subjects
        exam_objects = []
        for subj in it_subjects:
            for ec in exam_configs:
                # Find sections matching this semester
                matching_sections = [
                    s for (sem, sn), s in section_objects["IT"].items()
                    if sem == subj.semester and sn == "A"
                ]
                if not matching_sections:
                    continue
                section = matching_sections[0]
                exam = Examination(
                    subject_id=subj.id,
                    name=ec["name"],
                    exam_type=ec["type"],
                    max_marks=ec["max_marks"],
                    semester=subj.semester,
                    academic_year_id=ay.id,
                    section_id=section.id,
                    exam_date=date(2024, random.randint(7, 11), random.randint(1, 28))
                )
                db.session.add(exam)
                db.session.flush()
                exam_objects.append(exam)

        db.session.commit()

        # Create marks for students
        it_students = [s for s in student_objects if s.department.code == "IT"]
        for stu in it_students:
            # Get exams for this student's semester
            stu_exams = [e for e in exam_objects if e.semester == stu.current_semester]
            for exam in stu_exams:
                # Simulate student ability (0.4 to 1.0 scale)
                ability = random.uniform(0.4, 1.0)
                noise = random.uniform(-0.1, 0.1)
                raw = min(exam.max_marks, max(0, (ability + noise) * exam.max_marks))
                marks_val = round(raw, 1)

                existing = Mark.query.filter_by(student_id=stu.id, examination_id=exam.id).first()
                if not existing:
                    mark = Mark(
                        student_id=stu.id,
                        subject_id=exam.subject_id,
                        examination_id=exam.id,
                        marks_obtained=marks_val,
                        is_absent=False
                    )
                    db.session.add(mark)

        db.session.commit()

        # Attendance
        print("Creating attendance records...")
        today = date.today()
        start_date = today - timedelta(days=90)

        for stu in it_students[:20]:  # Generate for first 20 IT students
            stu_subjects = [s for s in it_subjects if s.semester == stu.current_semester]
            for subj in stu_subjects:
                curr = start_date
                while curr <= today:
                    if curr.weekday() < 5:  # Weekdays only
                        status = "present" if random.random() > 0.15 else "absent"
                        existing = AttendanceRecord.query.filter_by(
                            student_id=stu.id, subject_id=subj.id, date=curr
                        ).first()
                        if not existing:
                            att = AttendanceRecord(
                                student_id=stu.id,
                                subject_id=subj.id,
                                date=curr,
                                status=status
                            )
                            db.session.add(att)
                    curr += timedelta(days=1)

        db.session.commit()

        # Practice Questions
        print("Creating practice questions...")
        it_fac = Faculty.query.join(User).filter(User.role == "faculty").first()
        for dept_code, qlist in SAMPLE_QUESTIONS.items():
            dept_subjs = subject_objects.get(dept_code, [])
            if not dept_subjs:
                continue
            subj = dept_subjs[0]
            for qd in qlist:
                q = Question(
                    subject_id=subj.id,
                    question_text=qd["q"],
                    option_a=qd["a"], option_b=qd["b"],
                    option_c=qd["c"], option_d=qd["d"],
                    correct_answer=qd["ans"],
                    topic=qd["topic"],
                    difficulty=qd["diff"],
                    question_type="mcq",
                    created_by=it_fac.id if it_fac else None
                )
                db.session.add(q)

        # Student Tasks
        sample_student = it_students[0] if it_students else None
        if sample_student:
            sample_tasks = [
                {"title": "Complete Data Structures assignment", "priority": "high",
                 "due_date": today + timedelta(days=3)},
                {"title": "Revise Operating Systems chapter 3", "priority": "medium",
                 "due_date": today + timedelta(days=7)},
                {"title": "Prepare for IA-3 Mathematics", "priority": "high",
                 "due_date": today + timedelta(days=5)},
            ]
            for td in sample_tasks:
                task = StudentTask(
                    student_id=sample_student.id,
                    title=td["title"],
                    priority=td["priority"],
                    due_date=td["due_date"]
                )
                db.session.add(task)

        # Motivational Quotes
        for qt, auth in MOTIVATIONAL_QUOTES:
            q = MotivationalQuote(quote_text=qt, author=auth)
            db.session.add(q)

        db.session.commit()
        print("\n=== Synthetic data created successfully! ===")
        print("\nDemo Login Credentials:")
        print("Admin:   ADMIN001 / ADMIN001")
        print("Faculty: FACIT01  / FACIT01")
        print("Faculty: FACIT02  / FACIT02")
        print("Faculty: FACCS01  / FACCS01")
        print(f"Student: IT24001A / IT24001A  (Semester 1, Section A)")
        print(f"Student: IT23001A / IT23001A  (Semester 2, Section A)")
        print(f"Student: IT22001A / IT22001A  (Semester 3, Section A)")
        print("(Full list in README.md)")


if __name__ == "__main__":
    create_synthetic_data()
