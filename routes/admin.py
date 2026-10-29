from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, date
import csv
import io
import os
import json
import re
import pandas as pd
from extensions import db
from models import (
    Department, AcademicYear, Section, User, Admin, Faculty, Student,
    Subject, FacultySubjectAssignment, Examination, Mark, AttendanceRecord,
    Question, StudentTask, MotivationalQuote, MLModelRecord,
    ImportHistory, StudentAggregateAttendance
)
from ml_pipeline import get_model_path, train_model, prepare_training_data
from excel_importer import (
    generate_master_workbook_template,
    inspect_master_workbook,
    execute_master_workbook_import
)

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return login_required(decorated)


def get_admin_stats():
    total_students = Student.query.filter_by(is_active=True).count()
    total_faculty = Faculty.query.filter_by(is_active=True).count()
    total_depts = Department.query.filter_by(is_active=True).count()
    total_subjects = Subject.query.filter_by(is_active=True).count()
    total_marks = Mark.query.count()
    return {
        'total_students': total_students,
        'total_faculty': total_faculty,
        'total_departments': total_depts,
        'total_subjects': total_subjects,
        'total_marks_recorded': total_marks,
    }


@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    stats = get_admin_stats()
    recent_students = Student.query.order_by(Student.enrolled_at.desc()).limit(5).all()
    departments = Department.query.filter_by(is_active=True).all()

    # Dept-wise student counts
    dept_data = []
    for d in departments:
        count = Student.query.filter_by(department_id=d.id, is_active=True).count()
        dept_data.append({'name': d.name, 'count': count, 'code': d.code})

    # Attendance summary
    total_att = AttendanceRecord.query.count()
    present_att = AttendanceRecord.query.filter_by(status='present').count()
    att_pct = round(present_att / total_att * 100, 1) if total_att > 0 else 0

    return render_template('admin/dashboard.html',
                           stats=stats,
                           recent_students=recent_students,
                           dept_data=dept_data,
                           att_pct=att_pct,
                           admin=current_user.admin)


@admin_bp.route('/departments', methods=['GET', 'POST'])
@admin_required
def departments():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name', '').strip()
            code = request.form.get('code', '').strip().upper()
            description = request.form.get('description', '').strip()

            if not name or not code:
                flash('Department name and code are required.', 'danger')
            elif Department.query.filter_by(code=code).first():
                flash(f'Department code {code} already exists.', 'danger')
            elif Department.query.filter_by(name=name).first():
                flash(f'Department "{name}" already exists.', 'danger')
            else:
                dept = Department(name=name, code=code, description=description)
                db.session.add(dept)
                db.session.commit()
                flash(f'Department "{name}" created successfully!', 'success')

        elif action == 'toggle':
            dept_id = request.form.get('dept_id')
            dept = Department.query.get(dept_id)
            if dept:
                dept.is_active = not dept.is_active
                db.session.commit()
                flash(f'Department "{dept.name}" {"activated" if dept.is_active else "deactivated"}.', 'success')

        return redirect(url_for('admin.departments'))

    depts = Department.query.all()
    academic_years = AcademicYear.query.all()
    sections = Section.query.all()
    return render_template('admin/departments.html', departments=depts,
                           academic_years=academic_years, sections=sections)


@admin_bp.route('/sections', methods=['POST'])
@admin_required
def add_section():
    action = request.form.get('action')
    if action == 'add':
        dept_id = request.form.get('department_id')
        name = request.form.get('name', '').strip().upper()
        semester = request.form.get('semester')
        ay_id = request.form.get('academic_year_id')

        if not all([dept_id, name, semester, ay_id]):
            flash('All section fields are required.', 'danger')
        else:
            sec = Section(name=name, department_id=int(dept_id),
                          semester=int(semester), academic_year_id=int(ay_id))
            db.session.add(sec)
            db.session.commit()
            flash(f'Section {name} created!', 'success')

    return redirect(url_for('admin.departments'))


@admin_bp.route('/students', methods=['GET', 'POST'])
@admin_required
def students():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            return _add_student()
        elif action == 'toggle':
            student_id = request.form.get('student_id')
            stu = Student.query.get(student_id)
            if stu:
                stu.is_active = not stu.is_active
                stu.user.is_active = stu.is_active
                db.session.commit()
                flash(f'Student "{stu.name}" {"activated" if stu.is_active else "deactivated"}.', 'success')
        return redirect(url_for('admin.students'))

    # Filters
    dept_filter = request.args.get('dept_id', '')
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    query = Student.query
    if dept_filter:
        query = query.filter_by(department_id=int(dept_filter))
    if search:
        query = query.filter(
            db.or_(Student.name.ilike(f'%{search}%'), Student.roll_number.ilike(f'%{search}%'))
        )

    students_page = query.order_by(Student.enrolled_at.desc()).paginate(page=page, per_page=20, error_out=False)
    departments = Department.query.filter_by(is_active=True).all()
    sections = Section.query.all()
    academic_years = AcademicYear.query.all()

    return render_template('admin/students.html',
                           students=students_page,
                           departments=departments,
                           sections=sections,
                           academic_years=academic_years,
                           search=search,
                           dept_filter=dept_filter)


def _add_student():
    roll = request.form.get('roll_number', '').strip().upper()
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    dept_id = request.form.get('department_id')
    section_id = request.form.get('section_id')
    ay_id = request.form.get('academic_year_id')
    semester = request.form.get('current_semester', 1)

    if not all([roll, name, dept_id]):
        flash('Roll number, name, and department are required.', 'danger')
        return

    if User.query.filter_by(unique_id=roll).first():
        flash(f'Roll number {roll} already exists.', 'danger')
        return

    user = User(unique_id=roll, role='student')
    user.set_password(roll)
    db.session.add(user)
    db.session.flush()

    stu = Student(
        user_id=user.id, roll_number=roll, name=name, email=email,
        department_id=int(dept_id),
        section_id=int(section_id) if section_id else None,
        academic_year_id=int(ay_id) if ay_id else None,
        current_semester=int(semester)
    )
    db.session.add(stu)
    db.session.commit()
    flash(f'Student "{name}" ({roll}) created! Initial password: {roll}', 'success')


@admin_bp.route('/faculty', methods=['GET', 'POST'])
@admin_required
def faculty():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            fac_id = request.form.get('faculty_id', '').strip().upper()
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip()
            dept_id = request.form.get('department_id')
            designation = request.form.get('designation', 'Assistant Professor').strip()

            if not all([fac_id, name]):
                flash('Faculty ID and name are required.', 'danger')
            elif User.query.filter_by(unique_id=fac_id).first():
                flash(f'Faculty ID {fac_id} already exists.', 'danger')
            else:
                user = User(unique_id=fac_id, role='faculty')
                user.set_password(fac_id)
                db.session.add(user)
                db.session.flush()

                fac = Faculty(
                    user_id=user.id, faculty_id=fac_id, name=name, email=email,
                    department_id=int(dept_id) if dept_id else None,
                    designation=designation
                )
                db.session.add(fac)
                db.session.commit()
                flash(f'Faculty "{name}" ({fac_id}) created! Initial password: {fac_id}', 'success')

        elif action == 'assign':
            fac_id = request.form.get('faculty_id')
            subj_id = request.form.get('subject_id')
            sec_id = request.form.get('section_id')
            ay_id = request.form.get('academic_year_id')
            fac = Faculty.query.get(fac_id)
            if fac and subj_id and sec_id:
                existing = FacultySubjectAssignment.query.filter_by(
                    faculty_id=fac.id, subject_id=int(subj_id), section_id=int(sec_id)
                ).first()
                if existing:
                    flash('This assignment already exists.', 'warning')
                else:
                    fsa = FacultySubjectAssignment(
                        faculty_id=fac.id, subject_id=int(subj_id),
                        section_id=int(sec_id),
                        academic_year_id=int(ay_id) if ay_id else None
                    )
                    db.session.add(fsa)
                    db.session.commit()
                    flash('Subject assignment added!', 'success')

        return redirect(url_for('admin.faculty'))

    faculty_list = Faculty.query.all()
    departments = Department.query.filter_by(is_active=True).all()
    subjects = Subject.query.filter_by(is_active=True).all()
    sections = Section.query.all()
    academic_years = AcademicYear.query.all()

    return render_template('admin/faculty.html',
                           faculty_list=faculty_list,
                           departments=departments,
                           subjects=subjects,
                           sections=sections,
                           academic_years=academic_years)


