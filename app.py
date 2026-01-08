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


import json

STUDENTS_FILE = "students.json"

def load_students():
    if not os.path.exists(STUDENTS_FILE):
        return {}
    try:
        with open(STUDENTS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_student(data):
    students = load_students()
    # Use email or phone as a unique key (email prioritized)
    key = data.get("email") or data.get("phone")
    if key:
        students[key] = data
        with open(STUDENTS_FILE, "w") as f:
            json.dump(students, f, indent=4)

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
            "joining_date": request.form.get("joining_date")
        }
        # Save student for future use
        save_student(data)
        return render_template("form.html", prefill=data)
    return render_template("registration.html")

@app.route('/search_student')
def search_student():
    query = request.args.get('query', '').strip().lower()
    if not query:
        return {"success": False, "message": "Query required"}, 400
    
    students = load_students()
    
    # Check for exact matches first (Email/Phone)
    if query in students:
        return {"success": True, "data": students[query]}
    
    # Partial match search (Name, Email, or Phone)
    for key, s in students.items():
        name = s.get('name', '').lower()
        email = s.get('email', '').lower()
        phone = s.get('phone', '').lower()
        alt_phone = s.get('alt_phone', '').lower()
        
        if query in name or query in email or query in phone or query in alt_phone:
            return {"success": True, "data": s}
            
    return {"success": False, "message": "Student not found"}, 404

@app.route('/proceed_to_billing', methods=['POST'])
def proceed_to_billing():
    # This route takes JSON data of an existing student and renders the billing form
    data = request.json
    return render_template("form.html", prefill=data)


@app.route('/clear_database', methods=['GET'])
def clear_database():
    # Clear Student Data
    if os.path.exists(STUDENTS_FILE):
        os.remove(STUDENTS_FILE)
    
    # Reset Invoice Number
    with open("invoice.txt", "w") as f:
        f.write("1")
        
    return "Database cleared successfully! Students removed and invoice number reset to 1."


@app.route('/receipt', methods=["POST"])
def receipt():

    invoice_no = get_next_invoice_number()

    total_fee = int(request.form.get("fee", 0))
    discount = int(request.form.get("discount", 0))

    # get paid amount from form
    paid_amount = int(request.form.get("paid_amount", 0))
    
    # calculate balance
    balance = (total_fee - discount) - paid_amount
    
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

    html = render_template("receipt.html", data=data)

    base_url = os.path.dirname(os.path.abspath(__file__))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as pdf:
        HTML(string=html, base_url=base_url).write_pdf(pdf.name)
        return send_file(pdf.name, as_attachment=True, download_name=f"{invoice_no}.pdf")


if __name__ == '__main__':
    app.run(debug=True)
