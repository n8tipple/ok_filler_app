from flask import Flask, render_template, request, redirect, url_for, send_file, flash
import sqlite3
import os
import requests
import csv
import io

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Replace with a secure key in production

DATABASE = 'database.db'

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    # Create 'facilities' table if it doesn't exist
    c.execute('''
        CREATE TABLE IF NOT EXISTS facilities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            facility_name TEXT NOT NULL,
            api_numbers TEXT  -- Store multiple API numbers as a comma-separated string
        )
    ''')
    # Create 'responses' table with new fields
    c.execute('''
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            facility_id INTEGER,
            name TEXT,
            title TEXT,
            company TEXT,
            street TEXT,
            city TEXT,
            state TEXT,
            zip TEXT,
            phone_number TEXT,
            email TEXT,
            FOREIGN KEY(facility_id) REFERENCES facilities(id)
        )
    ''')
    # Create 'well_data' table to store multiple wells per facility
    c.execute('''
        CREATE TABLE IF NOT EXISTS well_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            facility_id INTEGER,
            api_number TEXT,
            WELL_NAME TEXT,
            WELL_NUM TEXT,
            OPERATOR TEXT,
            SH_LAT REAL,
            SH_LON REAL,
            COUNTY TEXT,
            SECTION TEXT,
            TOWNSHIP TEXT,
            RANGE TEXT,
            QTR2 TEXT,
            QTR1 TEXT,
            PLSS TEXT,
            FOREIGN KEY(facility_id) REFERENCES facilities(id)
        )
    ''')
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# Context processor to make facilities available in all templates
@app.context_processor
def inject_facilities():
    conn = get_db_connection()
    facilities = conn.execute('SELECT id, facility_name FROM facilities').fetchall()
    conn.close()
    return dict(nav_facilities=facilities)

init_db()

@app.route('/', methods=['GET', 'POST'])
def index():
    conn = get_db_connection()
    facilities = conn.execute('SELECT * FROM facilities').fetchall()
    conn.close()

    if request.method == 'POST':
        selected_facility = request.form.get('facility')
        if selected_facility:
            return redirect(url_for('facility_detail', facility_id=selected_facility))
    return render_template('index.html', facilities=facilities)

