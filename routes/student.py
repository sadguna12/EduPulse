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
    Student, Subject, Mark, AttendanceRecord, StudentAggregateAttendance, Examination,
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
    """
    Returns a pandas DataFrame of attendance records.
    Seamlessly supports both daily session logs and aggregate attendance records.
    """
    records = AttendanceRecord.query.filter_by(student_id=student.id).all()
    if records:
        data = [{'student_id': student.id, 'subject_id': r.subject_id, 'date': r.date,
                 'status': r.status} for r in records]
        return pd.DataFrame(data)

    # Fallback to StudentAggregateAttendance
    aggs = StudentAggregateAttendance.query.filter_by(student_id=student.id).all()
    if aggs:
        data = []
        for a in aggs:
            for _ in range(a.attended_classes):
                data.append({'student_id': student.id, 'subject_id': a.subject_id, 'date': date.today(), 'status': 'present'})
            for _ in range(max(0, a.total_classes - a.attended_classes)):
                data.append({'student_id': student.id, 'subject_id': a.subject_id, 'date': date.today(), 'status': 'absent'})
        return pd.DataFrame(data) if data else pd.DataFrame()

    return pd.DataFrame()


def _get_grade(pct):
    if pct >= 90: return 'A+'
    if pct >= 80: return 'A'
    if pct >= 70: return 'B+'
    if pct >= 60: return 'B'
    if pct >= 50: return 'C'
    if pct >= 40: return 'D'
    return 'F'


@student_bp.route('/dashboard')
@student_required
def dashboard():
    stu = get_current_student()
    if not stu:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('auth.login'))

    marks_df = get_student_marks_df(stu)
    att_df = get_student_attendance_df(stu)

    # Overall marks average & subject averages
    overall_avg = 0
    subject_avgs = []
    if not marks_df.empty:
        marks_df['pct'] = marks_df['marks_obtained'] / marks_df['max_marks'].replace(0, 1) * 100
        overall_avg = round(marks_df['pct'].mean(), 1)
        subj_avg = marks_df.groupby('subject_name')['pct'].mean().reset_index()
        subject_avgs = subj_avg.to_dict('records')

    # Overall attendance percentage
    att_pct = 0
    if not att_df.empty:
        total = len(att_df)
        present = len(att_df[att_df['status'] == 'present'])
        att_pct = round(present / total * 100, 1) if total > 0 else 0
    else:
        # Check aggregate records directly
        aggs = StudentAggregateAttendance.query.filter_by(student_id=stu.id).all()
        if aggs:
            tot = sum(a.total_classes for a in aggs)
            att = sum(a.attended_classes for a in aggs)
            att_pct = round(att / tot * 100, 1) if tot > 0 else 0

    # Registered subjects count
    registered_subjects = Subject.query.filter_by(department_id=stu.department_id, semester=stu.current_semester).all()
    if not registered_subjects:
        registered_subjects = Subject.query.filter_by(department_id=stu.department_id).all()
    subject_count = len(registered_subjects) if registered_subjects else len(subject_avgs)

    # Random motivational quote
    quotes = MotivationalQuote.query.all()
    quote = random.choice(quotes) if quotes else None

    # Pending tasks
    pending_tasks = StudentTask.query.filter_by(
        student_id=stu.id, is_completed=False
    ).order_by(StudentTask.due_date).limit(5).all()

    # If no tasks exist, automatically generate personalized weekly study tasks
    if not pending_tasks and StudentTask.query.filter_by(student_id=stu.id).count() == 0:
        _generate_deterministic_study_plan(stu)
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
                           subject_count=subject_count,
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


