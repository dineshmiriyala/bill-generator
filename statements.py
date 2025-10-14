from flask import Blueprint, render_template, request, send_file
from datetime import datetime
import io
import csv
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from db.models import *

statements_bp = Blueprint('statements', __name__)

@statements_bp.route('/statements')
def statements():
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    scope = request.args.get('scope', 'all')
    company_id = request.args.get('company_id')

    if not start_date_str or not end_date_str:
        return "Please provide start_date and end_date query parameters", 400

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        return "Invalid date format. Use YYYY-MM-DD.", 400

    query = Statement.query.filter(
        Statement.date >= start_date,
        Statement.date <= end_date
    )

    if scope == 'company' and company_id:
        query = query.filter(Statement.company_id == company_id)

    statements = query.all()

    output_format = request.args.get('format', 'html')

    if output_format == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Date', 'Amount', 'Description'])
        for s in statements:
            writer.writerow([s.id, s.date, s.amount, s.description])
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name='statements.csv'
        )

    elif output_format == 'pdf':
        output = io.BytesIO()
        p = canvas.Canvas(output, pagesize=letter)
        width, height = letter
        y = height - 50
        p.drawString(30, y, "Statements Report")
        y -= 30
        for s in statements:
            line = f"ID: {s.id}, Date: {s.date}, Amount: {s.amount}, Description: {s.description}"
            p.drawString(30, y, line)
            y -= 20
            if y < 50:
                p.showPage()
                y = height - 50
        p.save()
        output.seek(0)
        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='statements.pdf'
        )

    else:
        companies = Company.query.all()
        return render_template('statement.html', statements=statements, companies=companies, start_date=start_date_str, end_date=end_date_str, scope=scope, company_id=company_id)


@statements_bp.route('/statements_company')
def statements_company():
    company_id = request.args.get('company_id')
    if not company_id:
        return "Please provide company_id query parameter", 400

    company = Company.query.get(company_id)
    if not company:
        return "Company not found", 404

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return "Invalid date format. Use YYYY-MM-DD.", 400

        statements = Statement.query.filter(
            Statement.company_id == company_id,
            Statement.date >= start_date,
            Statement.date <= end_date
        ).all()
    else:
        statements = Statement.query.filter_by(company_id=company_id).all()

    output_format = request.args.get('format', 'html')

    if output_format == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Date', 'Amount', 'Description', 'Company'])
        for s in statements:
            writer.writerow([s.id, s.date, s.amount, s.description, company.name])
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'statements_{company.name}.csv'
        )

    elif output_format == 'pdf':
        output = io.BytesIO()
        p = canvas.Canvas(output, pagesize=letter)
        width, height = letter
        y = height - 50
        p.drawString(30, y, f"Statements Report for {company.name}")
        y -= 30
        for s in statements:
            line = f"ID: {s.id}, Date: {s.date}, Amount: {s.amount}, Description: {s.description}"
            p.drawString(30, y, line)
            y -= 20
            if y < 50:
                p.showPage()
                y = height - 50
        p.save()
        output.seek(0)
        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'statements_{company.name}.pdf'
        )

    else:
        return render_template('statements_company.html', company=company, statements=statements, start_date=start_date_str, end_date=end_date_str)
