import mysql.connector
import os
from dotenv import load_dotenv
import logging
from werkzeug.security import generate_password_hash, check_password_hash
from typing import Optional, Dict, Any, Union
import time

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('database.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_db_connection():
    """Create and return a new database connection with retry logic"""
    max_retries = 3
    retry_delay = 1  # seconds

    for attempt in range(max_retries):
        try:
            conn = mysql.connector.connect(
                host=os.getenv('DB_HOST', 'localhost'),
                user=os.getenv('DB_USER', 'root'),
                password=os.getenv('DB_PASSWORD', ''),
                database=os.getenv('DB_NAME', 'digibistro'),
                port=3306,
                auth_plugin='mysql_native_password',
                connect_timeout=5
            )
            logger.info("Database connection established successfully")
            return conn
        except mysql.connector.Error as err:
            logger.error(f"Database connection attempt {attempt + 1} failed: {err}")
            if attempt == max_retries - 1:
                raise
            time.sleep(retry_delay)
    return None

def create_tables() -> bool:
    """Create database tables with proper constraints and indexes"""
    table_definitions = [
        """CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            first_name VARCHAR(50) NOT NULL,
            last_name VARCHAR(50) NOT NULL,
            username VARCHAR(50) UNIQUE NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )""",

        """CREATE TABLE IF NOT EXISTS orders (
            order_id INT AUTO_INCREMENT PRIMARY KEY,
            customer_name VARCHAR(100) NOT NULL,
            phone_number VARCHAR(15) NOT NULL,
            customer_address TEXT NOT NULL,
            total_price DECIMAL(10,2) NOT NULL,
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INT NULL,
            payment_method VARCHAR(20) NOT NULL,
            order_code VARCHAR(10) UNIQUE,
            delivery_fee DECIMAL(10,2) DEFAULT 0,
            status ENUM('pending', 'processing', 'completed', 'cancelled') DEFAULT 'pending',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )""",

        """CREATE TABLE IF NOT EXISTS order_items (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT NOT NULL,
            item_name VARCHAR(50) NOT NULL,
            quantity INT NOT NULL,
            item_total DECIMAL(10,2) NOT NULL,
            notes TEXT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
        )"""
    ]

    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            for table_def in table_definitions:
                cursor.execute(table_def)
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Tables created/verified successfully")
            return True
    except mysql.connector.Error as err:
        logger.error(f"Error creating tables: {err}", exc_info=True)
        return False

def save_user(first_name: str, last_name: str, username: str, email: str, password: str) -> Optional[int]:
    """Save a new user with hashed password"""
    password_hash = generate_password_hash(password)
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute('''INSERT INTO users (first_name, last_name, username, email, password_hash)
                          VALUES (%s, %s, %s, %s, %s)''',
                       (first_name, last_name, username, email, password_hash))
            user_id = cursor.lastrowid
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"User {username} created with ID: {user_id}")
            return user_id
    except mysql.connector.IntegrityError as ie:
        logger.error(f"User creation failed (duplicate entry): {ie}")
        return None
    except Exception as e:
        logger.error(f"Error saving user: {e}", exc_info=True)
        return None

def get_user(username: str) -> Optional[Dict[str, Any]]:
    """Retrieve user by username"""
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()
            return user
    except Exception as e:
        logger.error(f"Error fetching user: {e}", exc_info=True)
        return None

def save_order_to_db(
    customer_name: str,
    phone_number: str,
    customer_address: str,
    order_details: Dict[str, Dict[str, Union[int, float]]],
    total_price: float,
    user_id: Optional[int] = None,
    payment_method: str = 'cash_on_delivery',
    order_code: Optional[str] = None,
    delivery_fee: float = 0,
    status: str = 'pending'
) -> Optional[int]:
    """Save a complete order with items to the database with transaction"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to establish database connection")
            return None

        cursor = conn.cursor()

        # Start transaction
        conn.start_transaction()

        # Insert order header
        cursor.execute('''INSERT INTO orders
                      (customer_name, phone_number, customer_address, total_price,
                       user_id, payment_method, order_code, delivery_fee, status)
                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                   (customer_name, phone_number, customer_address, total_price,
                    user_id, payment_method, order_code, delivery_fee, status))

        order_id = cursor.lastrowid
        if not order_id:
            raise Exception("Failed to get order ID after insertion")

        logger.info(f"Order record created with ID: {order_id}")

        # Insert order items
        items = []
        for item, details in order_details.items():
            if not isinstance(details, dict):
                logger.error(f"Invalid order details format for item {item}")
                raise ValueError(f"Invalid order details format for item {item}")

            quantity = details.get('quantity', 0)
            item_total = details.get('item_total', 0)

            if quantity <= 0:
                logger.warning(f"Invalid quantity {quantity} for item {item}")
                continue

            items.append((order_id, item, quantity, item_total))

        if not items:
            raise ValueError("No valid items to insert")

        cursor.executemany('''INSERT INTO order_items
                           (order_id, item_name, quantity, item_total)
                           VALUES (%s, %s, %s, %s)''', items)

        conn.commit()
        logger.info(f"Order {order_id} committed successfully")
        return order_id

    except mysql.connector.IntegrityError as ie:
        logger.error(f"Integrity error saving order: {ie}")
        if conn:
            conn.rollback()
        return None
    except Exception as e:
        logger.error(f"Error saving order: {str(e)}", exc_info=True)
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            if conn.is_connected():
                cursor.close()
                conn.close()

def test_order_insertion() -> str:
    """Test order insertion functionality"""
    try:
        order_id = save_order_to_db(
            customer_name="Test Customer",
            phone_number="1234567890",
            customer_address="123 Test Street",
            order_details={"Pasta": {"quantity": 2, "item_total": 240.00}},
            total_price=250.00,
            user_id=1,
            payment_method="cash_on_delivery",
            order_code="TEST01",
            delivery_fee=10.00
        )

        if order_id:
            return f"Success - Order ID: {order_id}"
        return "Failed - Order ID not returned"
    except Exception as e:
        return f"Error: {str(e)}"

# Initialize tables when module is imported
if __name__ == '__main__':
    create_tables()