@admin_bp.route('/subjects', methods=['GET', 'POST'])
@admin_required
def subjects():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            code = request.form.get('code', '').strip().upper()
            name = request.form.get('name', '').strip()
            dept_id = request.form.get('department_id')
            semester = request.form.get('semester')
            credits = request.form.get('credits', 3)
            subj_type = request.form.get('subject_type', 'theory')

            if not all([code, name, dept_id, semester]):
                flash('Code, name, department, and semester are required.', 'danger')
            else:
                existing = Subject.query.filter_by(code=code, department_id=int(dept_id),
                                                   semester=int(semester)).first()
                if existing:
                    flash(f'Subject {code} already exists for this department/semester.', 'danger')
                else:
                    subj = Subject(
                        code=code, name=name, department_id=int(dept_id),
                        semester=int(semester), credits=int(credits),
                        subject_type=subj_type
                    )
                    db.session.add(subj)
                    db.session.commit()
                    flash(f'Subject "{name}" ({code}) created!', 'success')

        elif action == 'toggle':
            subj_id = request.form.get('subject_id')
            subj = Subject.query.get(subj_id)
            if subj:
                subj.is_active = not subj.is_active
                db.session.commit()
                flash(f'Subject "{subj.name}" updated.', 'success')

        return redirect(url_for('admin.subjects'))

    dept_filter = request.args.get('dept_id', '')
    query = Subject.query
    if dept_filter:
        query = query.filter_by(department_id=int(dept_filter))
    subjects_list = query.order_by(Subject.department_id, Subject.semester).all()
    departments = Department.query.filter_by(is_active=True).all()

    return render_template('admin/subjects.html', subjects=subjects_list, departments=departments,
                           dept_filter=dept_filter)


def _read_uploaded_file(file):
    """Safely parse uploaded CSV or Excel file into a pandas DataFrame."""
    try:
        filename = file.filename.lower()
        if filename.endswith('.csv'):
            try:
                df = pd.read_csv(file, encoding='utf-8-sig')
            except UnicodeDecodeError:
                file.seek(0)
                df = pd.read_csv(file, encoding='latin1')
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file)
        else:
            return None, "Unsupported file format. Please upload a .csv, .xlsx, or .xls file."

        # Clean and normalize columns
        df.columns = [str(c).strip().lower().replace(' ', '_').replace('-', '_') for c in df.columns]
        df = df.dropna(how='all')
        return df, None
    except Exception as e:
        return None, f"Failed to parse file: {str(e)}"


@admin_bp.route('/dataset', methods=['GET', 'POST'])
@admin_required
def dataset():
    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    academic_years = AcademicYear.query.order_by(AcademicYear.id.desc()).all()
    sections = Section.query.filter_by(is_active=True).all()
    import_histories = ImportHistory.query.order_by(ImportHistory.imported_at.desc()).limit(20).all()

    preview_data = None
    preview_category = None
    preview_columns = []
    import_summary = None
    errors = []

    if request.method == 'POST':
        action = request.form.get('action')
        category = request.form.get('category', 'students')
        file = request.files.get('file')
        dept_id = request.form.get('department_id')
        dept_id = int(dept_id) if dept_id and dept_id.isdigit() else None
        dup_policy = request.form.get('duplicate_policy', 'skip')  # 'skip', 'update', 'error'

        if not file or not file.filename:
            flash('Please select a valid CSV or Excel file to upload.', 'warning')
            return redirect(url_for('admin.dataset'))

        df, err = _read_uploaded_file(file)
        if err:
            errors.append(err)
        elif df is None or df.empty:
            errors.append("Uploaded file contains no readable data rows.")
        elif action == 'preview':
            preview_category = category
            preview_columns = list(df.columns)
            preview_data = df.head(15).fillna('').to_dict('records')
            # Dry run validation preview
            val_errors = _validate_preview(df, category, dept_id)
            if val_errors:
                errors.extend(val_errors[:15])
                if len(val_errors) > 15:
                    errors.append(f"... and {len(val_errors) - 15} more warnings.")
            else:
                flash(f'File preview loaded successfully! {len(df)} rows detected and column requirements verified.', 'success')
        elif action == 'import':
            filename = file.filename
            summary, row_errors = _execute_dataset_import(df, category, dept_id, dup_policy, filename)
            import_summary = summary
            errors = row_errors
            # Refresh histories
            import_histories = ImportHistory.query.order_by(ImportHistory.imported_at.desc()).limit(20).all()
            if summary and summary.get('imported', 0) > 0:
                flash(f"Successfully processed {summary.get('imported')} records ({category.replace('_', ' ').capitalize()})!", 'success')
            elif errors:
                flash("Import completed with issues. Check the summary and error log below.", 'warning')

    return render_template(
        'admin/dataset.html',
        departments=departments,
        academic_years=academic_years,
        sections=sections,
        import_histories=import_histories,
        preview_data=preview_data,
        preview_category=preview_category,
        preview_columns=preview_columns,
        import_summary=import_summary,
        errors=errors
    )


@admin_bp.route('/dataset/master-template')
@admin_required
def download_master_template():
    """Download the official EduPulse Master Excel Template containing all 7 sheets."""
    buf = generate_master_workbook_template()
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='EduPulse_Master_Template.xlsx'
    )


@admin_bp.route('/dataset/master-preview', methods=['POST'])
@admin_required
def master_preview():
    """Upload and inspect master workbook containing all 7 sheets without committing changes."""
    file = request.files.get('master_file')
    dup_policy = request.form.get('duplicate_policy', 'skip')

    if not file or not file.filename:
        flash('Please select an Excel workbook (.xlsx) file to upload.', 'warning')
        return redirect(url_for('admin.dataset'))

    if not file.filename.endswith(('.xlsx', '.xls')):
        flash('Please upload a valid Excel workbook file (.xlsx).', 'danger')
        return redirect(url_for('admin.dataset'))

    upload_folder = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    temp_path = os.path.join(upload_folder, f'staged_master_{current_user.id}.xlsx')
    file.save(temp_path)

    try:
        inspection = inspect_master_workbook(temp_path)
    except Exception as e:
        flash(f'Failed to parse Excel workbook: {str(e)}', 'danger')
        return redirect(url_for('admin.dataset'))

    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    academic_years = AcademicYear.query.order_by(AcademicYear.id.desc()).all()
    sections = Section.query.filter_by(is_active=True).all()
    import_histories = ImportHistory.query.order_by(ImportHistory.imported_at.desc()).limit(20).all()

    flash(f"Master workbook '{file.filename}' parsed! Detected {inspection['summary']['total_sheets_detected']} worksheets with {inspection['summary']['total_rows']} total rows.", 'success')

    return render_template(
        'admin/dataset.html',
        departments=departments,
        academic_years=academic_years,
        sections=sections,
        import_histories=import_histories,
        master_inspection=inspection,
        master_filename=file.filename,
        dup_policy=dup_policy
    )


