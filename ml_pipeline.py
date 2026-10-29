"""
EduPulse ML Pipeline
Uses Scikit-learn to predict student performance based on historical marks.
"""
import os
import numpy as np
import pandas as pd
import joblib
from datetime import datetime
from sklearn.linear_model import Ridge, LinearRegression
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.base import BaseEstimator

MODEL_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "ml_models")
os.makedirs(MODEL_DIR, exist_ok=True)

MIN_TRAINING_SAMPLES = 15


def get_model_path(department_id, subject_id=None):
    suffix = f"dept{department_id}"
    if subject_id:
        suffix += f"_subj{subject_id}"
    return os.path.join(MODEL_DIR, f"model_{suffix}.pkl")


def build_features(marks_df):
    """
    Build feature matrix from marks DataFrame.
    Expected columns: student_id, subject_id, exam_type, marks_obtained, max_marks, exam_index
    Returns X (features), y (targets), student_ids
    """
    if marks_df.empty:
        return None, None, None

    marks_df = marks_df.copy()
    marks_df["pct"] = marks_df["marks_obtained"] / marks_df["max_marks"].replace(0, 1) * 100

    # Pivot: each row = student, each col = (subject, exam_type) percentage
    pivot = marks_df.pivot_table(
        index="student_id",
        columns=["subject_id", "exam_type"],
        values="pct",
        aggfunc="mean"
    )
    pivot.columns = [f"s{col[0]}_{col[1]}" for col in pivot.columns]
    pivot = pivot.fillna(pivot.mean())

    # Average internal marks per student
    internal_cols = [c for c in pivot.columns if "internal" in c]
    if internal_cols:
        pivot["avg_internal"] = pivot[internal_cols].mean(axis=1)
    else:
        pivot["avg_internal"] = 50.0

    # Count of completed assessments
    pivot["n_assessments"] = (~marks_df.pivot_table(
        index="student_id",
        columns="examination_id",
        values="marks_obtained",
        aggfunc="count"
    ).isna()).sum(axis=1) if "examination_id" in marks_df.columns else 0

    return pivot


def prepare_training_data(student_marks_df):
    """
    Prepare X, y for training: predict semester exam % from internal marks.
    """
    if student_marks_df.empty:
        return None, None, None

    marks_df = student_marks_df.copy()
    marks_df["pct"] = marks_df["marks_obtained"] / marks_df["max_marks"].replace(0, 1) * 100

    # Separate internals and semester exam per student per subject
    internal = marks_df[marks_df["exam_type"] == "internal"].copy()
    semester = marks_df[marks_df["exam_type"] == "semester"].copy()

    if internal.empty or semester.empty:
        return None, None, None

    # Aggregate internal marks by student
    int_agg = internal.groupby(["student_id", "subject_id"])["pct"].agg(
        ["mean", "max", "min", "std"]
    ).reset_index()
    int_agg.columns = ["student_id", "subject_id", "ia_mean", "ia_max", "ia_min", "ia_std"]
    int_agg["ia_std"] = int_agg["ia_std"].fillna(0)

    sem_agg = semester.groupby(["student_id", "subject_id"])["pct"].mean().reset_index()
    sem_agg.columns = ["student_id", "subject_id", "sem_pct"]

    merged = pd.merge(int_agg, sem_agg, on=["student_id", "subject_id"])
    if merged.empty:
        return None, None, None

    # Add student-level average across subjects
    student_avg = int_agg.groupby("student_id")["ia_mean"].mean().reset_index()
    student_avg.columns = ["student_id", "student_overall_avg"]
    merged = pd.merge(merged, student_avg, on="student_id")

    feature_cols = ["ia_mean", "ia_max", "ia_min", "ia_std", "student_overall_avg"]
    X = merged[feature_cols].values
    y = merged["sem_pct"].values
    student_ids = merged["student_id"].values

    return X, y, student_ids