@app.route('/facility/<int:facility_id>', methods=['GET', 'POST'])
def facility_detail(facility_id):
    conn = get_db_connection()
    facility = conn.execute('SELECT * FROM facilities WHERE id = ?', (facility_id,)).fetchone()
    response = conn.execute('SELECT * FROM responses WHERE facility_id = ?', (facility_id,)).fetchone()
    well_data_rows = conn.execute('SELECT * FROM well_data WHERE facility_id = ?', (facility_id,)).fetchall()
    conn.close()

    # Convert well_data_rows to a list of dictionaries
    well_data_list = [dict(row) for row in well_data_rows] if well_data_rows else []

    if request.method == 'POST':
        if 'save' in request.form:
            # Collect facility and response data from the form
            facility_name = request.form.get('facility_name', '').strip()
            api_numbers = request.form.get('api_numbers', '').strip()
            name = request.form.get('name', '').strip()
            title = request.form.get('title', '').strip()
            company = request.form.get('company', '').strip()
            street = request.form.get('street', '').strip()
            city = request.form.get('city', '').strip()
            state = request.form.get('state', '').strip()
            zip_code = request.form.get('zip', '').strip()
            phone_number = request.form.get('phone_number', '').strip()
            email = request.form.get('email', '').strip()

            # Basic validation
            if not facility_name or not name or not company or not phone_number or not email:
                flash('Please fill in all required fields.', 'error')
                return redirect(url_for('facility_detail', facility_id=facility_id))

            conn = get_db_connection()
            # Update facility information
            conn.execute('''
                UPDATE facilities
                SET facility_name = ?, api_numbers = ?
                WHERE id = ?
            ''', (facility_name, api_numbers, facility_id))

            # Update or insert response information
            if response:
                conn.execute('''
                    UPDATE responses
                    SET name = ?, title = ?, company = ?, street = ?, city = ?, state = ?, zip = ?, phone_number = ?, email = ?
                    WHERE facility_id = ?
                ''', (name, title, company, street, city, state, zip_code, phone_number, email, facility_id))
            else:
                conn.execute('''
                    INSERT INTO responses (facility_id, name, title, company, street, city, state, zip, phone_number, email)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (facility_id, name, title, company, street, city, state, zip_code, phone_number, email))
            conn.commit()
            conn.close()
            flash('Facility information saved successfully.', 'success')
            return redirect(url_for('facility_detail', facility_id=facility_id))
        elif 'delete_facility' in request.form:
            conn = get_db_connection()
            conn.execute('DELETE FROM facilities WHERE id = ?', (facility_id,))
            conn.execute('DELETE FROM responses WHERE facility_id = ?', (facility_id,))
            conn.execute('DELETE FROM well_data WHERE facility_id = ?', (facility_id,))
            conn.commit()
            conn.close()
            flash('Facility deleted successfully.', 'success')
            return redirect(url_for('index'))
        elif 'import_csv' in request.form:
            # Implement CSV import functionality
            api_numbers = facility['api_numbers']
            if not api_numbers:
                flash('API numbers are required to import RBDMS Well Data.', 'error')
                return redirect(url_for('facility_detail', facility_id=facility_id))

            # Split the API numbers into a list
            api_numbers_list = [api.strip() for api in api_numbers.split(',') if api.strip()]

            # Download the CSV file
            csv_url = 'https://oklahoma.gov/content/dam/ok/en/occ/documents/og/ogdatafiles/rbdms-wells.csv'
            try:
                response_csv = requests.get(csv_url)
                response_csv.raise_for_status()
                csv_content = response_csv.content.decode('utf-8', errors='replace')
                csv_file = io.StringIO(csv_content)
                csv_reader = csv.DictReader(csv_file)
                csv_data = list(csv_reader)  # Read all rows into a list
            except Exception as e:
                flash(f'Error downloading or processing the CSV file: {e}', 'error')
                return redirect(url_for('facility_detail', facility_id=facility_id))

            imported_wells = []
            for api_number in api_numbers_list:
                matching_rows = [row for row in csv_data if row.get('API') == api_number]
                if len(matching_rows) == 0:
                    flash(f'No matching records found for API number: {api_number}', 'error')
                    continue
                elif len(matching_rows) > 1:
                    flash(f'Multiple records found for API number: {api_number}', 'error')
                    continue
                else:
                    well_info = matching_rows[0]
                    # Prepare data for import
                    imported_data = {'api_number': api_number}
                    for field in [
                        'WELL_NAME', 'WELL_NUM', 'OPERATOR',
                        'SH_LAT', 'SH_LON',
                        'COUNTY', 'SECTION', 'TOWNSHIP', 'RANGE',
                        'QTR2', 'QTR1'
                    ]:
                        value = well_info.get(field, '').strip()
                        if field in ['SH_LAT', 'SH_LON']:
                            try:
                                value = round(float(value), 5) if value else None
                            except ValueError:
                                value = None
                        elif field in ['WELL_NAME', 'OPERATOR', 'COUNTY']:
                            value = value.title() if value else None
                        else:
                            value = value if value else None
                        imported_data[field] = value

                    # Construct PLSS
                    section = imported_data.get('SECTION', '')
                    township = imported_data.get('TOWNSHIP', '')
                    range_ = imported_data.get('RANGE', '')
                    qtr2 = imported_data.get('QTR2', '')
                    qtr1 = imported_data.get('QTR1', '')
                    plss_parts = []
                    if section:
                        plss_parts.append(f"S{section}")
                    if township:
                        plss_parts.append(f"T{township}")
                    if range_:
                        plss_parts.append(f"R{range_}")
                    if qtr2 and qtr1:
                        plss_parts.append(f"{qtr2}{qtr1}")
                    elif qtr1:
                        plss_parts.append(f"{qtr1}")
                    plss = ' '.join(plss_parts) if plss_parts else None
                    imported_data['PLSS'] = plss

                    imported_wells.append(imported_data)

            if imported_wells:
                conn = get_db_connection()
                # Delete existing well data for this facility
                conn.execute('DELETE FROM well_data WHERE facility_id = ?', (facility_id,))
                # Insert new well data
                for well in imported_wells:
                    conn.execute('''
                        INSERT INTO well_data (
                            facility_id, api_number, WELL_NAME, WELL_NUM, OPERATOR,
                            SH_LAT, SH_LON,
                            COUNTY, SECTION, TOWNSHIP, RANGE, QTR2, QTR1, PLSS
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        facility_id,
                        well['api_number'],
                        well['WELL_NAME'],
                        well['WELL_NUM'],
                        well['OPERATOR'],
                        well['SH_LAT'],
                        well['SH_LON'],
                        well['COUNTY'],
                        well['SECTION'],
                        well['TOWNSHIP'],
                        well['RANGE'],
                        well['QTR2'],
                        well['QTR1'],
                        well['PLSS']
                    ))
                conn.commit()
                conn.close()
                flash('RBDMS Well Data imported successfully.', 'success')
                return redirect(url_for('facility_detail', facility_id=facility_id))
            else:
                flash('No well data was imported due to errors.', 'error')
                return redirect(url_for('facility_detail', facility_id=facility_id))

    # If no response exists, use default values for the form
    if not response:
        response = {
            'name': 'Ethan Boor',
            'title': 'Air Compliance Manager',
            'company': 'Camino Natural Resources LLC',
            'street': '1200 17th Street, Suite 2200',
            'city': 'Denver',
            'state': 'CO',
            'zip': '80202',
            'phone_number': '720-405-2609',
            'email': 'eboor@caminoresources.com'
        }

    # Render the facility detail template with the data
    return render_template('facility_detail.html', facility=facility, response=response, well_data_list=well_data_list)

