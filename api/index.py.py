import boto3
import json
import os
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, jsonify

# Create Flask application
app = Flask(__name__)

# Add date functions to Jinja environment
app.jinja_env.globals.update(date=date, now=datetime.now)

# Get AWS credentials from environment variables
aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
bucket_name = os.environ.get('AWS_BUCKET_NAME', 'canada-stay-tracker-data')

# Set up S3 client with environment variables
s3 = boto3.client(
    's3',
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_key
)

# Constants
DATA_FILE = 'canada_stays_data.json'
PR_DATE = os.environ.get('PR_DATE', '2024-05-30')  # Your PR date (May 30, 2024)

# Helper function to read data from S3
def get_data():
    try:
        response = s3.get_object(Bucket=bucket_name, Key=DATA_FILE)
        data = json.loads(response['Body'].read().decode('utf-8'))
        
        # Always override the PR settings with the hardcoded date
        data['pr_settings'] = {
            'pr_date': PR_DATE,
            'updated_at': datetime.now().strftime('%Y-%m-%d')
        }
            
        return data
    except s3.exceptions.NoSuchKey:
        # If file doesn't exist, create default structure with PR date
        default_data = {
            "stays": [],
            "pr_settings": {
                'pr_date': PR_DATE,
                'updated_at': datetime.now().strftime('%Y-%m-%d')
            }
        }
        save_data(default_data)
        return default_data

# Helper function to save data to S3
def save_data(data):
    s3.put_object(
        Bucket=bucket_name,
        Key=DATA_FILE,
        Body=json.dumps(data, default=str),
        ContentType='application/json'
    )

# Routes
@app.route('/')
def index():
    data = get_data()
    return render_template('index.html', stays=data['stays'])

@app.route('/add_stay', methods=['POST'])
def add_stay():
    data = get_data()
    
    # Generate new ID (max ID + 1)
    new_id = 1
    if data['stays']:
        new_id = max(stay['id'] for stay in data['stays']) + 1
    
    # Create new stay
    new_stay = {
        'id': new_id,
        'entry_date': request.form.get('entry_date'),
        'exit_date': request.form.get('exit_date') if request.form.get('exit_date') and request.form.get('exit_date').strip() else None,
        'notes': request.form.get('notes', '')
    }
    
    # Add to stays list
    data['stays'].append(new_stay)
    
    # Save updated data
    save_data(data)
    
    return redirect(url_for('index'))

@app.route('/update_stay/<int:stay_id>', methods=['POST'])
def update_stay(stay_id):
    data = get_data()
    
    # Find the stay to update
    for stay in data['stays']:
        if stay['id'] == stay_id:
            stay['entry_date'] = request.form.get('entry_date')
            stay['exit_date'] = request.form.get('exit_date') if request.form.get('exit_date') and request.form.get('exit_date').strip() else None
            stay['notes'] = request.form.get('notes', '')
            break
    
    # Save updated data
    save_data(data)
    
    return redirect(url_for('index'))

@app.route('/delete_stay/<int:stay_id>', methods=['POST'])
def delete_stay(stay_id):
    data = get_data()
    
    # Remove the stay with the matching ID
    data['stays'] = [stay for stay in data['stays'] if stay['id'] != stay_id]
    
    # Save updated data
    save_data(data)
    
    return redirect(url_for('index'))

@app.route('/pr_settings', methods=['GET'])
def pr_settings():
    data = get_data()
    
    # Only GET request - show the PR settings form with non-editable date
    pr_date = data['pr_settings']['pr_date']
    return render_template('pr_settings.html', pr_date=pr_date)

@app.route('/stats')
def stats():
    data = get_data()
    stays = data['stays']
    total_days = 0
    
    for stay in stays:
        entry_date = datetime.strptime(stay['entry_date'], '%Y-%m-%d')
        
        if stay['exit_date']:  # If there's an exit date
            exit_date = datetime.strptime(stay['exit_date'], '%Y-%m-%d')
        else:
            # If no exit date, assume it's ongoing until today
            exit_date = datetime.now()
        
        # Calculate days for this stay (+1 to include both entry and exit days)
        days = (exit_date - entry_date).days + 1
        total_days += max(0, days)  # Ensure no negative days
    
    # Get PR-related stats
    pr_date = data['pr_settings']['pr_date']
    pr_stats = calculate_pr_stats(pr_date, stays)
    
    return render_template('stats.html', stays=stays, total_days=total_days, pr_date=pr_date, pr_stats=pr_stats)

def calculate_pr_stats(pr_date, stays):
    pr_date_obj = datetime.strptime(pr_date, '%Y-%m-%d')
    today = datetime.now()
    
    # Calculate the 5-year period for PR renewal
    five_years_from_pr = pr_date_obj + timedelta(days=5*365)
    
    # Calculate days spent in Canada within the 5-year PR period
    days_in_five_year_period = 0
    eligible_days_needed = 730  # 2 years (730 days) required for PR renewal
    
    for stay in stays:
        entry_date = datetime.strptime(stay['entry_date'], '%Y-%m-%d')
        
        if stay['exit_date']:  # If there's an exit date
            exit_date = datetime.strptime(stay['exit_date'], '%Y-%m-%d')
        else:
            # If no exit date, assume it's ongoing until today
            exit_date = today
        
        # Skip stays entirely before PR date
        if exit_date < pr_date_obj:
            continue
        
        # Adjust entry date if before PR date
        if entry_date < pr_date_obj:
            entry_date = pr_date_obj
        
        # Adjust exit date if after 5-year period
        if exit_date > five_years_from_pr:
            exit_date = five_years_from_pr
        
        # Calculate days for this stay that fall within the 5-year period
        if entry_date <= exit_date:  # Only count if entry is before or equal to exit
            days = (exit_date - entry_date).days + 1
            days_in_five_year_period += max(0, days)
    
    # Calculate days remaining for eligibility
    days_remaining = max(0, eligible_days_needed - days_in_five_year_period)
    
    # Calculate percentage toward the 2-year requirement
    percentage = min(100, (days_in_five_year_period / eligible_days_needed) * 100)
    
    # Calculate days left in the 5-year period
    days_left_in_period = max(0, (five_years_from_pr - today).days)
    
    return {
        'five_year_end_date': five_years_from_pr.strftime('%Y-%m-%d'),
        'days_in_period': days_in_five_year_period,
        'days_needed': eligible_days_needed,
        'days_remaining': days_remaining,
        'percentage': percentage,
        'days_left_in_period': days_left_in_period
    }