def train_model(X, y, model_path):
    """Train and evaluate the model, return info dict."""
    if X is None or len(X) < MIN_TRAINING_SAMPLES:
        return {"success": False, "reason": "insufficient_data", "samples": len(X) if X is not None else 0}

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    candidates = {
        "Ridge": Pipeline([("scaler", StandardScaler()), ("model", Ridge(alpha=1.0))]),
        "RandomForest": Pipeline([("scaler", StandardScaler()),
                                   ("model", RandomForestRegressor(n_estimators=50, random_state=42))]),
        "GradientBoosting": Pipeline([("scaler", StandardScaler()),
                                       ("model", GradientBoostingRegressor(n_estimators=50, random_state=42))]),
    }

    # Baseline: predict mean of training targets
    baseline_pred = np.full(len(y_test), np.mean(y_train))
    baseline_mae = mean_absolute_error(y_test, baseline_pred)

    best_model = None
    best_mae = float("inf")
    best_name = None
    results = {}

    for name, pipe in candidates.items():
        try:
            if len(X_train) < 5:
                cv_scores = [r2_score(y_train, pipe.fit(X_train, y_train).predict(X_train))]
            else:
                cv_n = min(5, len(X_train))
                cv_scores = cross_val_score(pipe, X_train, y_train, cv=cv_n,
                                            scoring="neg_mean_absolute_error")
            cv_mae = -np.mean(cv_scores)

            pipe.fit(X_train, y_train)
            test_pred = pipe.predict(X_test)
            test_mae = mean_absolute_error(y_test, test_pred)
            test_r2 = r2_score(y_test, test_pred) if len(y_test) > 1 else 0.0

            results[name] = {"cv_mae": cv_mae, "test_mae": test_mae, "test_r2": test_r2}
            if test_mae < best_mae:
                best_mae = test_mae
                best_model = pipe
                best_name = name
        except Exception as e:
            results[name] = {"error": str(e)}

    if best_model is None:
        return {"success": False, "reason": "training_failed"}

    # Only save if meaningfully better than baseline
    beats_baseline = best_mae < baseline_mae
    joblib.dump({"model": best_model, "feature_cols": ["ia_mean", "ia_max", "ia_min", "ia_std", "student_overall_avg"],
                 "trained_at": datetime.utcnow().isoformat()}, model_path)

    return {
        "success": True,
        "model_name": best_name,
        "test_mae": round(best_mae, 2),
        "test_r2": round(results[best_name]["test_r2"], 3),
        "baseline_mae": round(baseline_mae, 2),
        "beats_baseline": beats_baseline,
        "training_samples": len(X),
        "all_results": results,
    }


def predict_for_student(student_id, marks_df, model_path):
    """
    Predict future semester performance for a student.
    Returns dict with prediction, confidence, and explanation.
    """
    if not os.path.exists(model_path):
        return _baseline_prediction(student_id, marks_df)

    try:
        saved = joblib.load(model_path)
        model = saved["model"]
    except Exception:
        return _baseline_prediction(student_id, marks_df)

    marks_df = marks_df.copy()
    if "pct" not in marks_df.columns:
        marks_df["pct"] = marks_df["marks_obtained"] / marks_df["max_marks"].replace(0, 1) * 100

    student_marks = marks_df[marks_df["student_id"] == student_id].copy()
    if student_marks.empty:
        return {"prediction": None, "method": "no_data", "message": "No marks data available."}

    internal = student_marks[student_marks["exam_type"] == "internal"]

    if internal.empty:
        return _baseline_prediction(student_id, marks_df)

    ia_values = internal["pct"].values
    int_all = marks_df[marks_df["exam_type"] == "internal"]
    student_overall_avg = float(int_all["pct"].mean()) if not int_all.empty else float(np.mean(ia_values))

    X_pred = np.array([[
        np.mean(ia_values),
        np.max(ia_values),
        np.min(ia_values),
        np.std(ia_values) if len(ia_values) > 1 else 0.0,
        student_overall_avg
    ]])

    try:
        pred_pct = float(model.predict(X_pred)[0])
        pred_pct = np.clip(pred_pct, 0, 100)
        return {
            "prediction": round(pred_pct, 1),
            "method": "ml_model",
            "ia_mean": round(np.mean(ia_values), 1),
            "confidence": "moderate",
            "message": "Predicted using machine learning model trained on historical data."
        }
    except Exception:
        return _baseline_prediction(student_id, marks_df)


def _baseline_prediction(student_id, marks_df):
    """Simple baseline: weighted average of internal marks."""
    if marks_df is None or marks_df.empty:
        return {"prediction": None, "method": "no_data", "message": "Insufficient data for prediction."}

    student_marks = marks_df[marks_df["student_id"] == student_id].copy()
    if student_marks.empty:
        return {"prediction": None, "method": "no_data", "message": "No marks found for this student."}

    student_marks["pct"] = student_marks["marks_obtained"] / student_marks["max_marks"].replace(0, 1) * 100
    mean_pct = student_marks["pct"].mean()

    return {
        "prediction": round(float(mean_pct), 1),
        "method": "baseline",
        "ia_mean": round(float(mean_pct), 1),
        "confidence": "low",
        "message": "Baseline estimate (insufficient data for ML model). Based on average of available marks."
    }


