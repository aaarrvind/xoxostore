from flask_mail import Message, Mail
from flask import current_app, url_for, render_template
import secrets
import os
from datetime import datetime, timedelta, timezone
from itsdangerous import URLSafeTimedSerializer

# Create a global mail instance
mail = Mail()

def init_mail(app, mail_instance):
    """Initialize Flask-Mail with the app"""
    # Check if email configuration exists
    mail_username = os.getenv('MAIL_USERNAME')
    mail_password = os.getenv('MAIL_PASSWORD')
    mail_sender = os.getenv('MAIL_DEFAULT_SENDER')
    
    if not mail_username:
        app.logger.error("MAIL_USERNAME not set in environment variables")
        return False
    if not mail_password:
        app.logger.error("MAIL_PASSWORD not set in environment variables")
        return False
    if not mail_sender:
        app.logger.error("MAIL_DEFAULT_SENDER not set in environment variables")
        return False
        
    try:
        app.config['MAIL_SERVER'] = 'smtp.gmail.com'
        app.config['MAIL_PORT'] = 587
        app.config['MAIL_USE_TLS'] = True
        app.config['MAIL_USERNAME'] = mail_username
        app.config['MAIL_PASSWORD'] = mail_password
        app.config['MAIL_DEFAULT_SENDER'] = mail_sender
        mail_instance.init_app(app)
        app.logger.info("Flask-Mail initialized successfully")
        return True
    except Exception as e:
        app.logger.error(f"Failed to initialize Flask-Mail: {str(e)}")
        return False

def generate_verification_token():
    """Generate a secure random token"""
    return secrets.token_urlsafe(32)

def generate_verification_url(token):
    """Generate the verification URL"""
    return url_for('verify_email', token=token, _external=True)

def send_verification_email(user_email, token):
    """Send verification email to user"""
    try:
        if not current_app.mail:
            current_app.logger.error("Flask-Mail not initialized")
            return False
            
        verification_url = generate_verification_url(token)
        
        msg = Message(
            'Verify Your Email - XOXO By SLOG',
            recipients=[user_email]
        )
        
        msg.html = f'''
        <h2>Welcome to XOXO By SLOG!</h2>
        <p>Thank you for signing up. Please verify your email address by clicking the link below:</p>
        <p><a href="{verification_url}" style="
            display: inline-block;
            padding: 12px 24px;
            background-color: #007bff;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            margin: 20px 0;
        ">Verify Email Address</a></p>
        <p>If you did not create an account, please ignore this email.</p>
        <p>This link will expire in 24 hours.</p>
        <p>Best regards,<br>XOXO By SLOG Team</p>
        '''
        
        current_app.logger.info(f"Attempting to send verification email to {user_email}")
        current_app.logger.debug(f"Using SMTP server: {current_app.config['MAIL_SERVER']}:{current_app.config['MAIL_PORT']}")
        
        current_app.mail.send(msg)
        current_app.logger.info(f"Verification email sent successfully to {user_email}")
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send verification email to {user_email}")
        current_app.logger.error(f"Error details: {str(e)}")
        current_app.logger.error(f"SMTP Configuration: Server={current_app.config.get('MAIL_SERVER')}, "
                               f"Port={current_app.config.get('MAIL_PORT')}, "
                               f"Username={current_app.config.get('MAIL_USERNAME')}")
        return False

def is_valid_email(email):
    """Basic email validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def send_order_status_email(order, status):
    """Send order status update email to customer"""
    try:
        if not current_app.mail:
            current_app.logger.error("Flask-Mail not initialized")
            return False

        msg = Message(
            subject=f'Order Status Update - Order #{order.id}',
            recipients=[order.customer.email],
            html=render_template('email/order_status.html', order=order, status=status)
        )
        
        current_app.logger.info(f"Sending order status update email to {order.customer.email}")
        current_app.mail.send(msg)
        current_app.logger.info(f"Order status update email sent successfully to {order.customer.email}")
        return True
        
    except Exception as e:
        current_app.logger.error(f"Failed to send order status update email to {order.customer.email}: {str(e)}")
        return False

def send_order_confirmation_email(order):
    """Send order confirmation email to customer"""
    try:
        if not current_app.mail:
            current_app.logger.error("Flask-Mail not initialized")
            return False

        # Get customer email
        customer_email = order.customer.email
        if not customer_email:
            current_app.logger.error(f"No email found for customer in order #{order.id}")
            return False

        # Create message
        msg = Message(
            subject=f'Order Confirmation - Order #{order.id}',
            recipients=[customer_email],
            html=render_template('email/order_confirmation.html', order=order)
        )
        
        current_app.logger.info(f"Attempting to send order confirmation email to {customer_email}")
        current_app.logger.debug(f"Order details: ID={order.id}, Total=₹{order.total_price}")
        
        # Send email
        current_app.mail.send(msg)
        current_app.logger.info(f"Order confirmation email sent successfully to {customer_email}")
        return True
        
    except Exception as e:
        current_app.logger.error(f"Failed to send order confirmation email to {order.customer.email}: {str(e)}")
        current_app.logger.error(f"Error details: {str(e)}")
        return False 