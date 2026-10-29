from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sections = db.relationship('Section', backref='department', lazy=True)
    students = db.relationship('Student', backref='department', lazy=True)
    faculty = db.relationship('Faculty', backref='department', lazy=True)
    subjects = db.relationship('Subject', backref='department', lazy=True)

    def __repr__(self):
        return f'<Department {self.code}>'


class AcademicYear(db.Model):
    __tablename__ = 'academic_years'
    id = db.Column(db.Integer, primary_key=True)
    year_label = db.Column(db.String(20), unique=True, nullable=False)  # e.g. "2024-25"
    is_current = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Section(db.Model):
    __tablename__ = 'sections'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(10), nullable=False)  # e.g. "A", "B"
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    academic_year_id = db.Column(db.Integer, db.ForeignKey('academic_years.id'))
    semester = db.Column(db.Integer, nullable=False)
    max_students = db.Column(db.Integer, default=60)
    is_active = db.Column(db.Boolean, default=True)

    academic_year = db.relationship('AcademicYear', backref='sections')
    students = db.relationship('Student', backref='section', lazy=True)

    def __repr__(self):
        return f'<Section {self.name}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'faculty', 'student'
    is_active = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship('Student', backref='user', uselist=False, lazy=True)
    faculty = db.relationship('Faculty', backref='user', uselist=False, lazy=True)
    admin = db.relationship('Admin', backref='user', uselist=False, lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self.id)


class Admin(db.Model):
    __tablename__ = 'admins'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True)
    phone = db.Column(db.String(20))


class Faculty(db.Model):
    __tablename__ = 'faculty'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    faculty_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    designation = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    subject_assignments = db.relationship('FacultySubjectAssignment', backref='faculty', lazy=True)


class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'))
    academic_year_id = db.Column(db.Integer, db.ForeignKey('academic_years.id'))
    current_semester = db.Column(db.Integer, default=1)
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(10))
    is_active = db.Column(db.Boolean, default=True)
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow)

    academic_year = db.relationship('AcademicYear', backref='students')
    marks = db.relationship('Mark', backref='student', lazy=True)
    attendance_records = db.relationship('AttendanceRecord', backref='student', lazy=True)
    tasks = db.relationship('StudentTask', backref='student', lazy=True)
    goals = db.relationship('StudentGoal', backref='student', lazy=True)
    question_attempts = db.relationship('QuestionAttempt', backref='student', lazy=True)

    def __repr__(self):
        return f'<Student {self.roll_number}>'


class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    credits = db.Column(db.Integer, default=3)
    subject_type = db.Column(db.String(20), default='theory')  # theory, lab, project
    is_active = db.Column(db.Boolean, default=True)

    examinations = db.relationship('Examination', backref='subject', lazy=True)
    marks = db.relationship('Mark', backref='subject', lazy=True)
    attendance_records = db.relationship('AttendanceRecord', backref='subject', lazy=True)
    questions = db.relationship('Question', backref='subject', lazy=True)

    __table_args__ = (db.UniqueConstraint('code', 'department_id', 'semester', name='uq_subject_dept_sem'),)


class FacultySubjectAssignment(db.Model):
    __tablename__ = 'faculty_subject_assignments'
    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'), nullable=False)
    academic_year_id = db.Column(db.Integer, db.ForeignKey('academic_years.id'))
    is_active = db.Column(db.Boolean, default=True)

    subject = db.relationship('Subject', backref='faculty_assignments')
    section = db.relationship('Section', backref='faculty_assignments')
    academic_year = db.relationship('AcademicYear', backref='faculty_assignments')

    __table_args__ = (db.UniqueConstraint('faculty_id', 'subject_id', 'section_id', name='uq_fsa'),)


class Examination(db.Model):
    __tablename__ = 'examinations'
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # e.g. "IA1", "IA2", "Semester Exam"
    exam_type = db.Column(db.String(30), nullable=False)  # 'internal', 'semester', 'assignment'
    max_marks = db.Column(db.Float, nullable=False)
    weightage = db.Column(db.Float, default=1.0)
    exam_date = db.Column(db.Date)
    semester = db.Column(db.Integer)
    academic_year_id = db.Column(db.Integer, db.ForeignKey('academic_years.id'))
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    academic_year = db.relationship('AcademicYear', backref='examinations')
    section = db.relationship('Section', backref='examinations')
    marks = db.relationship('Mark', backref='examination', lazy=True)