def generate_recommendations(student_id, marks_df, attendance_df=None, tasks_df=None):
    """
    Rule-based recommendation engine.
    Returns list of recommendation dicts.
    """
    recommendations = []

    if marks_df is None or marks_df.empty:
        return [{"type": "info", "message": "No academic data available yet. Records will appear after marks are entered."}]

    student_marks = marks_df[marks_df["student_id"] == student_id].copy()
    if student_marks.empty:
        return [{"type": "info", "message": "No marks found for this student."}]

    student_marks["pct"] = student_marks["marks_obtained"] / student_marks["max_marks"].replace(0, 1) * 100

    # Subject-wise analysis
    subject_avg = student_marks.groupby("subject_name")["pct"].mean()

    for subj_name, avg in subject_avg.items():
        if avg < 40:
            recommendations.append({
                "type": "critical",
                "subject": subj_name,
                "message": f"⚠️ Critical: You are scoring below 40% in {subj_name} ({avg:.1f}%). "
                           f"Immediate attention required. Consider consulting faculty."
            })
        elif avg < 60:
            recommendations.append({
                "type": "warning",
                "subject": subj_name,
                "message": f"📚 Study More: {subj_name} needs improvement ({avg:.1f}%). "
                           f"Review fundamentals and practice more problems."
            })
        elif avg >= 85:
            recommendations.append({
                "type": "strength",
                "subject": subj_name,
                "message": f"✅ Strength: You are performing well in {subj_name} ({avg:.1f}%). Keep it up!"
            })

    # Overall average
    overall = student_marks["pct"].mean()
    if overall < 50:
        recommendations.append({
            "type": "critical",
            "message": f"Your overall average is {overall:.1f}%. Focus on your weakest subjects first."
        })
    elif overall < 70:
        recommendations.append({
            "type": "tip",
            "message": f"Your overall average is {overall:.1f}%. With consistent practice you can improve significantly."
        })
    else:
        recommendations.append({
            "type": "positive",
            "message": f"Great work! Your overall average is {overall:.1f}%. Keep maintaining this standard."
        })

    # Attendance recommendations
    if attendance_df is not None and not attendance_df.empty:
        student_att = attendance_df[attendance_df["student_id"] == student_id]
        if not student_att.empty:
            total = len(student_att)
            present = len(student_att[student_att["status"] == "present"])
            att_pct = (present / total * 100) if total > 0 else 0
            if att_pct < 75:
                recommendations.append({
                    "type": "critical",
                    "message": f"⚠️ Attendance Alert: Your attendance is {att_pct:.1f}%, below the 75% minimum. "
                               f"Improve attendance immediately to avoid academic penalties."
                })
            elif att_pct < 85:
                recommendations.append({
                    "type": "warning",
                    "message": f"📅 Attendance: {att_pct:.1f}% - aim for 85%+ to stay on track."
                })

    # Trend analysis (if multiple assessments)
    if "exam_index" in student_marks.columns:
        trend = student_marks.groupby("exam_index")["pct"].mean()
        if len(trend) >= 2:
            if trend.iloc[-1] < trend.iloc[-2] - 10:
                recommendations.append({
                    "type": "warning",
                    "message": "📉 Your recent scores show a declining trend. Review your study habits."
                })
            elif trend.iloc[-1] > trend.iloc[-2] + 10:
                recommendations.append({
                    "type": "positive",
                    "message": "📈 Great improvement in your recent assessments! Keep up the momentum."
                })

    return recommendations if recommendations else [{"type": "info", "message": "Keep up your consistent academic performance!"}]


def get_weak_areas(student_id, marks_df):
    """Returns list of weak subjects with scores."""
    if marks_df is None or marks_df.empty:
        return []

    student_marks = marks_df[marks_df["student_id"] == student_id].copy()
    if student_marks.empty:
        return []

    student_marks["pct"] = student_marks["marks_obtained"] / student_marks["max_marks"].replace(0, 1) * 100
    subject_avg = student_marks.groupby(["subject_id", "subject_name"])["pct"].mean().reset_index()
    subject_avg.columns = ["subject_id", "subject_name", "avg_pct"]
    subject_avg = subject_avg.sort_values("avg_pct")

    weak = subject_avg[subject_avg["avg_pct"] < 60].to_dict("records")
    return weak


def retrain_if_needed(department_id, marks_df, model_path, force=False):
    """Retrain model if enough new data is available."""
    if not os.path.exists(model_path) or force:
        X, y, _ = prepare_training_data(marks_df)
        return train_model(X, y, model_path)

    # Check training timestamp
    try:
        saved = joblib.load(model_path)
        trained_at = datetime.fromisoformat(saved.get("trained_at", "2000-01-01"))
        age_days = (datetime.utcnow() - trained_at).days
        if age_days > 7:  # Retrain weekly
            X, y, _ = prepare_training_data(marks_df)
            return train_model(X, y, model_path)
    except Exception:
        X, y, _ = prepare_training_data(marks_df)
        return train_model(X, y, model_path)

    return {"success": False, "reason": "model_is_recent"}
