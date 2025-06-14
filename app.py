from flask import Flask, render_template, redirect, url_for, flash, request, session
import logging
import json
from init_database import save_order_to_db, get_db_connection, test_order_insertion
from dotenv import load_dotenv
import os
from auth import auth_bp
from functools import wraps
import random
import string

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key')

app.register_blueprint(auth_bp, url_prefix='/auth')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

ITEM_PRICES = {
    "Pasta": 120.00,
    "Chi-Momo": 160.00,
    "Burger": 220.00,
    "Coffee": 120.00,
    "Tea": 30.00,
    "Chowmein": 180.00,
    "Samosa": 35.00,
    "Keema Noodles": 190.00,
    "Laphing": 120.00,
    "Corn Dog": 220.00,
    "Sauces": 330.00,
    "Momo": 150.00
}

DELIVERY_FEE = 10.00

def format_currency(value):
    return f"Nrs: {value:,.2f}"

@app.template_filter('format_currency')
def format_currency_filter(value):
    return format_currency(value)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_user():
    user = None
    user_id = session.get('user_id')
    if user_id:
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Error fetching user from DB: {e}", exc_info=True)
    return dict(user=user)

def generate_order_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

@app.route('/')
@app.route('/index.html')
def index():
    return render_template('index.html')

@app.route('/contactus.html')
def contactUs():
    return render_template('contactus.html')

@app.route('/aboutus.html')
def aboutus():
    return render_template('aboutus.html')

@app.route('/viewMenu.html', methods=['GET', 'POST'])
@login_required
def view_menu():
    if request.method == 'POST':
        items = {}
        for item in ITEM_PRICES:
            qty = request.form.get(item, 0)
            try:
                qty = int(qty)
                if qty > 0:
                    items[item] = qty
            except ValueError:
                flash(f"Invalid quantity for {item}.", "error")
                return redirect(url_for('view_menu'))
        if not items:
            flash("Please select at least one item!", "error")
            return redirect(url_for('view_menu'))
        session['items'] = json.dumps(items)
        logger.info(f"Menu items saved to session: {items}")
        return redirect(url_for('select_payment'))
    return render_template('viewMenu.html')

@app.route('/select-payment', methods=['GET', 'POST'])
@login_required
def select_payment():
    if request.method == 'POST':
        payment_method = request.form.get('payment_method')
        if payment_method not in ['card', 'cash_on_delivery']:
            flash("Invalid payment method selected.", "error")
            return redirect(url_for('view_menu'))
        
        if payment_method == 'card':
            flash("Online payment is not available in your country. Please use Cash on Delivery.", "error")
            return redirect(url_for('select_payment'))
        
        session['payment_method'] = payment_method
        logger.info(f"Payment method selected: {payment_method}")
        return redirect(url_for('order_details'))
    
    try:
        items = json.loads(session.get('items', '{}'))
    except json.JSONDecodeError:
        flash("Your session has expired. Please select items again.", "error")
        return redirect(url_for('view_menu'))
    
    if not items:
        flash("Please select items first.", "error")
        return redirect(url_for('view_menu'))
    
    subtotal = sum(ITEM_PRICES[item] * qty for item, qty in items.items())
    logger.info(f"Calculating order - subtotal: {subtotal}")
    return render_template('order_payment.html', 
                         items=items, 
                         subtotal=subtotal,
                         delivery_fee=DELIVERY_FEE,
                         ITEM_PRICES=ITEM_PRICES)

@app.route('/order-details', methods=['GET', 'POST'])
@login_required
def order_details():
    if request.method == 'POST':
        logger.info("Order details form submitted")
        customer_name = request.form.get('customer-name', '').strip()
        phone_number = request.form.get('phone-number', '').strip()
        customer_address = request.form.get('customer-address', '').strip()
        house_no = request.form.get('house-no', '').strip()
        
        logger.info(f"Received order details - Name: {customer_name}, Phone: {phone_number}, Address: {customer_address}")
        
        if not all([customer_name, phone_number, customer_address]):
            flash("Please fill in all required fields.", "error")
            logger.warning("Missing required fields in order form")
            return redirect(url_for('order_details'))
        
        try:
            items = json.loads(session.get('items', '{}'))
            payment_method = session.get('payment_method', 'cash_on_delivery')
            
            if not items:
                flash("Your order is empty. Please select items again.", "error")
                logger.warning("Empty items in session during order processing")
                return redirect(url_for('view_menu'))
            
            subtotal = sum(ITEM_PRICES[item] * qty for item, qty in items.items())
            delivery_fee = DELIVERY_FEE if payment_method == 'cash_on_delivery' else 0
            total_price = subtotal + delivery_fee
            
            logger.info(f"Order calculations - Subtotal: {subtotal}, Delivery: {delivery_fee}, Total: {total_price}")
            
            order_details = {}
            for item_name, quantity in items.items():
                order_details[item_name] = {
                    'quantity': quantity,
                    'item_total': ITEM_PRICES[item_name] * quantity
                }
            
            order_code = generate_order_code()
            user_id = session.get('user_id')
            
            logger.info(f"Attempting to save order with code: {order_code} for user: {user_id}")
            
            order_id = save_order_to_db(
                customer_name=customer_name,
                phone_number=phone_number,
                customer_address=customer_address,
                order_details=order_details,
                total_price=total_price,
                user_id=user_id,
                payment_method=payment_method,
                order_code=order_code,
                delivery_fee=delivery_fee
            )
            
            if not order_id:
                flash("Failed to save order. Please try again.", "error")
                logger.error("Order save returned None")
                return redirect(url_for('view_menu'))
            
            logger.info(f"Order saved successfully with ID: {order_id}")
            
            session.pop('items', None)
            session.pop('payment_method', None)
            
            return render_template('order_summary.html',
                               customer_name=customer_name,
                               customer_address=customer_address,
                               house_no=house_no if house_no else 'N/A',
                               phone_number=phone_number,
                               order_details=order_details,
                               subtotal=subtotal,
                               total_price=total_price,
                               payment_method=payment_method,
                               order_code=order_code,
                               delivery_fee=delivery_fee)
        
        except Exception as e:
            logger.error(f"Order processing error: {str(e)}", exc_info=True)
            flash(f"An error occurred: {str(e)}", "error")
            return redirect(url_for('view_menu'))
    
    return render_template('order.html')

@app.route('/test-db-insert')
def test_db_insert():
    try:
        result = test_order_insertion()
        return f"Test order insertion result: {result}"
    except Exception as e:
        return f"Error during test insertion: {str(e)}"

@app.route('/test-db')
def test_db():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT version()")
            version = cursor.fetchone()
            
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = DATABASE()
            """)
            tables = [row[0] for row in cursor.fetchall()]
            
            counts = {}
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                counts[table] = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            return render_template('db_test.html',
                                 version=version[0],
                                 tables=tables,
                                 counts=counts)
        except Exception as e:
            return f"Error: {str(e)}"
    return "Failed to connect to database"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)