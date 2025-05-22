from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    current_app,
)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from models import Customer, Order, db, Product, ProductImage
from dotenv import load_dotenv
from flask_login import login_required
from flask_migrate import Migrate
from datetime import datetime, timedelta, timezone
from email_utils import (
    init_mail,
    generate_verification_token,
    send_verification_email,
    is_valid_email,
)
from flask_mail import Mail
from flask_mail import Message
import redis

load_dotenv()

app = Flask(__name__)
csrf = CSRFProtect(app)
migrate = Migrate(app, db)

# Initialize Flask-Mail
mail = Mail(app)

# Configure Flask-Limiter with memory storage initially
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Initialize Redis after app creation
def init_redis():
    redis_url = os.getenv('REDIS_URL')
    if redis_url:
        try:
            redis_client = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=30,
                socket_timeout=30,
                retry_on_timeout=True,
                health_check_interval=30,
                ssl=True
            )
            # Test the connection
            redis_client.ping()
            app.logger.info("Successfully connected to Redis Cloud")
            
            # Update limiter to use Redis
            limiter.storage_uri = redis_url
            limiter.storage_options = {
                "socket_connect_timeout": 30,
                "socket_timeout": 30,
                "retry_on_timeout": True,
                "ssl": True
            }
            return redis_client
        except Exception as e:
            app.logger.error(f"Failed to connect to Redis Cloud: {str(e)}")
            return None
    else:
        app.logger.warning("No REDIS_URL provided, using memory storage")
        return None

# Initialize Redis
redis_client = init_redis()

# Load configuration from environment variables
app.config["RATELIMIT_STORAGE_URL"] = os.getenv("REDIS_URL", "memory://")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY", "your_secret_key_here"
)  # Fallback for development
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = 3600  # 1 hour in seconds

# Mail configuration
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER")

db.init_app(app)

# Initialize Flask-Mail with app context
with app.app_context():
    init_mail(app, mail)

# Make mail instance available globally
app.mail = mail

# Admin login credentials
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# Configure upload folder
UPLOAD_FOLDER = "static/images"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Valid categories
VALID_CATEGORIES = ["tshirt", "shirt", "accessories", "jacket"]

# Allowed image extensions
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif"}


# Context processor to provide cart item count to all templates
@app.context_processor
def inject_cart_item_count():
    cart = session.get("cart", {})
    cart_item_count = 0
    for value in cart.values():
        if isinstance(value, dict):  # New format: {size: quantity}
            cart_item_count += sum(value.values())
        else:  # Old format: quantity (int)
            cart_item_count += value
    return dict(cart_item_count=cart_item_count)


@app.route("/")
def home():
    products = Product.query.filter_by(is_featured=True).limit(3).all()
    return render_template("home.html", products=products)


@app.route("/shop")
def shop():
    page = request.args.get("page", 1, type=int)
    per_page = 9  # Show 9 products per page (3x3 grid)
    products = Product.query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template("shop.html", products=products, category=None)


@app.route("/shop/category/<category>")
def shop_category(category):
    if category not in VALID_CATEGORIES:
        flash(f"Invalid category: {category}. Showing all products instead.", "warning")
        return redirect(url_for("shop"))

    page = request.args.get("page", 1, type=int)
    per_page = 9  # Show 9 products per page (3x3 grid)
    products = Product.query.filter_by(category=category).paginate(
        page=page, per_page=per_page, error_out=False
    )
    category_title = category.capitalize() + "s"
    return render_template(
        "shop.html",
        products=products,
        category_title=f"Shop {category_title}",
        category=category,
    )


@app.route("/product/<int:product_id>", methods=["GET", "POST"])
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template("product.html", product=product)


