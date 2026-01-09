import os
from flask import Flask, render_template, request, send_file
from weasyprint import HTML
import tempfile

app = Flask(__name__)

def get_next_invoice_number():
    prefix = "ACT-025-R-"
    
    if not os.path.exists("invoice.txt"):
        with open("invoice.txt", "w") as f:
            f.write("1")

    with open("invoice.txt", "r+") as f:
        content = f.read().strip()
        number = int(content) if content else 1
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
                name=?, address=?, alt_phone=?, course=?, duration=?, joining_date=?, total_installments=?
                WHERE id=?
            ''', (data.get("name"), data.get("address"), data.get("alt_phone"), 
                  data.get("course"), data.get("duration"), data.get("joining_date"), data.get("total_installments"), student['id']))
            s_id = student['id']
        else:
            # Insert new
            cursor = conn.execute('''
                INSERT INTO students (name, email, phone, address, alt_phone, course, duration, joining_date, total_installments)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (data.get("name"), data.get("email"), data.get("phone"), data.get("address"), 
                  data.get("alt_phone"), data.get("course"), data.get("duration"), data.get("joining_date"), data.get("total_installments")))
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
        # Get data from registration form
        data = {
            "name": request.form.get("name"),
            "address": request.form.get("address"),
            "email": request.form.get("email"),
            "phone": request.form.get("phone"),
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
        # Search by name, email, phone or alt_phone
        search_query = f"%{query}%"
        cursor = conn.execute('''
            SELECT * FROM students 
            WHERE lower(name) LIKE ? OR lower(email) LIKE ? OR phone LIKE ? OR alt_phone LIKE ?
        ''', (search_query, search_query, search_query, search_query))
        student = cursor.fetchone()
        
        if student:
            student_data = dict(student)
            # Fetch payment history
            payments_cursor = conn.execute("SELECT amount FROM payments WHERE student_id = ?", (student['id'],))
            payments = payments_cursor.fetchall()
            
            total_paid = sum(p['amount'] for p in payments)
            student_data["previous_total_paid"] = total_paid
            student_data["next_installment"] = min(len(payments) + 1, 3)
            # Ensure total_installments is returned (default to 3 if not set)
            if not student_data.get("total_installments"):
                student_data["total_installments"] = 3
            
            # Return fee and discount if they exist
            student_data["fee_preset"] = student['fee'] if student['fee'] is not None else 0
            student_data["discount_preset"] = student['discount'] if student['discount'] is not None else 0
            
            return {"success": True, "data": student_data}
            
    return {"success": False, "message": "Student not found"}, 404

@app.route('/proceed_to_billing', methods=['POST'])
def proceed_to_billing():
    data = request.json
    return render_template("form.html", prefill=data)


@app.route('/clear_database', methods=['GET'])
def clear_database():
    # Clear SQL Tables
    with sqlite3.connect(DATABASE) as conn:
        conn.execute("DELETE FROM payments")
        conn.execute("DELETE FROM students")
    
    # Reset Invoice Number
    with open("invoice.txt", "w") as f:
        f.write("1")
        
    from flask import redirect, url_for
    return redirect(url_for('home'))


@app.route('/receipt', methods=["POST"])
def receipt():

    invoice_no = get_next_invoice_number()

    total_fee = int(request.form.get("fee", 0))
    discount = int(request.form.get("discount", 0))

    # get paid amount from form
    paid_amount = int(request.form.get("paid_amount", 0))
    already_paid = int(request.form.get("already_paid", 0))
    
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
            # Update student fee/discount/approved_text/total_installments if they were changed
            conn.execute("UPDATE students SET fee = ?, discount = ?, approved_text = ?, total_installments = ? WHERE id = ?", 
                        (total_fee, discount, request.form.get("approved"), request.form.get("installment"), s_id))
            
            # Record payment
            conn.execute('''
                INSERT INTO payments (student_id, invoice_no, amount, payment_date)
                VALUES (?, ?, ?, ?)
            ''', (s_id, invoice_no, paid_amount, data["invoice_date"]))

    html = render_template("receipt.html", data=data)

    base_url = os.path.dirname(os.path.abspath(__file__))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as pdf:
        HTML(string=html, base_url=base_url).write_pdf(pdf.name)
        student_name = request.form.get("name", "Student").replace(" ", "_")
        return send_file(pdf.name, as_attachment=True, download_name=f"{invoice_no}_{student_name}.pdf")


if __name__ == '__main__':
    app.run(debug=True)
