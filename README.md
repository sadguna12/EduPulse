# 🎓 EduPulse — AI-Powered Student Academic Performance Prediction System

EduPulse is a complete, modern, responsive web application for student academic performance analysis, machine-learning-based performance prediction, and personalized academic recommendations.

Built without external generative AI APIs, EduPulse uses conventional machine learning (Scikit-learn Ridge, Random Forest, and Gradient Boosting regressors), statistical analysis, and rule-based diagnostic algorithms to provide transparent, explainable academic insights.

---

## 🌟 Key Features

### 🏛️ 1. Administrator Portal & Dataset Management Engine
- **Academic Data Management Hub**: Complete multi-category import system supporting:
  1. **Departments & Sections**: Setup or update academic departments and section batches.
  2. **Students**: Import enrollments with automatic department & section binding and user account creation.
  3. **Faculty**: Import faculty profiles, designations, and assign them to specific subjects and sections.
  4. **Subjects & Academics**: Upload curriculum catalogs, semester course definitions, and credit structures.
  5. **Examinations**: Configure internal assessments, midterms, practical labs, and semester examinations.
  6. **Subject-Wise Marks**:
     - **Long Format**: One assessment record per row (`roll_number, subject_code, exam_name, marks_obtained, max_marks`).
     - **Wide Format**: Matrix layout with subjects as columns (`roll_number, exam_name, IT101, IT102, ...`), automatically unpivoted by the engine.
  7. **Attendance Records**:
     - **Session Format**: Individual lecture date and status logs (`roll_number, subject_code, date, status`).
     - **Aggregate Format**: Summary class counts (`roll_number, subject_code, total_classes, attended_classes, attendance_percentage`) without fabricating individual sessions.
- **Department & Academic Scope Controls**: Select target department, academic year, semester, and section to filter or bind imports when files lack department codes.
- **Duplicate Detection & Safe Update Policies**:
  - `Skip Existing`: Preserves existing database records and skips duplicates safely.
  - `Update Permitted Fields`: Safely updates student/faculty personal details without touching academic marks or attendance history.
  - `Flag as Duplicate Error`: Flags existing IDs as row validation errors.
- **File Preview & Validation**: Non-destructive pre-validation of columns, dry-run checks against database constraints, and table preview before committing.
- **Import Audit History & Downloadable Error Logs**: Detailed records of all imports with row-level error reports available for instant CSV download.
- **Automated Model Invalidation & Retraining**: Automatically triggers Scikit-learn model retraining when new marks datasets are committed.
- **Comprehensive Academic Export Center**: Instant export of Students, Faculty, Marks Ledgers, Attendance Registers, and Institutional Analytics in both **CSV** and **Excel (.xlsx)** formats.

### 👨‍🏫 2. Faculty Portal
- **Overview Dashboard**: Course assignment counters, class average statistics, and quick action shortcuts.
- **Student Roster**: Filter students by department, section, and semester with contact and enrollment details.
- **Marks Management**: Create assessment tests (Internal Assessments, Semester Exams, Practical Labs) and record marks per student.
- **Attendance Registry**: Mark session attendance (Present/Absent) with automatic calculation of percentages.
- **Performance Analytics**: Subject-wise grade distributions, class averages, and top-performer rankings.
- **ML Predictions & Risk Detector**: Run predictive algorithms to flag students at risk of backlog or scoring below 40%.
- **Question Bank**: Create and manage multiple-choice practice questions categorized by subject and difficulty.
- **Tasks & Alerts**: Assign targeted homework or revision tasks directly to specific students with due dates and priority tags.
- **Authorized Reports & Exports**: Export authorized marks sheets, student rosters, and attendance logs strictly restricted to the faculty's assigned subjects and sections.

### 🎓 3. Student Portal
- **Personalized Dashboard**: Real-time performance indicators, motivational quotes, upcoming deadlines, and quick subject averages.
- **Academic Performance**: In-depth breakdown of all examination scores with interactive Chart.js visualizations and historical logs.
- **Performance Prediction**: ML-forecasted final semester score, confidence metrics, historical trend curves, and what-if goal simulators.
- **Strengths & Weak Areas**: Algorithmic classification into Critical Subjects (<60%) and Key Strengths (≥75%) with recovery strategies.
- **Attendance Audit**: Subject-by-subject attendance percentages, 75% regulatory compliance indicators, and session logs.
- **Weekly Study Plan**: Priority subject study scheduling based on identified weak areas, plus interactive task checklists.
- **Practice Question Bank**: Interactive MCQs with immediate feedback, answer verification, and attempt counters.
- **Self-Improvement Tracker**: Set custom academic goals with deadlines and progress adjustment sliders.
- **Official Reports**: Download complete student marks transcripts and attendance audit sheets in CSV format.