@app.route("/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    if "cart" not in session:
        session["cart"] = {}

    cart = session["cart"]
    quantity = int(request.form.get("quantity", 1))
    size = request.form.get("size")

    if not size:
        flash("Please select a size before adding to cart.", "danger")
        return redirect(request.referrer or url_for("shop"))

    product = Product.query.get_or_404(product_id)
    stock_field = f"stock_{size.lower()}"
    available_stock = getattr(product, stock_field, 0)

    current_quantity = cart.get(str(product_id), {}).get(size, 0)
    new_quantity = current_quantity + quantity

    if new_quantity > available_stock:
        error_message = (
            f"Not enough stock for size {size}. Only {available_stock} left."
        )
        return render_template("product.html", product=product, error=error_message)

    if str(product_id) not in cart:
        cart[str(product_id)] = {}

    cart[str(product_id)][size] = new_quantity
    session["cart"] = cart
    flash(f"Added {quantity} {product.name} (size {size}) to your cart!", "success")
    return redirect(url_for("product_detail", product_id=product_id))


@app.route("/update_cart/<int:product_id>", methods=["POST"])
def update_cart(product_id):
    if "cart" not in session:
        session["cart"] = {}

    cart = session["cart"]
    quantity = int(request.form.get("quantity", 1))
    size = request.form.get("size")

    if quantity < 1:
        quantity = 1

    product = Product.query.get_or_404(product_id)
    stock_field = f"stock_{size.lower()}"
    available_stock = getattr(product, stock_field, 0)

    if quantity > available_stock:
        quantity = available_stock
        flash(
            f"Adjusted quantity to available stock for size {size}: {available_stock}",
            "warning",
        )

    if str(product_id) in cart and size in cart[str(product_id)]:
        cart[str(product_id)][size] = quantity
        session["cart"] = cart

    return redirect(url_for("cart"))


@app.route("/remove_from_cart/<int:product_id>", methods=["POST"])
def remove_from_cart(product_id):
    if "cart" in session:
        cart = session["cart"]
        size = request.form.get("size")
        if str(product_id) in cart and size in cart[str(product_id)]:
            del cart[str(product_id)][size]
            if not cart[str(product_id)]:
                del cart[str(product_id)]
            session["cart"] = cart
    return redirect(url_for("cart"))


@app.route("/cart")
def cart():
    cart = session.get("cart", {})
    cart_items = []
    total_price = 0

    for product_id, sizes in cart.items():
        product = Product.query.get(int(product_id))
        if product:
            if isinstance(sizes, dict):
                for size, quantity in sizes.items():
                    stock_field = f"stock_{size.lower()}"
                    available_stock = getattr(product, stock_field, 0)
                    if quantity > available_stock:
                        quantity = available_stock
                        cart[str(product_id)][size] = quantity
                        session["cart"] = cart
                        flash(
                            f"Adjusted quantity for {product.name} (size {size}) to available stock: {available_stock}",
                            "warning",
                        )

                    item_total = product.price * quantity
                    total_price += item_total
                    cart_items.append(
                        {
                            "product": product,
                            "size": size,
                            "quantity": quantity,
                            "item_total": item_total,
                        }
                    )
            else:
                quantity = sizes
                item_total = product.price * quantity
                total_price += item_total
                cart_items.append(
                    {
                        "product": product,
                        "size": "N/A",
                        "quantity": quantity,
                        "item_total": item_total,
                    }
                )

    return render_template("cart.html", cart_items=cart_items, total_price=total_price)


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    # Check if user is logged in
    if not session.get("customer_id"):
        session["next"] = url_for("checkout")  # Store the intended destination
        flash("Please login to complete your purchase", "warning")
        return redirect(url_for("login"))

    cart = session.get("cart", {})
    if not cart:
        return redirect(url_for("home"))
    
    cart_items = []
    total_price = 0
    
    for product_id, sizes in cart.items():
        product = Product.query.get(int(product_id))
        if product:
            if isinstance(sizes, dict):
                for size, quantity in sizes.items():
                    stock_field = f"stock_{size.lower()}"
                    available_stock = getattr(product, stock_field, 0)
                    if quantity > available_stock:
                        quantity = available_stock
                        cart[str(product_id)][size] = quantity
                        session["cart"] = cart
                        flash(
                            f"Adjusted quantity for {product.name} (size {size}) to available stock: {available_stock}",
                            "warning",
                        )
                    item_total = product.price * quantity
                    total_price += item_total
                    cart_items.append(
                        {
                            "product": product,
                            "size": size,
                            "quantity": quantity,
                            "item_total": item_total,
                        }
                    )
            else:
                quantity = sizes
                item_total = product.price * quantity
                total_price += item_total
                cart_items.append(
                    {
                        "product": product,
                        "size": "N/A",
                        "quantity": quantity,
                        "item_total": item_total,
                    }
                )

    if request.method == "POST":
        # Validate required address fields
        required_fields = [
            "delivery_address",
            "delivery_city",
            "delivery_state",
            "delivery_pincode",
            "delivery_phone",
        ]
        for field in required_fields:
            if not request.form.get(field):
                flash(f'Please provide your {field.replace("_", " ")}', "danger")
                return redirect(url_for("checkout"))

        payment_method = request.form.get("payment_method", "COD")
        order_items = []
        
        try:
            # Start a transaction
            for item in cart_items:
                product = item["product"]
                size = item["size"]
                quantity = item["quantity"]
                
                # Reduce stock immediately for both COD and Online payment
                if size != "N/A":
                    stock_field = f"stock_{size.lower()}"
                    current_stock = getattr(product, stock_field, 0)
                    if current_stock < quantity:
                        raise ValueError(f"Not enough stock for {product.name} (size {size})")
                    new_stock = current_stock - quantity
                    setattr(product, stock_field, new_stock)
                
                if size == "N/A":
                    order_items.append(f"{product.name} x {quantity}")
                else:
                    order_items.append(f"{product.name} ({size}) x {quantity}")

            # Create order with customer_id and delivery address
            order = Order(
                customer_id=session["customer_id"],
                items=", ".join(order_items),
                total_price=total_price,
                payment_method=payment_method,
                payment_status="Pending",
                delivery_address=request.form["delivery_address"],
                delivery_city=request.form["delivery_city"],
                delivery_state=request.form["delivery_state"],
                delivery_pincode=request.form["delivery_pincode"],
                delivery_phone=request.form["delivery_phone"],
            )

            if payment_method == "COD":
                # Set advance payment details for COD
                order.advance_payment = 200.0
                order.remaining_amount = total_price - 200.0
                order.advance_payment_status = "Pending"
            
            db.session.add(order)
            db.session.commit()

            if payment_method == "COD":
                return render_template("advance_payment.html", total_price=total_price, order_id=order.id)
            else:  # Online payment
                return render_template("payment.html", total_price=total_price, order_id=order.id)
                
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "danger")
            return redirect(url_for("checkout"))
        except Exception as e:
            db.session.rollback()
            flash("An error occurred while processing your order. Please try again.", "danger")
            return redirect(url_for("checkout"))

    return render_template(
        "checkout.html", cart_items=cart_items, total_price=total_price
    )