@admin_bp.route('/dataset/master-confirm', methods=['POST'])
@admin_required
def master_confirm():
    """Execute dependency-ordered transaction import for staged master workbook."""
    upload_folder = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'uploads')
    temp_path = os.path.join(upload_folder, f'staged_master_{current_user.id}.xlsx')
    dup_policy = request.form.get('duplicate_policy', 'skip')
    filename = request.form.get('filename', 'EduPulse_Dataset.xlsx')

    if not os.path.exists(temp_path):
        flash('No staged master workbook found to import. Please upload again.', 'warning')
        return redirect(url_for('admin.dataset'))

    result = execute_master_workbook_import(temp_path, dup_policy=dup_policy, user_id=current_user.id, filename=filename)

    # Clean up staged file
    try:
        os.remove(temp_path)
    except Exception:
        pass

    if result.get('success'):
        counts = result.get('imported_counts', {})
        summary_txt = (
            f"✅ Master Workbook Import Completed! "
            f"Saved {result['total_imported']} records across all 7 sheets "
            f"(Depts: {counts.get('departments', 0)}, Students: {counts.get('students', 0)}, "
            f"Faculty: {counts.get('faculty', 0)}, Subjects: {counts.get('subjects', 0)}, "
            f"Exams: {counts.get('examinations', 0)}, Marks: {counts.get('marks', 0)}, "
            f"Attendance: {counts.get('attendance', 0)}). "
            f"Skipped {result['total_skipped']} duplicates."
        )
        flash(summary_txt, 'success')
        if result.get('total_failed', 0) > 0:
            flash(f"⚠️ {result['total_failed']} records had validation issues and were safely skipped. Check the import history log below for audit details.", 'warning')
    else:
        flash(result.get('error', 'Master import encountered a fatal error and all changes were safely rolled back.'), 'danger')

    return redirect(url_for('admin.dataset'))


@admin_bp.route('/dataset/master-cancel', methods=['POST'])
@admin_required
def master_cancel():
    """Discard staged master workbook."""
    upload_folder = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'uploads')
    temp_path = os.path.join(upload_folder, f'staged_master_{current_user.id}.xlsx')
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except Exception:
            pass
    flash('Master workbook preview cancelled. No changes were made to the database.', 'info')
    return redirect(url_for('admin.dataset'))


def _validate_preview(df, category, dept_id):
    """Run non-destructive pre-validation check on file columns and department bindings."""
    warnings = []
    cols = set(df.columns)

    if category == 'departments_sections':
        if not {'department_code', 'department_name'}.issubset(cols):
            warnings.append("Expected columns: 'department_code', 'department_name'. Optional: 'section_name', 'semester'.")
    elif category == 'students':
        if not {'roll_number', 'name'}.issubset(cols):
            warnings.append("Expected required columns: 'roll_number', 'name'.")
        if 'department_code' not in cols and not dept_id:
            warnings.append("No 'department_code' found in file. You must select a Target Department from the dropdown.")
    elif category == 'faculty':
        if not {'faculty_id', 'name'}.issubset(cols):
            warnings.append("Expected required columns: 'faculty_id', 'name'.")
        if 'department_code' not in cols and not dept_id:
            warnings.append("No 'department_code' in file. Target Department dropdown selection is required.")
    elif category == 'subjects':
        if not {'subject_code', 'subject_name'}.issubset(cols):
            warnings.append("Expected required columns: 'subject_code', 'subject_name'. Optional: 'semester', 'credits'.")
        if 'department_code' not in cols and not dept_id:
            warnings.append("Target Department must be specified in the file or selected above.")
    elif category == 'examinations':
        if not {'subject_code', 'name', 'max_marks'}.issubset(cols):
            warnings.append("Expected columns: 'subject_code', 'name', 'max_marks'. Optional: 'exam_type', 'semester'.")
    elif category == 'marks':
        # Check if long format or wide format
        if 'roll_number' not in cols and 'student_id' not in cols:
            warnings.append("Marks dataset must include 'roll_number' column.")
    elif category == 'attendance':
        if 'roll_number' not in cols and 'student_id' not in cols:
            warnings.append("Attendance dataset must include 'roll_number' column.")

    return warnings


def _execute_dataset_import(df, category, dept_id, dup_policy, filename):
    """Dispatch file dataframe to specific category importer with full database transaction."""
    imported = 0
    skipped = 0
    failed = 0
    errors = []

    # Clear any lingering read state before starting write transaction
    try:
        db.session.rollback()
    except Exception:
        pass

    try:
        if category == 'departments_sections':
            imported, skipped, failed, errors = _import_departments_sections(df, dup_policy)
        elif category == 'students':
            imported, skipped, failed, errors = _import_students(df, dept_id, dup_policy)
        elif category == 'faculty':
            imported, skipped, failed, errors = _import_faculty(df, dept_id, dup_policy)
        elif category == 'subjects':
            imported, skipped, failed, errors = _import_subjects(df, dept_id, dup_policy)
        elif category == 'examinations':
            imported, skipped, failed, errors = _import_examinations(df, dept_id, dup_policy)
        elif category == 'marks':
            imported, skipped, failed, errors = _import_marks(df, dept_id, dup_policy)
        elif category == 'attendance':
            imported, skipped, failed, errors = _import_attendance(df, dept_id, dup_policy)
        else:
            errors.append(f"Unknown dataset category: {category}")

        # Commit all academic records atomically
        db.session.commit()

        status = 'completed' if failed == 0 else ('partial' if imported > 0 else 'failed')

        # Persist Import History Log in an isolated block
        try:
            history = ImportHistory(
                category=category,
                department_id=dept_id,
                filename=filename,
                records_imported=imported,
                records_skipped=skipped,
                records_failed=failed,
                status=status,
                error_summary=json.dumps(errors),
                user_id=current_user.id
            )
            db.session.add(history)
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

        # Invalidate / Retrain ML models if marks were added
        if category == 'marks' and imported > 0:
            try:
                _trigger_ml_retraining(dept_id)
            except Exception:
                pass

        return {
            'imported': imported,
            'skipped': skipped,
            'failed': failed,
            'total': len(df),
            'status': status
        }, errors

    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            history = ImportHistory(
                category=category,
                department_id=dept_id,
                filename=filename,
                records_imported=0,
                records_skipped=0,
                records_failed=len(df),
                status='failed',
                error_summary=json.dumps([f"Fatal transaction error: {str(e)}"]),
                user_id=current_user.id
            )
            db.session.add(history)
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        return None, [f"Transaction aborted: {str(e)}"]


