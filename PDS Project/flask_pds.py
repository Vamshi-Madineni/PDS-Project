# Import necessary libraries
from flask import Flask, render_template, request, redirect, url_for, session
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired
import mysql.connector
import matplotlib.pyplot as plt
from io import BytesIO
import base64

is_root = False

class AddCustomerForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    billing_address = StringField('Billing Address', validators=[DataRequired()])
    submit = SubmitField('Add Customer')

# Initialize Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static'
app.secret_key = 'your_secret_key'

# Route for the home page
@app.route('/')
def home():
    return render_template('home.html')

# MySQL configurations
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',  # or 'your_mysql_password' if you have one
    'database': 'shems',
}


# Function to create a MySQL connection
def get_db_connection():
    return mysql.connector.connect(**db_config)

# Route for listing customers
@app.route('/customers')
def customers():
    # Check if the user is logged in
    if session['user_id'] != 12:
        return redirect(url_for('login'))

    # Fetch customers from the database
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Customer")
    customers = cursor.fetchall()
    connection.close()

    return render_template('customers.html', customers=customers)


# Route for the login page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        customer_id = request.form['customer_id']
        password = request.form['password']

        # Check if the customer ID and password are valid
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM Customer WHERE CustomerID = %s AND Password = %s", (customer_id, password))
        user = cursor.fetchone()
        is_root = False
        # Determine if the user is root
        if user:
            is_root = (user['CustomerID'] == 12)  # Replace 12 with the root user ID
            
        connection.close()

        if user:
            # Store user information in the session
            session['user_id'] = user['CustomerID']
            session['is_root'] = is_root

            # Remove the error from the session (if exists)
            session.pop('error', None)

            # Redirect to the dashboard after successful login
            return redirect(url_for('dashboard'))
        else:
            # Store an error in the session
            session['error'] = "Invalid customer ID or password. Please try again."

    # Pass the error to the template if it exists
    error = session.pop('error', None)

    return render_template('login.html', error=error)


# Route for the dashboard
@app.route('/dashboard')
def dashboard():
    # Check if the user is logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    return render_template('dashboard.html')

# Route for managing service locations
@app.route('/service_locations', methods=['GET', 'POST'])
def service_locations():
    # Check if the user is logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    customer_id = session['user_id']

    if request.method == 'POST':
        # Handle form submission for adding/editing service locations
        location_id = request.form.get('location_id')
        street_address = request.form['street_address']
        zip_code = request.form['zip_code']

        connection = get_db_connection()
        cursor = connection.cursor()

        if location_id:
            # Edit existing service location
            cursor.execute("UPDATE ServiceLocation SET StreetAddress = %s, ZipCode = %s WHERE LocationID = %s AND CustomerID = %s",
                           (street_address, zip_code, location_id, customer_id))
        else:
            # Add new service location
            cursor.execute("INSERT INTO ServiceLocation (StreetAddress, ZipCode, CustomerID) VALUES (%s, %s, %s)",
                           (street_address, zip_code, customer_id))

        connection.commit()
        connection.close()

    # Fetch and display existing service locations
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT LocationID, StreetAddress, ZipCode FROM ServiceLocation WHERE CustomerID = %s", (customer_id,))
    service_locations = cursor.fetchall()
    connection.close()

    return render_template('service_locations.html', service_locations=service_locations)

# Route for removing a service location
@app.route('/remove_location/<int:location_id>')
def remove_location(location_id):
    # Delete the service location from the database
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM ServiceLocation WHERE LocationID = %s", (location_id,))
    connection.commit()
    connection.close()

    return redirect(url_for('service_locations'))