@app.route("/process_dummy_payment/<int:order_id>", methods=["POST"])
def process_dummy_payment(order_id):
    order = Order.query.get_or_404(order_id)
    card_number = request.form.get("card_number")
    # Simulate payment logic: accept test card "4111 1111 1111 1111"
    if card_number == "4111 1111 1111 1111":
        try:
            order.payment_status = "Completed"
            # Deduct stock for successful payment
            items = order.items.split(", ")
            for item in items:
                # Parse item string, e.g., "Test T-Shirt (M) x 2"
                name_size, quantity = item.rsplit(" x ", 1)
                quantity = int(quantity)
                if "(" in name_size:
                    name, size = name_size.split(" (")
                    size = size.rstrip(")")
                    product = Product.query.filter_by(name=name).first()
                    if product:
                        stock_field = f"stock_{size.lower()}"
                        current_stock = getattr(product, stock_field, 0)
                        new_stock = max(0, current_stock - quantity)
                        setattr(product, stock_field, new_stock)
            
            db.session.commit()
            
            # Send order confirmation email
            try:
                from email_utils import send_order_confirmation_email
                if send_order_confirmation_email(order):
                    current_app.logger.info(f"Order confirmation email sent successfully for order #{order.id}")
                else:
                    current_app.logger.warning(f"Failed to send order confirmation email for order #{order.id}")
            except Exception as e:
                current_app.logger.error(f"Error sending order confirmation email: {str(e)}")
            
            flash("Test payment successful!", "success")
            session.pop("cart", None)
            return render_template("order_success.html", order=order)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error processing payment: {str(e)}")
            flash("An error occurred while processing your payment", "error")
            return redirect(url_for("cart"))
    else:
        order.payment_status = "Failed"
        db.session.commit()
        flash("Test payment failed. Please use card number 4111 1111 1111 1111.", "danger")
        return render_template("order_success.html", order=order)


