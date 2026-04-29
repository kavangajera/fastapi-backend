#!/usr/bin/env python3
import requests
import json
import random
import string
import urllib3

# Disable SSL warnings for localhost
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = 'https://localhost:8443'

# Helper functions
def generate_random_string(length=4):
    return ''.join(random.choices(string.digits, k=length))

def generate_password():
    return ''.join(random.choices(string.digits, k=10))

def make_request(method, endpoint, data=None, token=None):
    url = f'{BASE_URL}{endpoint}'
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    
    try:
        if method == 'POST':
            response = requests.post(url, json=data, headers=headers, verify=False, timeout=10)
        else:
            response = requests.get(url, headers=headers, verify=False, timeout=10)
        
        result = response.json()
        return result
    except Exception as e:
        return {'error': str(e), 'status_code': 0}

# Test connectivity
print('Testing connectivity to localhost:8443...')
try:
    requests.get(f'{BASE_URL}/docs', verify=False, timeout=5)
    print('✓ Backend is reachable\n')
except Exception as e:
    print(f'✗ Backend unreachable: {e}')
    exit(1)

# Data structures to track created items
owners = []
pharmacies_by_owner = []
technicians_by_pharmacy = []

print('=== Creating Pharmacy Owners ===\n')
for i in range(2):
    rand = generate_random_string(4)
    owner_email = f'DemoOwner{rand}@example.com'
    owner_password = generate_password()
    
    # Sign up
    signup_response = make_request('POST', '/user/signup', {
        'user_email': owner_email,
        'input_password': owner_password
    })
    
    if signup_response.get('status_code', 0) < 400:
        print(f'✓ Signed up: {owner_email}')
        
        # Login
        login_response = make_request('POST', '/user/login', {
            'user_email': owner_email,
            'input_password': owner_password
        })
        
        if login_response.get('status_code', 0) < 400 and login_response.get('data'):
            token = login_response['data'].get('access_token')
            owner_id = login_response['data'].get('id')
            
            owner_record = {
                'owner_id': owner_id,
                'email': owner_email,
                'password': owner_password,
                'pharmacies': []
            }
            owners.append(owner_record)
            print(f'✓ Logged in: {owner_email}\n')
            
            # Create 3 pharmacies for this owner
            print(f'  Creating pharmacies for {owner_email}...')
            for j in range(3):
                pharmacy_code = f'PHM{rand}{j}'
                pharmacy_data = {
                    'pharmacy_title': f'Pharmacy {rand}-{j+1}',
                    'pharmacy_code': pharmacy_code,
                    'address': {
                        'address_line_1': f'{100+j} Main Street',
                        'address_line_2': f'Suite {200+j}',
                        'city': 'Demo City',
                        'state': 'DC',
                        'zip_code': f'{10000+j}'
                    }
                }
                
                pharm_response = make_request('POST', '/pharmacy/create-pharmacy', pharmacy_data, token)
                
                if pharm_response.get('status_code', 0) < 400 and pharm_response.get('data'):
                    pharmacy_id = pharm_response.get('data', {}).get('id')
                    pharmacy_record = {
                        'pharmacy_id': pharmacy_id,
                        'owner_email': owner_email,
                        'code': pharmacy_code,
                        'title': pharmacy_data['pharmacy_title'],
                        'address': pharmacy_data['address'],
                        'technicians': []
                    }
                    owner_record['pharmacies'].append(pharmacy_record)
                    pharmacies_by_owner.append(pharmacy_record)
                    print(f'    ✓ Created pharmacy: {pharmacy_code}')
                    
                    # Create 2 technicians for this pharmacy
                    for k in range(2):
                        tech_rand = generate_random_string(4)
                        tech_name = f'Tech{tech_rand}'
                        tech_email = f'tech{tech_rand}@example.com'
                        tech_password = generate_password()
                        
                        tech_data = {
                            'user_name': tech_name,
                            'user_email': tech_email,
                            'input_password': tech_password,
                            'contact': f'555-{1000+k}{j}{i}',
                            'pharmacy_id': pharmacy_id
                        }
                        
                        tech_response = make_request('POST', '/user/create-technician', tech_data, token)
                        
                        if tech_response.get('status_code', 0) < 400 and tech_response.get('data'):
                            technician_record = {
                                'technician_id': tech_response.get('data', {}).get('id'),
                                'name': tech_name,
                                'email': tech_email,
                                'pharmacy_code': pharmacy_code,
                                'contact': tech_data['contact']
                            }
                            pharmacy_record['technicians'].append(technician_record)
                            technicians_by_pharmacy.append(technician_record)
                            print(f'      ✓ Created technician: {tech_email}')
                        else:
                            print(f'      ✗ Failed to create technician: {tech_response.get("message", "Unknown error")}')
                else:
                    print(f'    ✗ Failed to create pharmacy: {pharm_response.get("message", "Unknown error")}')
            print()
        else:
            print(f'✗ Failed to login: {login_response.get("message", "Unknown error")}\n')
    else:
        print(f'✗ Failed to sign up: {signup_response.get("message", "Unknown error")}\n')

# Print summary
print('\n=== SEEDING COMPLETE ===\n')
summary = {
    'status': 'success',
    'owners_created': len(owners),
    'pharmacies_created': len(pharmacies_by_owner),
    'technicians_created': len(technicians_by_pharmacy),
    'owners': [
        {
            'email': owner['email'],
            'password': owner['password'],
            'pharmacies_count': len(owner['pharmacies']),
            'pharmacies': [
                {
                    'code': p['code'],
                    'title': p['title'],
                    'address': p['address'],
                    'technicians_count': len(p['technicians']),
                    'technicians': [
                        {
                            'name': t['name'],
                            'email': t['email'],
                            'contact': t['contact']
                        }
                        for t in p['technicians']
                    ]
                }
                for p in owner['pharmacies']
            ]
        }
        for owner in owners
    ]
}

print(json.dumps(summary, indent=2))


# Here are the pharmacy owner credentials I set:

# 1. **Email:** `DemoOwner43256@example.com`  
#    **Password:** `148162`

# 2. **Email:** `DemoOwner89907@example.com`  
#    **Password:** `950826`