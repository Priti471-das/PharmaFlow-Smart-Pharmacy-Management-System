import os
import json
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, send_file
import csv
from io import StringIO

app = Flask(__name__, template_folder="template")
app.secret_key = 'pharma_secret'

DATA_FILES = {
    'inventory': 'inventory.json',
    'invoices': 'invoices.json',
    'expenses': 'expenses.json',
    'customers': 'customers.json'
}

def read_collection(name):
    path = DATA_FILES[name]
    if not os.path.exists(path):
        with open(path, 'w') as f:
            json.dump([], f)
        return []
    with open(path, 'r') as f:
        return json.load(f)

def write_collection(name, data):
    with open(DATA_FILES[name], 'w') as f:
        json.dump(data, f)

def append_to_collection(name, item):
    data = read_collection(name)
    data.append(item)
    write_collection(name, data)

def find_collection(name, criteria):
    data = read_collection(name)
    for item in data:
        match = True
        for k, v in criteria.items():
            if item.get(k) != v:
                match = False
                break
        if match:
            return item
    return None

def update_collection_item(name, key, value, new_data):
    data = read_collection(name)
    for i, item in enumerate(data):
        if item.get(key) == value:
            data[i] = new_data
            write_collection(name, data)
            return True
    return False

def delete_collection_item(name, key, value):
    data = read_collection(name)
    new_data = [item for item in data if item.get(key) != value]
    if len(new_data) != len(data):
        write_collection(name, new_data)
        return True
    return False

def predict_next_week_sales(invoices):
    daily_totals = {}
    for i in range(7):
        date = datetime.utcnow().date() - timedelta(days=6 - i)
        daily_totals[str(date)] = 0.0
    seven_days_ago = str(datetime.utcnow().date() - timedelta(days=7))
    for inv in invoices:
        if inv['date'] >= seven_days_ago:
            if inv['date'] in daily_totals:
                daily_totals[inv['date']] += inv['grand_total']
    values = list(daily_totals.values())
    avg = sum(values) / len(values) if values else 0
    trend = 0
    if len(values) >= 2:
        trend = (values[-1] - values[0]) / max(1, len(values) - 1)
    prediction = (avg + trend) * 7
    return round(max(0, prediction), 2)

def predict_low_stock_items(inventory, invoices):
    usage = {}
    thirty_days_ago = str(datetime.utcnow().date() - timedelta(days=30))
    for inv in invoices:
        if inv['date'] >= thirty_days_ago:
            for item in inv['items']:
                name = item['name']
                usage[name] = usage.get(name, 0) + item['quantity']
    low_risk = []
    for item in inventory:
        name = item['name']
        used = usage.get(name, 0)
        daily_avg = used / 30 if used > 0 else 0
        days_left = item['quantity'] / daily_avg if daily_avg > 0 else 999
        if days_left < 14:
            low_risk.append({**item, 'days_until_empty': round(days_left)})
    low_risk.sort(key=lambda x: x['days_until_empty'])
    return low_risk

def get_dashboard_stats(invoices, expenses, inventory):
    today = datetime.utcnow().date()
    thirty_days_ago = str(today - timedelta(days=30))
    stats = {
        'total_revenue': 0,
        'profit': 0,
        'misc_expenditure': 0,
        'total_purchase_cost': 0,
        'expiring_soon': [],
        'low_stock': [],
        'item_sales': {},
        'sales_last_7_days': {},
        'predicted_next_week_sales': predict_next_week_sales(invoices),
        'predicted_low_stock_items': predict_low_stock_items(inventory, invoices),
    }
    for i in range(7):
        date = today - timedelta(days=6 - i)
        stats['sales_last_7_days'][str(date)] = 0.0
    for inv in invoices:
        if inv['date'] >= thirty_days_ago:
            stats['total_revenue'] += inv['grand_total']
            stats['profit'] += inv['profit']
        for item in inv['items']:
            stats['item_sales'][item['name']] = stats['item_sales'].get(item['name'], 0) + item['quantity']
        if inv['date'] in stats['sales_last_7_days']:
            stats['sales_last_7_days'][inv['date']] += inv['grand_total']
    for exp in expenses:
        if exp['date'] >= thirty_days_ago:
            stats['misc_expenditure'] += exp['amount']
    stats['profit'] -= stats['misc_expenditure']
    for item in inventory:
        stats['total_purchase_cost'] += item['purchase_cost'] * item['quantity']
        if 0 < item['quantity'] < 10:
            stats['low_stock'].append(item)
        expiry = item.get('expiry')
        if expiry:
            expiry_date = datetime.strptime(expiry, '%Y-%m-%d').date()
            if expiry_date <= today + timedelta(days=30) and expiry_date >= today:
                stats['expiring_soon'].append(item)
    stats['item_sales'] = dict(sorted(stats['item_sales'].items(), key=lambda x: x[1], reverse=True))
    return stats