@app.route('/add_facility', methods=['GET', 'POST'])
def add_facility():
    if request.method == 'POST':
        facility_name = request.form.get('facility_name', '').strip()
        api_numbers = request.form.get('api_numbers', '').strip()

        # Basic validation
        if not facility_name:
            flash('Facility Name is required.', 'error')
            return redirect(url_for('add_facility'))

        conn = get_db_connection()
        conn.execute('INSERT INTO facilities (facility_name, api_numbers) VALUES (?, ?)', (facility_name, api_numbers))
        facility_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.commit()
        conn.close()
        flash('Facility added successfully.', 'success')
        return redirect(url_for('facility_detail', facility_id=facility_id))
    return render_template('add_facility.html')

@app.route('/export/<int:facility_id>', methods=['GET'])
def export(facility_id):
    conn = get_db_connection()
    facility = conn.execute('SELECT * FROM facilities WHERE id = ?', (facility_id,)).fetchone()
    response = conn.execute('SELECT * FROM responses WHERE facility_id = ?', (facility_id,)).fetchone()
    well_data_rows = conn.execute('SELECT * FROM well_data WHERE facility_id = ?', (facility_id,)).fetchall()
    conn.close()

    if facility:
        content = f"""Facility ID: {facility['id']}
Facility Name: {facility['facility_name']}
API Numbers: {facility['api_numbers']}
Name: {response['name'] if response else ''}
Title: {response['title'] if response else ''}
Company: {response['company'] if response else ''}
Street: {response['street'] if response else ''}
City: {response['city'] if response else ''}
State: {response['state'] if response else ''}
Zip: {response['zip'] if response else ''}
Phone Number: {response['phone_number'] if response else ''}
Email: {response['email'] if response else ''}

RBDMS Well Data:
"""
        if well_data_rows:
            for well_data_row in well_data_rows:
                well_data = dict(well_data_row)
                content += f"\nAPI Number: {well_data['api_number']}\n"
                fields_to_include = [
                    'WELL_NAME', 'WELL_NUM', 'OPERATOR',
                    'SH_LAT', 'SH_LON',
                    'COUNTY', 'PLSS'
                ]
                for key in fields_to_include:
                    value = well_data.get(key, '')
                    content += f"{key.replace('_', ' ').title()}: {value}\n"
        else:
            content += "No RBDMS Well Data imported.\n"

        file_path = f'export_facility_{facility_id}.txt'
        with open(file_path, 'w') as f:
            f.write(content)
        return send_file(file_path, as_attachment=True)
    else:
        flash('No data to export.', 'error')
        return redirect(url_for('facility_detail', facility_id=facility_id))

if __name__ == '__main__':
    app.run(debug=True, port=5001)
