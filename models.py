from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    is_featured = db.Column(db.Boolean, default=False)
    stock_s = db.Column(db.Integer, default=0)
    stock_m = db.Column(db.Integer, default=0)
    stock_l = db.Column(db.Integer, default=0)
    stock_xl = db.Column(db.Integer, default=0)
    category = db.Column(db.String(50), nullable=False, default='tshirt')
    images = db.relationship('ProductImage', backref='product', lazy=True, cascade="all, delete-orphan")  # New relationship

class ProductImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    image_filename = db.Column(db.String(200), nullable=False)
    

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)

    product = db.relationship('Product')


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    items = db.Column(db.Text, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(20), nullable=False, default='COD')
    payment_status = db.Column(db.String(20), nullable=False, default='Pending')
    order_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # Delivery address fields
    delivery_address = db.Column(db.String(200), nullable=False)
    delivery_city = db.Column(db.String(100), nullable=False)
    delivery_state = db.Column(db.String(100), nullable=False)
    delivery_pincode = db.Column(db.String(20), nullable=False)
    delivery_phone = db.Column(db.String(20), nullable=False)
    # New fields for advance payment
    advance_payment = db.Column(db.Float, nullable=False, default=0.0)
    remaining_amount = db.Column(db.Float, nullable=False, default=0.0)
    advance_payment_status = db.Column(db.String(20), nullable=False, default='Pending')
    customer = db.relationship('Customer', backref='orders')

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100), unique=True)
    verification_token_expires = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