def _import_departments_sections(df, dup_policy):
    imported = 0
    skipped = 0
    failed = 0
    errors = []

    for idx, row in df.iterrows():
        row_num = idx + 2
        code = str(row.get('department_code', '')).strip().upper()
        name = str(row.get('department_name', '')).strip()

        if not code or not name:
            errors.append(f"Row {row_num}: department_code and department_name are required.")
            failed += 1
            continue

        dept = Department.query.filter_by(code=code).first()
        if dept:
            if dup_policy == 'error':
                errors.append(f"Row {row_num}: Department code '{code}' already exists.")
                failed += 1
                continue
            elif dup_policy == 'update':
                dept.name = name
                if 'description' in row and pd.notna(row['description']):
                    dept.description = str(row['description']).strip()
                imported += 1
            else:
                skipped += 1
        else:
            desc = str(row.get('description', '')).strip() if pd.notna(row.get('description')) else ''
            dept = Department(code=code, name=name, description=desc)
            db.session.add(dept)
            db.session.flush()
            imported += 1

        # Section handling if specified
        sec_name = str(row.get('section_name', '')).strip().upper() if pd.notna(row.get('section_name')) else ''
        if sec_name and dept:
            sem = int(row.get('semester', 1)) if pd.notna(row.get('semester')) and str(row.get('semester')).isdigit() else 1
            existing_sec = Section.query.filter_by(department_id=dept.id, name=sec_name, semester=sem).first()
            if not existing_sec:
                sec = Section(name=sec_name, department_id=dept.id, semester=sem)
                db.session.add(sec)

    db.session.flush()
    return imported, skipped, failed, errors


def _import_students(df, selected_dept_id, dup_policy):
    imported = 0
    skipped = 0
    failed = 0
    errors = []

    for idx, row in df.iterrows():
        row_num = idx + 2
        roll = str(row.get('roll_number', row.get('student_id', ''))).strip().upper()
        name = str(row.get('name', row.get('full_name', ''))).strip()

        if not roll or not name:
            errors.append(f"Row {row_num}: Missing required roll_number or name.")
            failed += 1
            continue

        # Resolve Department
        dept = None
        dept_code = str(row.get('department_code', '')).strip().upper() if pd.notna(row.get('department_code')) else ''
        if dept_code:
            dept = Department.query.filter_by(code=dept_code).first()
            if not dept:
                errors.append(f"Row {row_num}: Department code '{dept_code}' not found.")
                failed += 1
                continue
        elif selected_dept_id:
            dept = Department.query.get(selected_dept_id)

        if not dept:
            errors.append(f"Row {row_num}: No department specified or selected for student '{roll}'.")
            failed += 1
            continue

        # Resolve Section
        sec_name = str(row.get('section', row.get('section_name', 'A'))).strip().upper()
        sem = int(row.get('semester', 1)) if pd.notna(row.get('semester')) and str(row.get('semester')).isdigit() else 1
        sec = Section.query.filter_by(department_id=dept.id, name=sec_name, semester=sem).first()
        if not sec:
            sec = Section(name=sec_name, department_id=dept.id, semester=sem)
            db.session.add(sec)
            db.session.flush()

        email = str(row.get('email', '')).strip() if pd.notna(row.get('email')) else None
        phone = str(row.get('phone', '')).strip() if pd.notna(row.get('phone')) else None
        gender = str(row.get('gender', '')).strip() if pd.notna(row.get('gender')) else None

        existing_user = User.query.filter_by(unique_id=roll).first()
        existing_student = Student.query.filter_by(roll_number=roll).first()

        if existing_student or existing_user:
            if dup_policy == 'error':
                errors.append(f"Row {row_num}: Student ID '{roll}' already exists.")
                failed += 1
                continue
            elif dup_policy == 'update' and existing_student:
                existing_student.name = name
                if email: existing_student.email = email
                if phone: existing_student.phone = phone
                if gender: existing_student.gender = gender
                existing_student.current_semester = sem
                existing_student.section_id = sec.id
                imported += 1
            else:
                skipped += 1
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
                gender=gender,
                department_id=dept.id,
                section_id=sec.id,
                current_semester=sem
            )
            db.session.add(stu)
            imported += 1

    db.session.flush()
    return imported, skipped, failed, errors


def _import_faculty(df, selected_dept_id, dup_policy):
    imported = 0
    skipped = 0
    failed = 0
    errors = []

    for idx, row in df.iterrows():
        row_num = idx + 2
        fac_id = str(row.get('faculty_id', row.get('id', ''))).strip().upper()
        name = str(row.get('name', row.get('full_name', ''))).strip()

        if not fac_id or not name:
            errors.append(f"Row {row_num}: faculty_id and name are required.")
            failed += 1
            continue

        dept = None
        dept_code = str(row.get('department_code', '')).strip().upper() if pd.notna(row.get('department_code')) else ''
        if dept_code:
            dept = Department.query.filter_by(code=dept_code).first()
            if not dept:
                errors.append(f"Row {row_num}: Department code '{dept_code}' not found.")
                failed += 1
                continue
        elif selected_dept_id:
            dept = Department.query.get(selected_dept_id)

        if not dept:
            errors.append(f"Row {row_num}: No department specified for faculty '{fac_id}'.")
            failed += 1
            continue

        email = str(row.get('email', '')).strip() if pd.notna(row.get('email')) else None
        phone = str(row.get('phone', '')).strip() if pd.notna(row.get('phone')) else None
        designation = str(row.get('designation', 'Assistant Professor')).strip() if pd.notna(row.get('designation')) else 'Assistant Professor'

        existing_user = User.query.filter_by(unique_id=fac_id).first()
        existing_fac = Faculty.query.filter_by(faculty_id=fac_id).first()

        faculty_obj = None
        if existing_fac or existing_user:
            if dup_policy == 'error':
                errors.append(f"Row {row_num}: Faculty ID '{fac_id}' already exists.")
                failed += 1
                continue
            elif dup_policy == 'update' and existing_fac:
                existing_fac.name = name
                if email: existing_fac.email = email
                if phone: existing_fac.phone = phone
                existing_fac.designation = designation
                faculty_obj = existing_fac
                imported += 1
            else:
                skipped += 1
                faculty_obj = existing_fac
        else:
            user = User(unique_id=fac_id, role='faculty')
            user.set_password(fac_id)
            db.session.add(user)
            db.session.flush()

            faculty_obj = Faculty(
                user_id=user.id,
                faculty_id=fac_id,
                name=name,
                email=email,
                phone=phone,
                department_id=dept.id,
                designation=designation
            )
            db.session.add(faculty_obj)
            db.session.flush()
            imported += 1

        # Process Assigned Subjects / Sections if provided
        assigned_subs = str(row.get('assigned_subjects', '')).strip() if pd.notna(row.get('assigned_subjects')) else ''
        assigned_secs = str(row.get('assigned_sections', 'A')).strip() if pd.notna(row.get('assigned_sections')) else 'A'

        if faculty_obj and assigned_subs:
            sub_codes = [s.strip().upper() for s in assigned_subs.split(',') if s.strip()]
            sec_names = [s.strip().upper() for s in assigned_secs.split(',') if s.strip()] or ['A']
            for sc in sub_codes:
                sub = Subject.query.filter_by(code=sc, department_id=dept.id).first()
                if sub:
                    for sn in sec_names:
                        sec = Section.query.filter_by(department_id=dept.id, name=sn, semester=sub.semester).first()
                        if not sec:
                            sec = Section(department_id=dept.id, name=sn, semester=sub.semester)
                            db.session.add(sec)
                            db.session.flush()

                        fsa = FacultySubjectAssignment.query.filter_by(
                            faculty_id=faculty_obj.id, subject_id=sub.id, section_id=sec.id
                        ).first()
                        if not fsa:
                            db.session.add(FacultySubjectAssignment(
                                faculty_id=faculty_obj.id, subject_id=sub.id, section_id=sec.id
                            ))

    db.session.flush()
    return imported, skipped, failed, errors


