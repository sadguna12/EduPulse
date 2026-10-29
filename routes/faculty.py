from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, date, timedelta
import csv
import io
import pandas as pd
from extensions import db
from models import (
    Faculty, Student, Subject, Section, Examination, Mark,
    AttendanceRecord, Question, StudentTask, FacultySubjectAssignment,
    Department, AcademicYear
)

faculty_bp = Blueprint('faculty', __name__)


def faculty_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'faculty':
            flash('Faculty access required.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return login_required(decorated)


def get_current_faculty():
    return Faculty.query.filter_by(user_id=current_user.id).first()


def get_faculty_sections(fac):
    """
    Returns distinct sections assigned to this faculty member.
    Falls back to department sections if direct assignments are not yet configured.
    """
    assignments = FacultySubjectAssignment.query.filter_by(faculty_id=fac.id, is_active=True).all()
    section_ids = list({a.section_id for a in assignments if a.section_id})
    if section_ids:
        return Section.query.filter(Section.id.in_(section_ids), Section.is_active == True).all()
    # Fallback to faculty's own department sections
    if fac.department_id:
        return Section.query.filter_by(department_id=fac.department_id, is_active=True).all()
    return []


def get_faculty_subjects(fac, section_id=None):
    """
    Returns subjects taught by this faculty member.
    Falls back to department subjects if direct assignments are not yet configured.
    """
    query = FacultySubjectAssignment.query.filter_by(faculty_id=fac.id, is_active=True)
    if section_id:
        query = query.filter_by(section_id=section_id)
    assignments = query.all()
    subject_ids = list({a.subject_id for a in assignments})
    if subject_ids:
        return Subject.query.filter(Subject.id.in_(subject_ids), Subject.is_active == True).all()
    if fac.department_id:
        return Subject.query.filter_by(department_id=fac.department_id, is_active=True).all()
    return []


def get_faculty_students(fac, section_id=None, subject_id=None, semester=None, academic_year_id=None):
    """
    Dynamically loads students assigned to this faculty member with multi-criteria filtering
    and strict backend department/section authorization.
    """
    sections = get_faculty_sections(fac)
    sec_ids = [s.id for s in sections]

    query = Student.query.filter(Student.is_active == True)
    if sec_ids and fac.department_id:
        query = query.filter(db.or_(Student.section_id.in_(sec_ids), Student.department_id == fac.department_id))
    elif sec_ids:
        query = query.filter(Student.section_id.in_(sec_ids))
    elif fac.department_id:
        query = query.filter(Student.department_id == fac.department_id)
    else:
        return []

    # Filter by section
    if section_id and str(section_id).isdigit():
        sec_int = int(section_id)
        if sec_int in sec_ids:
            query = query.filter(Student.section_id == sec_int)
        else:
            return []

    # Filter by semester
    if semester and str(semester).isdigit():
        query = query.filter(Student.current_semester == int(semester))

    # Filter by academic year
    if academic_year_id and str(academic_year_id).isdigit():
        query = query.filter(Student.academic_year_id == int(academic_year_id))

    # Filter by subject (students enrolled in that subject's semester/department)
    if subject_id and str(subject_id).isdigit():
        sub = Subject.query.get(int(subject_id))
        if sub and (sub.department_id == fac.department_id or sub.id in [s.id for s in get_faculty_subjects(fac)]):
            query = query.filter(Student.current_semester == sub.semester)
        else:
            return []

    return query.order_by(Student.roll_number).all()


@faculty_bp.route('/dashboard')
@faculty_required
def dashboard():
    fac = get_current_faculty()
    if not fac:
        flash('Faculty profile not found.', 'danger')
        return redirect(url_for('auth.login'))

    sections = get_faculty_sections(fac)
    subjects = get_faculty_subjects(fac)
    students = get_faculty_students(fac)

    # Recent exams in faculty subjects
    recent_exams = []
    if subjects:
        recent_exams = Examination.query.filter(
            Examination.subject_id.in_([s.id for s in subjects])
        ).order_by(Examination.created_at.desc()).limit(5).all()

    return render_template('faculty/dashboard.html',
                           faculty=fac,
                           sections=sections,
                           subjects=subjects,
                           student_count=len(students),
                           recent_exams=recent_exams)


@faculty_bp.route('/students')
@faculty_required
def my_students():
    fac = get_current_faculty()
    if not fac:
        return redirect(url_for('auth.login'))

    section_id = request.args.get('section_id', '')
    subject_id = request.args.get('subject_id', '')
    semester = request.args.get('semester', '')
    academic_year_id = request.args.get('academic_year_id', '')
    search = request.args.get('search', '').strip()

    sections = get_faculty_sections(fac)
    subjects = get_faculty_subjects(fac)
    academic_years = AcademicYear.query.order_by(AcademicYear.id.desc()).all()

    students = get_faculty_students(
        fac,
        section_id=section_id,
        subject_id=subject_id,
        semester=semester,
        academic_year_id=academic_year_id
    )

    if search:
        search_lower = search.lower()
        students = [s for s in students
                    if search_lower in s.name.lower() or search_lower in s.roll_number.lower()]

    return render_template('faculty/students.html',
                           faculty=fac,
                           students=students,
                           sections=sections,
                           subjects=subjects,
                           academic_years=academic_years,
                           section_id=section_id,
                           selected_subject_id=subject_id,
                           selected_semester=semester,
                           selected_ay_id=academic_year_id,
                           search=search)


@faculty_bp.route('/marks', methods=['GET', 'POST'])
@faculty_required
def marks():
    fac = get_current_faculty()
    if not fac:
        return redirect(url_for('auth.login'))

    sections = get_faculty_sections(fac)
    subjects = get_faculty_subjects(fac)
    academic_years = AcademicYear.query.all()
    examinations = []
    students_marks = []
    selected = {}

    auth_subject_ids = [s.id for s in subjects]
    auth_section_ids = [s.id for s in sections]

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'load':
            subj_id = request.form.get('subject_id')
            sec_id = request.form.get('section_id')
            exam_id = request.form.get('exam_id')
            selected = {'subject_id': subj_id, 'section_id': sec_id, 'exam_id': exam_id}

            if subj_id and sec_id:
                s_id = int(subj_id)
                sc_id = int(sec_id)
                # Authorization check
                if s_id not in auth_subject_ids or sc_id not in auth_section_ids:
                    flash('Unauthorized subject or section selected.', 'danger')
                    return redirect(url_for('faculty.marks'))

                examinations = Examination.query.filter_by(subject_id=s_id).all()
                section_students = Student.query.filter_by(
                    section_id=sc_id, is_active=True
                ).order_by(Student.roll_number).all()

                if exam_id:
                    for stu in section_students:
                        mark = Mark.query.filter_by(
                            student_id=stu.id, examination_id=int(exam_id)
                        ).first()
                        students_marks.append({'student': stu, 'mark': mark})

        elif action == 'save_marks':
            exam_id = request.form.get('exam_id')
            section_id = request.form.get('section_id')
            subject_id = request.form.get('subject_id')

            exam = Examination.query.get(exam_id)
            if not exam or exam.subject_id not in auth_subject_ids:
                flash('Unauthorized examination ID.', 'danger')
                return redirect(url_for('faculty.marks'))

            saved = 0
            errors = []

            for key, value in request.form.items():
                if key.startswith('mark_'):
                    stu_id = int(key.split('_')[1])
                    stu = Student.query.get(stu_id)
                    # Verify student belongs to faculty's authorized students
                    if not stu or stu.department_id != fac.department_id:
                        continue

                    try:
                        marks_val = float(value)
                        if marks_val < 0 or marks_val > exam.max_marks:
                            errors.append(f"Student {stu.roll_number}: Mark {marks_val} out of range (0-{exam.max_marks})")
                            continue

                        existing = Mark.query.filter_by(
                            student_id=stu_id, examination_id=exam.id
                        ).first()
                        if existing:
                            existing.marks_obtained = marks_val
                            existing.recorded_by = fac.id
                            existing.updated_at = datetime.utcnow()
                        else:
                            mark = Mark(
                                student_id=stu_id,
                                subject_id=exam.subject_id,
                                examination_id=exam.id,
                                marks_obtained=marks_val,
                                recorded_by=fac.id
                            )
                            db.session.add(mark)
                        saved += 1
                    except (ValueError, TypeError):
                        pass

            db.session.commit()
            flash(f'{saved} marks saved successfully!', 'success')
            if errors:
                for err in errors[:5]:
                    flash(err, 'warning')

            selected = {'subject_id': subject_id, 'section_id': section_id, 'exam_id': exam_id}
            return redirect(url_for('faculty.marks'))

        elif action == 'add_exam':
            subj_id = request.form.get('subject_id')
            exam_name = request.form.get('exam_name', '').strip()
            exam_type = request.form.get('exam_type', 'internal')
            max_marks = request.form.get('max_marks', 30)
            sec_id = request.form.get('section_id')
            ay_id = request.form.get('academic_year_id')
            exam_date_str = request.form.get('exam_date')

            if subj_id and exam_name:
                s_id = int(subj_id)
                if s_id not in auth_subject_ids:
                    flash('Unauthorized subject ID.', 'danger')
                    return redirect(url_for('faculty.marks'))

                existing = Examination.query.filter_by(
                    subject_id=s_id, name=exam_name,
                    section_id=int(sec_id) if sec_id else None
                ).first()
                if existing:
                    flash(f'Examination "{exam_name}" already exists for this subject/section.', 'warning')
                else:
                    exam_date = None
                    if exam_date_str:
                        try:
                            exam_date = date.fromisoformat(exam_date_str)
                        except ValueError:
                            pass
                    exam = Examination(
                        subject_id=s_id, name=exam_name, exam_type=exam_type,
                        max_marks=float(max_marks),
                        section_id=int(sec_id) if sec_id else None,
                        academic_year_id=int(ay_id) if ay_id else None,
                        exam_date=exam_date
                    )
                    db.session.add(exam)
                    db.session.commit()
                    flash(f'Examination "{exam_name}" created!', 'success')

            return redirect(url_for('faculty.marks'))

    if subjects:
        examinations = Examination.query.filter(
            Examination.subject_id.in_(auth_subject_ids)
        ).all()

    return render_template('faculty/marks.html',
                           faculty=fac,
                           sections=sections,
                           subjects=subjects,
                           examinations=examinations,
                           students_marks=students_marks,
                           selected=selected,
                           academic_years=academic_years)


@faculty_bp.route('/attendance', methods=['GET', 'POST'])
@faculty_required
def attendance():
    fac = get_current_faculty()
    if not fac:
        return redirect(url_for('auth.login'))

    sections = get_faculty_sections(fac)
    subjects = get_faculty_subjects(fac)
    students_att = []
    selected = {}

    auth_subject_ids = [s.id for s in subjects]
    auth_section_ids = [s.id for s in sections]

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'load':
            subj_id = request.form.get('subject_id')
            sec_id = request.form.get('section_id')
            att_date = request.form.get('date', date.today().isoformat())
            selected = {'subject_id': subj_id, 'section_id': sec_id, 'date': att_date}

            if subj_id and sec_id:
                s_id = int(subj_id)
                sc_id = int(sec_id)
                if s_id not in auth_subject_ids or sc_id not in auth_section_ids:
                    flash('Unauthorized subject or section selected.', 'danger')
                    return redirect(url_for('faculty.attendance'))

                section_students = Student.query.filter_by(
                    section_id=sc_id, is_active=True
                ).order_by(Student.roll_number).all()

                try:
                    att_date_obj = date.fromisoformat(att_date)
                except ValueError:
                    att_date_obj = date.today()

                for stu in section_students:
                    att_record = AttendanceRecord.query.filter_by(
                        student_id=stu.id, subject_id=s_id, date=att_date_obj
                    ).first()
                    students_att.append({'student': stu, 'record': att_record})

        elif action == 'save_attendance':
            subj_id = int(request.form.get('subject_id'))
            sec_id = int(request.form.get('section_id'))
            att_date_str = request.form.get('date', date.today().isoformat())

            if subj_id not in auth_subject_ids or sec_id not in auth_section_ids:
                flash('Unauthorized subject or section selected.', 'danger')
                return redirect(url_for('faculty.attendance'))

            try:
                att_date_obj = date.fromisoformat(att_date_str)
            except ValueError:
                att_date_obj = date.today()

            section_students = Student.query.filter_by(
                section_id=sec_id, is_active=True
            ).all()

            saved = 0
            for stu in section_students:
                status = request.form.get(f'status_{stu.id}', 'absent')
                if status not in ('present', 'absent', 'late'):
                    status = 'absent'

                existing = AttendanceRecord.query.filter_by(
                    student_id=stu.id, subject_id=subj_id, date=att_date_obj
                ).first()
                if existing:
                    existing.status = status
                    existing.recorded_by = fac.id
                else:
                    att = AttendanceRecord(
                        student_id=stu.id, subject_id=subj_id,
                        date=att_date_obj, status=status, recorded_by=fac.id
                    )
                    db.session.add(att)
                saved += 1

            db.session.commit()
            flash(f'Attendance saved for {saved} students on {att_date_str}!', 'success')
            return redirect(url_for('faculty.attendance'))

    return render_template('faculty/attendance.html',
                           faculty=fac,
                           sections=sections,
                           subjects=subjects,
                           students_att=students_att,
                           selected=selected,
                           today=date.today().isoformat())


@faculty_bp.route('/analytics')
@faculty_required
def analytics():
    fac = get_current_faculty()
    if not fac:
        return redirect(url_for('auth.login'))

    sections = get_faculty_sections(fac)
    subjects = get_faculty_subjects(fac)

    subject_analytics = []
    for subj in subjects:
        marks = Mark.query.filter_by(subject_id=subj.id).all()
        if marks:
            scores = [m.marks_obtained / m.examination.max_marks * 100
                      for m in marks if m.examination and m.examination.max_marks > 0]
            avg = round(sum(scores) / len(scores), 1) if scores else 0
            below_40 = sum(1 for s in scores if s < 40)
            above_75 = sum(1 for s in scores if s >= 75)
            subject_analytics.append({
                'subject': subj,
                'avg': avg,
                'below_40': below_40,
                'above_75': above_75,
                'total_marks': len(marks),
                'scores': [round(s, 1) for s in scores[:50]]
            })

    return render_template('faculty/analytics.html',
                           faculty=fac,
                           sections=sections,
                           subjects=subjects,
                           subject_analytics=subject_analytics)


@faculty_bp.route('/predictions')
@faculty_required
def predictions():
    fac = get_current_faculty()
    if not fac:
        return redirect(url_for('auth.login'))

    sections = get_faculty_sections(fac)
    students = get_faculty_students(fac)

    # Identify at-risk students (avg below 50%)
    at_risk = []
    for stu in students:
        marks = Mark.query.filter_by(student_id=stu.id).all()
        if marks:
            scores = [m.marks_obtained / m.examination.max_marks * 100
                      for m in marks if m.examination and m.examination.max_marks > 0]
            avg = sum(scores) / len(scores) if scores else 0
            if avg < 50:
                at_risk.append({'student': stu, 'avg': round(avg, 1)})

    from ml_pipeline import retrain_if_needed, get_model_path
    dept_id = fac.department_id

    marks_data = []
    for stu in students:
        for m in stu.marks:
            if m.examination:
                marks_data.append({
                    'student_id': stu.id,
                    'subject_id': m.subject_id,
                    'exam_type': m.examination.exam_type,
                    'marks_obtained': m.marks_obtained,
                    'max_marks': m.examination.max_marks,
                    'examination_id': m.examination_id,
                })

    ml_info = {"success": False, "reason": "no_data"}
    if marks_data:
        marks_df = pd.DataFrame(marks_data)
        model_path = get_model_path(dept_id)
        ml_info = retrain_if_needed(dept_id, marks_df, model_path)

    return render_template('faculty/predictions.html',
                           faculty=fac,
                           at_risk=at_risk,
                           sections=sections,
                           ml_info=ml_info)


@faculty_bp.route('/questions', methods=['GET', 'POST'])
@faculty_required
def questions():
    fac = get_current_faculty()
    if not fac:
        return redirect(url_for('auth.login'))

    subjects = get_faculty_subjects(fac)
    auth_subject_ids = [s.id for s in subjects]

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            subj_id = request.form.get('subject_id')
            q_text = request.form.get('question_text', '').strip()
            opt_a = request.form.get('option_a', '').strip()
            opt_b = request.form.get('option_b', '').strip()
            opt_c = request.form.get('option_c', '').strip()
            opt_d = request.form.get('option_d', '').strip()
            correct = request.form.get('correct_answer', '').strip().upper()
            topic = request.form.get('topic', '').strip()
            difficulty = request.form.get('difficulty', 'medium')
            explanation = request.form.get('explanation', '').strip()

            if not q_text or not subj_id:
                flash('Question text and subject are required.', 'danger')
            elif int(subj_id) not in auth_subject_ids:
                flash('Unauthorized subject selection.', 'danger')
            else:
                q = Question(
                    subject_id=int(subj_id), question_text=q_text,
                    option_a=opt_a, option_b=opt_b, option_c=opt_c, option_d=opt_d,
                    correct_answer=correct if correct in ('A', 'B', 'C', 'D') else None,
                    topic=topic, difficulty=difficulty, explanation=explanation,
                    question_type='mcq' if opt_a else 'descriptive',
                    created_by=fac.id
                )
                db.session.add(q)
                db.session.commit()
                flash('Question added to Question Bank!', 'success')

        elif action == 'delete':
            q_id = request.form.get('question_id')
            q = Question.query.get(q_id)
            if q and (q.created_by == fac.id or q.subject_id in auth_subject_ids):
                q.is_active = False
                db.session.commit()
                flash('Question removed from active bank.', 'success')

        return redirect(url_for('faculty.questions'))

    subj_filter = request.args.get('subject_id', '')
    query = Question.query.filter(
        Question.subject_id.in_(auth_subject_ids),
        Question.is_active == True
    )
    if subj_filter and subj_filter.isdigit():
        query = query.filter_by(subject_id=int(subj_filter))
    question_list = query.order_by(Question.created_at.desc()).all()

    return render_template('faculty/questions.html',
                           faculty=fac,
                           subjects=subjects,
                           questions=question_list,
                           subj_filter=subj_filter)


@faculty_bp.route('/tasks', methods=['GET', 'POST'])
@faculty_required
def tasks():
    fac = get_current_faculty()
    if not fac:
        return redirect(url_for('auth.login'))

    sections = get_faculty_sections(fac)
    subjects = get_faculty_subjects(fac)
    students = get_faculty_students(fac)
    auth_student_ids = [s.id for s in students]

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            stu_id = request.form.get('student_id')
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            subj_id = request.form.get('subject_id')
            due_date_str = request.form.get('due_date')
            priority = request.form.get('priority', 'medium')

            if not stu_id or not title:
                flash('Student and task title are required.', 'danger')
            elif int(stu_id) not in auth_student_ids:
                flash('Unauthorized student selected.', 'danger')
            else:
                try:
                    due_date = date.fromisoformat(due_date_str) if due_date_str else None
                except ValueError:
                    due_date = None

                task = StudentTask(
                    student_id=int(stu_id), title=title, description=description,
                    subject_id=int(subj_id) if subj_id else None,
                    assigned_by=fac.id, due_date=due_date, priority=priority
                )
                db.session.add(task)
                db.session.commit()
                flash('Task assigned successfully!', 'success')

        return redirect(url_for('faculty.tasks'))

    tasks_list = StudentTask.query.filter_by(assigned_by=fac.id).order_by(StudentTask.created_at.desc()).all()

    return render_template('faculty/tasks.html',
                           faculty=fac,
                           sections=sections,
                           subjects=subjects,
                           students=students,
                           tasks=tasks_list)


@faculty_bp.route('/reports')
@faculty_required
def reports():
    fac = get_current_faculty()
    if not fac:
        return redirect(url_for('auth.login'))

    sections = get_faculty_sections(fac)
    subjects = get_faculty_subjects(fac)
    return render_template('faculty/reports.html', faculty=fac, sections=sections, subjects=subjects)


@faculty_bp.route('/export/marks')
@faculty_required
def export_marks():
    fac = get_current_faculty()
    students = get_faculty_students(fac)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Roll Number', 'Name', 'Subject', 'Examination', 'Marks Obtained', 'Max Marks', 'Percentage'])

    for stu in students:
        for mark in stu.marks:
            if mark.examination:
                pct = round(mark.marks_obtained / mark.examination.max_marks * 100, 1) if mark.examination.max_marks > 0 else 0
                writer.writerow([
                    stu.roll_number, stu.name, mark.subject.name if mark.subject else '',
                    mark.examination.name, mark.marks_obtained,
                    mark.examination.max_marks, pct
                ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'faculty_marks_{fac.faculty_id}.csv'
    )


@faculty_bp.route('/export/students')
@faculty_required
def export_students():
    fac = get_current_faculty()
    students = get_faculty_students(fac)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Roll Number', 'Name', 'Department', 'Email', 'Section', 'Semester'])
    for stu in students:
        writer.writerow([
            stu.roll_number, stu.name,
            stu.department.code if stu.department else '',
            stu.email or '',
            stu.section.name if stu.section else '',
            stu.current_semester
        ])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'faculty_students_{fac.faculty_id}.csv'
    )


@faculty_bp.route('/export/attendance')
@faculty_required
def export_attendance():
    fac = get_current_faculty()
    subjects = get_faculty_subjects(fac)
    subj_ids = [s.id for s in subjects]
    records = AttendanceRecord.query.filter(AttendanceRecord.subject_id.in_(subj_ids)).order_by(AttendanceRecord.date.desc()).all() if subj_ids else []

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Roll Number', 'Student Name', 'Subject Code', 'Subject Name', 'Date', 'Status'])
    for r in records:
        writer.writerow([
            r.student.roll_number if r.student else '',
            r.student.name if r.student else '',
            r.subject.code if r.subject else '',
            r.subject.name if r.subject else '',
            r.date.strftime('%Y-%m-%d') if r.date else '',
            r.status
        ])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'faculty_attendance_{fac.faculty_id}.csv'
    )
