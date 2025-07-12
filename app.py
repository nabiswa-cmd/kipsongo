from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import psycopg2.extras  
from datetime import datetime
from collections import defaultdict
from decimal import Decimal
from psycopg2.extras import RealDictCursor
import os
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
load_dotenv()


app = Flask(__name__)
app.secret_key = 'your_secret_key'

DATABASE_URL = os.environ['DATABASE_URL']
def get_connection():
    return psycopg2.connect(DATABASE_URL)

# ───────────────────────────────────────────────
#  Imports you already have …
#  add these two if they’re not present
# ───────────────────────────────────────────────
from functools import wraps          # ← NEW
from flask import session, redirect, url_for, flash, render_template, request

# ───────────────────────────────────────────────
#  Helper : only‑admins gate
# ───────────────────────────────────────────────
def admin_required(f):
    """Decorator: allow access only if the logged‑in user is admin."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admins only ❌", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapped


# ───────────────────────────────────────────────
#  Auth + dashboard
# ───────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    username = request.form["username"].lower()
    password = request.form["password"]

    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, username, password, role 
                FROM users 
                WHERE LOWER(username) = %s
            """, (username,))
            user = cur.fetchone()

        if user:
            user_id, uname, stored_password, role = user

            # 💬 Compare directly if using plain-text
            if password == stored_password:
                session["user_id"] = user_id
                session["username"] = uname
                session["role"] = role or "user"
                flash("Login successful ✅", "success")
                return redirect(url_for("dashboard"))
            else:
                flash("❌ Incorrect password", "error")
        else:
            flash("❌ User not found", "error")

    except Exception as e:
        flash(f"Database error: {e}", "error")

    return redirect(url_for("home"))



@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return redirect(url_for("home"))

    return render_template(
        "dashboard.html",
        username=session["username"],
        role=session.get("role", "user")
    )





# ───────────────────────────────────────────────
#  Logout helper
# ───────────────────────────────────────────────
@app.post("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("home"))

from flask import request, redirect, url_for, render_template
from datetime import datetime
@app.route('/prepaid-form')
def Prepaidform():
    gas_id = request.args.get("gas_id", type=int)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT gas_id, gas_name FROM gas_table")
            gases = cur.fetchall()

    return render_template("Prepaidform.html", gases=gases, selected_gas_id=gas_id)
# --- ACCOUNT DASHBOARD ————————————————————————————
from werkzeug.security import generate_password_hash, check_password_hash   # optional but recommended

# GET  ➜ show “My account” page
@app.route("/account")
def my_account():
    if "username" not in session:                      # ⛔ not signed‑in
        flash("Please log in first.", "error")
        return redirect(url_for("home"))

    user = session["username"]

    # pull current data (in case you later want e‑mail, role, etc.)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT username FROM users WHERE username=%s", (user,))
        row = cur.fetchone()
        if not row:
            flash("User not found.", "error")
            return redirect(url_for("dashboard"))

    return render_template("account.html", username=row[0])


# POST ➜ update details
@app.post("/update-account")
def update_account():
    if "username" not in session:
        flash("Please log in first.", "error")
        return redirect(url_for("home"))

    current_user = session["username"]
    new_user     = request.form.get("new_username"  , "").strip().lower()
    new_pass     = request.form.get("new_password_1", "")
    confirm_pass = request.form.get("new_password_2", "")

    if new_pass or new_user:       # at least one field changed
        if new_pass and new_pass != confirm_pass:
            flash("Passwords do not match.", "error")
            return redirect(url_for("my_account"))

        try:
            with get_connection() as conn, conn.cursor() as cur:

                # 1) change username (if requested)
                if new_user and new_user != current_user:
                    cur.execute("""
                        UPDATE users SET username=%s
                        WHERE username=%s
                    """, (new_user, current_user))
                    session["username"] = new_user          # keep session fresh
                    current_user = new_user                 # chain for PW update

                # 2) change password (if requested)
                if new_pass:
                        
                    cur.execute("""
                        UPDATE users SET password=%s
                        WHERE username=%s
                    """, (new_pass , current_user))

                conn.commit()
                flash("Account updated ✔️", "success")

        except Exception as e:
            conn.rollback()
            flash(f"Error: {e}", "error")

    else:
        flash("Nothing to update.", "info")

    return redirect(url_for("my_account"))


# ─────────────────────────────────────────────────────────────
#  GET  –  Supplier / Pricing Manager page
#  URL  : /manage-pricing
# ─────────────────────────────────────────────────────────────
@app.route('/manage-pricing')
@admin_required
def manage_pricing():
    with get_connection() as conn, conn.cursor() as cur:

        # 1. Suppliers → list of dicts
        cur.execute("""
            SELECT company_id, company_name
            FROM   buying_company
            ORDER  BY company_name
        """)
        companies = [
            {"company_id": cid, "company_name": cname}
            for cid, cname in cur.fetchall()
        ]

        # 2. Gas brands → list of dicts
        cur.execute("""
            SELECT gas_id, gas_name
            FROM   gas_table
            ORDER  BY gas_name
        """)
        gases = [
            {"gas_id": gid, "gas_name": gname}
            for gid, gname in cur.fetchall()
        ]

        # 3. Current price matrix → list of dicts
        cur.execute("""
            SELECT c.company_name,
                   g.gas_name,
                   COALESCE(p.refill_price,0),
                   COALESCE(p.full_price,0),
                   p.last_updated
            FROM   company_gas_price p
            JOIN   buying_company c ON p.company_id = c.company_id
            JOIN   gas_table      g ON p.gas_id     = g.gas_id
            ORDER  BY c.company_name, g.gas_name
        """)
        prices = [
            {
                "company_name": row[0],
                "gas_name":     row[1],
                "refill_price": float(row[2]),
                "full_price":   float(row[3]),
                "last_updated": row[4]
            }
            for row in cur.fetchall()
        ]

    return render_template(
        "manage_pricing.html",
        companies=companies,
        gases=gases,
        prices=prices
    )

# ─────────────────────────────────────────────────────────────
#  POST  –  Add new supplier / station
# ─────────────────────────────────────────────────────────────
@app.route('/add-supplier', methods=['POST'])
def add_supplier():
    name = request.form['company_name'].strip()
    with get_connection() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO buying_company (company_name)
                VALUES (%s)
                ON CONFLICT (company_name) DO NOTHING
                RETURNING company_id
            """, (name,))
            cid = cur.fetchone()
            if cid:
                # auto‑create price rows for every gas brand
                cur.execute("""
                    INSERT INTO company_gas_price (company_id, gas_id)
                    SELECT %s, gas_id FROM gas_table
                    ON CONFLICT DO NOTHING
                """, (cid[0],))
            conn.commit()
            flash("Supplier added.", "success")
        except Exception as e:
            conn.rollback()
            flash(str(e), "error")
    return redirect(url_for('manage_pricing'))
@app.route('/set-price', methods=['POST'])
def set_price():
    comp_id = int(request.form['company_id'])
    gid_raw = request.form['gas_id']
    refill  = float(request.form['refill_price'] or 0)
    full    = float(request.form['full_price'] or 0)

    with get_connection() as conn, conn.cursor() as cur:

        if gid_raw == "all_below":
            # Get all gas IDs not containing "13"
            cur.execute("""
                SELECT gas_id FROM gas_table
                WHERE gas_name NOT ILIKE '%%13%%'
            """)
            gas_ids = [row[0] for row in cur.fetchall()]

        elif gid_raw == "all_above":
            # Get all gas IDs containing "13"
            cur.execute("""
                SELECT gas_id FROM gas_table
                WHERE gas_name ILIKE '%%13%%'
            """)
            gas_ids = [row[0] for row in cur.fetchall()]

        else:
            # Only one gas selected
            gas_ids = [int(gid_raw)]

        # Insert or update all selected gas IDs
        for gid in gas_ids:
            cur.execute("""
                INSERT INTO company_gas_price (company_id, gas_id, refill_price, full_price)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (company_id, gas_id) DO UPDATE
                SET refill_price = %s,
                    full_price   = %s,
                    last_updated = NOW()
            """, (comp_id, gid, refill, full, refill, full))

        conn.commit()

    flash("Price saved.", "success")
    return redirect(url_for('manage_pricing'))

# ── show edit form ─────────────────────────────────────────────



@app.route("/prepaid-list")
def prepaid_list():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ps.id, ps.customer_name, ps.empty_given, ps.customer_picture, 
                           g.gas_name
                    FROM prepaid_sales ps
                    JOIN gas_table g ON ps.gas_id = g.gas_id
                    ORDER BY ps.created_at DESC;
                """)
                rows = cur.fetchall()

                pending_prepaid = []
                for row in rows:
                    pending_prepaid.append({
                        "id": row[0],
                        "customer_name": row[1],
                        "empty_given": row[2],
                        "customer_picture": row[3],
                        "gas_name": row[4] or "Unknown"
                    })

        return render_template("Prepaidlist.html", pending_prepaid=pending_prepaid)
        

    except Exception as e:
        return f"Error loading prepaid list: {e}"
        

