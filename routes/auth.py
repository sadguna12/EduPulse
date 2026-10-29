from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime
from extensions import db
from models import User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/', methods=['GET'])
def index():
    if current_user.is_authenticated:
        return redirect(url_for(f'{current_user.role}.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(f'{current_user.role}.dashboard'))

    if request.method == 'POST':
        unique_id = request.form.get('unique_id', '').strip()
        password = request.form.get('password', '')

        if not unique_id or not password:
            flash('Please enter both ID and password.', 'danger')
            return render_template('auth/login.html')

        user = User.query.filter_by(unique_id=unique_id).first()

        if user and user.is_active and user.check_password(password):
            login_user(user, remember=False)
            user.last_login = datetime.utcnow()
            db.session.commit()

            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            return redirect(url_for(f'{user.role}.dashboard'))
        else:
            flash('Invalid ID or password. Please try again.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pwd = request.form.get('current_password', '')
        new_pwd = request.form.get('new_password', '')
        confirm_pwd = request.form.get('confirm_password', '')

        if not current_user.check_password(current_pwd):
            flash('Current password is incorrect.', 'danger')
        elif len(new_pwd) < 6:
            flash('New password must be at least 6 characters.', 'danger')
        elif new_pwd != confirm_pwd:
            flash('New passwords do not match.', 'danger')
        else:
            current_user.set_password(new_pwd)
            db.session.commit()
            flash('Password changed successfully!', 'success')
            return redirect(url_for(f'{current_user.role}.dashboard'))

    return render_template('auth/change_password.html')


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    profile_obj = None
    if current_user.role == 'admin':
        profile_obj = current_user.admin
    elif current_user.role == 'faculty':
        profile_obj = current_user.faculty
    elif current_user.role == 'student':
        profile_obj = current_user.student

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()

        if not name:
            flash('Name is required.', 'danger')
        elif profile_obj:
            profile_obj.name = name
            profile_obj.email = email if email else None
            profile_obj.phone = phone if phone else None
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html', profile=profile_obj)

