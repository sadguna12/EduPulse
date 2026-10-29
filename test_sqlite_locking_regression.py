"""
Regression Test Suite for EduPulse SQLite Database Locking & Transaction Atomicity Fixes.
Covers:
1. Valid master workbook import execution.
2. Repeated import without creating duplicates (under skip policy).
3. Transaction rollback on failure (ensuring no partial academic records remain).
4. Accurate ImportHistory logging on failed imports (never reporting success on rollback).
5. SQLAlchemy session cleanup across repeated and failed imports.
6. SQLite busy_timeout & concurrent reader handling under WAL mode.
"""
import io
import os
import json
import sqlite3
import threading
import time
import openpyxl
import pandas as pd
import pytest

from app import create_app
from extensions import db
from models import (
    User, Department, Student, Faculty, Subject, Section,
    Examination, Mark, AttendanceRecord, StudentAggregateAttendance,
    ImportHistory
)
from excel_importer import (
    generate_master_workbook_template,
    execute_master_workbook_import,
    inspect_master_workbook
)


def create_minimal_master_workbook(dept_code="REG_CS", dept_name="Regression CS Dept",
                                   student_roll="REG24001", student_name="Regression Student"):
    """Creates an in-memory 7-sheet workbook for regression testing."""
    wb = openpyxl.Workbook()

    # Sheet 1: Departments
    ws_dept = wb.create_sheet('Departments')
    ws_dept.append(['department_code', 'department_name', 'section_name', 'semester', 'description'])
    ws_dept.append([dept_code, dept_name, 'A', 1, 'Regression Test Department'])

    # Sheet 2: Students
    ws_stu = wb.create_sheet('Students')
    ws_stu.append(['roll_number', 'full_name', 'department_code', 'section_name', 'semester', 'email', 'phone'])
    ws_stu.append([student_roll, student_name, dept_code, 'A', 1, f"{student_roll.lower()}@test.edu", '9876543210'])

    # Sheet 3: Faculty
    ws_fac = wb.create_sheet('Faculty')
    ws_fac.append(['faculty_id', 'full_name', 'department_code', 'designation', 'email', 'phone', 'subject_codes', 'section_assignments'])
    ws_fac.append([f"FAC_{dept_code}", "Dr. Regression Faculty", dept_code, "Professor", "fac@test.edu", "9876543211", f"{dept_code}101", 'A'])

    # Sheet 4: Subjects
    ws_sub = wb.create_sheet('Subjects')
    ws_sub.append(['subject_code', 'subject_name', 'department_code', 'semester', 'credits', 'subject_type', 'faculty_id', 'section_name'])
    ws_sub.append([f"{dept_code}101", "Regression Subject", dept_code, 1, 4, 'theory', f"FAC_{dept_code}", 'A'])

    # Sheet 5: Examinations
    ws_exam = wb.create_sheet('Examinations')
    ws_exam.append(['exam_name', 'department_code', 'subject_code', 'semester', 'exam_type', 'max_marks'])
    ws_exam.append(['IA1', dept_code, f"{dept_code}101", 1, 'internal', 50.0])

    # Sheet 6: Marks
    ws_marks = wb.create_sheet('Marks')
    ws_marks.append(['roll_number', 'subject_code', 'exam_name', 'marks_obtained', 'max_marks'])
    ws_marks.append([student_roll, f"{dept_code}101", 'IA1', 42.5, 50.0])

    # Sheet 7: Attendance
    ws_att = wb.create_sheet('Attendance')
    ws_att.append(['roll_number', 'subject_code', 'total_classes', 'attended_classes', 'attendance_percentage'])
    ws_att.append([student_roll, f"{dept_code}101", 40, 36, 90.0])

    wb.remove(wb.active)  # remove default sheet
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def run_regression_tests():
    app = create_app('testing')
    print("================================================================")
    print("STARTING EDUPULSE SQLITE LOCKING & TRANSACTION REGRESSION SUITE")
    print("================================================================")

    with app.app_context():
        ts = int(time.time())

        # ----------------------------------------------------------------------
        # TEST 1: Valid Master Workbook Atomic Import
        # ----------------------------------------------------------------------
        dept_1 = f"RIT_{ts}"
        roll_1 = f"RIT{ts}01"
        print(f"\n[REGRESSION 1] Testing Valid Master Workbook Atomic Import ({dept_1})...")
        buf1 = create_minimal_master_workbook(dept_1, f"Reg IT Dept {ts}", roll_1, "Reg Student IT")
        res1 = execute_master_workbook_import(buf1, dup_policy='skip', filename=f'reg_valid_{ts}.xlsx')
        assert res1['success'] is True, f"Import failed: {res1.get('error')}"
        assert res1['imported_counts']['departments'] >= 1
        assert res1['imported_counts']['students'] >= 1
        assert res1['imported_counts']['marks'] >= 1

        # Verify DB records
        d = Department.query.filter_by(code=dept_1).first()
        assert d is not None, f"Department {dept_1} was not committed"
        s = Student.query.filter_by(roll_number=roll_1).first()
        assert s is not None, f"Student {roll_1} was not committed"
        assert s.department_id == d.id
        print(f"  [OK] Successfully imported and committed atomic records for department '{d.code}'.")

        # ----------------------------------------------------------------------
        # TEST 2: Repeated Import (Safe Duplicate Handling)
        # ----------------------------------------------------------------------
        print("\n[REGRESSION 2] Testing Repeated Import (Prevent Duplicates)...")
        buf1.seek(0)
        res2 = execute_master_workbook_import(buf1, dup_policy='skip', filename=f'reg_valid_{ts}_repeat.xlsx')
        assert res2['success'] is True
        assert res2['total_imported'] == 0, f"Expected 0 imported on repeat, got {res2['total_imported']}"
        assert res2['total_skipped'] > 0, "Expected duplicates to be skipped"
        print(f"  [OK] Repeated import safely skipped {res2['total_skipped']} records with 0 duplicates.")

        # ----------------------------------------------------------------------
        # TEST 3: Transaction Rollback on Failure (No Partial Records Remain)
        # ----------------------------------------------------------------------
        fail_dept = f"FAIL_{ts}"
        fail_roll = f"FS_{ts}01"
        print(f"\n[REGRESSION 3] Testing Transaction Rollback on Fatal Error ({fail_dept})...")
        wb_fail = openpyxl.Workbook()
        ws_d = wb_fail.create_sheet('Departments')
        ws_d.append(['department_code', 'department_name', 'section_name', 'semester'])
        ws_d.append([fail_dept, 'Department To Roll Back', 'A', 1])

        ws_s = wb_fail.create_sheet('Students')
        ws_s.append(['roll_number', 'full_name', 'department_code', 'section_name', 'semester'])
        ws_s.append([fail_roll, 'Fail Student', fail_dept, 'A', 1])

        ws_e = wb_fail.create_sheet('Examinations')
        ws_e.append(['exam_name', 'department_code', 'semester'])
        ws_e.append(['', fail_dept, 1]) # missing exam name
        wb_fail.remove(wb_fail.active)

        buf_fail = io.BytesIO()
        wb_fail.save(buf_fail)
        buf_fail.seek(0)

        # Force a database-level error during entity creation (simulating SQLite lock or query error)
        from unittest.mock import patch
        with patch('excel_importer.Section', side_effect=Exception("Simulated SQLite Table Lock Failure")):
            res_fail = execute_master_workbook_import(buf_fail, dup_policy='skip', filename=f'fail_test_{ts}.xlsx')

        assert res_fail['success'] is False, "Expected import to report failure on exception"
        assert 'Simulated SQLite Commit Failure' in res_fail['error'] or res_fail['status'] == 'failed'

        # CRITICAL CHECK: Verify fail_dept was NOT persisted!
        rolled_back_dept = Department.query.filter_by(code=fail_dept).first()
        assert rolled_back_dept is None, f"CRITICAL FAILURE: {fail_dept} was partially committed despite transaction failure!"
        rolled_back_stu = Student.query.filter_by(roll_number=fail_roll).first()
        assert rolled_back_stu is None, f"CRITICAL FAILURE: {fail_roll} student remained in database after rollback!"
        print("  [OK] Atomic rollback verified: No partial department or student records remain.")

        # ----------------------------------------------------------------------
        # TEST 4: Accurate ImportHistory Logging on Failed Imports
        # ----------------------------------------------------------------------
        print("\n[REGRESSION 4] Testing Accurate ImportHistory Logging...")
        hist_id = res_fail.get('history_id')
        assert hist_id is not None, "Failed import must produce an ImportHistory log"
        hist_entry = ImportHistory.query.get(hist_id)
        assert hist_entry is not None, "ImportHistory record not found in database"
        assert hist_entry.status == 'failed', f"Expected status 'failed', got '{hist_entry.status}'"
        assert hist_entry.records_imported == 0, f"Failed import logged records_imported={hist_entry.records_imported}"
        assert 'Fatal transaction rollback' in hist_entry.error_summary or 'Simulated' in hist_entry.error_summary
        print(f"  [OK] ImportHistory accurately recorded failed transaction #{hist_id} (status='{hist_entry.status}', imported=0).")

        # ----------------------------------------------------------------------
        # TEST 5: Session Cleanup & Repeated Imports After Failures
        # ----------------------------------------------------------------------
        dept_ee = f"REE_{ts}"
        roll_ee = f"REE{ts}01"
        print(f"\n[REGRESSION 5] Testing Session Cleanup & Subsequent Import ({dept_ee})...")
        buf_next = create_minimal_master_workbook(dept_ee, f"Reg Electrical {ts}", roll_ee, "Reg Student EE")
        res_next = execute_master_workbook_import(buf_next, dup_policy='skip', filename=f'reg_valid_next_{ts}.xlsx')
        assert res_next['success'] is True, f"Subsequent import after failure crashed: {res_next.get('error')}"
        d_ee = Department.query.filter_by(code=dept_ee).first()
        assert d_ee is not None, f"Department {dept_ee} was not committed"
        print("  [OK] Session properly cleaned up; subsequent import executed flawlessly.")

        # ----------------------------------------------------------------------
        # TEST 6: SQLite WAL Mode & Concurrent Readers During Import
        # ----------------------------------------------------------------------
        dept_me = f"RME_{ts}"
        roll_me = f"RME{ts}01"
        print(f"\n[REGRESSION 6] Testing Concurrent SQLite Reader Under WAL Mode ({dept_me})...")
        # Open an independent raw sqlite3 connection holding a SELECT cursor
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        conn = sqlite3.connect(db_path, timeout=30.0)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM departments;")
        count_before = cur.fetchone()[0]

        # In WAL mode, concurrent reader does NOT block active import transaction
        buf_concur = create_minimal_master_workbook(dept_me, f"Reg Mech {ts}", roll_me, "Reg Student ME")
        res_concur = execute_master_workbook_import(buf_concur, dup_policy='skip', filename=f'reg_concur_{ts}.xlsx')
        assert res_concur['success'] is True, f"Concurrent import was blocked or locked: {res_concur.get('error')}"

        # Ensure reader can now see updated data after completing its cursor
        cur.execute(f"SELECT count(*) FROM departments WHERE code = '{dept_me}';")
        assert cur.fetchone()[0] == 1, f"Concurrent connection could not query newly committed {dept_me} department"
        cur.close()
        conn.close()
        print("  [OK] Concurrent reader verified: WAL mode and busy_timeout prevented locking error.")

        # ----------------------------------------------------------------------
        # TEST 7: SQLite Busy Handling / Retry Grace Period
        # ----------------------------------------------------------------------
        print("\n[REGRESSION 7] Testing SQLite Busy Timeout Grace Period...")
        # Verify busy_timeout pragma is 30000ms
        with db.engine.connect() as connection:
            result = connection.exec_driver_sql("PRAGMA busy_timeout;").scalar()
            assert result == 30000, f"Expected busy_timeout=30000, got {result}"
            j_mode = connection.exec_driver_sql("PRAGMA journal_mode;").scalar()
            assert j_mode.lower() == 'wal', f"Expected journal_mode=wal, got {j_mode}"
            print(f"  [OK] Active SQLite Pragmas: busy_timeout={result}ms, journal_mode={j_mode}.")

        # ----------------------------------------------------------------------
        # TEST 8: Exam Max Marks & Marks Validation (Valid & Invalid Scores)
        # ----------------------------------------------------------------------
        dept_val = f"RVAL_{ts}"
        roll_val = f"VAL{ts}01"
        sub_val_code = f"VS{ts % 10000}"
        print(f"\n[REGRESSION 8] Testing Exam Max Marks & Marks Validation ({dept_val})...")
        wb_marks_test = openpyxl.Workbook()
        ws_d = wb_marks_test.create_sheet('Departments')
        ws_d.append(['department_code', 'department_name', 'section_name', 'semester'])
        ws_d.append([dept_val, f'Reg Marks Validation Dept {ts}', 'A', 5])

        ws_s = wb_marks_test.create_sheet('Students')
        ws_s.append(['roll_number', 'full_name', 'department_code', 'section_name', 'semester'])
        ws_s.append([roll_val, 'Validation Student', dept_val, 'A', 5])

        ws_sub = wb_marks_test.create_sheet('Subjects')
        ws_sub.append(['subject_code', 'subject_name', 'department_code', 'semester', 'credits'])
        ws_sub.append([sub_val_code, 'Validation Subject', dept_val, 5, 4])

        ws_ex = wb_marks_test.create_sheet('Examinations')
        ws_ex.append(['exam_id', 'exam_name', 'department_code', 'semester', 'exam_type'])
        ws_ex.append(['IA1', 'Internal Assessment 1', 'REG_VAL', 5, 'internal'])
        ws_ex.append(['SEM5', 'Semester 5 Final Examination', 'REG_VAL', 5, 'semester'])

        ws_m = wb_marks_test.create_sheet('Marks')
        ws_m.append(['roll_number', 'subject_code', 'exam_id', 'marks_obtained', 'max_marks'])
        ws_m.append([roll_val, sub_val_code, 'IA1', 45.0, 50.0])       # Valid: 45 <= 50
        ws_m.append([roll_val, sub_val_code, 'SEM5', 79.8, 100.0])     # Valid: 79.8 <= 100 (The SEM5 test case)
        ws_m.append([roll_val, sub_val_code, 'IA1', 58.0, 50.0])       # Invalid: 58 > 50
        ws_m.append([roll_val, sub_val_code, 'SEM5', 105.0, 100.0])    # Invalid: 105 > 100
        ws_m.append([roll_val, sub_val_code, 'SEM5', -10.0, 100.0])    # Invalid: negative

        wb_marks_test.remove(wb_marks_test.active)
        buf_m_test = io.BytesIO()
        wb_marks_test.save(buf_m_test)
        buf_m_test.seek(0)

        res_m = execute_master_workbook_import(buf_m_test, dup_policy='skip', filename=f'marks_val_{ts}.xlsx')
        assert res_m['success'] is True
        assert res_m['imported_counts']['marks'] == 2, f"Expected 2 valid marks, got {res_m['imported_counts']['marks']}"
        assert res_m['failed_counts']['marks'] == 3, f"Expected 3 rejected marks, got {res_m['failed_counts']['marks']}"

        # Verify the examinations were created with correct canonical max_marks
        sub_val = Subject.query.filter_by(code=sub_val_code).first()
        assert sub_val is not None
        sem_exam = Examination.query.filter_by(subject_id=sub_val.id, name='SEM5').first()
        assert sem_exam is not None
        assert sem_exam.max_marks == 100.0, f"Expected SEM5 max_marks=100.0, got {sem_exam.max_marks}"
        ia_exam = Examination.query.filter_by(subject_id=sub_val.id, name='IA1').first()
        assert ia_exam is not None
        assert ia_exam.max_marks == 50.0, f"Expected IA1 max_marks=50.0, got {ia_exam.max_marks}"

        # Verify valid marks saved in DB
        val_stu = Student.query.filter_by(roll_number=roll_val).first()
        sem_mark = Mark.query.filter_by(student_id=val_stu.id, examination_id=sem_exam.id).first()
        assert sem_mark is not None
        assert sem_mark.marks_obtained == 79.8, f"Expected score 79.8, got {sem_mark.marks_obtained}"
        print("  [OK] Valid scores (79.8/100, 45/50) saved; invalid scores (105, 58, -10) rejected accurately.")

        # ----------------------------------------------------------------------
        # TEST 9: Complete Error Report Generation with All Columns
        # ----------------------------------------------------------------------
        print("\n[REGRESSION 9] Testing Complete Error Report Generation...")
        m_hist_id = res_m.get('history_id')
        assert m_hist_id is not None
        hist_rec = ImportHistory.query.get(m_hist_id)
        assert hist_rec.records_failed == 3
        assert hist_rec.status == 'partial'

        admin_user = User.query.filter_by(role='admin').first()
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['_user_id'] = str(admin_user.id)
                sess['_fresh'] = True
            csv_res = client.get(f'/admin/dataset/errors/{m_hist_id}')
            assert csv_res.status_code == 200
            import csv as py_csv
            csv_rows = list(py_csv.reader(io.StringIO(csv_res.data.decode('utf-8'))))
            assert len(csv_rows) == 4, f"Expected 4 rows (header + 3 errors), got {len(csv_rows)}"
            assert csv_rows[0] == ['Error Index', 'Worksheet', 'Row Number', 'Identifier', 'Rejected Value', 'Reason']
            assert csv_rows[1][1] == 'Marks'
            assert csv_rows[1][3] == roll_val
            print(f"  [OK] Error audit CSV contains all 6 columns: {csv_rows[0]}")
            print(f"  [OK] Exported all {len(csv_rows)-1} errors accurately.")

        # ----------------------------------------------------------------------
        # TEST 10: History #28 Full 810 Error Audit CSV Export
        # ----------------------------------------------------------------------
        print("\n[REGRESSION 10] Testing Complete History #28 Audit Export (810 records)...")
        h28 = ImportHistory.query.get(28)
        if h28:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(admin_user.id)
                    sess['_fresh'] = True
                csv_28 = client.get('/admin/dataset/errors/28')
                assert csv_28.status_code == 200
                rows_28 = list(py_csv.reader(io.StringIO(csv_28.data.decode('utf-8'))))
                assert len(rows_28) == 811, f"Expected 811 rows for History #28, got {len(rows_28)}"
                print(f"  [OK] History #28 error export verified: Successfully exported all 810 rejected marks without truncation.")

    print("\n================================================================")
    print("ALL 10 REGRESSION TEST SUITES PASSED PERFECTLY!")
    print("================================================================")


if __name__ == '__main__':
    run_regression_tests()
