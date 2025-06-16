from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from init_database import get_user, save_user
from werkzeug.security import check_password_hash, generate_password_hash
import re
from init_database import  get_db_connection
import os
import mysql.connector

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = get_user(username)
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('Logged in successfully!', 'success')
            next_url = request.args.get('next', url_for('view_menu'))
            return redirect(next_url)
        flash('Invalid username or password.', 'error')
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('Logged out successfully!', 'success')
    return redirect(url_for('index'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not all([first_name, last_name, username, email, password]):
            flash('All fields are required.', 'error')
            return redirect(url_for('auth.register'))

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('Please enter a valid email address.', 'error')
            return redirect(url_for('auth.register'))

        if get_user(username):
            flash('Username already exists.', 'error')
            return redirect(url_for('auth.register'))

        user_id = save_user(first_name, last_name, username, email, password)
        if user_id:
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('auth.login'))
        flash('Registration failed. Please try again.', 'error')
    return render_template('register.html')

@auth_bp.route('/register-admin', methods=['GET', 'POST'])
def register_admin():
    # Only allow admin registration if no admins exist yet
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin = TRUE")
    admin_count = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    if admin_count > 0:
        flash("Admin registration is closed", "error")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        secret_key = request.form.get('secret_key')
        if secret_key != os.getenv('ADMIN_SECRET_KEY', 'default_admin_key'):
            flash("Invalid admin registration key", "error")
            return redirect(url_for('auth.register_admin'))

        # Proceed with normal registration but set as admin
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO users 
                (first_name, last_name, username, email, password_hash, is_admin)
                VALUES (%s, %s, %s, %s, %s, TRUE)""",
                (first_name, last_name, username, email, generate_password_hash(password))
            )
            conn.commit()
            user_id = cursor.lastrowid
            cursor.close()
            conn.close()
            
            flash('Admin account created successfully! Please log in.', 'success')
            return redirect(url_for('auth.login'))
        except mysql.connector.IntegrityError:
            flash('Username or email already exists', 'error')
        except Exception as e:
            flash('Registration failed. Please try again.', 'error')

    return render_template('register_admin.html')