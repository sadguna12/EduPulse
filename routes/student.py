from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, jsonify
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, date, timedelta
import csv
import io
import random
import pandas as pd
from extensions import db
from models import (
    Student, Subject, Mark, AttendanceRecord, Examination,
    Question, QuestionAttempt, StudentTask, StudentGoal, MotivationalQuote, Department
)
from ml_pipeline import predict_for_student, generate_recommendations, get_weak_areas, get_model_path

student_bp = Blueprint('student', __name__)


def student_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'student':
            flash('Student access required.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return login_required(decorated)


def get_current_student():
    return Student.query.filter_by(user_id=current_user.id).first()


def get_student_marks_df(student):
    """Returns a pandas DataFrame of the student's marks."""
    marks = Mark.query.filter_by(student_id=student.id).all()
    data = []
    for m in marks:
        if m.examination:
            data.append({
                'student_id': student.id,
                'subject_id': m.subject_id,
                'subject_name': m.subject.name if m.subject else 'Unknown',
                'exam_type': m.examination.exam_type,
                'exam_name': m.examination.name,
                'marks_obtained': m.marks_obtained,
                'max_marks': m.examination.max_marks,
                'examination_id': m.examination_id,
                'recorded_at': m.recorded_at,
            })
    return pd.DataFrame(data) if data else pd.DataFrame()


def get_student_attendance_df(student):
    records = AttendanceRecord.query.filter_by(student_id=student.id).all()
    data = [{'student_id': student.id, 'subject_id': r.subject_id, 'date': r.date,
              'status': r.status} for r in records]
    return pd.DataFrame(data) if data else pd.DataFrame()


@student_bp.route('/dashboard')
@student_required
def dashboard():
    stu = get_current_student()
    if not stu:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('auth.login'))

    marks_df = get_student_marks_df(stu)
    att_df = get_student_attendance_df(stu)

    # Overall stats
    overall_avg = 0
    subject_avgs = []
    if not marks_df.empty:
        marks_df['pct'] = marks_df['marks_obtained'] / marks_df['max_marks'].replace(0, 1) * 100
        overall_avg = round(marks_df['pct'].mean(), 1)
        subj_avg = marks_df.groupby('subject_name')['pct'].mean().reset_index()
        subject_avgs = subj_avg.to_dict('records')

    att_pct = 0
    if not att_df.empty:
        total = len(att_df)
        present = len(att_df[att_df['status'] == 'present'])
        att_pct = round(present / total * 100, 1) if total > 0 else 0

    # Random motivational quote
    quotes = MotivationalQuote.query.all()
    quote = random.choice(quotes) if quotes else None

    # Pending tasks
    pending_tasks = StudentTask.query.filter_by(
        student_id=stu.id, is_completed=False
    ).order_by(StudentTask.due_date).limit(5).all()

    # Recent marks
    recent_marks = Mark.query.filter_by(student_id=stu.id).order_by(Mark.recorded_at.desc()).limit(5).all()

    return render_template('student/dashboard.html',
                           student=stu,
                           overall_avg=overall_avg,
                           att_pct=att_pct,
                           subject_avgs=subject_avgs,
                           quote=quote,
                           pending_tasks=pending_tasks,
                           recent_marks=recent_marks)


@student_bp.route('/performance')
@student_required
def performance():
    stu = get_current_student()
    if not stu:
        return redirect(url_for('auth.login'))

    marks_df = get_student_marks_df(stu)
    subject_data = []

    if not marks_df.empty:
        marks_df['pct'] = marks_df['marks_obtained'] / marks_df['max_marks'].replace(0, 1) * 100
        for subj_name, group in marks_df.groupby('subject_name'):
            exams = group.to_dict('records')
            avg = round(group['pct'].mean(), 1)
            subject_data.append({
                'name': subj_name,
                'avg': avg,
                'exams': exams,
                'grade': _get_grade(avg)
            })

    all_marks = Mark.query.filter_by(student_id=stu.id).order_by(Mark.recorded_at.desc()).all()

    return render_template('student/performance.html',
                           student=stu,
                           subject_data=subject_data,
                           all_marks=all_marks)


def _get_grade(pct):
    if pct >= 90: return 'A+'
    if pct >= 80: return 'A'
    if pct >= 70: return 'B+'
    if pct >= 60: return 'B'
    if pct >= 50: return 'C'
    if pct >= 40: return 'D'
    return 'F'


