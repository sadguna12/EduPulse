"""
EduPulse Unified Master Excel Importer & Template Generator
Handles single-workbook multi-sheet (.xlsx) uploads for 7 academic categories:
1. Departments
2. Students
3. Faculty
4. Subjects
5. Examinations
6. Marks
7. Attendance
"""
import io
import os
import json
import re
from datetime import datetime, date
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from extensions import db
from models import (
    Department, AcademicYear, Section, User, Faculty, Student,
    Subject, FacultySubjectAssignment, Examination, Mark,
    AttendanceRecord, StudentAggregateAttendance, ImportHistory
)


# Canonical sheet identifiers and aliases
SHEET_ALIASES = {
    'departments': ['departments', 'departments_sections', 'departments & sections', 'dept', 'depts', 'department', 'departments and sections'],
    'students': ['students', 'student details', 'student_data', 'student_records', 'student', 'students_data', 'students details'],
    'faculty': ['faculty', 'faculty details', 'staff', 'teachers', 'teacher_details', 'faculties', 'faculty_members'],
    'subjects': ['subjects', 'subject details', 'courses', 'course_details', 'subject', 'subjects_data'],
    'examinations': ['examinations', 'exams', 'exam details', 'tests', 'assessment_types', 'exam', 'assessments'],
    'marks': ['marks', 'student marks', 'results', 'scores', 'marks_records', 'mark', 'grades'],
    'attendance': ['attendance', 'attendance records', 'attendance_records', 'attendance_logs', 'att', 'attendance_sessions']
}

# Column aliases mapping
COLUMN_ALIASES = {
    'roll_number': ['roll_number', 'student_id', 'roll_no', 'usn', 'reg_no', 'rollno', 'student_roll', 'student_id_number'],
    'full_name': ['full_name', 'name', 'student_name', 'faculty_name', 'staff_name', 'candidate_name'],
    'faculty_id': ['faculty_id', 'staff_id', 'teacher_id', 'fac_id', 'employee_id', 'emp_id'],
    'department_code': ['department_code', 'dept_code', 'department', 'dept', 'branch', 'program'],
    'department_name': ['department_name', 'dept_name', 'name', 'program_name', 'branch_name'],
    'section_name': ['section_name', 'section', 'sec', 'sec_name', 'class_section'],
    'semester': ['semester', 'current_semester', 'sem', 'term'],
    'academic_year': ['academic_year', 'academic_year_label', 'year', 'ay', 'batch', 'session'],
    'subject_code': ['subject_code', 'subject_id', 'course_code', 'sub_code', 'code'],
    'subject_name': ['subject_name', 'course_name', 'sub_name', 'name', 'title'],
    'subject_codes': ['subject_codes', 'assigned_subjects', 'subjects', 'courses', 'taught_subjects'],
    'section_assignments': ['section_assignments', 'assigned_sections', 'sections', 'taught_sections'],
    'exam_id': ['exam_id', 'examination_id', 'exam_code'],
    'exam_name': ['exam_name', 'examination_name', 'examination', 'exam', 'test_name', 'name'],
    'exam_type': ['exam_type', 'type', 'assessment_type'],
    'marks_obtained': ['marks_obtained', 'marks', 'score', 'marks_scored', 'obtained_marks', 'score_obtained'],
    'max_marks': ['max_marks', 'total_marks', 'maximum_marks', 'out_of', 'total'],
    'date': ['date', 'attendance_date', 'session_date', 'day'],
    'status': ['status', 'attendance_status', 'attendance', 'presence'],
    'total_classes': ['total_classes', 'total_sessions', 'classes_held', 'total', 'lectures_held'],
    'attended_classes': ['attended_classes', 'classes_attended', 'attended', 'present_count', 'lectures_attended'],
    'attendance_percentage': ['attendance_percentage', 'percentage', 'attendance_pct', 'pct', 'attendance_rate'],
    'designation': ['designation', 'role', 'post', 'title'],
    'email': ['email', 'email_address', 'mail'],
    'phone': ['phone', 'mobile', 'contact', 'phone_number'],
    'credits': ['credits', 'credit_hours', 'credit'],
    'subject_type': ['subject_type', 'type', 'course_type'],
    'description': ['description', 'desc', 'remarks']
}


def normalize_string(s):
    if not s:
        return ''
    return re.sub(r'[\s_\-]+', '_', str(s).strip().lower())


def match_sheet_name(sheet_name):
    norm = normalize_string(sheet_name)
    for canonical, aliases in SHEET_ALIASES.items():
        for alias in aliases:
            if norm == normalize_string(alias):
                return canonical
    return None


def normalize_columns(df):
    """Normalize and rename dataframe columns using aliases dictionary while ensuring uniqueness."""
    seen = {}
    new_cols = []
    for col in df.columns:
        norm_col = normalize_string(col)
        matched = None
        for canonical, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                if norm_col == normalize_string(alias):
                    matched = canonical
                    break
            if matched:
                break
        final_name = matched if matched else norm_col
        if final_name in seen:
            seen[final_name] += 1
            final_name = f"{final_name}_{seen[final_name]}"
        else:
            seen[final_name] = 1
        new_cols.append(final_name)
    df.columns = new_cols
    return df



