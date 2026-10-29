from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from models import Department, Subject, Section, Student, Mark, AttendanceRecord, Examination
from extensions import db

api_bp = Blueprint('api', __name__)


@api_bp.route('/departments')
@login_required
def get_departments():
    depts = Department.query.filter_by(is_active=True).all()
    return jsonify([{'id': d.id, 'name': d.name, 'code': d.code} for d in depts])


@api_bp.route('/subjects/<int:dept_id>/<int:semester>')
@login_required
def get_subjects(dept_id, semester):
    subjects = Subject.query.filter_by(department_id=dept_id, semester=semester, is_active=True).all()
    return jsonify([{'id': s.id, 'name': s.name, 'code': s.code} for s in subjects])


@api_bp.route('/sections/<int:dept_id>')
@login_required
def get_sections(dept_id):
    semester = request.args.get('semester', type=int)
    query = Section.query.filter_by(department_id=dept_id, is_active=True)
    if semester:
        query = query.filter_by(semester=semester)
    sections = query.all()
    return jsonify([{'id': s.id, 'name': s.name, 'semester': s.semester} for s in sections])


@api_bp.route('/examinations/<int:subject_id>')
@login_required
def get_examinations(subject_id):
    section_id = request.args.get('section_id', type=int)
    query = Examination.query.filter_by(subject_id=subject_id, is_active=True)
    if section_id:
        query = query.filter_by(section_id=section_id)
    exams = query.all()
    return jsonify([{'id': e.id, 'name': e.name, 'type': e.exam_type,
                     'max_marks': e.max_marks} for e in exams])


@api_bp.route('/students/<int:section_id>')
@login_required
def get_section_students(section_id):
    if current_user.role == 'student':
        return jsonify({'error': 'Access denied'}), 403
    students = Student.query.filter_by(section_id=section_id, is_active=True).order_by(Student.roll_number).all()
    return jsonify([{'id': s.id, 'name': s.name, 'roll_number': s.roll_number} for s in students])


@api_bp.route('/chart/performance/<int:student_id>')
@login_required
def student_performance_chart(student_id):
    # Authorization check
    if current_user.role == 'student':
        from models import Student
        stu = Student.query.filter_by(user_id=current_user.id).first()
        if not stu or stu.id != student_id:
            return jsonify({'error': 'Access denied'}), 403

    marks = Mark.query.filter_by(student_id=student_id).all()
    data = {}
    for m in marks:
        if m.examination and m.subject:
            subj = m.subject.name
            pct = round(m.marks_obtained / m.examination.max_marks * 100, 1) if m.examination.max_marks > 0 else 0
            if subj not in data:
                data[subj] = []
            data[subj].append(pct)

    result = {
        'labels': list(data.keys()),
        'averages': [round(sum(v) / len(v), 1) for v in data.values()]
    }
    return jsonify(result)


@api_bp.route('/chart/attendance/<int:student_id>')
@login_required
def student_attendance_chart(student_id):
    if current_user.role == 'student':
        from models import Student
        stu = Student.query.filter_by(user_id=current_user.id).first()
        if not stu or stu.id != student_id:
            return jsonify({'error': 'Access denied'}), 403

    records = AttendanceRecord.query.filter_by(student_id=student_id).all()
    from collections import defaultdict
    by_subject = defaultdict(lambda: {'present': 0, 'total': 0})
    for r in records:
        subj_name = r.subject.name if r.subject else 'Unknown'
        by_subject[subj_name]['total'] += 1
        if r.status == 'present':
            by_subject[subj_name]['present'] += 1

    labels = list(by_subject.keys())
    percentages = [
        round(by_subject[s]['present'] / by_subject[s]['total'] * 100, 1)
        if by_subject[s]['total'] > 0 else 0
        for s in labels
    ]
    return jsonify({'labels': labels, 'percentages': percentages})