@app.route('/record-sale-and-open-prepay', methods=['POST'])
def record_sale_and_open_prepay():
    gas_id = request.args.get("gas_id", type=int)
    amount_paid_cash = float(request.form.get("amount_paid_cash", 0))
    amount_paid_till = float(request.form.get("amount_paid_till", 0))

    selected_source = request.form.get("source", "customer")
    source_kipsongo_pioneer = selected_source == "kipsongo_pioneer"
    source_mama_pam = selected_source == "mama_pam"
    source_external = selected_source == "external"

    sale_type = request.form.get("sale_type")
    complete_sale = sale_type == "complete_sale"
    empty_not_given = sale_type == "empty_not_given"
    exchange_cylinder = sale_type == "exchange_cylinder"

    time_sold = datetime.now()

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO sales_table (
                        gas_id, amount_paid_cash, amount_paid_till,
                        source_kipsongo_pioneer, source_mama_pam, source_external,
                        complete_sale, empty_not_given, exchange_cylinder, time_sold
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    gas_id, amount_paid_cash, amount_paid_till,
                    source_kipsongo_pioneer, source_mama_pam, source_external,
                    complete_sale, empty_not_given, exchange_cylinder, time_sold
                ))
                conn.commit()

        return redirect(url_for('Prepaidform', gas_id=gas_id))

    except Exception as e:
        return f"Error: {e}", 500


@app.route('/submit-prepaid-sale', methods=['POST'])
def submit_prepaid_sale():
    customer_name = request.form.get('customer_name')
    customer_phone = request.form.get('customer_phone')
    customer_address = request.form.get('customer_address')
    gas_id = request.form.get('gas_id')
    empty_given = 'empty_given' in request.form
    picture_file = request.files.get('customer_picture')

    picture_path = ''
    if picture_file:
        filename = secure_filename(picture_file.filename)
        picture_path = os.path.join('static/uploads', filename)
        picture_file.save(picture_path)

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO prepaid_sales (
                        gas_id, customer_name, customer_phone, customer_address,
                        empty_given, customer_picture
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (gas_id, customer_name, customer_phone, customer_address, empty_given, picture_path))

                if empty_given:
                    cur.execute("UPDATE gas_table SET empty_cylinders = empty_cylinders + 1 WHERE gas_id = %s", (gas_id,))

            conn.commit()
        flash('Prepaid sale recorded successfully', 'success')
    except Exception as e:
        flash(f"Error saving prepaid record: {e}", 'error')

    return redirect(url_for('sales'))


@app.route("/collect-prepaid/<int:prepaid_id>", methods=["POST"])
def collect_prepaid(prepaid_id):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Get prepaid record
                cur.execute("SELECT gas_id, empty_given, customer_name FROM prepaid_sales WHERE id = %s", (prepaid_id,))
                record = cur.fetchone()
                
                if not record:
                    flash("❌ Prepaid record not found", "error")
                    return redirect(url_for('prepaid_list'))

                gas_id, empty_given, customer_name = record

                # 2. Check gas availability
                cur.execute("SELECT filled_cylinders FROM gas_table WHERE gas_id = %s", (gas_id,))
                gas_status = cur.fetchone()

                if not gas_status or gas_status[0] <= 0:
                    flash("❌ No filled gas cylinders available for collection!", "error")
                    return redirect(url_for('prepaid_list'))

                # 3. Reduce filled by 1
                cur.execute("""
                    UPDATE gas_table SET filled_cylinders = filled_cylinders - 1
                    WHERE gas_id = %s
                """, (gas_id,))
                cur.execute("""
                    INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                    VALUES (%s, 'decrease_filled', -1, 'Collected prepaid sale')
                """, (gas_id,))

                # 4. Handle empty_given logic
                checkbox_checked = request.form.get("empty_given", "").lower() in ["true", "on", "1"]

                if not empty_given:  # If empty wasn't given initially
                    if checkbox_checked:
                        # Now empty has been given
                        cur.execute("""
                            UPDATE gas_table SET empty_cylinders = empty_cylinders + 1
                            WHERE gas_id = %s
                        """, (gas_id,))
                        cur.execute("""
                            INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                            VALUES (%s, 'increase_empty', 1, 'Empty received at collection')
                        """, (gas_id,))
                    else:
                        # No empty given still → record stock_out
                        cur.execute("""
                        INSERT INTO stock_out (gas_id, cylinder_state, destination_type, destination_value)
                        VALUES (%s, 'filled', 'customer', %s)
                    """, (gas_id,customer_name))
                        note = f"Prepaid collection without empty by {customer_name}"

                        cur.execute("""
                            INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                            VALUES (%s, 'stock_out', -1, %s)
                        """, (gas_id, note))


                # 5. Delete from prepaid_sales
                cur.execute("DELETE FROM prepaid_sales WHERE id = %s", (prepaid_id,))

                conn.commit()
                flash("✅ Collection completed successfully.", "success")
                return redirect(url_for('prepaid_list'))
            

    except Exception as e:
        flash(f"❌ Error during collection: {e}", "error")
        return redirect(url_for('prepaid_list'))