@student_bp.route('/prediction')
@student_required
def prediction():
    stu = get_current_student()
    if not stu:
        return redirect(url_for('auth.login'))

    marks_df = get_student_marks_df(stu)
    att_df = get_student_attendance_df(stu)

    # Get prediction
    dept_id = stu.department_id
    model_path = get_model_path(dept_id)

    prediction_result = None
    recommendations = []

    if not marks_df.empty:
        prediction_result = predict_for_student(stu.id, marks_df, model_path)
        recommendations = generate_recommendations(stu.id, marks_df, att_df)

    # Historical trend (last 5 exams)
    trend_data = []
    if not marks_df.empty:
        marks_df['pct'] = marks_df['marks_obtained'] / marks_df['max_marks'].replace(0, 1) * 100
        by_exam = marks_df.groupby('exam_name')['pct'].mean().reset_index()
        trend_data = by_exam.to_dict('records')

    return render_template('student/prediction.html',
                           student=stu,
                           prediction=prediction_result,
                           recommendations=recommendations,
                           trend_data=trend_data)


@student_bp.route('/weak-areas')
@student_required
def weak_areas():
    stu = get_current_student()
    if not stu:
        return redirect(url_for('auth.login'))

    marks_df = get_student_marks_df(stu)
    weak = []
    strong = []

    if not marks_df.empty:
        marks_df['pct'] = marks_df['marks_obtained'] / marks_df['max_marks'].replace(0, 1) * 100
        subj_avg = marks_df.groupby(['subject_id', 'subject_name'])['pct'].mean().reset_index()
        for _, row in subj_avg.iterrows():
            item = {'subject_name': row['subject_name'], 'avg_pct': round(row['pct'], 1)}
            if row['pct'] < 60:
                weak.append(item)
            elif row['pct'] >= 75:
                strong.append(item)

    return render_template('student/weak_areas.html',
                           student=stu,
                           weak_areas=weak,
                           strong_areas=strong)


@student_bp.route('/attendance')
@student_required
def attendance():
    stu = get_current_student()
    if not stu:
        return redirect(url_for('auth.login'))

    # Subject-wise attendance
    subjects = Subject.query.filter_by(department_id=stu.department_id,
                                       semester=stu.current_semester).all()
    subject_att = []
    for subj in subjects:
        records = AttendanceRecord.query.filter_by(student_id=stu.id, subject_id=subj.id).all()
        total = len(records)
        present = sum(1 for r in records if r.status == 'present')
        pct = round(present / total * 100, 1) if total > 0 else 0
        subject_att.append({
            'subject': subj,
            'total': total,
            'present': present,
            'absent': total - present,
            'pct': pct,
            'status': 'good' if pct >= 75 else ('warning' if pct >= 60 else 'danger')
        })

    # Recent attendance records
    recent_records = AttendanceRecord.query.filter_by(student_id=stu.id).order_by(
        AttendanceRecord.date.desc()).limit(30).all()

    # Overall
    all_records = AttendanceRecord.query.filter_by(student_id=stu.id).all()
    overall_total = len(all_records)
    overall_present = sum(1 for r in all_records if r.status == 'present')
    overall_pct = round(overall_present / overall_total * 100, 1) if overall_total > 0 else 0

    return render_template('student/attendance.html',
                           student=stu,
                           subject_att=subject_att,
                           recent_records=recent_records,
                           overall_pct=overall_pct,
                           overall_present=overall_present,
                           overall_total=overall_total)


@student_bp.route('/study-plan')
@student_required
def study_plan():
    stu = get_current_student()
    if not stu:
        return redirect(url_for('auth.login'))

    tasks = StudentTask.query.filter_by(student_id=stu.id).order_by(
        StudentTask.is_completed, StudentTask.due_date
    ).all()

    marks_df = get_student_marks_df(stu)
    weak = []
    if not marks_df.empty:
        marks_df['pct'] = marks_df['marks_obtained'] / marks_df['max_marks'].replace(0, 1) * 100
        subj_avg = marks_df.groupby('subject_name')['pct'].mean()
        weak = [s for s, avg in subj_avg.items() if avg < 60]

    return render_template('student/study_plan.html',
                           student=stu,
                           tasks=tasks,
                           weak_subjects=weak)


@student_bp.route('/complete-task/<int:task_id>', methods=['POST'])
@student_required
def complete_task(task_id):
    stu = get_current_student()
    task = StudentTask.query.get_or_404(task_id)
    if task.student_id != stu.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('student.study_plan'))
    task.is_completed = not task.is_completed
    task.completed_at = datetime.utcnow() if task.is_completed else None
    db.session.commit()
    flash(f'Task {"completed" if task.is_completed else "reopened"}!', 'success')
    return redirect(url_for('student.study_plan'))