def export_csv(data_type):
    if data_type == 'inventory':
        data = read_collection('inventory')
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Name', 'Quantity', 'Purchase Cost', 'Price Per Unit', 'Expiry'])
        for row in data:
            writer.writerow([row['id'], row['name'], row['quantity'], row['purchase_cost'], row['price_per_unit'], row['expiry']])
        output.seek(0)
        return send_file(output, mimetype='text/csv', as_attachment=True, download_name=f"export_inventory_{datetime.utcnow().strftime('%Y-%m-%d')}.csv")
    elif data_type == 'sales':
        invoices = read_collection('invoices')
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Invoice ID', 'Date', 'Customer Name', 'Customer Phone', 'Sub Total', 'Discount', 'Tax', 'Grand Total', 'Profit'])
        for inv in invoices:
            writer.writerow([inv['id'], inv['date'], inv['customer_name'], inv['customer_phone'], inv['sub_total'], inv['discount'], inv['tax'], inv['grand_total'], inv['profit']])
        output.seek(0)
        return send_file(output, mimetype='text/csv', as_attachment=True, download_name=f"export_sales_{datetime.utcnow().strftime('%Y-%m-%d')}.csv")
    elif data_type == 'financial':
        expenses = read_collection('expenses')
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Name', 'Amount', 'Date'])
        for exp in expenses:
            writer.writerow([exp['id'], exp['name'], exp['amount'], exp['date']])
        output.seek(0)
        return send_file(output, mimetype='text/csv', as_attachment=True, download_name=f"export_financial_{datetime.utcnow().strftime('%Y-%m-%d')}.csv")
    return "Invalid export type", 400