@student_bp.route('/prediction')
@student_required
def prediction():
    stu = get_current_student()
    if not stu:
        return redirect(url_for('auth.login'))

    marks_df = get_student_marks_df(stu)
    att_df = get_student_attendance_df(stu)

    # ML or statistical prediction
    dept_id = stu.department_id
    model_path = get_model_path(dept_id)

    prediction_result = None
    recommendations = []

    if not marks_df.empty:
        prediction_result = predict_for_student(stu.id, marks_df, model_path)
        recommendations = generate_recommendations(stu.id, marks_df, att_df)

    # Historical trend by exam
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

    # Subject-wise attendance calculation
    subjects = Subject.query.filter_by(department_id=stu.department_id,
                                       semester=stu.current_semester).all()
    if not subjects:
        subjects = Subject.query.filter_by(department_id=stu.department_id).all()

    subject_att = []
    total_classes_all = 0
    attended_classes_all = 0

    for subj in subjects:
        records = AttendanceRecord.query.filter_by(student_id=stu.id, subject_id=subj.id).all()
        agg = StudentAggregateAttendance.query.filter_by(student_id=stu.id, subject_id=subj.id).first()

        if records:
            total = len(records)
            present = sum(1 for r in records if r.status == 'present')
            pct = round(present / total * 100, 1) if total > 0 else 0
        elif agg:
            total = agg.total_classes
            present = agg.attended_classes
            pct = agg.attendance_percentage or (round(present / total * 100, 1) if total > 0 else 0)
        else:
            total = 0
            present = 0
            pct = 0

        total_classes_all += total
        attended_classes_all += present

        subject_att.append({
            'subject': subj,
            'total': total,
            'present': present,
            'absent': total - present,
            'pct': pct,
            'status': 'good' if pct >= 75 else ('warning' if pct >= 60 else 'danger')
        })

    # Overall Attendance stats
    overall_pct = round(attended_classes_all / total_classes_all * 100, 1) if total_classes_all > 0 else 0

    # Recent session records (if session-based logs exist)
    recent_records = AttendanceRecord.query.filter_by(student_id=stu.id).order_by(
        AttendanceRecord.date.desc()).limit(30).all()

    return render_template('student/attendance.html',
                           student=stu,
                           subject_att=subject_att,
                           recent_records=recent_records,
                           overall_pct=overall_pct,
                           overall_present=attended_classes_all,
                           overall_total=total_classes_all)


def _generate_deterministic_study_plan(stu):
    """
    Deterministic rule-based weekly study plan generator.
    Evaluates:
    - Subject-wise marks and exam scores
    - Attendance rates
    - Practice question accuracy
    - Incomplete tasks
    Generates structured StudentTask items linked to the student's actual enrolled subjects.
    """
    subjects = Subject.query.filter_by(department_id=stu.department_id, semester=stu.current_semester).all()
    if not subjects:
        subjects = Subject.query.filter_by(department_id=stu.department_id).all()

    if not subjects:
        return

    # Delete auto-generated incomplete tasks older than 7 days if regenerating
    StudentTask.query.filter_by(student_id=stu.id, is_completed=False, assigned_by=None).delete()

    today = date.today()
    marks_df = get_student_marks_df(stu)
    subj_scores = {}
    if not marks_df.empty:
        marks_df['pct'] = marks_df['marks_obtained'] / marks_df['max_marks'].replace(0, 1) * 100
        for subj_id, grp in marks_df.groupby('subject_id'):
            subj_scores[subj_id] = grp['pct'].mean()

    # Attendance rates
    subj_att = {}
    for s in subjects:
        recs = AttendanceRecord.query.filter_by(student_id=stu.id, subject_id=s.id).all()
        agg = StudentAggregateAttendance.query.filter_by(student_id=stu.id, subject_id=s.id).first()
        if recs:
            subj_att[s.id] = (sum(1 for r in recs if r.status == 'present') / len(recs) * 100) if len(recs) > 0 else 100
        elif agg and agg.total_classes > 0:
            subj_att[s.id] = agg.attendance_percentage or (agg.attended_classes / agg.total_classes * 100)
        else:
            subj_att[s.id] = 85.0

    # Practice question attempt rates
    subj_practice = {}
    for s in subjects:
        attempts = db.session.query(QuestionAttempt).join(Question).filter(
            QuestionAttempt.student_id == stu.id,
            Question.subject_id == s.id
        ).all()
        if attempts:
            subj_practice[s.id] = sum(1 for a in attempts if a.is_correct) / len(attempts) * 100
        else:
            subj_practice[s.id] = None

    # Compute priorities and create tasks
    day_offset = 1
    for s in subjects:
        avg_mark = subj_scores.get(s.id, 70.0)
        att_rate = subj_att.get(s.id, 85.0)
        prac_acc = subj_practice.get(s.id)

        # Deterministic priority calculation
        points = 0
        if avg_mark < 50: points += 40
        elif avg_mark < 60: points += 30
        elif avg_mark < 75: points += 15
        else: points += 5

        if att_rate < 75: points += 25
        elif att_rate < 85: points += 10

        if prac_acc is not None and prac_acc < 50: points += 20
        elif prac_acc is not None and prac_acc < 70: points += 10

        if points >= 45:
            priority = 'high'
            action = f"Intensive revision on Unit 2/3 core derivations, review midterm exam errors & practice 10 MCQs"
        elif points >= 25:
            priority = 'medium'
            action = f"Consolidate lecture notes, synthesize formula cheat sheet & solve weekly tutorial problems"
        else:
            priority = 'low'
            action = f"Periodic concept review, laboratory case-study exploration & peer discussion"

        due_date = today + timedelta(days=(day_offset % 7) + 1)
        day_offset += 1

        task = StudentTask(
            student_id=stu.id,
            title=f"{s.name} ({s.code}) — {priority.capitalize()} Priority Focus",
            description=action,
            subject_id=s.id,
            assigned_by=None,
            due_date=due_date,
            priority=priority,
            is_completed=False
        )
        db.session.add(task)

    db.session.commit()


