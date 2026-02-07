import os
from flask import Flask, render_template, request, send_file
from weasyprint import HTML
import tempfile

app = Flask(__name__)

def get_next_invoice_number(increment=True):
    prefix = "ACT-025-R-"
    
    if not os.path.exists("invoice.txt"):
        with open("invoice.txt", "w") as f:
            f.write("1")

    with open("invoice.txt", "r+") as f:
        content = f.read().strip()
        number = int(content) if content else 1
        if increment:
            new_number = number + 1
            f.seek(0)
            f.write(str(new_number))
            f.truncate()
        
    formatted = prefix + str(number).zfill(3)
    return formatted


import sqlite3
from contextlib import closing

DATABASE = "billing.db"

def init_db():
    with sqlite3.connect(DATABASE) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                phone TEXT UNIQUE,
                name TEXT,
                address TEXT,
                alt_phone TEXT,
                course TEXT,
                duration TEXT,
                joining_date TEXT,
                fee INTEGER,
                discount INTEGER,
                approved_text TEXT,
                total_installments INTEGER
            )
        ''')
        # Check if the column exists for existing databases
        cursor = conn.execute("PRAGMA table_info(students)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'total_installments' not in columns:
            conn.execute("ALTER TABLE students ADD COLUMN total_installments INTEGER")
        if 'approved_text' not in columns:
            conn.execute("ALTER TABLE students ADD COLUMN approved_text TEXT")
        if 'salutation' not in columns:
            conn.execute("ALTER TABLE students ADD COLUMN salutation TEXT")

        conn.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                invoice_no TEXT,
                amount INTEGER,
                payment_date TEXT,
                FOREIGN KEY (student_id) REFERENCES students (id)
            )
        ''')
    # Migrate existing JSON data if it exists
    if os.path.exists("students.json"):
        try:
            with open("students.json", "r") as f:
                data = json.load(f)
                for key, s in data.items():
                    save_student_db(s)
            os.rename("students.json", "students.json.bak")
        except:
            pass