def generate_master_workbook_template():
    """
    Generate an official EduPulse Master Excel Template (.xlsx)
    with 7 worksheets, styled headers, and realistic synthetic rows.
    """
    wb = openpyxl.Workbook()
    # Remove default sheet
    default_sheet = wb.active

    # Brand Colors
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Segoe UI", size=10, color="0F172A")
    thin_border = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='E2E8F0')
    )

    sheets_config = [
        {
            'name': 'Departments',
            'headers': ['department_code', 'department_name', 'section_name', 'academic_year', 'semester', 'description'],
            'rows': [
                ['IT', 'Information Technology', 'A', '2024-25', 1, 'Department of Information Technology'],
                ['IT', 'Information Technology', 'B', '2024-25', 1, 'Department of Information Technology'],
                ['CS', 'Computer Science & Engineering', 'A', '2024-25', 1, 'Department of Computer Science & Engineering'],
                ['CS', 'Computer Science & Engineering', 'B', '2024-25', 1, 'Department of Computer Science & Engineering'],
                ['EC', 'Electronics & Communication', 'A', '2024-25', 1, 'Department of Electronics & Communication']
            ]
        },
        {
            'name': 'Students',
            'headers': ['roll_number', 'full_name', 'email', 'department_code', 'section', 'academic_year', 'semester'],
            'rows': [
                ['IT24001A', 'Aarav Sharma', 'aarav.sharma@institution.edu', 'IT', 'A', '2024-25', 1],
                ['IT24002A', 'Priya Patel', 'priya.patel@institution.edu', 'IT', 'A', '2024-25', 1],
                ['IT24003A', 'Rahul Singh', 'rahul.singh@institution.edu', 'IT', 'B', '2024-25', 1],
                ['CS24001A', 'Rohan Gupta', 'rohan.gupta@institution.edu', 'CS', 'A', '2024-25', 1],
                ['CS24002A', 'Ananya Joshi', 'ananya.joshi@institution.edu', 'CS', 'A', '2024-25', 1],
                ['CS24003A', 'Aditya Verma', 'aditya.verma@institution.edu', 'CS', 'B', '2024-25', 1]
            ]
        },
        {
            'name': 'Faculty',
            'headers': ['faculty_id', 'full_name', 'email', 'department_code', 'designation', 'subject_codes', 'section_assignments'],
            'rows': [
                ['FACIT01', 'Dr. Ramesh Kumar', 'ramesh.kumar@institution.edu', 'IT', 'Associate Professor', 'IT101,IT102', 'A,B'],
                ['FACIT02', 'Prof. Sunita Sharma', 'sunita.sharma@institution.edu', 'IT', 'Assistant Professor', 'IT103,IT104', 'A'],
                ['FACCS01', 'Dr. Vijay Patel', 'vijay.patel@institution.edu', 'CS', 'Associate Professor', 'CS101,CS102', 'A,B'],
                ['FACCS02', 'Prof. Anita Joshi', 'anita.joshi@institution.edu', 'CS', 'Assistant Professor', 'CS103', 'A']
            ]
        },
        {
            'name': 'Subjects',
            'headers': ['subject_code', 'subject_name', 'department_code', 'semester', 'academic_year', 'section', 'faculty_id', 'max_marks'],
            'rows': [
                ['IT101', 'Programming in C', 'IT', 1, '2024-25', 'A', 'FACIT01', 100],
                ['IT102', 'Mathematics I', 'IT', 1, '2024-25', 'A', 'FACIT01', 100],
                ['IT103', 'Digital Logic Design', 'IT', 1, '2024-25', 'A', 'FACIT02', 100],
                ['CS101', 'Introduction to Computing', 'CS', 1, '2024-25', 'A', 'FACCS01', 100],
                ['CS102', 'Discrete Mathematics', 'CS', 1, '2024-25', 'A', 'FACCS01', 100],
                ['CS103', 'Programming Fundamentals', 'CS', 1, '2024-25', 'A', 'FACCS02', 100]
            ]
        },
        {
            'name': 'Examinations',
            'headers': ['exam_id', 'exam_name', 'department_code', 'semester', 'academic_year', 'exam_type'],
            'rows': [
                ['IA1', 'Internal Assessment 1', 'IT', 1, '2024-25', 'internal'],
                ['IA2', 'Internal Assessment 2', 'IT', 1, '2024-25', 'internal'],
                ['SEM1', 'Semester Final Exam', 'IT', 1, '2024-25', 'semester'],
                ['IA1', 'Internal Assessment 1', 'CS', 1, '2024-25', 'internal'],
                ['IA2', 'Internal Assessment 2', 'CS', 1, '2024-25', 'internal'],
                ['SEM1', 'Semester Final Exam', 'CS', 1, '2024-25', 'semester']
            ]
        },
        {
            'name': 'Marks',
            'headers': ['roll_number', 'subject_code', 'exam_id', 'marks_obtained', 'max_marks'],
            'rows': [
                ['IT24001A', 'IT101', 'IA1', 42.5, 50],
                ['IT24001A', 'IT102', 'IA1', 38.0, 50],
                ['IT24002A', 'IT101', 'IA1', 45.0, 50],
                ['IT24002A', 'IT102', 'IA1', 41.5, 50],
                ['CS24001A', 'CS101', 'IA1', 44.0, 50],
                ['CS24002A', 'CS101', 'IA1', 46.5, 50]
            ]
        },
        {
            'name': 'Attendance',
            'headers': ['roll_number', 'subject_code', 'date', 'status'],
            'rows': [
                ['IT24001A', 'IT101', '2024-09-02', 'present'],
                ['IT24001A', 'IT101', '2024-09-03', 'present'],
                ['IT24002A', 'IT101', '2024-09-02', 'absent'],
                ['CS24001A', 'CS101', '2024-09-02', 'present'],
                ['CS24002A', 'CS101', '2024-09-02', 'present']
            ]
        }
    ]

    for config in sheets_config:
        ws = wb.create_sheet(title=config['name'])
        ws.append(config['headers'])
        for row in config['rows']:
            ws.append(row)

        # Style header row
        for col_idx, header in enumerate(config['headers'], 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border
            ws.row_dimensions[1].height = 28

        # Style data rows and adjust column widths
        for row_idx in range(2, len(config['rows']) + 2):
            ws.row_dimensions[row_idx].height = 20
            for col_idx in range(1, len(config['headers']) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = data_font
                cell.border = thin_border
                cell.alignment = Alignment(vertical="center")

        for col_idx, header in enumerate(config['headers'], 1):
            col_letter = get_column_letter(col_idx)
            max_len = max(len(str(header)), max([len(str(r[col_idx - 1])) for r in config['rows']] or [0]))
            ws.column_dimensions[col_letter].width = max(max_len + 4, 14)

    # Instructions sheet
    instructions_ws = wb.create_sheet(title='Instructions', index=0)
    instructions_ws.column_dimensions['A'].width = 6
    instructions_ws.column_dimensions['B'].width = 30
    instructions_ws.column_dimensions['C'].width = 70

    instructions_ws.cell(row=2, column=2, value="EduPulse Master Excel Dataset Import Guide").font = Font(name="Segoe UI", size=14, bold=True, color="1E3A8A")
    instructions = [
        ("Step 1: Department & Sections", "Define your departments and sections in the 'Departments' sheet first. Each department code must be unique."),
        ("Step 2: Students & Faculty", "Add enrolled students and teaching faculty. Default initial password for new accounts is their ID (Roll Number / Faculty ID)."),
        ("Step 3: Subjects", "Define subjects for each department and semester. Optionally link faculty assignments via faculty_id or the Faculty sheet."),
        ("Step 4: Examinations", "Create assessment titles (e.g. IA1, IA2, Semester Exam). exam_type must be 'internal', 'semester', or 'assignment'."),
        ("Step 5: Marks Records", "Enter student marks per exam. Marks must be numeric, >= 0 and <= max_marks."),
        ("Step 6: Attendance Logs", "Enter daily session attendance ('present', 'absent', 'late') OR aggregate attendance (total_classes, attended_classes)."),
        ("Validation Safety", "The import engine verifies all cross-sheet foreign keys. If dependencies are missing, detailed row logs will guide corrections.")
    ]
    for idx, (title, desc) in enumerate(instructions, 4):
        c_title = instructions_ws.cell(row=idx, column=2, value=title)
        c_title.font = Font(name="Segoe UI", size=10, bold=True, color="0F172A")
        c_desc = instructions_ws.cell(row=idx, column=3, value=desc)
        c_desc.font = Font(name="Segoe UI", size=10, color="334155")
        instructions_ws.row_dimensions[idx].height = 22

    wb.remove(default_sheet)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def inspect_master_workbook(file_or_path):
    """
    Reads an uploaded .xlsx workbook, detects the 7 worksheets,
    normalizes columns, and performs thorough cross-sheet dependency validation.
    Returns:
        dict: {
            'detected_sheets': dict of canonical -> sheet_name,
            'missing_sheets': list of canonical names not found,
            'sheet_data': dict of canonical -> normalized DataFrame,
            'summary': dict of statistics,
            'validation_issues': list of error/warning strings,
            'missing_dependencies': list of dependency warnings,
            'samples': dict of canonical -> list of dict rows (top 5-10)
        }
    """
    xl = pd.ExcelFile(file_or_path, engine='openpyxl')
    sheet_names = xl.sheet_names

    detected_sheets = {}
    for name in sheet_names:
        matched = match_sheet_name(name)
        if matched and matched not in detected_sheets:
            detected_sheets[matched] = name

    canonical_all = ['departments', 'students', 'faculty', 'subjects', 'examinations', 'marks', 'attendance']
    missing_sheets = [s for s in canonical_all if s not in detected_sheets]

    sheet_dfs = {}
    samples = {}
    row_counts = {}

    for canonical, real_name in detected_sheets.items():
        try:
            df = xl.parse(real_name)
            df = df.dropna(how='all')
            df = normalize_columns(df)
            sheet_dfs[canonical] = df
            row_counts[canonical] = len(df)
            samples[canonical] = df.head(10).fillna('').to_dict('records')
        except Exception as e:
            sheet_dfs[canonical] = pd.DataFrame()
            row_counts[canonical] = 0
            samples[canonical] = []

    # Cross-sheet validation
    validation_issues = []
    missing_dependencies = []

    # 1. Existing DB entities
    with db.session.no_autoflush:
        db_depts = {d.code.upper(): d for d in Department.query.all()}
        db_students = {s.roll_number.upper(): s for s in Student.query.all()}
        db_faculty = {f.faculty_id.upper(): f for f in Faculty.query.all()}
        db_subjects = {s.code.upper(): s for s in Subject.query.all()}
        db_exams = {e.name.upper(): e for e in Examination.query.all()}

    # 2. In-file departments
    file_dept_codes = set()
    if 'departments' in sheet_dfs and not sheet_dfs['departments'].empty:
        df_dept = sheet_dfs['departments']
        for idx, row in df_dept.iterrows():
            code = str(row.get('department_code', '')).strip().upper()
            if code:
                file_dept_codes.add(code)
            else:
                validation_issues.append(f"Departments sheet (Row {idx+2}): Missing department_code.")

    all_dept_codes = file_dept_codes.union(set(db_depts.keys()))

    # Check for referenced departments across all sheets
    referenced_depts = set()
    for s_name in ['students', 'faculty', 'subjects', 'examinations']:
        if s_name in sheet_dfs and not sheet_dfs[s_name].empty:
            for _, r in sheet_dfs[s_name].iterrows():
                d = str(r.get('department_code', '')).strip().upper()
                if d and d not in ('', 'NAN', 'NONE'):
                    referenced_depts.add(d)

    if file_dept_codes:
        for d in sorted(referenced_depts):
            if d not in file_dept_codes:
                if d in db_depts:
                    missing_dependencies.append(f"Department '{d}' is referenced in workbook sheets but missing from the Departments worksheet (will link to existing database department '{d}').")
                else:
                    missing_dependencies.append(f"Department '{d}' is referenced in workbook sheets but NOT defined in Departments worksheet or database. Please define '{d}' in Departments sheet.")
    else:
        for d in sorted(referenced_depts):
            if d not in db_depts:
                missing_dependencies.append(f"Department '{d}' is referenced in workbook sheets but does not exist in the database. Please add a Departments sheet defining '{d}'.")

    # 3. Students
    file_student_rolls = set()
    if 'students' in sheet_dfs and not sheet_dfs['students'].empty:
        df_stu = sheet_dfs['students']
        for idx, row in df_stu.iterrows():
            roll = str(row.get('roll_number', '')).strip().upper()
            name = str(row.get('full_name', '')).strip()
            dept_c = str(row.get('department_code', '')).strip().upper()
            if not roll:
                validation_issues.append(f"Students sheet (Row {idx+2}): Missing roll_number.")
            else:
                file_student_rolls.add(roll)
            if not name:
                validation_issues.append(f"Students sheet (Row {idx+2}): Missing full_name for student '{roll}'.")
            if dept_c and dept_c not in all_dept_codes:
                missing_dependencies.append(f"Students sheet (Row {idx+2}): Student '{roll}' references undefined department '{dept_c}'.")

    all_student_rolls = file_student_rolls.union(set(db_students.keys()))

    # 4. Faculty
    file_faculty_ids = set()
    if 'faculty' in sheet_dfs and not sheet_dfs['faculty'].empty:
        df_fac = sheet_dfs['faculty']
        for idx, row in df_fac.iterrows():
            fac_id = str(row.get('faculty_id', '')).strip().upper()
            name = str(row.get('full_name', '')).strip()
            dept_c = str(row.get('department_code', '')).strip().upper()
            if not fac_id:
                validation_issues.append(f"Faculty sheet (Row {idx+2}): Missing faculty_id.")
            else:
                file_faculty_ids.add(fac_id)
            if not name:
                validation_issues.append(f"Faculty sheet (Row {idx+2}): Missing full_name for faculty '{fac_id}'.")
            if dept_c and dept_c not in all_dept_codes:
                missing_dependencies.append(f"Faculty sheet (Row {idx+2}): Faculty '{fac_id}' references undefined department '{dept_c}'.")

    # 5. Subjects
    file_subject_codes = set()
    if 'subjects' in sheet_dfs and not sheet_dfs['subjects'].empty:
        df_sub = sheet_dfs['subjects']
        for idx, row in df_sub.iterrows():
            sub_c = str(row.get('subject_code', '')).strip().upper()
            sub_n = str(row.get('subject_name', '')).strip()
            dept_c = str(row.get('department_code', '')).strip().upper()
            if not sub_c:
                validation_issues.append(f"Subjects sheet (Row {idx+2}): Missing subject_code.")
            else:
                file_subject_codes.add(sub_c)
            if not sub_n:
                validation_issues.append(f"Subjects sheet (Row {idx+2}): Missing subject_name for '{sub_c}'.")
            if dept_c and dept_c not in all_dept_codes:
                missing_dependencies.append(f"Subjects sheet (Row {idx+2}): Subject '{sub_c}' references undefined department '{dept_c}'.")

    all_subject_codes = file_subject_codes.union(set(db_subjects.keys()))

    # 6. Examinations
    file_exam_ids = set()
    if 'examinations' in sheet_dfs and not sheet_dfs['examinations'].empty:
        df_exam = sheet_dfs['examinations']
        for idx, row in df_exam.iterrows():
            eid = str(row.get('exam_id', row.get('exam_name', ''))).strip()
            if not eid:
                validation_issues.append(f"Examinations sheet (Row {idx+2}): Missing exam_id or exam_name.")
            else:
                file_exam_ids.add(eid.upper())

    # 7. Marks
    if 'marks' in sheet_dfs and not sheet_dfs['marks'].empty:
        df_marks = sheet_dfs['marks']
        is_long = 'subject_code' in df_marks.columns
        if is_long:
            for idx, row in df_marks.iterrows():
                roll = str(row.get('roll_number', '')).strip().upper()
                sub_c = str(row.get('subject_code', '')).strip().upper()
                marks_val = row.get('marks_obtained')
                max_val = row.get('max_marks', 100)

                if roll and roll not in all_student_rolls:
                    missing_dependencies.append(f"Marks sheet (Row {idx+2}): Student '{roll}' not found in Students sheet or database.")
                if sub_c and sub_c not in all_subject_codes:
                    missing_dependencies.append(f"Marks sheet (Row {idx+2}): Subject '{sub_c}' not found in Subjects sheet or database.")

                if pd.notna(marks_val):
                    try:
                        m_f = float(marks_val)
                        if m_f < 0:
                            validation_issues.append(f"Marks sheet (Row {idx+2}): Marks obtained ({m_f}) cannot be negative.")
                        if pd.notna(max_val):
                            try:
                                mx_f = float(max_val)
                                if m_f > mx_f:
                                    validation_issues.append(f"Marks sheet (Row {idx+2}): Marks ({m_f}) exceeds max marks ({mx_f}).")
                            except ValueError:
                                pass
                    except ValueError:
                        validation_issues.append(f"Marks sheet (Row {idx+2}): Non-numeric mark value '{marks_val}'.")

    # 8. Attendance
    if 'attendance' in sheet_dfs and not sheet_dfs['attendance'].empty:
        df_att = sheet_dfs['attendance']
        for idx, row in df_att.iterrows():
            roll = str(row.get('roll_number', '')).strip().upper()
            sub_c = str(row.get('subject_code', '')).strip().upper()

            if roll and roll not in all_student_rolls:
                missing_dependencies.append(f"Attendance sheet (Row {idx+2}): Student '{roll}' not found in Students sheet or database.")
            if sub_c and sub_c not in all_subject_codes:
                missing_dependencies.append(f"Attendance sheet (Row {idx+2}): Subject '{sub_c}' not found in Subjects sheet or database.")

            # Validate date or counts
            if 'date' in df_att.columns:
                date_str = str(row.get('date', '')).strip()
                if date_str:
                    try:
                        datetime.strptime(date_str, '%Y-%m-%d')
                    except ValueError:
                        validation_issues.append(f"Attendance sheet (Row {idx+2}): Invalid date format '{date_str}' (expected YYYY-MM-DD).")
            if 'total_classes' in df_att.columns and 'attended_classes' in df_att.columns:
                try:
                    tc = int(row.get('total_classes', 0))
                    ac = int(row.get('attended_classes', 0))
                    if ac > tc:
                        validation_issues.append(f"Attendance sheet (Row {idx+2}): Attended classes ({ac}) exceeds total classes ({tc}).")
                except (ValueError, TypeError):
                    validation_issues.append(f"Attendance sheet (Row {idx+2}): Total and attended classes must be integers.")

    # Deduplicate issues
    validation_issues = list(dict.fromkeys(validation_issues))
    missing_dependencies = list(dict.fromkeys(missing_dependencies))

    summary = {
        'total_sheets_detected': len(detected_sheets),
        'detected_sheet_names': detected_sheets,
        'missing_sheets': missing_sheets,
        'row_counts': row_counts,
        'total_rows': sum(row_counts.values()),
        'detected_departments': sorted(list(file_dept_codes)),
        'detected_students_count': len(file_student_rolls),
        'detected_faculty_count': len(file_faculty_ids),
        'detected_subjects_count': len(file_subject_codes),
        'validation_issues_count': len(validation_issues),
        'missing_dependencies_count': len(missing_dependencies),
        'can_import': len([issue for issue in validation_issues if 'Missing required' in issue or 'Non-numeric' in issue]) == 0
    }

    return {
        'detected_sheets': detected_sheets,
        'missing_sheets': missing_sheets,
        'sheet_data': sheet_dfs,
        'summary': summary,
        'validation_issues': validation_issues,
        'missing_dependencies': missing_dependencies,
        'samples': samples
    }


def execute_master_workbook_import(file_or_path, dup_policy='skip', user_id=None, filename='EduPulse_Dataset.xlsx'):
    """
    Executes atomic, dependency-ordered import of all sheets in master workbook:
    1. Departments & Sections
    2. Students & Faculty (with User account creation and secure password hashing)
    3. Subjects & Faculty Assignments
    4. Examinations
    5. Marks
    6. Attendance (session or aggregate)
    """
    # Clear any previous lingering read transaction or uncommitted state
    try:
        db.session.rollback()
    except Exception:
        pass

    inspection = inspect_master_workbook(file_or_path)
    sheet_dfs = inspection['sheet_data']

    imported_counts = {cat: 0 for cat in ['departments', 'students', 'faculty', 'subjects', 'examinations', 'marks', 'attendance']}
    skipped_counts = {cat: 0 for cat in ['departments', 'students', 'faculty', 'subjects', 'examinations', 'marks', 'attendance']}
    failed_counts = {cat: 0 for cat in ['departments', 'students', 'faculty', 'subjects', 'examinations', 'marks', 'attendance']}
    row_errors = []

    # In-memory entity caches to avoid redundant queries and eliminate autoflush locks
    dept_cache = {}
    section_cache = {}

    def get_dept(code_str):
        c = str(code_str).strip().upper()
        if not c:
            return None
        if c in dept_cache:
            return dept_cache[c]
        with db.session.no_autoflush:
            d = Department.query.filter_by(code=c).first()
        if d:
            dept_cache[c] = d
        return d

    def get_or_create_sec(department_id, s_name, s_sem):
        s_name = str(s_name).strip().upper()
        key = (department_id, s_name, s_sem)
        if key in section_cache:
            return section_cache[key]
        with db.session.no_autoflush:
            sec_obj = Section.query.filter_by(department_id=department_id, name=s_name, semester=s_sem).first()
        if not sec_obj:
            sec_obj = Section(department_id=department_id, name=s_name, semester=s_sem)
            db.session.add(sec_obj)
            db.session.flush()
        section_cache[key] = sec_obj
        return sec_obj

    try:
        # ==========================================================
        # STEP 1: Departments and Sections
        # ==========================================================
        if 'departments' in sheet_dfs and not sheet_dfs['departments'].empty:
            for idx, row in sheet_dfs['departments'].iterrows():
                row_num = idx + 2
                code = str(row.get('department_code', '')).strip().upper()
                name = str(row.get('department_name', '')).strip()

                if not code or not name:
                    row_errors.append(f"Departments (Row {row_num}): Department code and name are required.")
                    failed_counts['departments'] += 1
                    continue

                dept = get_dept(code)
                if dept:
                    if dup_policy == 'error':
                        row_errors.append(f"Departments (Row {row_num}): Department '{code}' already exists.")
                        failed_counts['departments'] += 1
                        continue
                    elif dup_policy == 'update':
                        dept.name = name
                        if pd.notna(row.get('description')):
                            dept.description = str(row.get('description')).strip()
                        imported_counts['departments'] += 1
                    else:
                        skipped_counts['departments'] += 1
                else:
                    desc = str(row.get('description', '')).strip() if pd.notna(row.get('description')) else ''
                    dept = Department(code=code, name=name, description=desc)
                    db.session.add(dept)
                    db.session.flush()
                    dept_cache[code] = dept
                    imported_counts['departments'] += 1

                # Section handling
                sec_name = str(row.get('section_name', 'A')).strip().upper() if pd.notna(row.get('section_name')) else 'A'
                sem = int(row.get('semester', 1)) if pd.notna(row.get('semester')) and str(row.get('semester')).isdigit() else 1
                if dept and sec_name:
                    get_or_create_sec(dept.id, sec_name, sem)

        db.session.flush()

        # ==========================================================
        # STEP 2: Students & Faculty
        # ==========================================================
        # 2A: Students
        if 'students' in sheet_dfs and not sheet_dfs['students'].empty:
            for idx, row in sheet_dfs['students'].iterrows():
                row_num = idx + 2
                roll = str(row.get('roll_number', '')).strip().upper()
                name = str(row.get('full_name', '')).strip()
                dept_c = str(row.get('department_code', '')).strip().upper()

                if not roll or not name:
                    row_errors.append(f"Students (Row {row_num}): roll_number and full_name are required.")
                    failed_counts['students'] += 1
                    continue

                dept = get_dept(dept_c)
                if not dept:
                    row_errors.append(f"Students (Row {row_num}): Student '{roll}' references undefined department '{dept_c}'. Record skipped.")
                    failed_counts['students'] += 1
                    continue

                sec_name = str(row.get('section_name', 'A')).strip().upper() if pd.notna(row.get('section_name')) else 'A'
                sem = int(row.get('semester', 1)) if pd.notna(row.get('semester')) and str(row.get('semester')).isdigit() else 1

                sec = get_or_create_sec(dept.id, sec_name, sem)

                email = str(row.get('email', '')).strip() if pd.notna(row.get('email')) else None
                phone = str(row.get('phone', '')).strip() if pd.notna(row.get('phone')) else None

                with db.session.no_autoflush:
                    existing_stu = Student.query.filter_by(roll_number=roll).first()
                    existing_usr = User.query.filter_by(unique_id=roll).first()

                if existing_stu or existing_usr:
                    if dup_policy == 'error':
                        row_errors.append(f"Students (Row {row_num}): Student roll '{roll}' already exists.")
                        failed_counts['students'] += 1
                        continue
                    elif dup_policy == 'update' and existing_stu:
                        existing_stu.name = name
                        if email: existing_stu.email = email
                        if phone: existing_stu.phone = phone
                        existing_stu.current_semester = sem
                        existing_stu.section_id = sec.id
                        imported_counts['students'] += 1
                    else:
                        skipped_counts['students'] += 1
                else:
                    user = User(unique_id=roll, role='student')
                    user.set_password(roll)
                    db.session.add(user)
                    db.session.flush()

                    stu = Student(
                        user_id=user.id,
                        roll_number=roll,
                        name=name,
                        email=email,
                        phone=phone,
                        department_id=dept.id,
                        section_id=sec.id,
                        current_semester=sem
                    )
                    db.session.add(stu)
                    db.session.flush()
                    imported_counts['students'] += 1

        # 2B: Faculty
        if 'faculty' in sheet_dfs and not sheet_dfs['faculty'].empty:
            for idx, row in sheet_dfs['faculty'].iterrows():
                row_num = idx + 2
                fac_id = str(row.get('faculty_id', '')).strip().upper()
                name = str(row.get('full_name', '')).strip()
                dept_c = str(row.get('department_code', '')).strip().upper()

                if not fac_id or not name:
                    row_errors.append(f"Faculty (Row {row_num}): faculty_id and full_name are required.")
                    failed_counts['faculty'] += 1
                    continue

                dept = get_dept(dept_c)
                if not dept:
                    row_errors.append(f"Faculty (Row {row_num}): Faculty '{fac_id}' references undefined department '{dept_c}'. Record skipped.")
                    failed_counts['faculty'] += 1
                    continue

                email = str(row.get('email', '')).strip() if pd.notna(row.get('email')) else None
                phone = str(row.get('phone', '')).strip() if pd.notna(row.get('phone')) else None
                designation = str(row.get('designation', 'Assistant Professor')).strip() if pd.notna(row.get('designation')) else 'Assistant Professor'

                with db.session.no_autoflush:
                    existing_fac = Faculty.query.filter_by(faculty_id=fac_id).first()
                    existing_usr = User.query.filter_by(unique_id=fac_id).first()
                fac_obj = None

                if existing_fac or existing_usr:
                    if dup_policy == 'error':
                        row_errors.append(f"Faculty (Row {row_num}): Faculty ID '{fac_id}' already exists.")
                        failed_counts['faculty'] += 1
                        continue
                    elif dup_policy == 'update' and existing_fac:
                        existing_fac.name = name
                        if email: existing_fac.email = email
                        if phone: existing_fac.phone = phone
                        existing_fac.designation = designation
                        fac_obj = existing_fac
                        imported_counts['faculty'] += 1
                    else:
                        fac_obj = existing_fac
                        skipped_counts['faculty'] += 1
                else:
                    user = User(unique_id=fac_id, role='faculty')
                    user.set_password(fac_id)
                    db.session.add(user)
                    db.session.flush()

                    fac_obj = Faculty(
                        user_id=user.id,
                        faculty_id=fac_id,
                        name=name,
                        email=email,
                        phone=phone,
                        department_id=dept.id,
                        designation=designation
                    )
                    db.session.add(fac_obj)
                    db.session.flush()
                    imported_counts['faculty'] += 1

                # Faculty assignments from Faculty sheet
                subs_raw = str(row.get('subject_codes', '')).strip() if pd.notna(row.get('subject_codes')) else ''
                secs_raw = str(row.get('section_assignments', 'A')).strip() if pd.notna(row.get('section_assignments')) else 'A'
                if fac_obj and subs_raw:
                    sub_list = [s.strip().upper() for s in subs_raw.split(',') if s.strip()]
                    sec_list = [s.strip().upper() for s in secs_raw.split(',') if s.strip()] or ['A']
                    for sc in sub_list:
                        with db.session.no_autoflush:
                            s_obj = Subject.query.filter_by(code=sc, department_id=dept.id).first()
                        if s_obj:
                            for sn in sec_list:
                                sec_obj = get_or_create_sec(dept.id, sn, s_obj.semester)
                                with db.session.no_autoflush:
                                    fsa = FacultySubjectAssignment.query.filter_by(
                                        faculty_id=fac_obj.id, subject_id=s_obj.id, section_id=sec_obj.id
                                    ).first()
                                if not fsa:
                                    db.session.add(FacultySubjectAssignment(
                                        faculty_id=fac_obj.id, subject_id=s_obj.id, section_id=sec_obj.id
                                    ))

        db.session.flush()

        # ==========================================================
        # STEP 3: Subjects & Additional Faculty Assignments
        # ==========================================================
        if 'subjects' in sheet_dfs and not sheet_dfs['subjects'].empty:
            for idx, row in sheet_dfs['subjects'].iterrows():
                row_num = idx + 2
                code = str(row.get('subject_code', '')).strip().upper()
                name = str(row.get('subject_name', '')).strip()
                dept_c = str(row.get('department_code', '')).strip().upper()

                if not code or not name:
                    row_errors.append(f"Subjects (Row {row_num}): subject_code and subject_name are required.")
                    failed_counts['subjects'] += 1
                    continue

                dept = get_dept(dept_c)
                if not dept:
                    row_errors.append(f"Subjects (Row {row_num}): Subject '{code}' references undefined department '{dept_c}'. Record skipped.")
                    failed_counts['subjects'] += 1
                    continue

                sem = int(row.get('semester', 1)) if pd.notna(row.get('semester')) and str(row.get('semester')).isdigit() else 1
                credits = int(row.get('credits', 3)) if pd.notna(row.get('credits')) and str(row.get('credits')).isdigit() else 3
                sub_type = str(row.get('subject_type', 'theory')).strip().lower() if pd.notna(row.get('subject_type')) else 'theory'

                with db.session.no_autoflush:
                    existing_sub = Subject.query.filter_by(code=code, department_id=dept.id, semester=sem).first()
                sub_obj = None

                if existing_sub:
                    if dup_policy == 'error':
                        row_errors.append(f"Subjects (Row {row_num}): Subject '{code}' already exists in sem {sem}.")
                        failed_counts['subjects'] += 1
                        continue
                    elif dup_policy == 'update':
                        existing_sub.name = name
                        existing_sub.credits = credits
                        existing_sub.subject_type = sub_type
                        sub_obj = existing_sub
                        imported_counts['subjects'] += 1
                    else:
                        sub_obj = existing_sub
                        skipped_counts['subjects'] += 1
                else:
                    sub_obj = Subject(
                        code=code, name=name, department_id=dept.id,
                        semester=sem, credits=credits, subject_type=sub_type
                    )
                    db.session.add(sub_obj)
                    db.session.flush()
                    imported_counts['subjects'] += 1

                # If faculty_id specified in Subjects sheet
                fac_ref = str(row.get('faculty_id', '')).strip().upper() if pd.notna(row.get('faculty_id')) else ''
                sec_ref = str(row.get('section_name', 'A')).strip().upper() if pd.notna(row.get('section_name')) else 'A'
                if sub_obj and fac_ref:
                    with db.session.no_autoflush:
                        f_obj = Faculty.query.filter_by(faculty_id=fac_ref).first()
                    if f_obj:
                        sec_obj = get_or_create_sec(dept.id, sec_ref, sem)
                        with db.session.no_autoflush:
                            fsa = FacultySubjectAssignment.query.filter_by(
                                faculty_id=f_obj.id, subject_id=sub_obj.id, section_id=sec_obj.id
                            ).first()
                        if not fsa:
                            db.session.add(FacultySubjectAssignment(
                                faculty_id=f_obj.id, subject_id=sub_obj.id, section_id=sec_obj.id
                            ))

        db.session.flush()

        # ==========================================================
        # STEP 4: Examinations
        # ==========================================================
        if 'examinations' in sheet_dfs and not sheet_dfs['examinations'].empty:
            for idx, row in sheet_dfs['examinations'].iterrows():
                row_num = idx + 2
                exam_name = str(row.get('exam_id', '')).strip() if (pd.notna(row.get('exam_id')) and str(row.get('exam_id')).strip() != '') else str(row.get('exam_name', '')).strip()
                dept_c = str(row.get('department_code', '')).strip().upper()
                sem = int(row.get('semester', 1)) if pd.notna(row.get('semester')) and str(row.get('semester')).isdigit() else 1
                exam_type = str(row.get('exam_type', 'internal')).strip().lower() if pd.notna(row.get('exam_type')) else 'internal'

                # Determine max_marks based on explicit value or academic defaults (Semester: 100, IA: 50, Assignment: 25)
                if pd.notna(row.get('max_marks')) and str(row.get('max_marks')).strip() != '':
                    try:
                        max_marks = float(row.get('max_marks'))
                    except (ValueError, TypeError):
                        max_marks = 100.0 if (exam_type == 'semester' or 'SEM' in exam_name.upper()) else 50.0
                else:
                    if exam_type == 'semester' or 'SEM' in exam_name.upper():
                        max_marks = 100.0
                    elif exam_type == 'assignment' or 'ASSIGN' in exam_name.upper():
                        max_marks = 25.0
                    else:
                        max_marks = 50.0

                if not exam_name:
                    err_msg = f"Examinations (Row {row_num}): Examination name is required."
                    row_errors.append({'worksheet': 'Examinations', 'row_number': row_num, 'identifier': dept_c, 'rejected_value': 'N/A', 'reason': err_msg, 'message': err_msg})
                    failed_counts['examinations'] += 1
                    continue

                # Subjects to bind this examination to:
                dept = get_dept(dept_c) if dept_c else None
                sub_code = str(row.get('subject_code', '')).strip().upper() if pd.notna(row.get('subject_code')) else ''

                target_subjects = []
                with db.session.no_autoflush:
                    if sub_code:
                        s_query = Subject.query.filter_by(code=sub_code)
                        if dept: s_query = s_query.filter_by(department_id=dept.id)
                        sub = s_query.first()
                        if sub: target_subjects.append(sub)
                    elif dept:
                        target_subjects = Subject.query.filter_by(department_id=dept.id, semester=sem).all()
                    else:
                        target_subjects = Subject.query.filter_by(semester=sem).all()

                if not target_subjects:
                    err_msg = f"Examinations (Row {row_num}): No applicable subjects found for exam '{exam_name}' (Dept: {dept_c}, Sem: {sem})."
                    row_errors.append({'worksheet': 'Examinations', 'row_number': row_num, 'identifier': f"{dept_c}-Sem{sem}", 'rejected_value': exam_name, 'reason': err_msg, 'message': err_msg})
                    failed_counts['examinations'] += 1
                    continue

                for sub in target_subjects:
                    with db.session.no_autoflush:
                        existing_exam = Examination.query.filter_by(subject_id=sub.id, name=exam_name, semester=sem).first()
                        if not existing_exam and row.get('exam_id'):
                            existing_exam = Examination.query.filter_by(subject_id=sub.id, name=str(row.get('exam_id')).strip(), semester=sem).first()

                    if existing_exam:
                        # Reconcile semester exam max_marks if it was previously set to 50
                        if dup_policy == 'update' or (existing_exam.max_marks == 50.0 and max_marks == 100.0 and existing_exam.exam_type == 'semester'):
                            existing_exam.max_marks = max_marks
                            existing_exam.exam_type = exam_type
                            imported_counts['examinations'] += 1
                        else:
                            skipped_counts['examinations'] += 1
                    else:
                        exam = Examination(
                            subject_id=sub.id,
                            name=exam_name,
                            exam_type=exam_type,
                            max_marks=max_marks,
                            semester=sem
                        )
                        db.session.add(exam)
                        imported_counts['examinations'] += 1

        db.session.flush()

        # ==========================================================
        # STEP 5: Marks
        # ==========================================================
        if 'marks' in sheet_dfs and not sheet_dfs['marks'].empty:
            df_m = sheet_dfs['marks']
            is_long = ('subject_code' in df_m.columns or 'subject_name' in df_m.columns) and ('marks_obtained' in df_m.columns or 'score' in df_m.columns)

            records = []
            if is_long:
                for idx, row in df_m.iterrows():
                    records.append((
                        idx + 2,
                        str(row.get('roll_number', '')).strip().upper(),
                        str(row.get('subject_code', '')).strip().upper(),
                        str(row.get('exam_id', row.get('exam_name', 'IA1'))).strip(),
                        row.get('marks_obtained'),
                        row.get('max_marks')
                    ))
            else:
                # Wide format unpivot
                fixed_cols = {'roll_number', 'student_id', 'exam_name', 'exam_id', 'exam_type', 'semester'}
                sub_cols = [c for c in df_m.columns if c not in fixed_cols]
                for idx, row in df_m.iterrows():
                    roll = str(row.get('roll_number', '')).strip().upper()
                    exam_ref = str(row.get('exam_name', row.get('exam_id', 'IA1'))).strip()
                    for sc in sub_cols:
                        val = row.get(sc)
                        if pd.notna(val) and str(val).strip() != '':
                            records.append((idx + 2, roll, sc.upper(), exam_ref, val, None))

            # Query caches to accelerate lookups and prevent SQLite lock contention
            student_cache = {}
            sub_cache = {}
            exam_cache = {}

            for row_num, roll, sub_code, exam_name, marks_val, max_val in records:
                if not roll or not sub_code:
                    err_msg = f"Marks (Row {row_num}): roll_number and subject_code are required."
                    row_errors.append({'worksheet': 'Marks', 'row_number': row_num, 'identifier': roll or 'MISSING', 'rejected_value': marks_val, 'reason': err_msg, 'message': err_msg})
                    failed_counts['marks'] += 1
                    continue

                if roll not in student_cache:
                    with db.session.no_autoflush:
                        student_cache[roll] = Student.query.filter_by(roll_number=roll).first()
                student = student_cache[roll]

                if not student:
                    err_msg = f"Marks (Row {row_num}): Student '{roll}' not found. Record skipped."
                    row_errors.append({'worksheet': 'Marks', 'row_number': row_num, 'identifier': roll, 'rejected_value': marks_val, 'reason': err_msg, 'message': err_msg})
                    failed_counts['marks'] += 1
                    continue

                sub_key = (sub_code, student.department_id)
                if sub_key not in sub_cache:
                    with db.session.no_autoflush:
                        sub = Subject.query.filter_by(code=sub_code, department_id=student.department_id).first()
                        if not sub:
                            sub = Subject.query.filter_by(code=sub_code).first()
                        sub_cache[sub_key] = sub
                sub = sub_cache[sub_key]

                if not sub:
                    err_msg = f"Marks (Row {row_num}): Subject '{sub_code}' not found for student '{roll}'."
                    row_errors.append({'worksheet': 'Marks', 'row_number': row_num, 'identifier': roll, 'rejected_value': marks_val, 'reason': err_msg, 'message': err_msg})
                    failed_counts['marks'] += 1
                    continue

                try:
                    obtained = float(marks_val)
                    if obtained < 0:
                        err_msg = f"Marks (Row {row_num}): Marks obtained ({obtained}) cannot be negative."
                        row_errors.append({'worksheet': 'Marks', 'row_number': row_num, 'identifier': roll, 'rejected_value': obtained, 'reason': err_msg, 'message': err_msg})
                        failed_counts['marks'] += 1
                        continue
                except (ValueError, TypeError):
                    err_msg = f"Marks (Row {row_num}): Invalid marks score '{marks_val}'."
                    row_errors.append({'worksheet': 'Marks', 'row_number': row_num, 'identifier': roll, 'rejected_value': marks_val, 'reason': err_msg, 'message': err_msg})
                    failed_counts['marks'] += 1
                    continue

                # Parse explicit max_marks from workbook if present
                m_explicit_max = None
                if max_val is not None and pd.notna(max_val) and str(max_val).strip() != '':
                    try:
                        m_explicit_max = float(max_val)
                    except (ValueError, TypeError):
                        pass

                # Find or create examination
                exam_key = (sub.id, exam_name)
                if exam_key not in exam_cache:
                    with db.session.no_autoflush:
                        exam = Examination.query.filter_by(subject_id=sub.id, name=exam_name).first()
                        if not exam:
                            if 'SEM' in exam_name.upper():
                                exam = Examination.query.filter(
                                    Examination.subject_id == sub.id,
                                    (Examination.name.ilike('%semester%') | Examination.name.ilike(f"%{exam_name}%"))
                                ).first()
                            elif 'IA' in exam_name.upper():
                                exam = Examination.query.filter(
                                    Examination.subject_id == sub.id,
                                    (Examination.name.ilike('%internal%') | Examination.name.ilike(f"%{exam_name}%"))
                                ).first()
                    exam_cache[exam_key] = exam
                exam = exam_cache[exam_key]

                if not exam:
                    m_max = m_explicit_max if m_explicit_max is not None else (100.0 if ('SEM' in exam_name.upper() or 'FINAL' in exam_name.upper()) else 50.0)
                    exam_type = 'semester' if ('SEM' in exam_name.upper() or 'FINAL' in exam_name.upper()) else 'internal'
                    exam = Examination(
                        subject_id=sub.id, name=exam_name, exam_type=exam_type,
                        max_marks=m_max, semester=sub.semester
                    )
                    db.session.add(exam)
                    db.session.flush()
                    exam_cache[exam_key] = exam
                else:
                    # Reconcile semester exam maximum if workbook explicitly provides 100.0 or exam was defaulted to 50.0
                    if m_explicit_max and m_explicit_max > exam.max_marks and (exam.exam_type == 'semester' or 'SEM' in exam.name.upper()):
                        exam.max_marks = m_explicit_max

                if obtained > exam.max_marks:
                    err_msg = f"Marks (Row {row_num}): Score ({obtained}) exceeds exam maximum ({exam.max_marks}) for '{exam.name}'."
                    row_errors.append({
                        'worksheet': 'Marks',
                        'row_number': row_num,
                        'identifier': roll,
                        'rejected_value': obtained,
                        'reason': err_msg,
                        'message': err_msg
                    })
                    failed_counts['marks'] += 1
                    continue

                with db.session.no_autoflush:
                    existing_m = Mark.query.filter_by(student_id=student.id, examination_id=exam.id).first()
                if existing_m:
                    if dup_policy == 'error':
                        err_msg = f"Marks (Row {row_num}): Mark record already exists for '{roll}' in '{exam.name}'."
                        row_errors.append({'worksheet': 'Marks', 'row_number': row_num, 'identifier': roll, 'rejected_value': obtained, 'reason': err_msg, 'message': err_msg})
                        failed_counts['marks'] += 1
                        continue
                    elif dup_policy == 'update':
                        existing_m.marks_obtained = obtained
                        imported_counts['marks'] += 1
                    else:
                        skipped_counts['marks'] += 1
                else:
                    m_entry = Mark(
                        student_id=student.id,
                        subject_id=sub.id,
                        examination_id=exam.id,
                        marks_obtained=obtained
                    )
                    db.session.add(m_entry)
                    imported_counts['marks'] += 1

        # ==========================================================
        # STEP 6: Attendance (Session & Aggregate)
        # ==========================================================
        if 'attendance' in sheet_dfs and not sheet_dfs['attendance'].empty:
            df_att = sheet_dfs['attendance']
            is_aggregate = 'total_classes' in df_att.columns or 'attendance_percentage' in df_att.columns or 'attended_classes' in df_att.columns

            for idx, row in df_att.iterrows():
                row_num = idx + 2
                roll = str(row.get('roll_number', '')).strip().upper()
                sub_code = str(row.get('subject_code', '')).strip().upper()

                if not roll or not sub_code:
                    row_errors.append(f"Attendance (Row {row_num}): roll_number and subject_code are required.")
                    failed_counts['attendance'] += 1
                    continue

                with db.session.no_autoflush:
                    student = Student.query.filter_by(roll_number=roll).first()
                if not student:
                    row_errors.append(f"Attendance (Row {row_num}): Student '{roll}' not found. Record skipped.")
                    failed_counts['attendance'] += 1
                    continue

                with db.session.no_autoflush:
                    sub = Subject.query.filter_by(code=sub_code, department_id=student.department_id).first()
                    if not sub:
                        sub = Subject.query.filter_by(code=sub_code).first()

                if not sub:
                    row_errors.append(f"Attendance (Row {row_num}): Subject '{sub_code}' not found.")
                    failed_counts['attendance'] += 1
                    continue

                if is_aggregate:
                    try:
                        total_c = int(row.get('total_classes', 0)) if pd.notna(row.get('total_classes')) else 0
                        att_c = int(row.get('attended_classes', 0)) if pd.notna(row.get('attended_classes')) else 0
                        pct = float(row.get('attendance_percentage', 0.0)) if pd.notna(row.get('attendance_percentage')) else 0.0
                        if total_c > 0 and att_c > 0 and pct == 0.0:
                            pct = round(att_c / total_c * 100, 1)
                    except (ValueError, TypeError):
                        row_errors.append(f"Attendance (Row {row_num}): Aggregate attendance counts must be integers.")
                        failed_counts['attendance'] += 1
                        continue

                    with db.session.no_autoflush:
                        agg = StudentAggregateAttendance.query.filter_by(student_id=student.id, subject_id=sub.id).first()
                    if agg:
                        if dup_policy == 'error':
                            row_errors.append(f"Attendance (Row {row_num}): Aggregate record already exists for {roll} in {sub.code}.")
                            failed_counts['attendance'] += 1
                            continue
                        elif dup_policy == 'update':
                            agg.total_classes = total_c
                            agg.attended_classes = att_c
                            agg.attendance_percentage = pct
                            imported_counts['attendance'] += 1
                        else:
                            skipped_counts['attendance'] += 1
                    else:
                        agg = StudentAggregateAttendance(
                            student_id=student.id,
                            subject_id=sub.id,
                            total_classes=total_c,
                            attended_classes=att_c,
                            attendance_percentage=pct
                        )
                        db.session.add(agg)
                        imported_counts['attendance'] += 1
                else:
                    # Session format
                    date_str = str(row.get('date', '')).strip()
                    status_val = str(row.get('status', 'present')).strip().lower()

                    try:
                        dt = datetime.strptime(date_str, '%Y-%m-%d').date() if '-' in date_str else date.today()
                    except ValueError:
                        row_errors.append(f"Attendance (Row {row_num}): Invalid date '{date_str}'. Expected YYYY-MM-DD.")
                        failed_counts['attendance'] += 1
                        continue

                    if status_val not in ['present', 'absent', 'late']:
                        status_val = 'present'

                    with db.session.no_autoflush:
                        existing_att = AttendanceRecord.query.filter_by(
                            student_id=student.id, subject_id=sub.id, date=dt
                        ).first()

                    if existing_att:
                        if dup_policy == 'error':
                            row_errors.append(f"Attendance (Row {row_num}): Attendance record already exists for {roll} on {dt}.")
                            failed_counts['attendance'] += 1
                            continue
                        elif dup_policy == 'update':
                            existing_att.status = status_val
                            imported_counts['attendance'] += 1
                        else:
                            skipped_counts['attendance'] += 1
                    else:
                        att_rec = AttendanceRecord(
                            student_id=student.id,
                            subject_id=sub.id,
                            date=dt,
                            status=status_val
                        )
                        db.session.add(att_rec)
                        imported_counts['attendance'] += 1

        # Commit full academic transaction
        db.session.commit()

        total_imported = sum(imported_counts.values())
        total_skipped = sum(skipped_counts.values())
        total_failed = sum(failed_counts.values())
        status = 'completed' if total_failed == 0 else ('partial' if total_imported > 0 else 'failed')

        # Persist master import history log in a dedicated block
        history_id = None
        try:
            history = ImportHistory(
                category='master_workbook',
                department_id=None,
                filename=filename,
                records_imported=total_imported,
                records_skipped=total_skipped,
                records_failed=total_failed,
                status=status,
                error_summary=json.dumps(row_errors),
                user_id=user_id
            )
            db.session.add(history)
            db.session.commit()
            history_id = history.id
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

        # Invalidate / Retrain ML models if marks were added
        # Run isolated so retraining errors do not affect import result
        retrain_error = None
        if imported_counts['marks'] > 0:
            try:
                from routes.admin import _trigger_ml_retraining
                _trigger_ml_retraining()
            except Exception as ml_err:
                retrain_error = str(ml_err)

        return {
            'success': True,
            'status': status,
            'imported_counts': imported_counts,
            'skipped_counts': skipped_counts,
            'failed_counts': failed_counts,
            'total_imported': total_imported,
            'total_skipped': total_skipped,
            'total_failed': total_failed,
            'errors': row_errors,
            'history_id': history_id,
            'retrain_error': retrain_error
        }

    except Exception as e:
        # Roll back all academic data changes immediately
        try:
            db.session.rollback()
        except Exception:
            pass

        # Safely record failed ImportHistory in its own transaction
        history_id = None
        try:
            history = ImportHistory(
                category='master_workbook',
                department_id=None,
                filename=filename,
                records_imported=0,
                records_skipped=0,
                records_failed=sum(failed_counts.values()) or 1,
                status='failed',
                error_summary=json.dumps([f"Fatal transaction rollback: {str(e)}"]),
                user_id=user_id
            )
            db.session.add(history)
            db.session.commit()
            history_id = history.id
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

        return {
            'success': False,
            'status': 'failed',
            'error': f"Transaction rolled back due to error: {str(e)}",
            'errors': [f"Fatal database error: {str(e)}"] + row_errors,
            'history_id': history_id,
            'total_imported': 0,
            'total_skipped': 0,
            'total_failed': sum(failed_counts.values()) or 1
        }