@student_bp.route('/practice')
@student_required
def practice():
    stu = get_current_student()
    if not stu:
        return redirect(url_for('auth.login'))

    subjects = Subject.query.filter_by(department_id=stu.department_id,
                                       semester=stu.current_semester).all()
    subj_filter = request.args.get('subject_id', '')
    diff_filter = request.args.get('difficulty', '')

    query = Question.query.filter(
        Question.subject_id.in_([s.id for s in subjects]),
        Question.is_active == True,
        Question.question_type == 'mcq'
    )
    if subj_filter:
        query = query.filter_by(subject_id=int(subj_filter))
    if diff_filter:
        query = query.filter_by(difficulty=diff_filter)

    questions = query.all()

    # Attempt stats
    attempt_counts = {}
    for q in questions:
        attempts = QuestionAttempt.query.filter_by(student_id=stu.id, question_id=q.id).count()
        correct = QuestionAttempt.query.filter_by(student_id=stu.id, question_id=q.id, is_correct=True).count()
        attempt_counts[q.id] = {'total': attempts, 'correct': correct}

    return render_template('student/practice.html',
                           student=stu,
                           subjects=subjects,
                           questions=questions,
                           attempt_counts=attempt_counts,
                           subj_filter=subj_filter,
                           diff_filter=diff_filter)


@student_bp.route('/attempt-question/<int:question_id>', methods=['POST'])
@student_required
def attempt_question(question_id):
    stu = get_current_student()
    q = Question.query.get_or_404(question_id)
    answer = request.form.get('answer', '').strip().upper()

    is_correct = (answer == q.correct_answer) if q.correct_answer else None
    attempt = QuestionAttempt(
        student_id=stu.id, question_id=q.id,
        answer_given=answer, is_correct=is_correct
    )
    db.session.add(attempt)
    db.session.commit()

    if is_correct:
        flash(f'✅ Correct! {q.explanation or ""}', 'success')
    else:
        flash(f'❌ Incorrect. Correct answer: {q.correct_answer}. {q.explanation or ""}', 'danger')

    return redirect(url_for('student.practice', subject_id=request.args.get('subject_id', '')))


@student_bp.route('/self-improvement', methods=['GET', 'POST'])
@student_required
def self_improvement():
    stu = get_current_student()
    if not stu:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_goal':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            target_date_str = request.form.get('target_date')
            if title:
                try:
                    target_date = date.fromisoformat(target_date_str) if target_date_str else None
                except ValueError:
                    target_date = None
                goal = StudentGoal(student_id=stu.id, title=title,
                                   description=description, target_date=target_date)
                db.session.add(goal)
                db.session.commit()
                flash('Goal added!', 'success')

        elif action == 'update_goal':
            goal_id = request.form.get('goal_id')
            progress = request.form.get('progress', 0)
            goal = StudentGoal.query.get(goal_id)
            if goal and goal.student_id == stu.id:
                goal.progress_percent = int(progress)
                goal.is_achieved = goal.progress_percent >= 100
                db.session.commit()
                flash('Goal updated!', 'success')

        return redirect(url_for('student.self_improvement'))

    goals = StudentGoal.query.filter_by(student_id=stu.id).order_by(StudentGoal.created_at.desc()).all()
    completed_tasks = StudentTask.query.filter_by(student_id=stu.id, is_completed=True).count()
    total_tasks = StudentTask.query.filter_by(student_id=stu.id).count()

    return render_template('student/self_improvement.html',
                           student=stu,
                           goals=goals,
                           completed_tasks=completed_tasks,
                           total_tasks=total_tasks)


@student_bp.route('/reports')
@student_required
def reports():
    stu = get_current_student()
    if not stu:
        return redirect(url_for('auth.login'))
    return render_template('student/reports.html', student=stu)


@student_bp.route('/download/marks')
@student_required
def download_marks():
    stu = get_current_student()
    marks = Mark.query.filter_by(student_id=stu.id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Subject', 'Examination', 'Type', 'Marks Obtained', 'Max Marks', 'Percentage', 'Date'])
    for m in marks:
        if m.examination:
            pct = round(m.marks_obtained / m.examination.max_marks * 100, 1) if m.examination.max_marks > 0 else 0
            writer.writerow([
                m.subject.name if m.subject else '', m.examination.name,
                m.examination.exam_type, m.marks_obtained,
                m.examination.max_marks, pct,
                m.recorded_at.strftime('%Y-%m-%d') if m.recorded_at else ''
            ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'{stu.roll_number}_marks.csv'
    )


@student_bp.route('/download/attendance')
@student_required
def download_attendance():
    stu = get_current_student()
    records = AttendanceRecord.query.filter_by(student_id=stu.id).order_by(AttendanceRecord.date).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Subject', 'Date', 'Status'])
    for r in records:
        writer.writerow([
            r.subject.name if r.subject else '',
            r.date.isoformat(),
            r.status
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'{stu.roll_number}_attendance.csv'
    )