def _import_subjects(df, selected_dept_id, dup_policy):
    imported = 0
    skipped = 0
    failed = 0
    errors = []

    for idx, row in df.iterrows():
        row_num = idx + 2
        code = str(row.get('subject_code', row.get('code', ''))).strip().upper()
        name = str(row.get('subject_name', row.get('name', ''))).strip()

        if not code or not name:
            errors.append(f"Row {row_num}: subject_code and subject_name are required.")
            failed += 1
            continue

        dept = None
        dept_code = str(row.get('department_code', '')).strip().upper() if pd.notna(row.get('department_code')) else ''
        if dept_code:
            dept = Department.query.filter_by(code=dept_code).first()
        elif selected_dept_id:
            dept = Department.query.get(selected_dept_id)

        if not dept:
            errors.append(f"Row {row_num}: Department could not be determined for subject '{code}'.")
            failed += 1
            continue

        sem = int(row.get('semester', 1)) if pd.notna(row.get('semester')) and str(row.get('semester')).isdigit() else 1
        credits = int(row.get('credits', 3)) if pd.notna(row.get('credits')) and str(row.get('credits')).isdigit() else 3
        sub_type = str(row.get('subject_type', 'theory')).strip().lower() if pd.notna(row.get('subject_type')) else 'theory'

        existing_sub = Subject.query.filter_by(code=code, department_id=dept.id, semester=sem).first()
        if existing_sub:
            if dup_policy == 'error':
                errors.append(f"Row {row_num}: Subject '{code}' already exists in semester {sem}.")
                failed += 1
                continue
            elif dup_policy == 'update':
                existing_sub.name = name
                existing_sub.credits = credits
                existing_sub.subject_type = sub_type
                imported += 1
            else:
                skipped += 1
        else:
            sub = Subject(
                code=code, name=name, department_id=dept.id,
                semester=sem, credits=credits, subject_type=sub_type
            )
            db.session.add(sub)
            imported += 1

    db.session.flush()
    return imported, skipped, failed, errors


def _import_examinations(df, selected_dept_id, dup_policy):
    imported = 0
    skipped = 0
    failed = 0
    errors = []

    for idx, row in df.iterrows():
        row_num = idx + 2
        sub_code = str(row.get('subject_code', '')).strip().upper()
        exam_name = str(row.get('name', row.get('exam_name', ''))).strip()

        if not sub_code or not exam_name:
            errors.append(f"Row {row_num}: subject_code and name are required.")
            failed += 1
            continue

        query = Subject.query.filter_by(code=sub_code)
        if selected_dept_id:
            query = query.filter_by(department_id=selected_dept_id)
        subject = query.first()

        if not subject:
            errors.append(f"Row {row_num}: Subject '{sub_code}' not found in database.")
            failed += 1
            continue

        try:
            max_m = float(row.get('max_marks', 100))
        except ValueError:
            max_m = 100.0

        exam_type = str(row.get('exam_type', 'internal')).strip().lower() if pd.notna(row.get('exam_type')) else 'internal'
        sem = int(row.get('semester', subject.semester)) if pd.notna(row.get('semester')) and str(row.get('semester')).isdigit() else subject.semester

        existing_exam = Examination.query.filter_by(subject_id=subject.id, name=exam_name, semester=sem).first()
        if existing_exam:
            if dup_policy == 'error':
                errors.append(f"Row {row_num}: Examination '{exam_name}' already exists for subject '{sub_code}'.")
                failed += 1
                continue
            elif dup_policy == 'update':
                existing_exam.max_marks = max_m
                existing_exam.exam_type = exam_type
                imported += 1
            else:
                skipped += 1
        else:
            exam = Examination(
                subject_id=subject.id,
                name=exam_name,
                exam_type=exam_type,
                max_marks=max_m,
                semester=sem
            )
            db.session.add(exam)
            imported += 1

    db.session.flush()
    return imported, skipped, failed, errors


def _import_marks(df, selected_dept_id, dup_policy):
    """
    Import subject-wise student marks.
    Supports BOTH Long Format (one mark per row) AND Wide Format (multiple subject columns per row).
    """
    imported = 0
    skipped = 0
    failed = 0
    errors = []

    # Detect Long vs Wide format
    is_long = ('subject_code' in df.columns or 'subject_name' in df.columns) and ('marks_obtained' in df.columns or 'score' in df.columns)

    if is_long:
        records_to_process = []
        for idx, row in df.iterrows():
            row_num = idx + 2
            roll = str(row.get('roll_number', row.get('student_id', ''))).strip().upper()
            sub_id_or_code = str(row.get('subject_code', row.get('subject_name', ''))).strip()
            exam_name = str(row.get('exam_name', row.get('exam_type', 'IA1'))).strip()
            marks_val = row.get('marks_obtained', row.get('score', 0))
            max_val = row.get('max_marks', None)
            records_to_process.append((row_num, roll, sub_id_or_code, exam_name, marks_val, max_val))
    else:
        # Wide Format: unpivot subject columns
        fixed_cols = {'roll_number', 'student_id', 'exam_name', 'exam_type', 'semester'}
        subject_cols = [c for c in df.columns if c not in fixed_cols]

        if not subject_cols:
            return 0, 0, len(df), ["Wide-format marks file must include subject columns after 'roll_number'."]

        records_to_process = []
        for idx, row in df.iterrows():
            row_num = idx + 2
            roll = str(row.get('roll_number', row.get('student_id', ''))).strip().upper()
            exam_name = str(row.get('exam_name', row.get('exam_type', 'IA1'))).strip()
            for sub_col in subject_cols:
                mark_val = row.get(sub_col)
                if pd.notna(mark_val) and str(mark_val).strip() != '':
                    records_to_process.append((row_num, roll, sub_col, exam_name, mark_val, None))

    for row_num, roll, sub_ref, exam_name, marks_val, max_val in records_to_process:
        if not roll or not sub_ref:
            errors.append(f"Row {row_num}: Missing roll number or subject code.")
            failed += 1
            continue

        student = Student.query.filter_by(roll_number=roll).first()
        if not student:
            errors.append(f"Row {row_num}: Student '{roll}' not found in database.")
            failed += 1
            continue

        # Match subject by Code or Name
        sub = Subject.query.filter(
            (Subject.code == sub_ref.upper()) | (Subject.name.ilike(sub_ref))
        ).filter_by(department_id=student.department_id).first()

        if not sub:
            # Try global match
            sub = Subject.query.filter((Subject.code == sub_ref.upper()) | (Subject.name.ilike(sub_ref))).first()

        if not sub:
            errors.append(f"Row {row_num}: Subject '{sub_ref}' not found for department {student.department.code if student.department else ''}.")
            failed += 1
            continue

        # Validate numeric marks
        try:
            obtained = float(marks_val)
            if obtained < 0:
                errors.append(f"Row {row_num}: Marks obtained ({obtained}) cannot be negative.")
                failed += 1
                continue
        except (ValueError, TypeError):
            errors.append(f"Row {row_num}: Marks value '{marks_val}' is not a valid number.")
            failed += 1
            continue

        # Find or create Examination
        exam = Examination.query.filter_by(subject_id=sub.id, name=exam_name).first()
        if not exam:
            try:
                m_max = float(max_val) if max_val and pd.notna(max_val) else (50.0 if 'IA' in exam_name.upper() else 100.0)
            except ValueError:
                m_max = 100.0
            exam_type = 'semester' if 'SEM' in exam_name.upper() else ('assignment' if 'ASSIGN' in exam_name.upper() else 'internal')
            exam = Examination(
                subject_id=sub.id,
                name=exam_name,
                exam_type=exam_type,
                max_marks=m_max,
                semester=sub.semester
            )
            db.session.add(exam)
            db.session.flush()

        if obtained > exam.max_marks:
            errors.append(f"Row {row_num}: Marks obtained ({obtained}) exceeds max marks ({exam.max_marks}) for '{exam.name}'.")
            failed += 1
            continue

        existing_mark = Mark.query.filter_by(student_id=student.id, examination_id=exam.id).first()
        if existing_mark:
            if dup_policy == 'error':
                errors.append(f"Row {row_num}: Mark record already exists for student {roll} and exam {exam.name}.")
                failed += 1
                continue
            elif dup_policy == 'update':
                existing_mark.marks_obtained = obtained
                imported += 1
            else:
                skipped += 1
        else:
            mark_entry = Mark(
                student_id=student.id,
                subject_id=sub.id,
                examination_id=exam.id,
                marks_obtained=obtained
            )
            db.session.add(mark_entry)
            imported += 1

    db.session.flush()
    return imported, skipped, failed, errors