@app.route('/logs')
def view_logs():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT sc.id, g.gas_name, sc.action, sc.quantity_change, sc.notes, sc.changed_at
                    FROM stock_change sc
                    JOIN gas_table g ON sc.gas_id = g.gas_id
                    ORDER BY sc.changed_at DESC
                """)
                logs = cur.fetchall()
        return render_template("logs.html", logs=logs)
    except Exception as e:
        return f"Error fetching logs: {e}"

@app.route('/undo-payment/<int:debt_id>', methods=['POST'])
def undo_payment(debt_id):
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get the most recent payment for this debt
                cur.execute("""
                    SELECT id, amount FROM gas_debt_payments
                    WHERE debt_id = %s
                    ORDER BY payment_date DESC, id DESC
                    LIMIT 1
                """, (debt_id,))
                last_payment = cur.fetchone()

                if not last_payment:
                    flash("No payment found to undo.", "warning")
                    return redirect(url_for('add_gas_debt'))

                payment_id = last_payment["id"]
                payment_amount = last_payment["amount"]

                # Delete the payment
                cur.execute("DELETE FROM gas_debt_payments WHERE id = %s", (payment_id,))

                # Update the main debt record (subtract the payment amount)
                cur.execute("""
                    UPDATE gas_debts
                    SET amount_paid = amount_paid - %s
                    WHERE id = %s
                """, (payment_amount, debt_id))

            conn.commit()
            flash("Last payment undone successfully.", "success")

    except Exception as e:
        flash(f"Error undoing payment: {e}", "danger")

    return redirect(url_for('add_gas_debt'))



@app.route('/add-payment/<int:debt_id>', methods=['POST'])
def add_payment(debt_id):
    try:
        amount = float(request.form['payment_amount'])

        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # 1. Insert payment
                cur.execute("""
                    INSERT INTO gas_debt_payments (debt_id, amount, payment_date)
                    VALUES (%s, %s, NOW())
                """, (debt_id, amount))

                # 2. Update amount_paid
                cur.execute("""
                    UPDATE gas_debts
                    SET amount_paid = amount_paid + %s
                    WHERE id = %s
                """, (amount, debt_id))

                # 3. Fetch updated debt info
                cur.execute("""
                    SELECT gas_id, amount_paid, amount_to_be_paid, cleared
                    FROM gas_debts
                    WHERE id = %s
                """, (debt_id,))
                debt = cur.fetchone()

                if not debt:
                    raise Exception("Debt record not found.")

                balance = float(debt['amount_to_be_paid']) - float(debt['amount_paid'])

                # 4. If fully paid and not yet cleared, record as a sale
                if balance <= 0 and not debt['cleared']:
                    cur.execute("""
                        INSERT INTO sales_table (
                            gas_id,
                            sale_date,
                            amount_paid_cash,
                            amount_paid_till,
                            complete_sale,
                            source_kipsongo_pioneer,
                            source_mama_pam,
                            source_external,
                            empty_not_given,
                            exchange_cylinder,
                            from_debt
                        ) VALUES (%s, NOW(), %s, 0, FALSE, FALSE, FALSE, FALSE, FALSE, FALSE, TRUE)
                    """, (
                        debt['gas_id'],
                        float(debt['amount_to_be_paid'])
                    ))

                    # 5. Mark the debt as cleared
                    cur.execute("""
                        UPDATE gas_debts SET cleared = TRUE WHERE id = %s
                    """, (debt_id,))

            conn.commit()

        flash("Payment added successfully!", "success")
        return redirect(url_for('add_gas_debt'))

    except Exception as e:
        print("Error in add_payment:", e)
        flash(f"Error processing payment: {e}", "error")
        return redirect(url_for('add_gas_debt'))
# ---------------------------------------------------------------
#  GET /empty-cylinders  – view EMPTY stock + subtotals
# ---------------------------------------------------------------
@app.route("/empty-cylinders")
def empty_cylinders_page():
    with get_connection() as conn, conn.cursor() as cur:
        # fetch ONLY brands that actually have empties (>0)
        cur.execute("""
            SELECT gas_id, gas_name, empty_cylinders
              FROM gas_table
             WHERE empty_cylinders > 0
             ORDER BY gas_name
        """)
        rows = cur.fetchall()                      # (id, name, empty)

    # ── compute the two subtotals
    total_13    = sum(r[2] for r in rows if "13kg" in r[1].lower())
    total_other = sum(r[2] for r in rows if "13kg" not in r[1].lower())
    grand_total = total_13 + total_other

    return render_template(
        "empty_cylinders.html",
        brands      = rows,
        total_13    = total_13,
        total_other = total_other,
        grand_total = grand_total
    )

# ───────────────────────────────────────────────────────────────
# GET  /manage-users      – show user list + add form
# POST /add-user          – create user
# POST /update-user/<id>  – change username / password / role
# POST /delete-user/<id>  – drop user
# ───────────────────────────────────────────────────────────────


@app.route("/manage-users")
def manage_users():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT user_id, username, role FROM users ORDER BY user_id")
        users = cur.fetchall()              # [(id,name,role), …]
    return render_template("manage_users.html", users=users)


@app.post("/add-user")
def add_user():
    uname = request.form["username"].strip()
    pwd   = request.form["password"]
    role  = request.form.get("role","user")
    if not uname or not pwd:
        flash("Username and password required.","error")
        return redirect(url_for("manage_users"))

    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (username,password,role)
                VALUES (%s,%s,%s)
            """, (uname,pwd, role))
            conn.commit()
            flash("User added ✔️","success")
    except Exception as e:
        flash(str(e),"error")

    return redirect(url_for("manage_users"))


@app.post("/update-user/<int:uid>")
def update_user(uid):
    uname = request.form["username"].strip()
    pwd   = request.form["password"].strip()      # blank means “leave as‑is”
    role  = request.form.get("role","user")

    try:
        with get_connection() as conn, conn.cursor() as cur:
            # build update dynamically
            if pwd:
                cur.execute("""
                    UPDATE users
                       SET username=%s,
                           password=%s,
                           role=%s
                     WHERE user_id=%s
                """, (uname, pwd, role, uid))
            else:            # keep old password
                cur.execute("""
                    UPDATE users
                       SET username=%s,
                           role=%s
                     WHERE user_id=%s
                """, (uname, role, uid))
            conn.commit()
            flash("User updated ✔️","success")
    except Exception as e:
        flash(str(e),"error")

    return redirect(url_for("manage_users"))


@app.post("/delete-user/<int:uid>")
def delete_user(uid):
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id=%s",(uid,))
            conn.commit()
            flash("User deleted.","success")
    except Exception as e:
        flash(str(e),"error")
    return redirect(url_for("manage_users"))