### 👤 4. Unified Profile & Account Management
- **Universal Topbar Profile Dropdown**: Accessible across all portals with user name, role badge, quick links to View Profile, Edit Profile, Change Password, and Sign Out.
- **Self-Service Personal Editing**: Users can edit permitted personal details (display name, email address, phone) with validation while preserving immutable academic attributes (roles, department assignments, roll numbers, marks).
- **Clean Single Login**: Redesigned modern login interface with institutional ID, password toggle control, and secure credential handling.

---

## 🛠️ Technology Stack

| Layer | Technologies |
|---|---|
| **Frontend** | HTML5, CSS3 (Modern Dark Glassmorphism, CSS Custom Properties), JavaScript (ES6+), Chart.js |
| **Backend** | Python 3.11+, Flask, Flask-SQLAlchemy, Flask-Login, Flask-WTF (CSRF Protection), Werkzeug |
| **Database** | SQLite (Production-ready schema migration path to MySQL/PostgreSQL) |
| **Machine Learning** | Scikit-learn (Ridge Regression, Random Forest, Gradient Boosting), Pandas, NumPy, Joblib |
| **Data Processing & Export** | Pandas, OpenPyXL, CSV, ReportLab |

---

## 📋 Dataset Specifications & Template Reference

EduPulse supports both `.csv` and Excel (`.xlsx`, `.xls`) files. Standard templates can be downloaded directly from the Dataset Management interface:

### 1. Students (`students`)
- **Required**: `roll_number`, `name`
- **Optional**: `email`, `phone`, `department_code`, `section`, `semester`, `gender`
- *Note*: If `department_code` is not in the file, select the Target Department in the UI dropdown.

### 2. Faculty (`faculty`)
- **Required**: `faculty_id`, `name`
- **Optional**: `email`, `phone`, `department_code`, `designation`, `assigned_subjects` (comma-separated codes e.g. `IT101,IT201`), `assigned_sections` (comma-separated section letters e.g. `A,B`)

### 3. Subject-Wise Marks (`marks`)
- **Long Format**: `roll_number`, `subject_code`, `exam_name`, `marks_obtained`, `max_marks`
- **Wide Format**: `roll_number`, `exam_name`, followed by Subject Code columns (e.g., `IT101`, `IT102`, `IT103`)

### 4. Attendance (`attendance`)
- **Session Format**: `roll_number`, `subject_code`, `date` (YYYY-MM-DD), `status` (`present`, `absent`, `late`)
- **Aggregate Format**: `roll_number`, `subject_code`, `total_classes`, `attended_classes`, `attendance_percentage`

### 5. Subjects (`subjects`)
- **Required**: `subject_code`, `subject_name`
- **Optional**: `department_code`, `semester`, `credits`, `subject_type` (`theory`, `lab`)

### 6. Examinations (`examinations`)
- **Required**: `subject_code`, `name`, `max_marks`
- **Optional**: `exam_type` (`internal`, `semester`, `assignment`), `semester`

### 7. Departments & Sections (`departments_sections`)
- **Required**: `department_code`, `department_name`
- **Optional**: `section_name`, `semester`, `description`

---

## 🚀 Getting Started

### 1. Prerequisites
Ensure you have Python 3.10+ installed.

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Seed Database & Train Initial ML Models
Generate realistic synthetic data for departments, courses, students, faculty, examinations, attendance records, questions, and train initial models:
```bash
python seed_data.py
```

### 4. Run the Application
```bash
python app.py
```
Open your browser and navigate to:
```
http://127.0.0.1:5000
```

---

## 🔑 Demo Login Credentials

The database comes pre-seeded with sample users for all roles (passwords match the IDs):

### Administrator
| Role | User ID / Username | Password |
|---|---|---|
| **System Admin** | `ADMIN001` | `ADMIN001` |

### Faculty
| Role | User ID / Username | Password | Department |
|---|---|---|---|
| **Faculty (IT)** | `FACIT01` | `FACIT01` | Information Technology |
| **Faculty (IT)** | `FACIT02` | `FACIT02` | Information Technology |
| **Faculty (CS)** | `FACCS01` | `FACCS01` | Computer Science |

### Students
| Role | Roll Number / ID | Password | Department / Semester |
|---|---|---|---|
| **Student** | `IT24001A` | `IT24001A` | IT, Semester 1, Section A |
| **Student** | `IT23001A` | `IT23001A` | IT, Semester 2, Section A |
| **Student** | `IT22001A` | `IT22001A` | IT, Semester 3, Section A |