@student_bp.route('/study-plan')
@student_required
def study_plan():
    stu = get_current_student()
    if not stu:
        return redirect(url_for('auth.login'))

    tasks = StudentTask.query.filter_by(student_id=stu.id).order_by(
        StudentTask.is_completed, StudentTask.due_date
    ).all()

    # If no tasks exist at all, generate deterministic study plan
    if not tasks:
        _generate_deterministic_study_plan(stu)
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


@student_bp.route('/generate-study-plan', methods=['POST'])
@student_required
def generate_study_plan():
    """Manually regenerate personalized weekly study plan based on latest academic records."""
    stu = get_current_student()
    if stu:
        _generate_deterministic_study_plan(stu)
        flash('Weekly study plan refreshed based on your latest academic performance and attendance!', 'success')
    return redirect(url_for('student.study_plan'))


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

    # Identify student's department and semester subjects
    subjects = Subject.query.filter_by(
        department_id=stu.department_id, semester=stu.current_semester, is_active=True
    ).all()
    if not subjects:
        subjects = Subject.query.filter_by(department_id=stu.department_id, is_active=True).all()

    subj_filter = request.args.get('subject_id', '')
    diff_filter = request.args.get('difficulty', '')
    topic_filter = request.args.get('topic', '').strip()

    subject_ids = [s.id for s in subjects]
    if not subject_ids:
        return render_template('student/practice.html',
                               student=stu,
                               subjects=[],
                               questions=[],
                               topics=[],
                               attempt_counts={},
                               stats={'total_q': 0, 'attempted': 0, 'correct': 0, 'accuracy': 0},
                               subj_filter='',
                               diff_filter='',
                               topic_filter='')

    # Extract distinct topics available for this student's subjects
    available_topics = [
        t[0] for t in db.session.query(Question.topic).filter(
            Question.subject_id.in_(subject_ids),
            Question.topic.isnot(None),
            Question.topic != '',
            Question.is_active == True
        ).distinct().order_by(Question.topic).all() if t[0]
    ]

    query = Question.query.filter(
        Question.subject_id.in_(subject_ids),
        Question.is_active == True,
        Question.question_type == 'mcq'
    )

    if subj_filter and subj_filter.isdigit():
        s_id = int(subj_filter)
        if s_id in subject_ids:
            query = query.filter_by(subject_id=s_id)
    if diff_filter and diff_filter in ['easy', 'medium', 'hard']:
        query = query.filter_by(difficulty=diff_filter)
    if topic_filter:
        query = query.filter_by(topic=topic_filter)

    questions = query.order_by(Question.id).all()

    # Attempt stats per question
    attempt_counts = {}
    for q in questions:
        attempts = QuestionAttempt.query.filter_by(student_id=stu.id, question_id=q.id).count()
        correct = QuestionAttempt.query.filter_by(student_id=stu.id, question_id=q.id, is_correct=True).count()
        attempt_counts[q.id] = {'total': attempts, 'correct': correct}

    # Overall practice statistics for student
    total_q = Question.query.filter(Question.subject_id.in_(subject_ids), Question.is_active == True).count()
    attempted_q_ids = [r[0] for r in db.session.query(QuestionAttempt.question_id).filter_by(student_id=stu.id).distinct().all()]
    attempted_count = len(attempted_q_ids)
    all_attempts = QuestionAttempt.query.filter_by(student_id=stu.id).all()
    correct_count = sum(1 for a in all_attempts if a.is_correct)
    accuracy_pct = round(correct_count / len(all_attempts) * 100, 1) if all_attempts else 0

    practice_stats = {
        'total_q': total_q,
        'attempted': attempted_count,
        'correct': correct_count,
        'accuracy': accuracy_pct
    }

    return render_template('student/practice.html',
                           student=stu,
                           subjects=subjects,
                           questions=questions,
                           topics=available_topics,
                           attempt_counts=attempt_counts,
                           stats=practice_stats,
                           subj_filter=subj_filter,
                           diff_filter=diff_filter,
                           topic_filter=topic_filter)


