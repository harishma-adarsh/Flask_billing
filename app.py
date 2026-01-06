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


@app.route('/')
def home():
    return render_template("form.html")


@app.route('/receipt', methods=["POST"])
def receipt():

    invoice_no = get_next_invoice_number()

    total_fee = int(request.form.get("fee", 0))
    discount = int(request.form.get("discount", 0))

    # calculate paid amount
    paid_amount = total_fee - discount
    
    # calculate balance
    balance = 0 # This could be calculated differently if needed
    
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