@app.route("/process_advance_payment/<int:order_id>", methods=["POST"])
def process_advance_payment(order_id):
    order = Order.query.get_or_404(order_id)
    card_number = request.form.get("card_number")

    # Simulate payment logic: accept test card "4111 1111 1111 1111"
    if card_number == "4111 1111 1111 1111":
        try:
            order.advance_payment_status = "Completed"
            order.payment_status = "Pending"  # Main payment still pending
            db.session.commit()

            # Send order confirmation email
            try:
                from email_utils import send_order_confirmation_email

                if send_order_confirmation_email(order):
                    current_app.logger.info(
                        f"Order confirmation email sent successfully for order #{order.id}"
                    )
                else:
                    current_app.logger.warning(
                        f"Failed to send order confirmation email for order #{order.id}"
                    )
            except Exception as e:
                current_app.logger.error(
                    f"Error sending order confirmation email: {str(e)}"
                )

            flash(
                "Advance payment successful! Please pay the remaining amount at delivery.",
                "success",
            )
            session.pop("cart", None)
            return render_template("order_success.html", order=order)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error processing advance payment: {str(e)}")
            flash("An error occurred while processing your payment", "error")
            return redirect(url_for("checkout"))
    else:
        flash(
            "Test payment failed. Please use card number 4111 1111 1111 1111.", "danger"
        )
        return redirect(url_for("checkout"))


@app.route("/clear_session")
def clear_session():
    session.pop("cart", None)
    return "Session cleared"


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        message = request.form.get("message")
        flash(
            f"Thank you, {name}! Your message has been received. We'll get back to you at {email} soon.",
            "success",
        )
        return redirect(url_for("contact"))
    return render_template("contact.html")