def save_student_db(data):
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        # Check if student exists
        cursor = conn.execute("SELECT id FROM students WHERE email = ? OR phone = ?", 
                            (data.get("email"), data.get("phone")))
        student = cursor.fetchone()
        
        if student:
            # Update existing
            conn.execute('''
                UPDATE students SET 
                name=?, address=?, alt_phone=?, course=?, duration=?, joining_date=?, total_installments=?, salutation=?
                WHERE id=?
            ''', (data.get("name"), data.get("address"), data.get("alt_phone"), 
                  data.get("course"), data.get("duration"), data.get("joining_date"), data.get("total_installments"), data.get("salutation"), student['id']))
            s_id = student['id']
        else:
            # Insert new
            cursor = conn.execute('''
                INSERT INTO students (name, email, phone, address, alt_phone, course, duration, joining_date, total_installments, salutation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (data.get("name"), data.get("email"), data.get("phone"), data.get("address"), 
                  data.get("alt_phone"), data.get("course"), data.get("duration"), data.get("joining_date"), data.get("total_installments"), data.get("salutation")))
            s_id = cursor.lastrowid
        
        # Save payments if provided in the data (used for migrations/updates)
        if "payments" in data:
            for p in data["payments"]:
                conn.execute('''
                    INSERT INTO payments (student_id, invoice_no, amount, payment_date)
                    VALUES (?, ?, ?, ?)
                ''', (s_id, p["invoice"], p["amount"], p["date"]))
        return s_id

init_db()

@app.route('/')
def home():
    return render_template("registration.html")


@app.route('/registration', methods=['GET', 'POST'])
def registration():
    if request.method == 'POST':
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        
        if not name:
            return "Name cannot be blank", 400
        if not email or "@" not in email:
            return "Valid email is required", 400
        if not phone or len(phone) < 10:
            return "Valid 10-digit phone number is required", 400

        # Get data from registration form
        data = {
            "name": name,
            "address": request.form.get("address"),
            "email": email,
            "phone": phone,
            "alt_phone": request.form.get("alt_phone"),
            "course": request.form.get("course"),
            "duration": request.form.get("duration"),
            "joining_date": request.form.get("joining_date"),
            "previous_total_paid": request.form.get("previous_total_paid", 0),
            "total_installments": request.form.get("total_installments", 3),
            "next_installment": request.form.get("next_installment", 1),
            "fee_preset": request.form.get("fee_preset", 0),
            "discount_preset": request.form.get("discount_preset", 0)
        }
        # Save student to DB
        save_student_db(data)
        return render_template("form.html", prefill=data)
    return render_template("registration.html")

@app.route('/search_student')
def search_student():
    query = request.args.get('query', '').strip().lower()
    if not query:
        return {"success": False, "message": "Query required"}, 400
    
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        # 1. Try Exact Match First
        cursor = conn.execute('''
            SELECT * FROM students 
            WHERE lower(name) = ? OR lower(email) = ? OR phone = ? OR alt_phone = ?
        ''', (query.lower(), query.lower(), query, query))
        student = cursor.fetchone()

        # 2. Fallback to Fuzzy Search if no exact match found
        if not student:
            search_query = f"%{query}%"
            cursor = conn.execute('''
                SELECT * FROM students 
                WHERE lower(name) LIKE ? OR lower(email) LIKE ? OR phone LIKE ? OR alt_phone LIKE ?
            ''', (search_query.lower(), search_query.lower(), search_query, search_query))
            student = cursor.fetchone()
        
        if student:
            student_data = dict(student)
            # Fetch payment history
            payments_cursor = conn.execute("SELECT amount FROM payments WHERE student_id = ?", (student['id'],))
            payments = payments_cursor.fetchall()
            
            total_paid = sum(p['amount'] for p in payments)
            student_data["previous_total_paid"] = total_paid
            
            total_allowed = student_data.get("total_installments")
            if not total_allowed:
                total_allowed = 1
                student_data["total_installments"] = 1
                
            num_paid = len(payments)
            if num_paid >= total_allowed:
                student_data["next_installment"] = "Payment Completed"
            else:
                student_data["next_installment"] = str(num_paid + 1)
            
            # Return fee and discount if they exist
            student_data["fee_preset"] = student['fee'] if student['fee'] is not None else 0
            student_data["discount_preset"] = student['discount'] if student['discount'] is not None else 0
            
            return {"success": True, "data": student_data}
            
    return {"success": False, "message": "Student not found"}, 404

@app.route('/proceed_to_billing', methods=['POST'])
def proceed_to_billing():
    data = request.json
    return render_template("form.html", prefill=data)





@app.route('/receipt', methods=["POST"])
def receipt():

    invoice_no = get_next_invoice_number()

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()

    name = request.form.get("name")
    email = request.form.get("email")
    phone = request.form.get("phone")
    paid_amount = int(request.form.get("paid_amount", 0))
    already_paid = int(request.form.get("already_paid", 0))
    total_fee = int(request.form.get("fee", 0))
    discount = int(request.form.get("discount", 0))
    
    # 1. Check if payment already exists (Prevent Refresh Duplicate)
    # We do this BEFORE incrementing the invoice number
    existing_invoice = None
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        student = conn.execute("SELECT id FROM students WHERE email = ? OR phone = ?", (email, phone)).fetchone()
        if student:
            s_id = student['id']
            # Look for an identical payment record from today
            from datetime import datetime
            raw_date = request.form.get("invoice_date")
            try:
                search_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d-%m-%Y")
            except:
                search_date = raw_date
                
            payment = conn.execute('''
                SELECT invoice_no FROM payments 
                WHERE student_id = ? AND amount = ? AND payment_date = ?
                ORDER BY id DESC LIMIT 1
            ''', (s_id, paid_amount, search_date)).fetchone()
            
            if payment:
                existing_invoice = payment['invoice_no']

    if existing_invoice:
        invoice_no = existing_invoice
    else:
        invoice_no = get_next_invoice_number(increment=True)

    
    # calculate balance
    balance = (total_fee - discount) - (already_paid + paid_amount)
    
    from num2words import num2words
    try:
        amount_in_words = num2words(paid_amount, lang='en_IN').title() + " Only"
    except:
        amount_in_words = ""

    from datetime import datetime
    
    def format_date(date_str):
        if not date_str:
            return ""
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
        except:
            return date_str

    data = {
        "invoice": invoice_no,
        "invoice_date": format_date(request.form.get("invoice_date")),
        "joining_date": format_date(request.form.get("joining_date")),
        "validity": format_date(request.form.get("validity")),
        "approved": request.form.get("approved"),
        "salutation": request.form.get("salutation", ""),
        
        "payment_method": request.form.get("payment_method"),
        "reference": request.form.get("reference", "NA"),

        "name": request.form.get("name"),
        "address": request.form.get("address"),
        "email": request.form.get("email"),
        "phone": request.form.get("phone"),
        "alt_phone": request.form.get("alt_phone"),

        "course": request.form.get("course"),
        "duration": request.form.get("duration"),
        "installment": request.form.get("installment"),

        "fee": total_fee,
        "discount": discount,
        "paid_amount": paid_amount,
        "already_paid": already_paid,
        "balance": balance,
        "amount_in_words": f"Rupees {amount_in_words}"
    }

    # Save payment record to SQLite DB
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        # Get student ID
        cursor = conn.execute("SELECT id FROM students WHERE email = ? OR phone = ?", 
                            (request.form.get("email"), request.form.get("phone")))
        student = cursor.fetchone()
        
        if student:
            s_id = student['id']
            
            # Use the existing_invoice logic from above to decide whether to insert
            if not existing_invoice:
                # Update student fee/discount/approved_text/total_installments if they were changed
                conn.execute("UPDATE students SET fee = ?, discount = ?, approved_text = ?, total_installments = ? WHERE id = ?", 
                            (total_fee, discount, request.form.get("approved"), request.form.get("installment"), s_id))
                
                # Record payment
                conn.execute('''
                    INSERT INTO payments (student_id, invoice_no, amount, payment_date)
                    VALUES (?, ?, ?, ?)
                ''', (s_id, invoice_no, paid_amount, data["invoice_date"]))
            else:
                # Duplicate submittion (refresh) - No changes to payment history
                pass

    html = render_template("receipt.html", data=data)

    base_url = os.path.dirname(os.path.abspath(__file__))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as pdf:
        HTML(string=html, base_url=base_url).write_pdf(pdf.name)
        student_name = request.form.get("name", "Student").replace(" ", "_")
        return send_file(pdf.name, as_attachment=True, download_name=f"{invoice_no}_{student_name}.pdf")


if __name__ == '__main__':
    app.run(debug=True)