@app.route('/', methods=['GET', 'POST'])
def index():
    view = request.args.get('view', 'dashboard')
    success = request.args.get('success')
    error = request.args.get('error')
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'add_stock':
                new_item = {
                    'id': f"stock_{uuid.uuid4().hex}",
                    'name': request.form['name'],
                    'quantity': int(request.form['quantity']),
                    'purchase_cost': float(request.form['purchase_cost']),
                    'price_per_unit': float(request.form['price_per_unit']),
                    'expiry': request.form['expiry'],
                }
                append_to_collection('inventory', new_item)
                return redirect(url_for('index', view='inventory', success=f"Stock item '{new_item['name']}' added successfully."))
            elif action == 'add_expense':
                new_expense = {
                    'id': f"exp_{uuid.uuid4().hex}",
                    'name': request.form['name'],
                    'amount': float(request.form['amount']),
                    'date': datetime.utcnow().strftime('%Y-%m-%d'),
                }
                append_to_collection('expenses', new_expense)
                return redirect(url_for('index', view='expenses', success=f"Expense '{new_expense['name']}' added successfully."))
            elif action == 'delete_expense':
                delete_collection_item('expenses', 'id', request.form['id'])
                return redirect(url_for('index', view='expenses', success="Expense deleted successfully."))
            elif action == 'add_invoice':
                items_names = request.form.getlist('items[name][]')
                items_qtys = request.form.getlist('items[quantity][]')
                customer_name = request.form['customer_name']
                customer_phone = request.form['customer_phone']
                customer_age = int(request.form.get('customer_age') or 0)
                discount = float(request.form.get('discount') or 0)
                tax = float(request.form.get('tax') or 0)
                invoice_items = []
                sub_total = 0
                total_cost = 0
                for name, qty_str in zip(items_names, items_qtys):
                    qty = int(qty_str)
                    if qty <= 0:
                        continue
                    stock_item = find_collection('inventory', {'name': name})
                    if not stock_item:
                        raise Exception(f"Item '{name}' not found in stock.")
                    if stock_item['quantity'] < qty:
                        raise Exception(f"Not enough stock for '{name}'. Available: {stock_item['quantity']}.")
                    price = stock_item['price_per_unit']
                    item_total = price * qty
                    sub_total += item_total
                    total_cost += stock_item['purchase_cost'] * qty
                    invoice_items.append({
                        'name': name,
                        'quantity': qty,
                        'price_per_unit': price,
                        'total': item_total
                    })
                tax_amount = (sub_total - discount) * (tax / 100)
                grand_total = (sub_total - discount) + tax_amount
                profit = grand_total - total_cost
                for item in invoice_items:
                    stock = find_collection('inventory', {'name': item['name']})
                    stock['quantity'] -= item['quantity']
                    update_collection_item('inventory', 'id', stock['id'], stock)
                new_invoice = {
                    'id': f"inv_{uuid.uuid4().hex}",
                    'date': datetime.utcnow().strftime('%Y-%m-%d'),
                    'customer_name': customer_name,
                    'customer_phone': customer_phone,
                    'customer_age': customer_age,
                    'items': invoice_items,
                    'sub_total': sub_total,
                    'discount': discount,
                    'tax': tax,
                    'tax_amount': tax_amount,
                    'grand_total': grand_total,
                    'total_cost': total_cost,
                    'profit': profit,
                }
                append_to_collection('invoices', new_invoice)
                customer = find_collection('customers', {'phone': customer_phone})
                if customer:
                    customer['total_spent'] += grand_total
                    customer['order_count'] += 1
                    customer['history'].append(new_invoice['id'])
                    update_collection_item('customers', 'phone', customer_phone, customer)
                else:
                    customer = {
                        'id': f"cust_{uuid.uuid4().hex}",
                        'name': customer_name,
                        'phone': customer_phone,
                        'age': customer_age,
                        'total_spent': grand_total,
                        'order_count': 1,
                        'history': [new_invoice['id']],
                    }
                    append_to_collection('customers', customer)
                return redirect(url_for('index', view='invoices', success=f"Invoice {new_invoice['id']} created successfully."))
        except Exception as e:
            return redirect(url_for('index', view=view, error=str(e)))
    detail_type = request.args.get('detail')
    detail_id = request.args.get('id')
    detail_record = None
    if detail_type and detail_id:
        if detail_type == 'invoice':
            detail_record = find_collection('invoices', {'id': detail_id})
        elif detail_type == 'stock':
            detail_record = find_collection('inventory', {'id': detail_id})
        elif detail_type == 'customer':
            detail_record = find_collection('customers', {'id': detail_id})
    export_type = request.args.get('export')
    if export_type:
        return export_csv(export_type)
    inventory = read_collection('inventory')
    invoices = read_collection('invoices')
    expenses = read_collection('expenses')
    customers = read_collection('customers')
    dashboard_data = get_dashboard_stats(invoices, expenses, inventory)
    return render_template('base.html',
                           view=view,
                           success=success,
                           error=error,
                           inventory=inventory,
                           invoices=invoices,
                           expenses=expenses,
                           customers=customers,
                           dashboard_data=dashboard_data,
                           detail_type=detail_type,
                           detail_record=detail_record)

if __name__ == '__main__':
    app.run(debug=True)