def _import_attendance(df, selected_dept_id, dup_policy):
    """
    Import attendance datasets.
    Supports BOTH Session Logs (date, status) AND Aggregate Records (total_classes, attended_classes).
    """
    imported = 0
    skipped = 0
    failed = 0
    errors = []

    is_aggregate = 'total_classes' in df.columns or 'attendance_percentage' in df.columns or 'attended_classes' in df.columns

    for idx, row in df.iterrows():
        row_num = idx + 2
        roll = str(row.get('roll_number', row.get('student_id', ''))).strip().upper()
        sub_ref = str(row.get('subject_code', row.get('subject_name', ''))).strip()

        if not roll or not sub_ref:
            errors.append(f"Row {row_num}: roll_number and subject_code are required.")
            failed += 1
            continue

        student = Student.query.filter_by(roll_number=roll).first()
        if not student:
            errors.append(f"Row {row_num}: Student '{roll}' not found in database.")
            failed += 1
            continue

        sub = Subject.query.filter(
            (Subject.code == sub_ref.upper()) | (Subject.name.ilike(sub_ref))
        ).filter_by(department_id=student.department_id).first()
        if not sub:
            sub = Subject.query.filter((Subject.code == sub_ref.upper()) | (Subject.name.ilike(sub_ref))).first()

        if not sub:
            errors.append(f"Row {row_num}: Subject '{sub_ref}' not found.")
            failed += 1
            continue

        if is_aggregate:
            # Store in StudentAggregateAttendance without inventing fake individual sessions
            try:
                total_c = int(row.get('total_classes', 0)) if pd.notna(row.get('total_classes')) else 0
                attended_c = int(row.get('attended_classes', 0)) if pd.notna(row.get('attended_classes')) else 0
                pct = float(row.get('attendance_percentage', 0.0)) if pd.notna(row.get('attendance_percentage')) else 0.0
                if total_c > 0 and attended_c > 0 and pct == 0.0:
                    pct = round(attended_c / total_c * 100, 1)
            except ValueError:
                errors.append(f"Row {row_num}: Attendance counts must be numeric.")
                failed += 1
                continue

            agg = StudentAggregateAttendance.query.filter_by(student_id=student.id, subject_id=sub.id).first()
            if agg:
                if dup_policy == 'error':
                    errors.append(f"Row {row_num}: Aggregate attendance already exists for {roll} in {sub.code}.")
                    failed += 1
                    continue
                elif dup_policy == 'update':
                    agg.total_classes = total_c
                    agg.attended_classes = attended_c
                    agg.attendance_percentage = pct
                    imported += 1
                else:
                    skipped += 1
            else:
                agg = StudentAggregateAttendance(
                    student_id=student.id,
                    subject_id=sub.id,
                    total_classes=total_c,
                    attended_classes=attended_c,
                    attendance_percentage=pct
                )
                db.session.add(agg)
                imported += 1
        else:
            # Session Attendance Record
            date_str = str(row.get('date', row.get('session_date', ''))).strip()
            status_val = str(row.get('status', 'present')).strip().lower()

            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d').date() if '-' in date_str else date.today()
            except ValueError:
                errors.append(f"Row {row_num}: Invalid date format '{date_str}'. Expected YYYY-MM-DD.")
                failed += 1
                continue

            if status_val not in ['present', 'absent', 'late']:
                status_val = 'present'

            existing_att = AttendanceRecord.query.filter_by(
                student_id=student.id, subject_id=sub.id, date=dt
            ).first()

            if existing_att:
                if dup_policy == 'error':
                    errors.append(f"Row {row_num}: Session attendance already exists for {roll} on {dt}.")
                    failed += 1
                    continue
                elif dup_policy == 'update':
                    existing_att.status = status_val
                    imported += 1
                else:
                    skipped += 1
            else:
                att = AttendanceRecord(
                    student_id=student.id,
                    subject_id=sub.id,
                    date=dt,
                    status=status_val
                )
                db.session.add(att)
                imported += 1

    db.session.flush()
    return imported, skipped, failed, errors


def _trigger_ml_retraining(dept_id=None):
    """Retrain ML models using actual marks from the database when new data arrives."""
    try:
        with db.session.no_autoflush:
            depts = [Department.query.get(dept_id)] if dept_id else Department.query.filter_by(is_active=True).all()
        for d in depts:
            if not d: continue
            with db.session.no_autoflush:
                marks = Mark.query.join(Mark.student).filter(Student.department_id == d.id).all()
            data = []
            for m in marks:
                if m.examination:
                    data.append({
                        'student_id': m.student_id,
                        'subject_id': m.subject_id,
                        'exam_type': m.examination.exam_type,
                        'marks_obtained': m.marks_obtained,
                        'max_marks': m.examination.max_marks
                    })
            if data:
                df = pd.DataFrame(data)
                X, y, _ = prepare_training_data(df)
                if X is not None and len(X) >= 5:
                    path = get_model_path(d.id)
                    train_model(X, y, path)
    except Exception:
        pass