@app.post("/delete-gas-debt/<int:debt_id>")
def delete_gas_debt(debt_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("SELECT amount_paid, amount_to_be_paid FROM gas_debts WHERE id = %s", (debt_id,))
        debt = cur.fetchone()

        if debt is None:
            flash("Debt record not found.")
        else:
            amount_paid = debt["amount_paid"] or 0
            amount_to_be_paid = debt["amount_to_be_paid"] or 0
            balance = amount_to_be_paid - amount_paid

            if balance > 0:
                flash("Cannot delete. Customer still has a balance.")
            else:
                cur.execute("DELETE FROM gas_debts WHERE id = %s", (debt_id,))
                conn.commit()
                flash("Debt record deleted successfully.")


    except Exception as e:
        conn.rollback()
        flash(f"Error occurred: {e}")
    finally:
        cur.close()
        conn.close()
    return render_template("dashboard.html")
    # <-- Change here to your actual list view function name

@app.route('/gas-debt', methods=['GET'])
def search_gas_debt():
    search_term = request.args.get('search', '').strip()

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
    cur = conn.cursor()

    if search_term:
        query = """
        SELECT d.*, g.gas_name
        FROM gas_debts d
        JOIN gas_table g ON d.gas_id = g.gas_id
        WHERE LOWER(g.gas_name) LIKE %s OR LOWER(d.customer_name) LIKE %s
        ORDER BY d.id DESC
        """
        cur.execute(query, (f'%{search_term.lower()}%', f'%{search_term.lower()}%'))
    else:
        cur.execute("""
        SELECT d.*, g.gas_name
        FROM gas_debts d
        JOIN gas_table g ON d.gas_id = g.gas_id
        ORDER BY d.id DESC
        """)

    debts = cur.fetchall()

    # Get payment history for each debt
    debt_list = []
    for debt in debts:
        cur.execute("SELECT amount, payment_date FROM gas_debt_payments WHERE debt_id = %s ORDER BY payment_date", (debt['id'],))
        payments = cur.fetchall()
        debt_dict = dict(debt)
        debt_dict['payments'] = payments
        debt_dict['amount_paid'] = sum([float(p['amount']) for p in payments])
        debt_dict['balance'] = float(debt['amount_to_be_paid']) - debt_dict['amount_paid']
        debt_list.append(debt_dict)

    cur.close()
    conn.close()

    return render_template("search_gas_debt.html", debt_list=debt_list)
@app.route('/add-gas-debt', methods=['GET', 'POST'])
def add_gas_debt():
    from collections import defaultdict
    from decimal import Decimal

    gas_id = request.args.get('gas_id')

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()

    if request.method == 'GET':
        if not gas_id:
            flash("Gas name must be selected to get into gas depth form.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for('sales'))

        cur.execute("SELECT gas_name, filled_cylinders FROM gas_table WHERE gas_id = %s", (gas_id,))
        gas = cur.fetchone()

        if not gas:
            flash("Gas not found.", "warning")
            cur.close()
            conn.close()
            return redirect(url_for('sales'))

        if gas['filled_cylinders'] <= 0:
            flash("No filled gas cylinder available for this type.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for('sales'))

    
        
    if request.method == 'POST':
        gas_id = request.form['gas_id']
        amount_paid = float(request.form.get('amount_paid', 0))
        amount_to_be_paid = float(request.form['amount_to_be_paid'])
        date_to_be_paid = request.form['date_to_be_paid']
        authorized_by = request.form['authorized_by']
        empty_given = 'empty_cylinder_given' in request.form
        customer_name = request.form['customer_name']
        customer_phone = request.form['customer_phone']
        customer_address = request.form['customer_address']
        
        # Handle image upload as base64 or skip
        customer_picture_file = request.files.get('customer_picture')
        customer_picture = customer_picture_file.read().decode('latin1') if customer_picture_file else None

        # 🟩 Insert gas debt
        cur.execute("""
            INSERT INTO gas_debts (
                gas_id, amount_paid, amount_to_be_paid, date_to_be_paid,
                authorized_by, empty_cylinder_given, customer_name,
                customer_phone, customer_address, customer_picture
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            gas_id, amount_paid, amount_to_be_paid, date_to_be_paid,
            authorized_by, empty_given, customer_name,
            customer_phone, customer_address, customer_picture
        ))

        # 🟩 Update gas stock
        if empty_given:
            # Decrease filled, increase empty
            cur.execute("""
                UPDATE gas_table
                SET filled_cylinders = filled_cylinders - 1,
                    empty_cylinders = empty_cylinders + 1
                WHERE gas_id = %s
            """, (gas_id,))
            
            # Log change
            cur.execute("""
                INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                VALUES (%s, %s, %s, %s)
            """, (
                gas_id, 'filled decrease while empty increase', 0,
                f"Gas collection without payment by '{customer_name}'"
            ))
            
        else:
            # Decrease filled only
            cur.execute("""
                UPDATE gas_table
                SET filled_cylinders = filled_cylinders - 1
                WHERE gas_id = %s
            """, (gas_id,))
            
            # Stock out to customer
            cur.execute("""
                INSERT INTO stock_out (
                    gas_id, cylinder_state, destination_type, destination_value
                ) VALUES (%s, %s, %s, %s)
            """, (
                gas_id, 'filled', 'customer', customer_name
            ))
            
            # Log change
            cur.execute("""
                INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                VALUES (%s, %s, %s, %s)
            """, (
                gas_id, 'filled decrease', -1,
                f"Gas collection without payment, no empty returned by '{customer_name}'"
            ))

        conn.commit()
        flash("Gas debt added successfully.", "success")
        return redirect(url_for('add_gas_debt', gas_id=gas_id))

        
            

    # Continue with GET rendering logic
   
     # GET logic
    search = request.args.get("search")
    query = """
        SELECT d.*, g.gas_name
        FROM gas_debts d
        JOIN gas_table g ON d.gas_id = g.gas_id
    """
    params = ()
    if search:
        query += " WHERE d.customer_name ILIKE %s OR g.gas_name ILIKE %s"
        params = (f"%{search}%", f"%{search}%")
    query += " ORDER BY d.time DESC"

    cur.execute(query, params)
    debt_list = cur.fetchall()

    # Fetch payments
    cur.execute("""
        SELECT debt_id, amount, payment_date
        FROM gas_debt_payments
        WHERE debt_id IN %s
        ORDER BY payment_date DESC
    """, (tuple(d['id'] for d in debt_list) if debt_list else (0,),))
    all_payments = cur.fetchall()

    # Group payments by debt_id
    from collections import defaultdict
    payments_by_debt = defaultdict(list)
    for p in all_payments:
        payments_by_debt[p['debt_id']].append(p)

    # Fetch related payments
    debt_ids = tuple(d['id'] for d in debt_list) or (0,)
    cur.execute("""
        SELECT debt_id, amount, payment_date
        FROM gas_debt_payments
        WHERE debt_id IN %s
        ORDER BY payment_date DESC
    """, (debt_ids,))
    all_payments = cur.fetchall()

    payments_by_debt = defaultdict(list)
    for p in all_payments:
        payments_by_debt[p['debt_id']].append(p)

    # Compute balance per debt
    for debt in debt_list:
        debt_payments = payments_by_debt.get(debt['id'], [])
        total_paid = sum(float(p['amount']) for p in debt_payments)
        balance = Decimal(str(debt['amount_to_be_paid'] or 0)) - Decimal(str(total_paid))

        debt['payments'] = debt_payments
        debt['amount_paid'] = total_paid
        debt['balance'] = balance

    gas_name = ''
    if gas_id:
        cur.execute("SELECT gas_name FROM gas_table WHERE gas_id = %s", (gas_id,))
        row = cur.fetchone()
        gas_name = row['gas_name'] if row else ''

    cur.close()
    conn.close()

    return render_template('add_gas_debt.html', gas_id=gas_id, gas_name=gas_name, debt_list=debt_list)

# ------------------------------------------------------------------
#  STOCK‑IN  (form  +  grouped list that can be returned)
# ------------------------------------------------------------------
@app.route("/stock-in")
def stock_in_page():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT gas_id, gas_name FROM gas_table ORDER BY gas_name")
        gases = cur.fetchall()

        # group ALSO by original source
        cur.execute("""
            SELECT g.gas_id,
                   g.gas_name,
                   si.cylinder_state,
                   si.source_type,
                   si.source_value,
                   COUNT(*)                      AS qty
            FROM   stock_in si
            JOIN   gas_table g ON g.gas_id = si.gas_id
            GROUP  BY g.gas_id, g.gas_name,
                     si.cylinder_state, si.source_type, si.source_value
            ORDER  BY g.gas_name, si.cylinder_state, si.source_type, si.source_value
        """)
        grouped = cur.fetchall()     # (gid,gname,state,src_t,src_v,qty)

    return render_template("stock_in.html",
                           gases=gases,
                           grouped=grouped)


# ------------------------------------------------------------------
#  POST /add-stock-in   – one cylinder INTO storage
# ------------------------------------------------------------------
@app.post("/add-stock-in")
def add_stock_in():
    try:
        gid   = int(request.form["gas_id"])
        state = request.form["cylinder_state"]              # 'empty' / 'filled'
        src_t = request.form["source_type"]
        src_v = request.form["source_value"].strip()

        with get_connection() as conn, conn.cursor() as cur:
            # ➊ write one row into stock_in
            cur.execute("""
                INSERT INTO stock_in (gas_id, cylinder_state,
                                       source_type, source_value)
                VALUES (%s,%s,%s,%s)
            """, (gid, state, src_t, src_v))

            # ➋ update main stock counts
            column = "filled_cylinders" if state == "filled" else "empty_cylinders"
            cur.execute(f"UPDATE gas_table SET {column} = {column} + 1 WHERE gas_id = %s", (gid,))

            # ➌ stock_change log ( +1 because item came **in** )
            note = f"Stock‑IN ({state}) from {src_t}: {src_v}"
            cur.execute("""
                INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                VALUES (%s,'stock_in',+1,%s)
            """, (gid, note))

            conn.commit()
        flash("Stock‑in recorded ✔️", "success")

    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("stock_in_page"))

# ------------------------------------------------------------------
#  POST /return-stock-in – return N cylinders to the origin
# ------------------------------------------------------------------
@app.post("/return-stock-in")
def return_stock_in():
    try:
        gid       = int(request.form["gas_id"])
        in_state  = request.form["cylinder_state"]          # state in store
        src_type  = request.form["source_type"]
        src_value = request.form["source_value"]
        qty       = int(request.form["return_qty"])
        out_state = request.form["returned_state"]          # empty / filled

        if qty <= 0:
            flash("Quantity must be positive.", "error")
            return redirect(url_for("stock_in_page"))

        with get_connection() as conn, conn.cursor() as cur:
            # ⬅️ Count how many are available
            cur.execute("""
                SELECT COUNT(*) FROM stock_in
                WHERE gas_id = %s
                  AND cylinder_state = %s
                  AND source_type    = %s
                  AND source_value   = %s
            """, (gid, in_state, src_type, src_value))
            available = cur.fetchone()[0]

            if qty > available:
                flash("❌ Not enough cylinders available.", "error")
                return redirect(url_for("stock_in_page"))

            # 🗑 Delete <qty> rows of this match
            cur.execute("""
                DELETE FROM stock_in
                WHERE ctid IN (
                    SELECT ctid FROM stock_in
                    WHERE gas_id = %s
                      AND cylinder_state = %s
                      AND source_type    = %s
                      AND source_value   = %s
                    ORDER BY time_in
                    LIMIT %s
                )
            """, (gid, in_state, src_type, src_value, qty))

            # ✅ Decrease either FILLED or EMPTY, based on returned_state
            col = "filled_cylinders" if out_state == "filled" else "empty_cylinders"
            cur.execute(f"""
                UPDATE gas_table
                   SET {col} = {col} - %s
                 WHERE gas_id = %s
            """, (qty, gid))

            # 📝 Log this return
            note = f"Returned {qty} {in_state} → sent back as {out_state} to {src_type}: {src_value}"
            cur.execute("""
                INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                VALUES (%s,'return_out',%s,%s)
            """, (gid, -qty, note))

            conn.commit()
            flash("Return recorded ✔️", "success")

    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("stock_in_page"))



# --- SALES PAGE AND SUBMISSION ---
from collections import defaultdict
from flask import render_template

@app.route("/sales", methods=["GET"])
def sales():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Fetch all recent sales (latest 50) including source fields
                cur.execute("""
                    SELECT 
                        s.sale_id, 
                        g.gas_name, 
                        s.amount_paid_cash, 
                        s.amount_paid_till, 
                        s.time_sold::date AS sale_date, 
                        s.time_sold::time,
                        s.from_debt,
                        s.source_mama_pam,
                        s.source_external,
                        s.source_kipsongo_pioneer
                    FROM sales_table s
                    JOIN gas_table g ON s.gas_id = g.gas_id
                    ORDER BY s.time_sold DESC 
                    LIMIT 50;
                """)
                rows = cur.fetchall()

                grouped_sales_dict = defaultdict(list)
                for sale in rows:
                    (sale_id, gas_name, cash, till, sale_date, time_only,
                     from_debt, source_mama_pam, source_external, source_kipsongo_pioneer) = sale

                    grouped_sales_dict[sale_date].append({
                        "id": sale_id,
                        "gas": gas_name,
                        "cash": float(cash),
                        "till": float(till),
                        "time": time_only.strftime("%I:%M %p"),
                        "from_debt": from_debt,
                        "source_mama_pam": source_mama_pam,
                        "source_external": source_external,
                        "source_kipsongo_pioneer": source_kipsongo_pioneer
                    })

                # Final structure for rendering
                grouped_sales = []
                for raw_date, sales_list in grouped_sales_dict.items():
                    grouped_sales.append({
                        "date": raw_date,
                        "date_str": raw_date.strftime("%A, %d %B %Y"),
                        "sales": sales_list,
                        "total_gas": len(sales_list)
                    })

                grouped_sales.sort(key=lambda x: x["date"], reverse=True)

                # Fetch gas dropdown list
                cur.execute("""
                    SELECT gas_id, gas_name, empty_cylinders, filled_cylinders
                    FROM gas_table 
                    ORDER BY gas_id ASC;
                """)
                gases = cur.fetchall()

        return render_template("sales.html", gases=gases, grouped_sales=grouped_sales)

    except Exception as e:
        return f"Error loading sales form: {e}"

@app.route("/edit-sale/<int:sale_id>", methods=["GET", "POST"])
def edit_sale(sale_id):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if request.method == "POST":
                    cash = float(request.form["amount_paid_cash"])
                    till = float(request.form["amount_paid_till"])
                    # Only update payment amounts, not gas_id
                    cur.execute("""
                        UPDATE sales_table
                        SET amount_paid_cash = %s, amount_paid_till = %s
                        WHERE sale_id = %s;
                    """, (cash, till, sale_id))
                    conn.commit()
                    return redirect(url_for('sales'))

                # For GET: load the existing sale
                cur.execute("SELECT gas_id, amount_paid_cash, amount_paid_till FROM sales_table WHERE sale_id = %s;", (sale_id,))
                row = cur.fetchone()
                if not row:
                    return "Sale not found."

                sale = {
                    "gas_id": row[0],
                    "amount_paid_cash": row[1],
                    "amount_paid_till": row[2]
                }

                # Load all gas types to show the gas name (readonly)
                cur.execute("SELECT gas_id, gas_name FROM gas_table ORDER BY gas_name ASC")
                gases = cur.fetchall()

        return render_template("edit_sale.html", sale=sale, gases=gases)
    except Exception as e:
        return f"An error occurred: {str(e)}"

    except Exception as e:
        return f"Error editing sale: {e}"
from datetime import datetime
# … plus your usual imports …

@app.route('/submit-sale', methods=['POST'])
def submit_sale():
    try:
        gas_id = int(request.form["gas_id"])
        cash   = float(request.form.get("amount_paid_cash", 0) or 0)
        till   = float(request.form.get("amount_paid_till", 0) or 0)

        selected_source = request.form.get("source", "customer")
        src_kipsongo = selected_source == "kipsongo_pioneer"
        src_mama     = selected_source == "mama_pam"
        src_external = selected_source == "external"
        source_selected = selected_source in ["kipsongo_pioneer", "mama_pam", "external"]

        sale_type       = request.form.get("sale_type")          # may be None
        complete_sale   = sale_type == "complete_sale"
        empty_not_given = sale_type == "empty_not_given"
        exchange_cyl    = sale_type == "exchange_cylinder"

        empty_customer  = request.form.get("empty_customer")    if empty_not_given else None
        exch_customer   = request.form.get("exchange_customer") if exchange_cyl    else None
        gas_id_received = request.form.get("gas_id_received")   if exchange_cyl    else None
        exch_note       = request.form.get("exchange_note") or ""

        time_sold = datetime.now()

        with get_connection() as conn, conn.cursor() as cur:
            # ─── Stock check ────────────────────────────────────────────
            cur.execute("SELECT filled_cylinders FROM gas_table WHERE gas_id=%s", (gas_id,))
            row = cur.fetchone()
            if not row:
                flash("Gas record not found.", "error")
                return redirect("/sales")

            filled = row[0]
            if filled == 0 and not source_selected:
                flash("No filled gas available in Ukweli store.", "error")
                return redirect("/sales")

            # ─── Insert sale row ───────────────────────────────────────
            cur.execute("""
                INSERT INTO sales_table (
                    gas_id, amount_paid_cash, amount_paid_till,
                    source_kipsongo_pioneer, source_mama_pam, source_external,
                    complete_sale, empty_not_given, exchange_cylinder, time_sold
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                gas_id, cash, till,
                src_kipsongo, src_mama, src_external,
                complete_sale, empty_not_given, exchange_cyl, time_sold
            ))

            # ─── Stock movements ───────────────────────────────────────
            if not source_selected:
                cur.execute("""
                    UPDATE gas_table
                       SET filled_cylinders = filled_cylinders - 1
                     WHERE gas_id = %s
                """, (gas_id,))
                cur.execute("""
                    INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                    VALUES (%s,'decrease_filled',-1,'Sale out')
                """, (gas_id,))

            # 2. Handle EMPTY movements
            if exchange_cyl:
                target_empty_id = int(gas_id_received) if gas_id_received else gas_id
                note_txt = f"Exchange empty from {exch_customer or 'customer'}: {exch_note}"
                cur.execute("""
                    UPDATE gas_table
                       SET empty_cylinders = empty_cylinders + 1
                     WHERE gas_id = %s
                """, (target_empty_id,))
                cur.execute("""
                    INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                    VALUES (%s,'increase_empty',1,%s)
                """, (target_empty_id, note_txt))

            elif not complete_sale and not empty_not_given:
                cur.execute("""
                    UPDATE gas_table
                       SET empty_cylinders = empty_cylinders + 1
                     WHERE gas_id = %s
                """, (gas_id,))
                cur.execute("""
                    INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                    VALUES (%s,'increase_empty',1,'Empty received')
                """, (gas_id,))

            # 3. Empty‑Not‑Given
            if empty_not_given:
                dest = empty_customer or "No name"
                cur.execute("""
                    INSERT INTO stock_out
                          (gas_id, cylinder_state, destination_type, destination_value)
                    VALUES (%s,'filled','customer',%s)
                """, (gas_id, dest))
                cur.execute("""
                    INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                    VALUES (%s,'stock_out',-1,'Filled taken w/out empty by ' || %s)
                """, (gas_id, dest))

            # 4. Complete sale
            if complete_sale:
                cur.execute("""
                    INSERT INTO stock_out
                          (gas_id, cylinder_state, destination_type, destination_value)
                    VALUES (%s,'filled','customer','complete sale')
                """, (gas_id,))
                cur.execute("""
                    INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                    VALUES (%s,'stock_out',-1,'Complete sale')
                """, (gas_id,))

            # 5. Source tables
            if src_kipsongo:
                cur.execute("""
                    INSERT INTO stock_in (gas_id, cylinder_state, source_type, source_value)
                    VALUES (%s, %s, %s, %s)
                """, (gas_id, 'filled', 'Work Station', 'Ukweli Lukhuna main'))
                cur.execute("""
                    INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                    VALUES (%s,'stock_in',+1,'empty from Ukweli Lukhuna main')
                """, (gas_id,))

            elif src_mama:
                cur.execute("""
                    INSERT INTO stock_in (gas_id, cylinder_state, source_type, source_value)
                    VALUES (%s, %s, %s, %s)
                """, (gas_id, 'filled', 'Work Station', 'Mama Pam'))
                cur.execute("""
                    INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                    VALUES (%s,'stock_in',+1,'empty from mama pam')
                """, (gas_id,))

           # … (earlier code unchanged)

            elif src_external:
                # user only types the free‑text box “external_value”
                ext_value = request.form.get("external_details", "").strip()
                if not ext_value:
                    ext_value = "external-unknown"

                # 1️⃣ record the incoming (filled) cylinder
                cur.execute("""
                    INSERT INTO stock_in (gas_id, cylinder_state, source_type, source_value)
                    VALUES (%s, %s, 'Work Station', %s)            -- <‑‑ source_type fixed to 'station'
                """, (gas_id, "filled", ext_value))

                # 2️⃣ log the change
                cur.execute("""
                    INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                    VALUES (%s, 'stock_in', +1, 'empty from external place: ' || %s)
                """, (gas_id, ext_value))


            conn.commit()
            flash("Sale recorded successfully.", "success")

    except Exception as e:
        flash(f"Error processing sale: {e}", "error")

    return redirect("/sales")


@app.route("/profit-list")
def profit_list():
    with get_connection() as conn, conn.cursor() as cur:

        # fetch every profit row with brand name + time
        cur.execute("""
            SELECT  p.profit_id,
                    g.gas_name,
                    p.qty,
                    p.revenue,
                    p.cost,
                    p.profit,
                    p.created_at::date  AS day,
                    p.created_at::time  AS clock
            FROM    profit_table p
            JOIN    gas_table    g ON g.gas_id = p.gas_id
            ORDER   BY day DESC, p.created_at DESC
        """)
        rows = cur.fetchall()

    # ---- group in Python -------------------------------------------------
    day_map = {}             # {date : [dict, …]}
    for pid, gname, qty, rev, cst, prf, day, tm in rows:
        rec = {
            "id": pid, "gas": gname, "qty": qty,
            "rev": float(rev), "cost": float(cst), "prf": float(prf),
            "clock": tm.strftime("%H:%M")
        }
        day_map.setdefault(day, []).append(rec)

    # build a list with totals ready for Jinja
    grouped = []
    for d, lst in day_map.items():
        tot_qty   = sum(r["qty"]  for r in lst)
        tot_rev   = sum(r["rev"]  for r in lst)
        tot_cost  = sum(r["cost"] for r in lst)
        tot_prf   = sum(r["prf"]  for r in lst)
        grouped.append({
            "day": d,
            "records": lst,
            "tot_qty":  tot_qty,
            "tot_rev":  tot_rev,
            "tot_cost": tot_cost,
            "tot_prf":  tot_prf
        })

    # newest day first
    grouped.sort(key=lambda x: x["day"], reverse=True)

    return render_template("profit_list.html", grouped=grouped)
@app.route('/stock-out', methods=['GET', 'POST'])
def stock_out():
    conn = get_connection()
    cur = conn.cursor()

    # Get gases for dropdown
    cur.execute("SELECT gas_id, gas_name ,empty_cylinders, filled_cylinders FROM gas_table ORDER BY gas_name")
    gases = cur.fetchall()

    # Get users for delivery dropdown
    cur.execute("SELECT user_id, username FROM users ORDER BY username")
    users = cur.fetchall()

    message = None

    if request.method == 'POST':
        gas_id = request.form['gas_id']
        cylinder_state = request.form['cylinder_state']
        destination_type = request.form['destination_type']

        # Pick correct destination value
        if destination_type == "station":
            destination_value = request.form.get("destination_value_station")
        elif destination_type == "delivery":
            destination_value = request.form.get("destination_value_delivery")
        elif destination_type == "customer":
            destination_value = request.form.get("destination_value_customer")
        else:
            destination_value = None

        empty_not_given = request.form.get('empty_not_given')

        # Check availability in gas_table
        cur.execute("SELECT empty_cylinders, filled_cylinders FROM gas_table WHERE gas_id = %s", (gas_id,))
        stock = cur.fetchone()

        if not stock:
            message = "Gas not found."
        else:
            empty, filled = stock
            available = filled if cylinder_state == 'filled' else empty

            if available < 1:
                message = f"No {cylinder_state} cylinders available to send out."
            else:
                # Subtract from gas_table
                if cylinder_state == 'filled':
                    cur.execute("UPDATE gas_table SET filled_cylinders = filled_cylinders - 1 WHERE gas_id = %s", (gas_id,))
                else:
                    cur.execute("UPDATE gas_table SET empty_cylinders = empty_cylinders - 1 WHERE gas_id = %s", (gas_id,))

                # Insert into stock_out table
                cur.execute("""
                    INSERT INTO stock_out (
                        gas_id, 
                        cylinder_state, 
                        destination_type, 
                        destination_value, 
                        time_out
                    ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (gas_id, cylinder_state, destination_type, destination_value))

                # Add to stock_change log
                note = f"Stock out to {destination_type}: {destination_value}"
                change = -1
                action = "stock_out_" + cylinder_state
                cur.execute("""
                    INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                    VALUES (%s, %s, %s, %s)
                """, (gas_id, action, change, note))

                conn.commit()
                message = "Stock out entry saved successfully."

    # Fetch stock_out records with gas name and unified destination detail
    cur.execute("""
        SELECT
          so.id,
          g.gas_name,
          so.cylinder_state,
          so.destination_type,
          so.destination_value,
          so.time_out
        FROM stock_out so
        JOIN gas_table g ON so.gas_id = g.gas_id
        ORDER BY so.time_out DESC
    """)
    stock_out_records = cur.fetchall()

    stock_out_list = []
    for row in stock_out_records:
        destination_type = row[3]
        destination_value = row[4]
        goes_to = customer_name = delivery_username = None

        if destination_type == 'station':
            goes_to = destination_value
        elif destination_type == 'customer':
            customer_name = destination_value
        elif destination_type == 'delivery':
            cur.execute("SELECT username FROM users WHERE user_id = %s", (destination_value,))
            result = cur.fetchone()
            delivery_username = result[0] if result else 'Unknown'

        stock_out_list.append({
            'id': row[0],
            'gas_name': row[1],
            'cylinder_state': row[2],
            'goes_to': goes_to,
            'customer_name': customer_name,
            'delivery_username': delivery_username,
            'time': row[5].strftime('%Y-%m-%d %H:%M:%S') if row[5] else ''
        })

    cur.close()
    conn.close()

    return render_template('stock_out.html',
                           gases=gases,
                           users=users,
                           stock_out_records=stock_out_list,
                           message=message)
@app.route('/gas-summary')
def gas_summary():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                      CASE 
                        WHEN gas_name ILIKE '%13%' THEN '13kg'
                        ELSE 'non-13kg'
                      END AS gas_type,
                      SUM(empty_cylinders) AS total_empty,
                      SUM(filled_cylinders) AS total_filled,
                      SUM(empty_cylinders + filled_cylinders) AS total_cylinders
                    FROM gas_table
                    GROUP BY gas_type;
                """)
                rows = cur.fetchall()

        summary = []
        for row in rows:
            summary.append({
                "type": row[0],
                "empty": row[1],
                "filled": row[2],
                "total": row[3]
            })

        return render_template("gas_summary.html", summary=summary)

    except Exception as e:
        flash(f"Error loading gas summary: {e}", "error")
        return redirect(url_for("dashboard"))


@app.route('/add-stock-out', methods=['POST'])
def add_stock_out():
    gas_id = request.form.get('gas_id')
    cylinder_state = request.form.get('cylinder_state')
    destination_type = request.form.get('destination_type')
    empty_not_given = request.form.get('empty_not_given')  # This will be None if unchecked

    # Validate required inputs
    if not gas_id or not cylinder_state or not destination_type:
        flash("All fields are required.", "error")
        return redirect(url_for('stock_out'))

    # Get correct destination_value from form
    destination_value = None
    if destination_type == 'station':
        destination_value = request.form.get('destination_value_station')
    elif destination_type == 'delivery':
        destination_value = request.form.get('destination_value_delivery')
    elif destination_type == 'customer':
        destination_value = request.form.get('destination_value_customer')

    if not destination_value:
        flash("Destination value is required.", "error")
        return redirect(url_for('stock_out'))

    conn = get_connection()
    cur = conn.cursor()

    # Check gas availability
    cur.execute("SELECT empty_cylinders, filled_cylinders FROM gas_table WHERE gas_id = %s", (gas_id,))
    stock = cur.fetchone()
    if not stock:
        flash("Gas record not found.", "error")
        cur.close()
        conn.close()
        return redirect(url_for('stock_out'))

    empty_stock, filled_stock = stock

    if cylinder_state == 'empty' and empty_stock <= 0:
        flash("No empty cylinders available for this gas.", "error")
        cur.close()
        conn.close()
        return redirect(url_for('stock_out'))

    if cylinder_state == 'filled' and filled_stock <= 0:
        flash("No filled cylinders available for this gas.", "error")
        cur.close()
        conn.close()
        return redirect(url_for('stock_out'))

    # Insert into stock_out table
    cur.execute("""
        INSERT INTO stock_out (gas_id, cylinder_state, destination_type, destination_value)
        VALUES (%s, %s, %s, %s)
    """, (gas_id, cylinder_state, destination_type, destination_value))

    # Update stock in gas_table
    if empty_not_given and destination_type == 'customer':
        # Special condition: customer didn't return the empty cylinder
        if cylinder_state == 'empty':
            cur.execute("UPDATE gas_table SET empty_cylinders = empty_cylinders - 1 WHERE gas_id = %s", (gas_id,))
        elif cylinder_state == 'filled':
            cur.execute("UPDATE gas_table SET filled_cylinders = filled_cylinders - 1 WHERE gas_id = %s", (gas_id,))
    else:
        # Default case
        if cylinder_state == 'empty':
            cur.execute("UPDATE gas_table SET empty_cylinders = empty_cylinders - 1 WHERE gas_id = %s", (gas_id,))
        elif cylinder_state == 'filled':
            cur.execute("UPDATE gas_table SET filled_cylinders = filled_cylinders - 1 WHERE gas_id = %s", (gas_id,))

    conn.commit()
    cur.close()
    conn.close()

    flash("Stock out recorded successfully.", "success")
    return redirect(url_for('stock_out'))
@app.route('/return-stock/<int:stock_id>', methods=['POST'])
def return_stock(stock_id):
    returned_state = request.form.get('returned_cylinder_state')
    if returned_state not in ['empty', 'filled']:
        flash('Invalid returned cylinder state.', 'error')
        return redirect(url_for('stock_out'))

    conn = get_connection()
    cur = conn.cursor()

    # ✅ Get stock out record by stock_id
    cur.execute("""
        SELECT id, gas_id, cylinder_state, destination_type, destination_value, time_out
        FROM stock_out
        WHERE id = %s
    """, (stock_id,))
    
    record = cur.fetchone()
    if not record:
        flash('Record not found.', 'error')
        cur.close()
        conn.close()
        return redirect(url_for('stock_out'))

    # ✅ Unpack stock_out record
    _, gas_id, original_state, destination_type, destination_value, _ = record
    display_name = destination_value  # Default note value

    # ✅ If destination is delivery, fetch delivery username
    if destination_type == 'delivery':
        cur.execute("SELECT username FROM users WHERE user_id = %s", (destination_value,))
    result = cur.fetchone()
    if result:
        display_name = result[0]  # Use name instead of ID
    else:
        display_name = f"Unknown delivery (ID: {destination_value})"


    # ✅ If it's a delivery return (from filled → empty), redirect to payment
    if destination_type == 'delivery' and original_state == 'filled' and returned_state == 'empty':
        session['delivery_return_info'] = {
            'gas_id': gas_id,
            'stock_id': stock_id,
            'delivery_id': destination_value  # Still needed for later use
        }
        cur.close()
        conn.close()
        return redirect(url_for('record_delivery_sale'))

    # ✅ Log return in stock_change
    cur.execute("""
        INSERT INTO stock_change (gas_id, action, quantity_change, notes)
        VALUES (%s, %s, %s, %s)
    """, (
        gas_id,
        f"return_{returned_state}",
        1,
        f"Returned from {destination_type}: {display_name}"
    ))

    # ✅ Delete stock_out record
    cur.execute("DELETE FROM stock_out WHERE id = %s", (stock_id,))

    # ✅ Update cylinder count
    if returned_state == 'empty':
        cur.execute("UPDATE gas_table SET empty_cylinders = empty_cylinders + 1 WHERE gas_id = %s", (gas_id,))
    else:
        cur.execute("UPDATE gas_table SET filled_cylinders = filled_cylinders + 1 WHERE gas_id = %s", (gas_id,))

    conn.commit()
    cur.close()
    conn.close()

    flash("Gas returned successfully!", "success")
    return redirect(url_for('stock_out'))

@app.route("/delete-sale/<int:sale_id>")
def delete_sale(sale_id):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Fetch the sale record
                cur.execute("""
                    SELECT gas_id, source_kipsongo_pioneer, source_mama_pam, source_external
                    FROM sales_table WHERE sale_id = %s
                """, (sale_id,))
                sale = cur.fetchone()

                if not sale:
                    return "Sale not found.", 404

                gas_id, is_kipsongo, is_mama_pam, is_external = sale

                # Undo the gas count updates
                if is_kipsongo:
                    # Subtract 1 from kipsongo_sales
                    cur.execute("UPDATE kipsongo_gas_in_ukweli SET number_of_gas = number_of_gas - 1 WHERE gas_id = %s", (gas_id,))
                    cur.execute("UPDATE gas_table SET empty_cylinders = empty_cylinders - 1 WHERE gas_id = %s", (gas_id,))
                elif is_mama_pam:
                    cur.execute("UPDATE mama_pam_gas_in_ukweli SET number_of_gas = number_of_gas - 1 WHERE gas_id = %s", (gas_id,))
                    cur.execute("UPDATE gas_table SET empty_cylinders = empty_cylinders - 1 WHERE gas_id = %s", (gas_id,))
                elif is_external:
                    cur.execute("UPDATE external_gas_in_ukweli SET number_of_gas = number_of_gas - 1 WHERE gas_id = %s", (gas_id,))
                    cur.execute("UPDATE gas_table SET empty_cylinders = empty_cylinders - 1 WHERE gas_id = %s", (gas_id,))
                else:
                    # No source selected: reverse both empty and filled
                    cur.execute("""
                        UPDATE gas_table 
                        SET empty_cylinders = empty_cylinders - 1,
                            filled_cylinders = filled_cylinders + 1
                        WHERE gas_id = %s
                    """, (gas_id,))

                # Delete the sale record
                cur.execute("DELETE FROM sales_table WHERE sale_id = %s", (sale_id,))
                conn.commit()

        flash("Sale deleted .", "success")
        return redirect(url_for('sales'))

    except Exception as e:
        return f"Error deleting sale: {e}"

@app.route('/record-delivery-sale', methods=['GET', 'POST'])
def record_delivery_sale():
    info = session.get('delivery_return_info')
    if not info:
        flash("No delivery return info found in session.", "error")
        return redirect(url_for('stock_out'))

    if request.method == 'POST':
        amount_cash = request.form.get('amount_paid_cash')
        amount_till = request.form.get('amount_paid_till')

        try:
            amount_cash = float(amount_cash) if amount_cash else 0
            amount_till = float(amount_till) if amount_till else 0
        except ValueError:
            flash("Enter valid numeric values for payment.", "error")
            return redirect(url_for('record_delivery_sale'))

        gas_id = info['gas_id']
        stock_id = info['stock_id']
        delivery_id = info['delivery_id']

        conn = get_connection()
        cur = conn.cursor()

        # ✅ Insert into sales_table
        cur.execute("""
            INSERT INTO sales_table (
                gas_id, amount_paid_cash, amount_paid_till,
                source_external, complete_sale
            ) VALUES (%s, %s, %s, TRUE, TRUE)
        """, (gas_id, amount_cash, amount_till))

        # ✅ Record in stock_change (return from delivery)
        cur.execute("""
            INSERT INTO stock_change (gas_id, action, quantity_change, notes)
            VALUES (%s, %s, %s, %s)
        """, (gas_id, "return_empty", 1, f"Returned from delivery ID: {delivery_id}"))

        # ✅ Delete from stock_out
        cur.execute("DELETE FROM stock_out WHERE id = %s", (stock_id,))

        # ✅ Increase empty_cylinders
        cur.execute("UPDATE gas_table SET empty_cylinders = empty_cylinders + 1 WHERE gas_id = %s", (gas_id,))

        conn.commit()
        cur.close()
        conn.close()

        session.pop('delivery_return_info', None)  # ✅ Clear session after done
        flash("Delivery return and sale recorded successfully.", "success")
        return redirect(url_for('stock_out'))

    # If GET request, show form
    return render_template("record_delivery_sale.html")



# --- GAS SOURCE HANDLER ---


# --- EXTRA PAGES ---

#  GET page
# app.py  ─────────────────────────────────────────────
from collections import defaultdict, namedtuple
from datetime import datetime, date
from flask import render_template, flash, redirect, url_for, request

# ───────────────────────────────────────────────
# GET  /refill  – show form + grouped history
# ───────────────────────────────────────────────
@app.route('/refill')
def refill_page():
    with get_connection() as conn, conn.cursor() as cur:
        # ①  suppliers
        cur.execute("""
            SELECT company_id, company_name
            FROM   buying_company
            ORDER  BY company_name
        """)
        companies = [
            dict(company_id=c, company_name=n)
            for c, n in cur.fetchall()
        ]

        # ②  gas brands (with current stock)
        cur.execute("""
            SELECT gas_id, gas_name, empty_cylinders, filled_cylinders
            FROM   gas_table
            ORDER  BY gas_name
        """)
        gases = [
            dict(gas_id=g, gas_name=gn, empty=emp, filled=fil)
            for g, gn, emp, fil in cur.fetchall()
        ]

        # ③  last 150 refill rows (newest first)
        cur.execute("""
            SELECT
                DATE(r.refill_time)        AS d,    -- day bucket
                r.refill_time::time        AS t,    -- hh:mm:ss
                bc.company_name,
                g.gas_name,
                r.quantity,
                r.unit_price,
                r.total_cost
            FROM   refill_table  r
            JOIN   buying_company bc ON bc.company_id = r.company_id
            JOIN   gas_table      g  ON g.gas_id      = r.gas_id
            ORDER  BY r.refill_time DESC
            LIMIT 150
        """)
        raw = cur.fetchall()

    # ───────── Build nested structure → history[day][company] = list(records)
    HistoryRec = namedtuple("HistoryRec", "gas qty price total time")
    day_map: dict[date, dict[str, list[HistoryRec]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for d, t, comp, gas, qty, price, total in raw:
        day_map[d][comp].append(
            HistoryRec(gas, qty, float(price), float(total), t)
        )

    # Flatten into list‑of‑dicts for Jinja
    history: list[dict] = []
    for d in sorted(day_map.keys(), reverse=True):          # newest day first
        companies_group = []
        for comp in sorted(day_map[d].keys()):
            recs = day_map[d][comp]
            tot_qty  = sum(r.qty   for r in recs)
            tot_cost = sum(r.total for r in recs)
            companies_group.append({
                "company":    comp,
                "records":    recs,
                "total_qty":  tot_qty,
                "total_cost": tot_cost
            })
        history.append({
            "date":      d,
            "companies": companies_group
        })

    return render_template(
        "refill.html",
        companies = companies,
        gases     = gases,
        history   = history
    )
# finance.py (or place near the other routes) ──────────────────────────
@app.route("/finance")
@admin_required  # <- only admins may view
def finance_page():
    """
    High‑level financial dashboard – profit, cost, etc.
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(SUM(revenue - cost), 0) 
                FROM profit_table
            """)
            total_profit = float(cur.fetchone()[0])

        return render_template("finance.html", total_profit=total_profit)

    except Exception as e:
        flash(f"Finance page error: {e}", "error")
        return redirect(url_for("dashboard"))

@app.route('/profit')
def view_profit():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT DATE(created_at)      AS day,
                   SUM(revenue)          AS total_revenue,
                   SUM(cost)             AS total_cost,
                   SUM(profit)           AS total_profit
            FROM   profit_table
            GROUP  BY day
            ORDER  BY day DESC
        """)
        daily = [
            {"day": d, "revenue": float(r), "cost": float(c), "profit": float(p)}
            for d, r, c, p in cur.fetchall()
        ]
    return render_template("profit.html", daily=daily)

# ───────────────────────────────────────────────
# POST /add-refill  – save refill
# ───────────────────────────────────────────────
@app.route('/add-refill', methods=['POST'])
def add_refill():
    try:
        comp_id = int(request.form['company_id'])
        gid     = int(request.form['gas_id'])
        qty     = int(request.form['refill_qty'])

        if qty <= 0:
            flash("Quantity must be positive.", "error")
            return redirect(url_for('refill_page'))

        with get_connection() as conn, conn.cursor() as cur:

            # ── pull unit‑price from matrix ─────────────────────────────
            cur.execute("""
                SELECT refill_price
                FROM   company_gas_price
                WHERE  company_id = %s AND gas_id = %s
            """, (comp_id, gid))
            row = cur.fetchone()
            if not row or row[0] in (None, 0):
                flash("No price set for this supplier and gas brand.", "error")
                return redirect(url_for('refill_page'))

            unit_price = float(row[0])

            # ── 1) update stock (safety check: enough empties?) ─────────
            cur.execute("""
                UPDATE gas_table
                   SET filled_cylinders = filled_cylinders + %s,
                       empty_cylinders  = empty_cylinders  - %s
                 WHERE gas_id          = %s
                   AND empty_cylinders >= %s        -- safety
                RETURNING empty_cylinders, filled_cylinders
            """, (qty, qty, gid, qty))

            updated_row = cur.fetchone()          # None → no row updated
            if updated_row is None:
                conn.rollback()
                flash("❌ Not enough empty cylinders available for this brand.", "error")
                return redirect(url_for('refill_page'))

            # ── 2) insert into refill_table ────────────────────────────
            cur.execute("""
                INSERT INTO refill_table (company_id, gas_id, quantity, unit_price)
                VALUES (%s, %s, %s, %s)
            """, (comp_id, gid, qty, unit_price))

            # ── 3) stock_change log ────────────────────────────────────
            notes = f"Refill from supplier {comp_id} at {unit_price:.2f} KSh"
            cur.execute("""
                INSERT INTO stock_change (gas_id, action, quantity_change, notes)
                VALUES (%s, 'refill', %s, %s)
            """, (gid, qty, notes))

            conn.commit()
            flash("Refill saved.", "success")

    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for('refill_page'))

# ───────────────────────────────────────────────
# Optional: Ajax helper to auto‑fill price
# ───────────────────────────────────────────────
@app.route('/get-price')
def get_price():
    comp = request.args.get('company_id', type=int)
    gid  = request.args.get('gas_id', type=int)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT refill_price
            FROM   company_gas_price
            WHERE  company_id = %s AND gas_id = %s
        """, (comp, gid))
        row = cur.fetchone()
    return {"price": float(row[0]) if row else 0}

@app.route('/refill')
def refill():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT gas_id, gas_name, empty_cylinders, filled_cylinders
            FROM   gas_table
            ORDER  BY gas_name
        """)
        gases = [
            {"gas_id": gid, "gas_name": name, "empty_cylinders": empty, "filled_cylinders": filled}
            for gid, name, empty, filled in cur.fetchall()
        ]

        cur.execute("SELECT company_id, company_name FROM buying_company ORDER BY company_name")
        companies = cur.fetchall()

    return render_template("refill.html", gases=gases, companies=companies)

# -----------------------
#  GAS  –  ADD / UPDATE / DELETE
# -----------------------

@app.route("/gas-form")                      # ➊ show page
def gas_form():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT gas_id, gas_name,
                   empty_cylinders, filled_cylinders,
                   (empty_cylinders + filled_cylinders) AS total
            FROM   gas_table
            ORDER  BY gas_id
        """)
        gases = cur.fetchall()
    return render_template("gas_form.html", gases=gases)


@app.post("/add-gas")                       # ➋ insert new brand
def add_gas():
    name   = request.form["gas_name"].strip()
    empty  = int(request.form["empty_cylinders"]  or 0)
    filled = int(request.form["filled_cylinders"] or 0)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO gas_table (gas_name, empty_cylinders, filled_cylinders)
            VALUES (%s,%s,%s)
        """, (name, empty, filled))
        conn.commit()
    flash("Gas added ✅", "success")
    return redirect(url_for("gas_form"))


@app.post("/update-gas/<int:gid>")          # ➌ update counts / name
def update_gas(gid):
    name   = request.form["gas_name"].strip()
    empty  = int(request.form["empty_cylinders"]  or 0)
    filled = int(request.form["filled_cylinders"] or 0)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE gas_table
               SET gas_name = %s,
                   empty_cylinders  = %s,
                   filled_cylinders = %s
             WHERE gas_id = %s
        """, (name, empty, filled, gid))
        conn.commit()
    flash("Gas updated ✅", "success")
    return redirect(url_for("gas_form"))


@app.post("/delete-gas/<int:gid>")          # ➍ delete brand
def delete_gas(gid):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM gas_table WHERE gas_id=%s", (gid,))
        conn.commit()
    flash("Gas deleted 🗑️", "success")
    return redirect(url_for("gas_form"))
# --- MAIN APP ---

if __name__ == '__main__':
    app.run(debug=True)