class Mark(db.Model):
    __tablename__ = 'marks'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    examination_id = db.Column(db.Integer, db.ForeignKey('examinations.id'), nullable=False)
    marks_obtained = db.Column(db.Float, nullable=False)
    is_absent = db.Column(db.Boolean, default=False)
    recorded_by = db.Column(db.Integer, db.ForeignKey('faculty.id'))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    remarks = db.Column(db.String(200))

    recorder = db.relationship('Faculty', backref='recorded_marks')

    __table_args__ = (db.UniqueConstraint('student_id', 'examination_id', name='uq_mark'),)


class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_records'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(10), nullable=False)  # 'present', 'absent', 'late'
    recorded_by = db.Column(db.Integer, db.ForeignKey('faculty.id'))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)

    recorder = db.relationship('Faculty', backref='recorded_attendance')

    __table_args__ = (db.UniqueConstraint('student_id', 'subject_id', 'date', name='uq_attendance'),)


class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(300))
    option_b = db.Column(db.String(300))
    option_c = db.Column(db.String(300))
    option_d = db.Column(db.String(300))
    correct_answer = db.Column(db.String(1))  # 'A', 'B', 'C', 'D' or for descriptive: None
    explanation = db.Column(db.Text)
    topic = db.Column(db.String(100))
    difficulty = db.Column(db.String(20), default='medium')  # easy, medium, hard
    question_type = db.Column(db.String(20), default='mcq')  # mcq, descriptive
    created_by = db.Column(db.Integer, db.ForeignKey('faculty.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    creator = db.relationship('Faculty', backref='created_questions')
    attempts = db.relationship('QuestionAttempt', backref='question', lazy=True)


class QuestionAttempt(db.Model):
    __tablename__ = 'question_attempts'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    answer_given = db.Column(db.String(300))
    is_correct = db.Column(db.Boolean)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)


class StudentTask(db.Model):
    __tablename__ = 'student_tasks'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'))
    assigned_by = db.Column(db.Integer, db.ForeignKey('faculty.id'))
    due_date = db.Column(db.Date)
    is_completed = db.Column(db.Boolean, default=False)
    priority = db.Column(db.String(10), default='medium')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    subject = db.relationship('Subject', backref='tasks')
    assigner = db.relationship('Faculty', backref='assigned_tasks')


class StudentGoal(db.Model):
    __tablename__ = 'student_goals'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    target_date = db.Column(db.Date)
    progress_percent = db.Column(db.Integer, default=0)
    is_achieved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MotivationalQuote(db.Model):
    __tablename__ = 'motivational_quotes'
    id = db.Column(db.Integer, primary_key=True)
    quote_text = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(100))
    category = db.Column(db.String(50), default='academic')


class MLModelRecord(db.Model):
    __tablename__ = 'ml_model_records'
    id = db.Column(db.Integer, primary_key=True)
    model_name = db.Column(db.String(100))
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'))
    model_path = db.Column(db.String(300))
    training_samples = db.Column(db.Integer)
    r2_score = db.Column(db.Float)
    mae = db.Column(db.Float)
    trained_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    department = db.relationship('Department', backref='ml_models')
    subject = db.relationship('Subject', backref='ml_models')


class ImportHistory(db.Model):
    __tablename__ = 'import_history'
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)  # 'departments', 'students', 'faculty', 'subjects', 'examinations', 'marks', 'attendance'
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    records_imported = db.Column(db.Integer, default=0)
    records_skipped = db.Column(db.Integer, default=0)
    records_failed = db.Column(db.Integer, default=0)
    status = db.Column(db.String(30), default='completed')  # 'completed', 'partial', 'failed'
    error_summary = db.Column(db.Text)  # JSON formatted error details per row
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    department = db.relationship('Department', backref='import_histories')
    user = db.relationship('User', backref='import_histories')


class StudentAggregateAttendance(db.Model):
    __tablename__ = 'student_aggregate_attendance'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    total_classes = db.Column(db.Integer, nullable=False, default=0)
    attended_classes = db.Column(db.Integer, nullable=False, default=0)
    attendance_percentage = db.Column(db.Float, nullable=False, default=0.0)
    academic_year_id = db.Column(db.Integer, db.ForeignKey('academic_years.id'), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student = db.relationship('Student', backref='aggregate_attendances')
    subject = db.relationship('Subject', backref='aggregate_attendances')
    academic_year = db.relationship('AcademicYear', backref='aggregate_attendances')

    __table_args__ = (db.UniqueConstraint('student_id', 'subject_id', name='uq_agg_attendance'),)