@app.route('/energy_cost_graph', methods=['GET', 'POST'])
def energy_cost_graph():
    if request.method == 'POST':
        year = request.form['year']

        # Perform the database query to get energy cost data
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT SL.LocationID, SUM(EC.EnergyConsumed * EP.PricePerKwh) AS TotalEnergyCost
            FROM ServiceLocation SL
            JOIN SmartDevice SD ON SL.LocationID = SD.LocationID
            JOIN EnergyConsumption EC ON SD.DeviceID = EC.DeviceID
            JOIN EnergyPrice EP ON SL.ZipCode = EP.ZipCode
            AND EP.TimeStamp = (
                SELECT MAX(TimeStamp) FROM EnergyPrice
                WHERE ZipCode = SL.ZipCode AND TimeStamp <= EC.TimeStamp
            )
            JOIN Customer C ON SL.CustomerID = C.CustomerID
            WHERE YEAR(EC.TimeStamp) = %s AND C.CustomerID = %s
            GROUP BY SL.LocationID
        """
        try:
            cursor.execute(query, (year, session['user_id']))
            data = cursor.fetchall()

            if not data:
                # No data available for the selected year
                return render_template('energy_cost_graph.html', year=year, image_base64=None)

            location_ids = [int(row['LocationID']) for row in data]
            total_costs = [row['TotalEnergyCost'] for row in data]

            # Plotting
            plt.switch_backend('Agg')  # Set the backend to Agg
            plt.bar(location_ids, total_costs, align='center', alpha=0.7)
            plt.xlabel('Location ID')
            plt.ylabel('Total Energy Cost')
            plt.title(f'Total Energy Cost per Location in {year}')
            plt.xticks(location_ids, [str(int(loc)) for loc in location_ids]) 

            # Save the plot to a BytesIO object
            image_stream = BytesIO()
            plt.savefig(image_stream, format='png')
            image_stream.seek(0)

            # Convert the image to base64 for embedding in HTML
            image_base64 = base64.b64encode(image_stream.read()).decode('utf-8')

            # Pass the base64 encoded image to the HTML template
            return render_template('energy_cost_graph.html', year=year, image_base64=image_base64)

        except Exception as e:
            # Handle the exception, you might want to log it or render an error template
            print(f"Error: {e}")
            return render_template('error.html')

        finally:
            connection.close()

    # Render the form when the request method is GET
    return render_template('energy_cost_form.html')


# Route for most used device type on input date
@app.route('/most_used_device_type', methods=['GET', 'POST'])
def most_used_device_type():
    if request.method == 'POST':
        input_date = request.form['input_date']

        # Perform the database query to get most used device type data
        connection = get_db_connection()  # Replace with your actual function
        cursor = connection.cursor()
        query = """
            SELECT DeviceType, SUM(EnergyConsumed) AS TotalEnergyConsumption
            FROM EnergyConsumption
            NATURAL JOIN SmartDevice
            NATURAL JOIN ServiceLocation
            WHERE CustomerID = %s AND DATE(TimeStamp) = %s
            GROUP BY DeviceType
            ORDER BY TotalEnergyConsumption DESC
            LIMIT 1
        """
        try:
            cursor.execute(query, (session['user_id'], input_date))
            data = cursor.fetchone()

            if not data:
                # No data available for the selected date
                return render_template('most_used_device_type.html', input_date=input_date, device_type=None)

            device_type, total_energy_consumption = data

            return render_template('most_used_device_type.html', input_date=input_date, device_type=device_type)

        except Exception as e:
            # Handle the exception, you might want to log it or render an error template
            print(f"Error: {e}")
            return render_template('error.html')

        finally:
            connection.close()

    # Render the form when the request method is GET
    return render_template('most_used_device_type_form.html')

@app.route('/energy_consumption_graph', methods=['GET', 'POST'])
def energy_consumption_graph():
    if request.method == 'POST':
        year = request.form['year']

        # Perform the database query to get energy consumption data
        connection = get_db_connection()  # Replace with your actual function
        cursor = connection.cursor()
        query = """
            SELECT MONTH(TimeStamp) AS Month, SUM(EnergyConsumed) AS TotalConsumption
            FROM EnergyConsumption NATURAL JOIN SmartDevice NATURAL JOIN ServiceLocation
            WHERE YEAR(TimeStamp) = %s AND CustomerID = %s
            GROUP BY MONTH(TimeStamp)
        """
        try:
            cursor.execute(query, (year, session['user_id']))
            data = cursor.fetchall()

            if not data:
                # No data available for the selected year
                return render_template('energy_consumption_graph.html', year=year, image_base64=None)

            months = [row[0] for row in data]
            consumption = [row[1] for row in data]
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

            # Plotting
            plt.switch_backend('Agg')  # Set the backend to Agg
            plt.bar(months, consumption, align='center')  # Add align='center' to align bars with the center of the ticks
            plt.xlabel('Month')
            plt.ylabel('Energy Consumption')
            plt.title(f'Energy Consumption per Month in {year}')
            plt.xticks(range(1, 13), month_names)
            plt.ylim(0, 500)

            # Save the plot to a BytesIO object
            image_stream = BytesIO()
            plt.savefig(image_stream, format='png')
            image_stream.seek(0)

            # Convert the image to base64 for embedding in HTML
            image_base64 = base64.b64encode(image_stream.read()).decode('utf-8')

            # Pass the base64 encoded image to the HTML template
            return render_template('energy_consumption_graph.html', year=year, image_base64=image_base64)

        except Exception as e:
            # Handle the exception, you might want to log it or render an error template
            print(f"Error: {e}")
            return render_template('error.html')

        finally:
            connection.close()

    # Render the form when the request method is GET
    return render_template('energy_consumption_form.html')





# Route for modifying customer password
@app.route('/modify_password', methods=['GET', 'POST'])
def modify_password():
    # Check if the user is logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        new_password = request.form['new_password']
        customer_id = session['user_id']

        # Update the customer's password in the database
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("UPDATE Customer SET Password = %s WHERE CustomerID = %s", (new_password, customer_id))
        connection.commit()
        connection.close()

        # Redirect to a success page or the dashboard
        return redirect(url_for('dashboard'))

    return render_template('modify_password.html')


# Route for adding a new customer
@app.route('/add_customer', methods=['GET', 'POST'])
def add_customer():
    # Check if the user is logged in
    if session['user_id'] != 12:
        return redirect(url_for('login'))

    form = AddCustomerForm()

    if form.validate_on_submit():
        first_name = form.first_name.data
        last_name = form.last_name.data
        billing_address = form.billing_address.data
        password = "default_password"
        # Insert the new customer into the database
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("INSERT INTO Customer (FirstName, LastName, BillingAddress,Password) VALUES (%s, %s, %s, %s)",
                       (first_name, last_name, billing_address,password))
        connection.commit()
        connection.close()

        return redirect(url_for('customers'))

    return render_template('add_customer.html', form=form)


# Route for removing a customer
@app.route('/remove_customer/<int:customer_id>')
def remove_customer(customer_id):
    # Delete the customer from the database
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM Customer WHERE CustomerID = %s", (customer_id,))
    connection.commit()
    connection.close()

    return redirect(url_for('customers'))


# Route for energy consumption
@app.route('/energy_consumption')
def energy_consumption():
    # Check if the user is logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Fetch energy consumption data from the database based on the user's session ID
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    # Assuming 'user_id' in the session represents CustomerID
    customer_id = session['user_id']
    
    # Adjust the query to include the customer ID
    query = """
        SELECT SD.DeviceType, AVG(EC.EnergyConsumed) AS AverageEnergyConsumption
        FROM SmartDevice SD
        JOIN EnergyConsumption EC ON SD.DeviceID = EC.DeviceID
        JOIN ServiceLocation SL ON SD.LocationID = SL.LocationID
        JOIN Customer C ON C.CustomerID = SL.CustomerID
        WHERE C.CustomerID = %s AND EC.EnergyConsumed > 0
        GROUP BY SD.DeviceType;
    """
    cursor.execute(query, (customer_id,))
    energy_data = cursor.fetchall()
    connection.close()

    return render_template('energy_consumption.html', energy_data=energy_data)


# Route for adding a new smart device
@app.route('/add_device', methods=['GET', 'POST'])
def add_device():
    # Check if the user is root
    if 'user_id' not in session:
        return redirect(url_for('login'))

    location_id = None  # Initialize location_id
    error_message = None
    if request.method == 'POST':
        device_type = request.form['device_type']
        model_number = request.form['model_number']
        street_address = request.form['street_address']
        zip_code = request.form['zip_code']

        # Fetch LocationID and CustomerID based on StreetAddress and ZipCode
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT LocationID, CustomerID FROM ServiceLocation WHERE StreetAddress = %s AND ZipCode = %s",
                       (street_address, zip_code))
        result = cursor.fetchone()
        location_id = result['LocationID'] if result else None
        customer_id = result['CustomerID'] if result else None
        connection.close()

        if location_id is not None and customer_id == session['user_id']:
            # Insert the new smart device into the database
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute("INSERT INTO SmartDevice (DeviceType, ModelNumber, LocationID) VALUES (%s, %s, %s)",
                           (device_type, model_number, location_id))
            connection.commit()
            connection.close()

            return redirect(url_for('add_device'))
        else:
            error_message = "You don't have this service location registered with us. Please check your Street Address and Zip Code."
    # Fetch device types and model numbers for the form
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT DISTINCT DeviceType FROM SmartDevice")
    device_types = cursor.fetchall()

    models_by_type = {}
    for device_type in device_types:
        cursor.execute("SELECT DISTINCT ModelNumber FROM SmartDevice WHERE DeviceType = %s", (device_type['DeviceType'],))
        model_numbers = cursor.fetchall()
        models_by_type[device_type['DeviceType']] = model_numbers

    cursor.execute("SELECT DISTINCT StreetAddress, ZipCode FROM ServiceLocation")
    locations = cursor.fetchall()

    connection.close()

    return render_template('add_device.html', device_types=device_types, models_by_type=models_by_type, locations=locations, CustomerID=session['user_id'], location_id=location_id, error_message=error_message)

# Route for logging out
@app.route('/logout')
def logout():
    # Clear the user session
    session.pop('user_id', None)
    is_root = False
    return redirect(url_for('login'))


# Similar routes and functions can be added for ServiceLocation and SmartDevice

if __name__ == '__main__':
    app.run(debug=True)