@student_bp.route('/attempt-question/<int:question_id>', methods=['POST'])
@student_required
def attempt_question(question_id):
    stu = get_current_student()
    q = Question.query.get_or_404(question_id)

    # Authorization: Student cannot attempt questions from another department
    if q.subject and q.subject.department_id != stu.department_id:
        flash('Access denied: question is not from your registered department.', 'danger')
        return redirect(url_for('student.practice'))

    answer = request.form.get('answer', '').strip().upper()
    is_correct = (answer == q.correct_answer) if q.correct_answer else None

    attempt = QuestionAttempt(
        student_id=stu.id,
        question_id=q.id,
        answer_given=answer,
        is_correct=is_correct
    )
    db.session.add(attempt)
    db.session.commit()

    if is_correct:
        flash(f'✅ Correct! Option {q.correct_answer} is right. {q.explanation or ""}', 'success')
    else:
        flash(f'❌ Incorrect. Correct answer is Option {q.correct_answer}. {q.explanation or ""}', 'danger')

    return redirect(url_for('student.practice',
                            subject_id=request.args.get('subject_id', ''),
                            topic=request.args.get('topic', ''),
                            difficulty=request.args.get('difficulty', '')))


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

        elif action == 'delete_goal':
            goal_id = request.form.get('goal_id')
            goal = StudentGoal.query.get(goal_id)
            if goal and goal.student_id == stu.id:
                db.session.delete(goal)
                db.session.commit()
                flash('Goal removed.', 'info')

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
    writer.writerow(['Roll Number', 'Student Name', 'Subject Code', 'Subject Name', 'Examination', 'Type', 'Marks Obtained', 'Max Marks', 'Percentage', 'Date'])
    for m in marks:
        if m.examination:
            pct = round(m.marks_obtained / m.examination.max_marks * 100, 1) if m.examination.max_marks > 0 else 0
            writer.writerow([
                stu.roll_number, stu.name,
                m.subject.code if m.subject else '',
                m.subject.name if m.subject else '',
                m.examination.name,
                m.examination.exam_type,
                m.marks_obtained,
                m.examination.max_marks,
                pct,
                m.recorded_at.strftime('%Y-%m-%d') if m.recorded_at else ''
            ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'{stu.roll_number}_academic_marks.csv'
    )


@student_bp.route('/download/attendance')
@student_required
def download_attendance():
    stu = get_current_student()
    records = AttendanceRecord.query.filter_by(student_id=stu.id).order_by(AttendanceRecord.date).all()
    output = io.StringIO()
    writer = csv.writer(output)

    if records:
        writer.writerow(['Roll Number', 'Student Name', 'Subject Code', 'Subject Name', 'Date', 'Status'])
        for r in records:
            writer.writerow([
                stu.roll_number, stu.name,
                r.subject.code if r.subject else '',
                r.subject.name if r.subject else '',
                r.date.isoformat() if r.date else '',
                r.status
            ])
    else:
        # Export aggregate attendance
        aggs = StudentAggregateAttendance.query.filter_by(student_id=stu.id).all()
        writer.writerow(['Roll Number', 'Student Name', 'Subject Code', 'Subject Name', 'Total Classes', 'Attended Classes', 'Attendance Percentage'])
        for a in aggs:
            writer.writerow([
                stu.roll_number, stu.name,
                a.subject.code if a.subject else '',
                a.subject.name if a.subject else '',
                a.total_classes,
                a.attended_classes,
                a.attendance_percentage
            ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'{stu.roll_number}_attendance_audit.csv'
    )