@admin_bp.route('/dataset/template/<category>')
@admin_required
def download_template(category):
    """Provide realistic downloadable sample templates for every dataset category."""
    sample_data = {
        'departments_sections': {
            'headers': ['department_code', 'department_name', 'section_name', 'semester', 'description'],
            'rows': [
                ['IT', 'Information Technology', 'A', '1', 'Department of Information Technology'],
                ['CS', 'Computer Science', 'A', '1', 'Department of Computer Science & Engineering'],
                ['EC', 'Electronics & Communication', 'A', '1', 'Department of Electronics']
            ]
        },
        'students': {
            'headers': ['roll_number', 'name', 'email', 'department_code', 'section', 'semester', 'gender'],
            'rows': [
                ['IT24050A', 'Aditya Verma', 'aditya.v@institution.edu', 'IT', 'A', '1', 'Male'],
                ['IT24051A', 'Pooja Iyer', 'pooja.i@institution.edu', 'IT', 'A', '1', 'Female'],
                ['CS24050A', 'Karan Mehta', 'karan.m@institution.edu', 'CS', 'A', '1', 'Male']
            ]
        },
        'faculty': {
            'headers': ['faculty_id', 'name', 'email', 'department_code', 'designation', 'assigned_subjects', 'assigned_sections'],
            'rows': [
                ['FACIT05', 'Dr. Ramesh Nair', 'ramesh.nair@institution.edu', 'IT', 'Associate Professor', 'IT101,IT201', 'A,B'],
                ['FACCS05', 'Prof. Sunita Rao', 'sunita.rao@institution.edu', 'CS', 'Assistant Professor', 'CS101', 'A']
            ]
        },
        'subjects': {
            'headers': ['subject_code', 'subject_name', 'department_code', 'semester', 'credits', 'subject_type'],
            'rows': [
                ['IT105', 'Computational Thinking', 'IT', '1', '3', 'theory'],
                ['IT106', 'Computing Laboratory', 'IT', '1', '2', 'lab'],
                ['CS105', 'Discrete Structures', 'CS', '1', '4', 'theory']
            ]
        },
        'examinations': {
            'headers': ['subject_code', 'name', 'exam_type', 'max_marks', 'semester'],
            'rows': [
                ['IT101', 'IA1', 'internal', '50', '1'],
                ['IT101', 'IA2', 'internal', '50', '1'],
                ['IT101', 'Semester Final Exam', 'semester', '100', '1']
            ]
        },
        'marks_long': {
            'headers': ['roll_number', 'subject_code', 'exam_name', 'marks_obtained', 'max_marks'],
            'rows': [
                ['IT24001A', 'IT101', 'IA1', '42.5', '50'],
                ['IT24001A', 'IT102', 'IA1', '38.0', '50'],
                ['IT24002A', 'IT101', 'IA1', '45.0', '50']
            ]
        },
        'marks_wide': {
            'headers': ['roll_number', 'exam_name', 'IT101', 'IT102', 'IT103', 'IT104'],
            'rows': [
                ['IT24001A', 'IA1', '42', '38', '45', '40'],
                ['IT24002A', 'IA1', '46', '44', '48', '42'],
                ['IT24003A', 'IA1', '35', '30', '34', '36']
            ]
        },
        'attendance_sessions': {
            'headers': ['roll_number', 'subject_code', 'date', 'status'],
            'rows': [
                ['IT24001A', 'IT101', '2026-10-25', 'present'],
                ['IT24001A', 'IT101', '2026-10-26', 'present'],
                ['IT24002A', 'IT101', '2026-10-25', 'absent']
            ]
        },
        'attendance_aggregate': {
            'headers': ['roll_number', 'subject_code', 'total_classes', 'attended_classes', 'attendance_percentage'],
            'rows': [
                ['IT24001A', 'IT101', '40', '35', '87.5'],
                ['IT24002A', 'IT101', '40', '28', '70.0'],
                ['IT24003A', 'IT101', '40', '38', '95.0']
            ]
        }
    }

    item = sample_data.get(category, sample_data['students'])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(item['headers'])
    for r in item['rows']:
        writer.writerow(r)
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'{category}_template.csv'
    )


@admin_bp.route('/dataset/errors/<int:history_id>')
@admin_required
def download_import_errors(history_id):
    """Download row-level validation errors from a specific import attempt."""
    history = ImportHistory.query.get_or_404(history_id)
    err_list = json.loads(history.error_summary) if history.error_summary else []

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Error Index', 'Worksheet', 'Row Number', 'Identifier', 'Rejected Value', 'Reason'])

    score_pattern = re.compile(r"Score \(([-+]?\d*\.?\d+)\)", re.IGNORECASE)
    row_pattern = re.compile(r"Row (\d+)", re.IGNORECASE)

    for i, err in enumerate(err_list, 1):
        if isinstance(err, dict):
            writer.writerow([
                i,
                err.get('worksheet', 'N/A'),
                err.get('row_number', 'N/A'),
                err.get('identifier', 'N/A'),
                err.get('rejected_value', 'N/A'),
                err.get('reason', err.get('message', ''))
            ])
        else:
            err_str = str(err)
            ws = 'N/A'
            for prefix in ['Marks', 'Attendance', 'Students', 'Faculty', 'Subjects', 'Examinations', 'Departments']:
                if err_str.startswith(prefix):
                    ws = prefix
                    break

            row_m = row_pattern.search(err_str)
            row_num = row_m.group(1) if row_m else 'N/A'

            score_m = score_pattern.search(err_str)
            rej_val = score_m.group(1) if score_m else 'N/A'

            # Identifier if present in brackets or text
            id_m = re.search(r"\[(.*?)\]", err_str) or re.search(r"student '([^']+)'", err_str) or re.search(r"for '([^']+)'", err_str)
            identifier = id_m.group(1) if id_m else 'N/A'

            reason = err_str.split(':', 1)[1].strip() if ':' in err_str else err_str
            writer.writerow([i, ws, row_num, identifier, rej_val, reason])

    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'import_errors_{history.category}_{history_id}.csv'
    )


# ==========================================
# Comprehensive Export Engine
# ==========================================

@admin_bp.route('/export/students')
@admin_required
def export_students():
    dept_id = request.args.get('dept_id')
    sec_id = request.args.get('section_id')
    export_fmt = request.args.get('format', 'csv')

    query = Student.query.filter_by(is_active=True)
    if dept_id and dept_id.isdigit():
        query = query.filter_by(department_id=int(dept_id))
    if sec_id and sec_id.isdigit():
        query = query.filter_by(section_id=int(sec_id))

    students = query.order_by(Student.roll_number).all()

    data = [{
        'Roll Number': s.roll_number,
        'Name': s.name,
        'Email': s.email or '',
        'Phone': s.phone or '',
        'Department': s.department.name if s.department else '',
        'Department Code': s.department.code if s.department else '',
        'Section': s.section.name if s.section else '',
        'Semester': s.current_semester,
        'Enrolled Date': s.enrolled_at.strftime('%Y-%m-%d') if s.enrolled_at else ''
    } for s in students]

    df = pd.DataFrame(data)
    if export_fmt == 'excel':
        out = io.BytesIO()
        df.to_excel(out, index=False, engine='openpyxl')
        out.seek(0)
        return send_file(out, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='students_export.xlsx')

    out = io.StringIO()
    df.to_csv(out, index=False)
    out.seek(0)
    return send_file(io.BytesIO(out.getvalue().encode()), mimetype='text/csv',
                     as_attachment=True, download_name='students_export.csv')


@admin_bp.route('/export/faculty')
@admin_required
def export_faculty():
    dept_id = request.args.get('dept_id')
    export_fmt = request.args.get('format', 'csv')

    query = Faculty.query.filter_by(is_active=True)
    if dept_id and dept_id.isdigit():
        query = query.filter_by(department_id=int(dept_id))
    fac_list = query.order_by(Faculty.faculty_id).all()

    data = []
    for f in fac_list:
        subs = ', '.join([a.subject.code for a in f.subject_assignments if a.subject])
        secs = ', '.join(set([a.section.name for a in f.subject_assignments if a.section]))
        data.append({
            'Faculty ID': f.faculty_id,
            'Name': f.name,
            'Email': f.email or '',
            'Phone': f.phone or '',
            'Department': f.department.name if f.department else '',
            'Designation': f.designation or '',
            'Assigned Subjects': subs,
            'Assigned Sections': secs
        })

    df = pd.DataFrame(data)
    if export_fmt == 'excel':
        out = io.BytesIO()
        df.to_excel(out, index=False, engine='openpyxl')
        out.seek(0)
        return send_file(out, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='faculty_export.xlsx')

    out = io.StringIO()
    df.to_csv(out, index=False)
    out.seek(0)
    return send_file(io.BytesIO(out.getvalue().encode()), mimetype='text/csv',
                     as_attachment=True, download_name='faculty_export.csv')