# Admin Routes
def allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/admin")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    page = request.args.get("page", 1, type=int)
    per_page = 10  # Show 10 products per page in admin dashboard

    products = Product.query.order_by(Product.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template("admin/admin_dashboard.html", products=products)


@app.route("/admin/orders")
def admin_orders():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    # Get search parameters from request
    search_id = request.args.get("search_id")
    search_customer = request.args.get("search_customer")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    status = request.args.get("status")
    payment_method = request.args.get("payment_method")
    page = request.args.get("page", 1, type=int)
    per_page = 10  # Show 10 orders per page

    # Start with base query
    query = Order.query

    # Apply filters if provided
    if search_id:
        query = query.filter(Order.id == search_id)
    if search_customer:
        query = query.join(Customer).filter(
            (Customer.name.ilike(f"%{search_customer}%"))
            | (Customer.email.ilike(f"%{search_customer}%"))
        )
    if start_date:
        query = query.filter(Order.order_date >= start_date)
    if end_date:
        query = query.filter(Order.order_date <= end_date)
    if status:
        query = query.filter(Order.payment_status == status)
    if payment_method:
        query = query.filter(Order.payment_method == payment_method)

    # Order by date descending and paginate
    orders = query.order_by(Order.order_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Fetch customer details for each order
    order_details = []
    for order in orders.items:
        customer = Customer.query.get(order.customer_id)
        order_details.append(
            {
                "order": order,
                "customer_name": customer.name if customer else "Unknown",
                "customer_email": customer.email if customer else "Unknown",
            }
        )

    return render_template(
        "admin/admin_orders.html",
        order_details=order_details,
        orders=orders,
        search_id=search_id,
        search_customer=search_customer,
        start_date=start_date,
        end_date=end_date,
        status=status,
        payment_method=payment_method,
    )


@app.route("/admin/add", methods=["GET", "POST"])
def add_product():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        try:
            name = request.form["name"]
            price = float(request.form["price"])
            description = request.form["description"]
            is_featured = "is_featured" in request.form
            stock_s = int(request.form.get("stock_s", 0))
            stock_m = int(request.form.get("stock_m", 0))
            stock_l = int(request.form.get("stock_l", 0))
            stock_xl = int(request.form.get("stock_xl", 0))
            category = request.form.get("category", "tshirt")

            if category not in VALID_CATEGORIES:
                flash(f"Invalid category: {category}.", "danger")
                return redirect(url_for("add_product"))

            product = Product(
                name=name,
                price=price,
                description=description,
                is_featured=is_featured,
                stock_s=stock_s,
                stock_m=stock_m,
                stock_l=stock_l,
                stock_xl=stock_xl,
                category=category,
            )
            db.session.add(product)
            db.session.commit()

            images = request.files.getlist("images")
            for image in images:
                if image and allowed_file(image.filename):
                    image_filename = image.filename
                    image_path = os.path.join(
                        app.config["UPLOAD_FOLDER"], image_filename
                    )
                    if not os.path.exists(image_path):
                        image.save(image_path)
                    product_image = ProductImage(
                        product_id=product.id, image_filename=image_filename
                    )
                    db.session.add(product_image)

            db.session.commit()
            flash(f"Product '{name}' added successfully!", "success")
            return redirect(url_for("admin_dashboard"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding product: {str(e)}", "danger")
            return redirect(url_for("add_product"))

    return render_template("admin/add_product.html")


@app.route("/admin/edit/<int:product_id>", methods=["GET", "POST"])
def edit_product(product_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    
    product = Product.query.get_or_404(product_id)
    
    if request.method == "POST":
        try:
            # Debug: Log when a POST request is received
            print(f"Received POST request for product ID {product_id}")
            print(f"Form data received: {request.form}")

            # Validate required fields
            if (
                "name" not in request.form
                or "price" not in request.form
                or "description" not in request.form
            ):
                flash(
                    "Missing required fields (name, price, or description).", "danger"
                )
                return redirect(url_for("edit_product", product_id=product_id))

            if "category" not in request.form:
                flash("Category is required.", "danger")
                return redirect(url_for("edit_product", product_id=product_id))

            # Update product fields
            product.name = request.form["name"]
            product.price = float(request.form["price"])
            product.description = request.form["description"]
            product.is_featured = "is_featured" in request.form

            # Handle stock fields, ensuring they are submitted
            stock_s = request.form.get("stock_s")
            stock_m = request.form.get("stock_m")
            stock_l = request.form.get("stock_l")
            stock_xl = request.form.get("stock_xl")

            # Validate stock fields
            if (
                stock_s is None
                or stock_m is None
                or stock_l is None
                or stock_xl is None
            ):
                flash("All stock fields (S, M, L, XL) are required.", "danger")
                return redirect(url_for("edit_product", product_id=product_id))

            product.stock_s = int(stock_s)
            product.stock_m = int(stock_m)
            product.stock_l = int(stock_l)
            product.stock_xl = int(stock_xl)

            product.category = request.form["category"]
            if product.category not in VALID_CATEGORIES:
                flash(f"Invalid category: {product.category}.", "danger")
                return redirect(url_for("edit_product", product_id=product_id))

            # Handle new image uploads
            images = request.files.getlist("images")
            for image in images:
                if image and allowed_file(image.filename):
                    image_filename = image.filename
                    image_path = os.path.join(
                        app.config["UPLOAD_FOLDER"], image_filename
                    )
                    if not os.path.exists(image_path):
                        image.save(image_path)
                    product_image = ProductImage(
                        product_id=product.id, image_filename=image_filename
                    )
                    db.session.add(product_image)

            db.session.commit()
            flash(f"Product '{product.name}' updated successfully!", "success")
            return redirect(url_for("admin_dashboard"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating product: {str(e)}", "danger")
            return redirect(url_for("edit_product", product_id=product_id))

    return render_template("admin/edit_product.html", product=product)


@app.route("/admin/delete_image/<int:image_id>", methods=["POST"])
def delete_image(image_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    try:
        image = ProductImage.query.get_or_404(image_id)
        product_id = image.product_id
        filename = image.image_filename
        db.session.delete(image)
        db.session.commit()

        remaining_references = ProductImage.query.filter_by(
            image_filename=filename
        ).count()
        if remaining_references == 0:
            image_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            if os.path.exists(image_path):
                os.remove(image_path)

        flash(f"Image '{filename}' removed from product!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error removing image: {str(e)}", "danger")

    return redirect(url_for("edit_product", product_id=product_id))


@app.route("/admin/delete/<int:product_id>", methods=["POST"])
def delete_product(product_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    
    product = Product.query.get_or_404(product_id)
    try:
        # Delete product first
        db.session.delete(product)
        db.session.commit()

        # Check for orphaned images and delete files
        for image in product.images:
            remaining_references = ProductImage.query.filter_by(
                image_filename=image.image_filename
            ).count()
            if remaining_references == 0:
                image_path = os.path.join(
                    app.config["UPLOAD_FOLDER"], image.image_filename
                )
                if os.path.exists(image_path):
                    os.remove(image_path)

        flash(f"Product '{product.name}' deleted successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting product: {str(e)}", "danger")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("3 per 5 minutes")
def admin_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            return render_template(
                "admin/admin_login.html", error="Invalid credentials. Try again."
            )

    return render_template("admin/admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


# User Routes
@app.route("/test-email")
def test_email():
    """Test route to verify email configuration and send a test email"""
    try:
        # Check if mail configuration is set
        if not all(
            [
                app.config.get("MAIL_USERNAME"),
                app.config.get("MAIL_PASSWORD"),
                app.config.get("MAIL_DEFAULT_SENDER"),
            ]
        ):
            return (
                "Email configuration is incomplete. Please check your environment variables.",
                500,
            )

        # Create a test message
        msg = Message(
            subject="Test Email from XOXO By SLOG",
            recipients=[app.config["MAIL_USERNAME"]],  # Send to the configured email
            body="This is a test email to verify the email configuration.",
            html="<h1>Test Email</h1><p>This is a test email to verify the email configuration.</p>",
        )

        # Send the email
        app.mail.send(msg)
        return "Test email sent successfully! Please check your inbox.", 200

    except Exception as e:
        app.logger.error(f"Error sending test email: {str(e)}")
        return f"Error sending test email: {str(e)}", 500


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        # Validate email format
        if not is_valid_email(email):
            flash("Please enter a valid email address.", "danger")
            return redirect(url_for("signup"))

        existing_customer = Customer.query.filter_by(email=email).first()
        if existing_customer:
            flash("Email already registered.", "danger")
            return redirect(url_for("signup"))

        # Generate verification token
        verification_token = generate_verification_token()
        # Ensure timezone-aware datetime
        token_expires = datetime.now(timezone.utc) + timedelta(hours=24)

        hashed_password = generate_password_hash(password)
        new_customer = Customer(
            name=name,
            email=email,
            password=hashed_password,
            verification_token=verification_token,
            verification_token_expires=token_expires,
        )

        try:
            db.session.add(new_customer)
            db.session.commit()

            # Send verification email
            if not init_mail(app, app.mail):
                flash(
                    "Email service is not properly configured. Please contact support.",
                    "danger",
                )
                return redirect(url_for("signup"))

            if send_verification_email(email, verification_token):
                flash(
                    "Registration successful! Please check your email to verify your account.",
                    "success",
                )
            else:
                flash(
                    "Registration successful, but we could not send the verification email. Please contact support.",
                    "warning",
                )

            return redirect(url_for("login"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error during signup: {str(e)}")
            flash("An error occurred during registration. Please try again.", "danger")
            return redirect(url_for("signup"))

    return render_template("signup.html")


@app.route("/verify-email/<token>")
def verify_email(token):
    customer = Customer.query.filter_by(verification_token=token).first()

    if not customer:
        return render_template(
            "verify_email.html",
            success=False,
            error_message="Invalid verification link.",
        )

    # Convert naive datetime to UTC if it's not already timezone-aware
    if customer.verification_token_expires.tzinfo is None:
        customer.verification_token_expires = (
            customer.verification_token_expires.replace(tzinfo=timezone.utc)
        )

    if customer.verification_token_expires < datetime.now(timezone.utc):
        return render_template(
            "verify_email.html",
            success=False,
            error_message="Verification link has expired.",
        )

    if customer.is_verified:
        return render_template(
            "verify_email.html", success=False, error_message="Email already verified."
        )

    try:
        customer.is_verified = True
        customer.verification_token = None
        customer.verification_token_expires = None
        db.session.commit()
        return render_template("verify_email.html", success=True)
    except Exception as e:
        db.session.rollback()
        return render_template(
            "verify_email.html",
            success=False,
            error_message="An error occurred during verification.",
        )


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per 5 minutes")
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        customer = Customer.query.filter_by(email=email).first()
        if customer and check_password_hash(customer.password, password):
            if not customer.is_verified:
                flash("Please verify your email before logging in.", "warning")
                return redirect(url_for("login"))

            session["customer_id"] = customer.id
            session["customer_name"] = customer.name

            next_page = session.pop("next", None)
            if next_page:
                return redirect(next_page)
            return redirect(url_for("home"))
        else:
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("customer_id", None)
    session.pop("customer_name", None)
    return redirect(url_for("home"))


@app.route("/admin/order/<int:order_id>")
def admin_order_detail(order_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    order = Order.query.get_or_404(order_id)
    customer = Customer.query.get(order.customer_id)

    # Parse order items into a more readable format
    items = []
    for item in order.items.split(", "):
        if "(" in item:
            name, size_quantity = item.split(" (")
            size, quantity = size_quantity.rstrip(")").split(") x ")
            items.append({"name": name, "size": size, "quantity": int(quantity)})
        else:
            name, quantity = item.split(" x ")
            items.append({"name": name, "size": "N/A", "quantity": int(quantity)})

    return render_template(
        "admin/order_detail.html", order=order, customer=customer, items=items
    )


@app.route("/admin/order/<int:order_id>/update", methods=["POST"])
def admin_update_order(order_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    order = Order.query.get_or_404(order_id)
    new_status = request.form.get("status")

    if new_status not in ["Pending", "Completed", "Failed"]:
        flash("Invalid status", "danger")
        return redirect(url_for("admin_order_detail", order_id=order_id))

    try:
        order.payment_status = new_status
        db.session.commit()
        flash(f"Order status updated to {new_status}", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error updating order status: {str(e)}", "danger")

    return redirect(url_for("admin_order_detail", order_id=order_id))


@app.route("/my_orders")
def my_orders():
    if not session.get("customer_id"):
        flash("Please login to view your orders.", "warning")
        return redirect(url_for("login"))

    page = request.args.get("page", 1, type=int)
    per_page = 5  # Show 5 orders per page

    orders = (
        Order.query.filter_by(customer_id=session["customer_id"])
        .order_by(Order.order_date.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    order_details = []
    for order in orders.items:
        parsed_items = []
        for item in order.items.split(","):
            if " (" in item:
                name, size_quantity = item.split(" (")
                size, quantity = size_quantity.rstrip(")").split(") x ")
                # Get product information
                product = Product.query.filter_by(name=name).first()
                image_url = None
                if product and product.images:
                    image_url = url_for(
                        "static", filename=f"images/{product.images[0].image_filename}"
                    )
                parsed_items.append(
                    {
                        "name": name,
                        "size": size,
                        "quantity": int(quantity),
                        "image_url": image_url,
                    }
                )
            else:
                name, quantity = item.split(" x ")
                # Get product information
                product = Product.query.filter_by(name=name).first()
                image_url = None
                if product and product.images:
                    image_url = url_for(
                        "static", filename=f"images/{product.images[0].image_filename}"
                    )
                parsed_items.append(
                    {
                        "name": name,
                        "size": "N/A",
                        "quantity": int(quantity),
                        "image_url": image_url,
                    }
                )

        order_details.append({"order": order, "parsed_items": parsed_items})

    return render_template("my_orders.html", order_details=order_details, orders=orders)


@app.route("/order/complete", methods=["POST"])
@login_required
def complete_order():
    try:
        # Get cart items
        cart_items = CartItem.query.filter_by(customer_id=current_user.id).all()
        if not cart_items:
            flash("Your cart is empty", "error")
            return redirect(url_for("cart"))

        # Create order
        order = Order(
            customer_id=current_user.id,
            status="pending",
            payment_method=request.form.get("payment_method", "cod"),
            shipping_address_id=request.form.get("shipping_address_id"),
        )
        db.session.add(order)

        # Add items to order
        total_amount = 0
        for cart_item in cart_items:
            order_item = OrderItem(
                order=order,
                product_id=cart_item.product_id,
                quantity=cart_item.quantity,
                price=cart_item.product.price,
            )
            total_amount += cart_item.quantity * cart_item.product.price
            db.session.add(order_item)

        # Update order total
        order.total_amount = total_amount
        order.shipping_cost = 10.00  # Fixed shipping cost
        order.subtotal = total_amount

        # Clear cart
        CartItem.query.filter_by(customer_id=current_user.id).delete()

        # Commit changes
        db.session.commit()

        # Send order confirmation email
        try:
            from email_utils import send_order_confirmation_email

            if send_order_confirmation_email(order):
                current_app.logger.info(
                    f"Order confirmation email sent successfully for order #{order.id}"
                )
            else:
                current_app.logger.warning(
                    f"Failed to send order confirmation email for order #{order.id}"
                )
        except Exception as e:
            current_app.logger.error(
                f"Error sending order confirmation email: {str(e)}"
            )

        flash("Order placed successfully!", "success")
        return redirect(url_for("order_confirmation", order_id=order.id))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error completing order: {str(e)}")
        flash("An error occurred while processing your order", "error")
        return redirect(url_for("cart"))


@app.route("/order/online-payment/complete", methods=["POST"])
@login_required
def complete_online_payment():
    try:
        # Get cart items
        cart_items = CartItem.query.filter_by(customer_id=current_user.id).all()
        if not cart_items:
            flash("Your cart is empty", "error")
            return redirect(url_for("cart"))

        # Create order
        order = Order(
            customer_id=current_user.id,
            status="paid",
            payment_method="online",
            shipping_address_id=request.form.get("shipping_address_id"),
        )
        db.session.add(order)

        # Add items to order
        total_amount = 0
        for cart_item in cart_items:
            order_item = OrderItem(
                order=order,
                product_id=cart_item.product_id,
                quantity=cart_item.quantity,
                price=cart_item.product.price,
            )
            total_amount += cart_item.quantity * cart_item.product.price
            db.session.add(order_item)

        # Update order total
        order.total_amount = total_amount
        order.shipping_cost = 10.00  # Fixed shipping cost
        order.subtotal = total_amount

        # Clear cart
        CartItem.query.filter_by(customer_id=current_user.id).delete()

        # Commit changes
        db.session.commit()

        # Send order confirmation email
        try:
            from email_utils import send_order_confirmation_email

            if send_order_confirmation_email(order):
                current_app.logger.info(
                    f"Order confirmation email sent successfully for order #{order.id}"
                )
            else:
                current_app.logger.warning(
                    f"Failed to send order confirmation email for order #{order.id}"
                )
        except Exception as e:
            current_app.logger.error(
                f"Error sending order confirmation email: {str(e)}"
            )

        flash("Payment successful! Your order has been placed.", "success")
        return redirect(url_for("order_confirmation", order_id=order.id))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error completing online payment: {str(e)}")
        flash("An error occurred while processing your payment", "error")
        return redirect(url_for("cart"))


@app.route("/admin/order/<int:order_id>/cancel", methods=["POST"])
def admin_cancel_order(order_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    order = Order.query.get_or_404(order_id)

    try:
        # Restore stock for each item in the order
        items = order.items.split(", ")
        for item in items:
            # Parse item string, e.g., "Test T-Shirt (M) x 2"
            name_size, quantity = item.rsplit(" x ", 1)
            quantity = int(quantity)
            if "(" in name_size:
                name, size = name_size.split(" (")
                size = size.rstrip(")")
                product = Product.query.filter_by(name=name).first()
                if product:
                    stock_field = f"stock_{size.lower()}"
                    current_stock = getattr(product, stock_field, 0)
                    new_stock = current_stock + quantity
                    setattr(product, stock_field, new_stock)

        # Update order status
        order.payment_status = "Cancelled"
        db.session.commit()

        flash("Order cancelled and stock restored successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error cancelling order: {str(e)}", "danger")

    return redirect(url_for("admin_order_detail", order_id=order_id))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
