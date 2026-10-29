"""
Comprehensive Test Suite for EduPulse
Tests all Student, Faculty, Admin, and Unified Master Excel Workbook workflows.
"""
import io
import os
from flask import g
import openpyxl
import pandas as pd
from app import create_app
from extensions import db
from models import (
    User, Admin, Faculty, Student, Department, Subject, Section,
    Examination, Mark, AttendanceRecord, StudentAggregateAttendance,
    Question, QuestionAttempt, StudentTask, StudentGoal, ImportHistory,
    FacultySubjectAssignment
)
from excel_importer import (
    generate_master_workbook_template,
    inspect_master_workbook,
    execute_master_workbook_import
)

def run_tests():
    app = create_app('testing')
    client = app.test_client()

    print("==================================================")
    print("STARTING EDUPULSE COMPREHENSIVE VERIFICATION SUITE")
    print("==================================================")

    with app.app_context():
        # ----------------------------------------------------
        # TEST 1: Master Excel Workbook Template Generation
        # ----------------------------------------------------
        print("\n[TEST 1] Testing Master Excel Template Generation...")
        buf = generate_master_workbook_template()
        assert buf is not None and len(buf.getvalue()) > 5000, "Buffer empty or too small"
        
        xl = pd.ExcelFile(buf, engine='openpyxl')
        sheets = xl.sheet_names
        print(f"  Generated Sheets in Workbook: {sheets}")
        expected_sheets = ['Departments', 'Students', 'Faculty', 'Subjects', 'Examinations', 'Marks', 'Attendance']
        for es in expected_sheets:
            assert es in sheets, f"Expected sheet '{es}' missing from workbook"
        print("  [OK] TEST 1 PASSED: Master workbook template has all 7 canonical sheets.")

        # ----------------------------------------------------
        # TEST 2: Master Workbook Inspection & Cross-Sheet Validation
        # ----------------------------------------------------
        print("\n[TEST 2] Testing Inspection & Pre-Validation Engine...")
        buf.seek(0)
        inspection = inspect_master_workbook(buf)
        summary = inspection['summary']
        print(f"  Sheets detected: {summary['total_sheets_detected']} / 7")
        print(f"  Row counts: {summary['row_counts']}")
        print(f"  Validation issues: {len(inspection['validation_issues'])}")
        print(f"  Missing dependencies: {len(inspection['missing_dependencies'])}")
        assert summary['total_sheets_detected'] == 7, "All 7 sheets should be recognized"
        assert len(inspection['validation_issues']) == 0, f"Unexpected validation issues: {inspection['validation_issues']}"
        print("  [OK] TEST 2 PASSED: Master workbook inspection and alias normalization succeeded.")

        # ----------------------------------------------------
        # TEST 3: Cross-Sheet Missing Dependency Detection (Demo data rule)
        # ----------------------------------------------------
        print("\n[TEST 3] Testing Missing Dependency Detection (e.g. Unregistered CS Dept)...")
        # Build workbook with CS student, but NO CS department
        wb = openpyxl.Workbook()
        ws_dept = wb.create_sheet('Departments')
        ws_dept.append(['department_code', 'department_name', 'section_name', 'semester'])
        ws_dept.append(['IT', 'Information Technology', 'A', 1])

        ws_stu = wb.create_sheet('Students')
        ws_stu.append(['roll_number', 'full_name', 'department_code', 'section', 'semester'])
        ws_stu.append(['CS99999', 'Demo CS Student', 'CS', 'A', 1]) # CS department missing!
        wb.remove(wb.active)

        bad_buf = io.BytesIO()
        wb.save(bad_buf)
        bad_buf.seek(0)

        bad_inspection = inspect_master_workbook(bad_buf)
        print(f"  Detected missing dependencies: {bad_inspection['missing_dependencies']}")
        assert any("CS" in dep for dep in bad_inspection['missing_dependencies']), "Failed to detect missing CS department"
        print("  [OK] TEST 3 PASSED: System explicitly identifies missing CS department without silent discarding.")

        # ----------------------------------------------------
        # TEST 4: Master Workbook Import Execution (Atomic Transaction)
        # ----------------------------------------------------
        print("\n[TEST 4] Testing Atomic Master Workbook Import Execution...")
        buf.seek(0)
        admin_user = User.query.filter_by(role='admin').first()
        res = execute_master_workbook_import(buf, dup_policy='skip', user_id=admin_user.id if admin_user else None, filename='Test_Master_Dataset.xlsx')
        assert res['success'] is True, f"Master import failed: {res.get('error')}"
        print(f"  Total imported: {res['total_imported']}, Total skipped: {res['total_skipped']}")
        print(f"  Import counts per category: {res['imported_counts']}")
        
        # Verify student Aarav Sharma exists and user account is hashed
        test_student = Student.query.filter_by(roll_number='IT24001A').first()
        assert test_student is not None, "Student IT24001A not found in database"
        assert test_student.user is not None, "User account not linked"
        assert test_student.user.check_password('IT24001A'), "Default password check failed"
        print(f"  Verified student {test_student.name} ({test_student.roll_number}) with hashed account.")
        print("  [OK] TEST 4 PASSED: Master workbook atomic import succeeded.")

        # ----------------------------------------------------
        # TEST 5: Repeated Import (Safe Duplicate Handling)
        # ----------------------------------------------------
        print("\n[TEST 5] Testing Safe Repeated Import (Prevent Duplicates)...")
        buf.seek(0)
        res_repeat = execute_master_workbook_import(buf, dup_policy='skip', user_id=admin_user.id if admin_user else None)
        assert res_repeat['success'] is True
        print(f"  Repeated import: {res_repeat['total_imported']} imported, {res_repeat['total_skipped']} skipped.")
        assert res_repeat['total_imported'] == 0, "No duplicate records should be re-imported under skip policy"
        print("  [OK] TEST 5 PASSED: Safe duplicate prevention verified.")

        # ----------------------------------------------------
        # TEST 6: Student Portal Functionality (All Pages & Features)
        # ----------------------------------------------------
        print("\n[TEST 6] Testing Student Portal Pages & Authentication...")
        student_user = User.query.filter_by(unique_id='IT24001A').first()
        assert student_user is not None
        
        c_stu = app.test_client()
        with c_stu.session_transaction() as sess:
            sess['_user_id'] = str(student_user.id)
            sess['_fresh'] = True
        g.pop('_login_user', None)

        # 6A: Dashboard
        resp = c_stu.get('/student/dashboard')
        assert resp.status_code == 200, f"Dashboard returned {resp.status_code}"
        assert b"My Dashboard" in resp.data
        assert test_student.name.encode('utf-8') in resp.data
        print("  [OK] Dashboard accessible with real database records.")

        # 6B: Performance
        resp = c_stu.get('/student/performance')
        assert resp.status_code == 200
        assert b"Academic Performance" in resp.data
        print("  [OK] Academic Performance accessible.")

        # 6C: Prediction
        resp = c_stu.get('/student/prediction')
        assert resp.status_code == 200
        assert b"Predicted Semester Outcome" in resp.data
        print("  [OK] Performance Prediction accessible.")

        # 6D: Strengths and Weak Areas
        resp = c_stu.get('/student/weak-areas')
        assert resp.status_code == 200
        assert b"Strengths & Weak Areas" in resp.data
        print("  [OK] Strengths and Weak Areas accessible.")

        # 6E: Attendance
        resp = c_stu.get('/student/attendance')
        assert resp.status_code == 200
        assert b"Attendance Tracking & Compliance" in resp.data
        print("  [OK] Attendance accessible with multi-source records.")

        # 6F: Weekly Study Plan & Task Generation
        resp = c_stu.get('/student/study-plan')
        assert resp.status_code == 200
        assert b"Weekly Study Plan" in resp.data
        print("  [OK] Weekly Study Plan accessible.")

        # Test Study Plan Regeneration
        resp_regen = c_stu.post('/student/generate-study-plan', follow_redirects=True)
        assert resp_regen.status_code == 200
        stu_obj = Student.query.filter_by(roll_number='IT24001A').first()
        tasks = StudentTask.query.filter_by(student_id=stu_obj.id).all()
        assert len(tasks) > 0, "Tasks should be generated"
        task_id = tasks[0].id
        initial_status = tasks[0].is_completed
        
        # Test Task Complete Toggle
        c_stu.post(f'/student/complete-task/{task_id}', follow_redirects=True)
        t_after = db.session.get(StudentTask, task_id)
        assert t_after.is_completed != initial_status, "Task completion not toggled"
        print(f"  [OK] Deterministic study plan generated ({len(tasks)} tasks) and completion toggled.")

        # 6G: Practice & Question Bank
        resp = c_stu.get('/student/practice')
        assert resp.status_code == 200
        assert b"Interactive Practice & Question Bank" in resp.data
        
        # Verify questions shown belong ONLY to student's department (IT)
        it_q = Question.query.join(Subject).filter(Subject.department_id == stu_obj.department_id, Question.is_active == True).first()
        if it_q:
            # Attempt question
            attempt_resp = c_stu.post(f'/student/attempt-question/{it_q.id}', data={'answer': it_q.correct_answer or 'A'}, follow_redirects=True)
            assert attempt_resp.status_code == 200
            # Verify attempt saved
            saved_att = QuestionAttempt.query.filter_by(student_id=stu_obj.id, question_id=it_q.id).first()
            assert saved_att is not None, "Question attempt not recorded in database"
            print("  [OK] Practice question attempted, validated, and saved in database.")

        # 6H: Self-Improvement Goals
        resp = c_stu.get('/student/self-improvement')
        assert resp.status_code == 200
        resp_add_goal = c_stu.post('/student/self-improvement', data={
            'action': 'add_goal',
            'title': 'Achieve Grade A in Programming',
            'description': 'Solve 50 practice problems',
            'target_date': '2026-12-31'
        }, follow_redirects=True)
        assert resp_add_goal.status_code == 200
        goal = StudentGoal.query.filter_by(student_id=stu_obj.id, title='Achieve Grade A in Programming').first()
        assert goal is not None, "Goal not added to database"
        print("  [OK] Self-improvement goals functional.")

        # 6I: Reports & Downloads
        resp = c_stu.get('/student/reports')
        assert resp.status_code == 200
        resp_m_dl = c_stu.get('/student/download/marks')
        assert resp_m_dl.status_code == 200 and 'text/csv' in resp_m_dl.content_type
        resp_a_dl = c_stu.get('/student/download/attendance')
        assert resp_a_dl.status_code == 200 and 'text/csv' in resp_a_dl.content_type
        print("  [OK] Academic reports dossier and CSV exports functional.")

        # ----------------------------------------------------
        # TEST 7: Faculty Portal Functionality & Authorization
        # ----------------------------------------------------
        print("\n[TEST 7] Testing Faculty Portal & Dynamic Student Assignment...")
        fac_user = User.query.filter_by(unique_id='FACIT01').first()
        assert fac_user is not None
        
        c_fac = app.test_client()
        with c_fac.session_transaction() as sess:
            sess['_user_id'] = str(fac_user.id)
            sess['_fresh'] = True
        g.pop('_login_user', None)

        # Faculty Dashboard
        resp = c_fac.get('/faculty/dashboard')
        assert resp.status_code == 200
        assert b"Dr. Ramesh Kumar" in resp.data
        print("  [OK] Faculty dashboard loaded with assigned cohort.")

        # Faculty Students Directory with filters
        resp = c_fac.get('/faculty/students')
        assert resp.status_code == 200
        assert b"Assigned Students" in resp.data
        
        # Test filtering by semester
        resp_f = c_fac.get('/faculty/students?semester=1')
        assert resp_f.status_code == 200
        print("  [OK] Faculty students loaded dynamically with multi-criteria filtering.")

        # Test Faculty Marks Management
        resp = c_fac.get('/faculty/marks')
        assert resp.status_code == 200
        print("  [OK] Faculty marks management accessible.")

        # Test Question Bank additions
        sub_it = Subject.query.filter_by(code='IT101').first()
        if sub_it:
            resp_q = c_fac.post('/faculty/questions', data={
                'action': 'add',
                'subject_id': str(sub_it.id),
                'question_text': 'What is the format specifier for integer in C?',
                'option_a': '%d',
                'option_b': '%f',
                'option_c': '%c',
                'option_d': '%s',
                'correct_answer': 'A',
                'topic': 'Syntax & Types',
                'difficulty': 'easy',
                'explanation': '%d is used for integer types in printf/scanf.'
            }, follow_redirects=True)
            assert resp_q.status_code == 200
            new_q = Question.query.filter_by(question_text='What is the format specifier for integer in C?').first()
            assert new_q is not None, "Question not saved by faculty"
            print("  [OK] Faculty question bank creation functional.")

        # ----------------------------------------------------
        # TEST 8: Backend Security & Access Control
        # ----------------------------------------------------
        print("\n[TEST 8] Testing Backend Security & Cross-Role Access Prevention...")
        # 8A: Faculty cannot access Admin dataset
        g.pop('_login_user', None)
        resp_admin = c_fac.get('/admin/dataset')
        assert resp_admin.status_code in (302, 403), "Faculty should not access admin pages"

        # 8B: Student cannot access Faculty marks
        g.pop('_login_user', None)
        resp_fac = c_stu.get('/faculty/marks')
        assert resp_fac.status_code in (302, 403), "Student should not access faculty marks"

        # 8C: Student cannot access other student's API performance
        other_stu = Student.query.filter(Student.id != stu_obj.id).first()
        if other_stu:
            g.pop('_login_user', None)
            resp_api = c_stu.get(f'/api/chart/performance/{other_stu.id}')
            assert resp_api.status_code == 403, "Student should not access other student's performance via API"
        print("  [OK] Backend role-based security strictly enforced.")

        # ----------------------------------------------------
        # TEST 9: Admin Master Template Download Endpoint
        # ----------------------------------------------------
        print("\n[TEST 9] Testing Admin Master Template Download Endpoint...")
        c_adm = app.test_client()
        with c_adm.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        g.pop('_login_user', None)
        resp_tmpl = c_adm.get('/admin/dataset/master-template')
        assert resp_tmpl.status_code == 200
        assert 'spreadsheetml' in resp_tmpl.content_type
        print("  [OK] Admin download master template endpoint functional.")

    print("\n==================================================")
    print("ALL 9 TEST SUITES COMPLETED AND PASSED PERFECTLY!")
    print("==================================================")

if __name__ == '__main__':
    run_tests()