@admin_bp.route('/export/marks')
@admin_required
def export_marks():
    dept_id = request.args.get('dept_id')
    sem = request.args.get('semester')
    exam_id = request.args.get('exam_id')
    export_fmt = request.args.get('format', 'csv')

    query = Mark.query.join(Student).join(Subject).join(Examination)
    if dept_id and dept_id.isdigit():
        query = query.filter(Student.department_id == int(dept_id))
    if sem and sem.isdigit():
        query = query.filter(Subject.semester == int(sem))
    if exam_id and exam_id.isdigit():
        query = query.filter(Mark.examination_id == int(exam_id))

    marks = query.order_by(Student.roll_number).all()

    data = [{
        'Roll Number': m.student.roll_number if m.student else '',
        'Student Name': m.student.name if m.student else '',
        'Department': m.student.department.code if m.student and m.student.department else '',
        'Subject Code': m.subject.code if m.subject else '',
        'Subject Name': m.subject.name if m.subject else '',
        'Semester': m.subject.semester if m.subject else '',
        'Examination': m.examination.name if m.examination else '',
        'Exam Type': m.examination.exam_type if m.examination else '',
        'Marks Obtained': m.marks_obtained,
        'Max Marks': m.examination.max_marks if m.examination else 100,
        'Percentage': round(m.marks_obtained / m.examination.max_marks * 100, 1) if m.examination and m.examination.max_marks > 0 else 0
    } for m in marks]

    df = pd.DataFrame(data)
    if export_fmt == 'excel':
        out = io.BytesIO()
        df.to_excel(out, index=False, engine='openpyxl')
        out.seek(0)
        return send_file(out, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='marks_export.xlsx')

    out = io.StringIO()
    df.to_csv(out, index=False)
    out.seek(0)
    return send_file(io.BytesIO(out.getvalue().encode()), mimetype='text/csv',
                     as_attachment=True, download_name='marks_export.csv')


@admin_bp.route('/export/attendance')
@admin_required
def export_attendance():
    dept_id = request.args.get('dept_id')
    export_fmt = request.args.get('format', 'csv')

    query = AttendanceRecord.query.join(Student).join(Subject)
    if dept_id and dept_id.isdigit():
        query = query.filter(Student.department_id == int(dept_id))

    records = query.order_by(AttendanceRecord.date.desc()).all()

    data = [{
        'Roll Number': r.student.roll_number if r.student else '',
        'Student Name': r.student.name if r.student else '',
        'Department': r.student.department.code if r.student and r.student.department else '',
        'Subject Code': r.subject.code if r.subject else '',
        'Subject Name': r.subject.name if r.subject else '',
        'Date': r.date.strftime('%Y-%m-%d') if r.date else '',
        'Status': r.status
    } for r in records]

    df = pd.DataFrame(data)
    if export_fmt == 'excel':
        out = io.BytesIO()
        df.to_excel(out, index=False, engine='openpyxl')
        out.seek(0)
        return send_file(out, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='attendance_export.xlsx')

    out = io.StringIO()
    df.to_csv(out, index=False)
    out.seek(0)
    return send_file(io.BytesIO(out.getvalue().encode()), mimetype='text/csv',
                     as_attachment=True, download_name='attendance_export.csv')


@admin_bp.route('/export/analytics')
@admin_required
def export_analytics():
    dept_id = request.args.get('dept_id')
    export_fmt = request.args.get('format', 'csv')

    query = Department.query.filter_by(is_active=True)
    if dept_id and dept_id.isdigit():
        query = query.filter_by(id=int(dept_id))
    depts = query.all()

    data = []
    for d in depts:
        stus = Student.query.filter_by(department_id=d.id, is_active=True).all()
        stu_ids = [s.id for s in stus]
        marks = Mark.query.filter(Mark.student_id.in_(stu_ids)).all() if stu_ids else []
        avg_p = 0.0
        if marks:
            avg_p = round(sum(m.marks_obtained / m.examination.max_marks * 100 for m in marks if m.examination and m.examination.max_marks > 0) / len(marks), 1)
        atts = AttendanceRecord.query.filter(AttendanceRecord.student_id.in_(stu_ids)).all() if stu_ids else []
        att_p = 0.0
        if atts:
            att_p = round(sum(1 for a in atts if a.status == 'present') / len(atts) * 100, 1)

        data.append({
            'Department Code': d.code,
            'Department Name': d.name,
            'Enrolled Students': len(stus),
            'Assigned Faculty': len(d.faculty),
            'Subjects Count': len(d.subjects),
            'Average Marks %': avg_p,
            'Average Attendance %': att_p
        })

    df = pd.DataFrame(data)
    if export_fmt == 'excel':
        out = io.BytesIO()
        df.to_excel(out, index=False, engine='openpyxl')
        out.seek(0)
        return send_file(out, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='academic_analytics_export.xlsx')

    out = io.StringIO()
    df.to_csv(out, index=False)
    out.seek(0)
    return send_file(io.BytesIO(out.getvalue().encode()), mimetype='text/csv',
                     as_attachment=True, download_name='academic_analytics_export.csv')


@admin_bp.route('/analytics')
@admin_required
def analytics():
    departments = Department.query.filter_by(is_active=True).all()
    dept_analytics = []

    for dept in departments:
        students = Student.query.filter_by(department_id=dept.id, is_active=True).all()
        student_ids = [s.id for s in students]

        marks = Mark.query.filter(Mark.student_id.in_(student_ids)).all() if student_ids else []
        avg_pct = 0
        if marks:
            valid_marks = [m for m in marks if m.examination and m.examination.max_marks > 0]
            if valid_marks:
                total_pct = sum(m.marks_obtained / m.examination.max_marks * 100 for m in valid_marks)
                avg_pct = round(total_pct / len(valid_marks), 1)

        att_records = AttendanceRecord.query.filter(
            AttendanceRecord.student_id.in_(student_ids)).all() if student_ids else []
        att_pct = 0
        if att_records:
            present = sum(1 for a in att_records if a.status == 'present')
            att_pct = round(present / len(att_records) * 100, 1)

        dept_analytics.append({
            'dept': dept,
            'student_count': len(students),
            'avg_performance': avg_pct,
            'avg_attendance': att_pct,
        })

    return render_template('admin/analytics.html', dept_analytics=dept_analytics)


@admin_bp.route('/settings')
@admin_required
def settings():
    academic_years = AcademicYear.query.all()
    return render_template('admin/settings.html', academic_years=academic_years)


@admin_bp.route('/academic-years', methods=['POST'])
@admin_required
def add_academic_year():
    label = request.form.get('year_label', '').strip()
    is_current = request.form.get('is_current') == 'on'
    if label:
        if is_current:
            AcademicYear.query.update({'is_current': False})
        ay = AcademicYear(year_label=label, is_current=is_current)
        db.session.add(ay)
        db.session.commit()
        flash(f'Academic year {label} added!', 'success')
    return redirect(url_for('admin.settings'))

