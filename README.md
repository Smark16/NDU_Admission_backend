# NDU Admission Portal

A comprehensive Django-based admission management system for Niger Delta University (NDU) with multi-campus support, role-based access control, and audit logging.

## Features

### Core Functionality
- **Multi-campus Support**: Manage multiple campuses with campus-specific data access
- **Role-based Access Control**: Super Admin, Admin, Admission Officer, Finance Officer, and Applicant roles
- **Batch Management**: Create and manage admission batches with different application periods
- **Application Processing**: Complete application lifecycle from submission to enrollment
- **Document Management**: Upload and manage application documents (O-Level, A-Level, qualifications, passport photos)
- **Academic Results**: Structured entry for O-Level (credits) and A-Level (numerical) results per Ugandan NHCE standards
- **Payment Integration**: Mobile money payment system for application fees
- **Audit Logging**: Complete audit trail for all user actions and system activities

### User Roles & Permissions
- **Super Admin**: Full system access, can manage all campuses and users
- **Admin**: Campus-specific management, user creation, application review
- **Admission Officer**: Application review and evaluation
- **Finance Officer**: Payment processing and financial oversight
- **Applicant**: Application submission, document upload, payment

### Technical Features
- **Non-repudiation**: Complete audit trails for all actions
- **Campus Isolation**: Users can only access data from their assigned campuses
- **File Management**: Local storage for documents and profile pictures
- **Responsive Design**: Modern, sleek UI that works on all devices
- **Modular Architecture**: Clean, maintainable code structure

## Installation

### Prerequisites
- Python 3.8+
- PostgreSQL 12+
- pip

### Setup Instructions

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd ndu-application-admission-portal
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration**
   ```bash
   cp .env.example .env
   # Edit .env with your database and email settings
   ```

5. **Database Setup**
   ```bash
   # Create PostgreSQL database
   createdb ndu_portal
   
   # Run migrations
   python manage.py makemigrations
   python manage.py migrate
   ```

6. **Create Initial Data**
   ```bash
   python manage.py setup_initial_data
   ```

7. **Create Superuser** (if not created by setup command)
   ```bash
   python manage.py createsuperuser
   ```

8. **Run Development Server**
   ```bash
   python manage.py runserver
   ```

9. **Access the Application**
   - Open http://127.0.0.1:8000 in your browser
   - Login with: username: `admin`, password: `admin123`

## Project Structure

```
ndu_portal/
├── accounts/                 # User management and authentication
│   ├── models.py            # Custom User model with campus assignment
│   ├── views.py             # Authentication and user management views
│   ├── forms.py             # User-related forms
│   └── admin.py             # Admin interface for users
├── admissions/              # Core admission functionality
│   ├── models.py            # Application, Program, Batch models
│   ├── views.py             # Application processing views
│   ├── forms.py             # Application and review forms
│   └── admin.py             # Admin interface for admissions
├── payments/                # Payment processing
│   ├── models.py            # Payment and mobile money models
│   └── views.py             # Payment processing views
├── audit/                   # Audit logging system
│   ├── models.py            # Audit log models
│   ├── middleware.py        # Audit middleware
│   └── views.py             # Audit log viewing
├── templates/               # HTML templates
│   ├── base.html           # Base template with sidebar
│   ├── accounts/           # Authentication templates
│   └── admissions/         # Application templates
├── static/                  # Static files
│   ├── css/style.css       # Custom styling
│   └── js/main.js          # JavaScript functionality
└── manage.py               # Django management script
```

## Configuration

### Database Settings
Update `settings.py` or `.env` file with your PostgreSQL credentials:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'ndu_portal',
        'USER': 'your_username',
        'PASSWORD': 'your_password',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

### Email Configuration
Configure SMTP settings for email notifications:
```python
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-email@gmail.com'
EMAIL_HOST_PASSWORD = 'your-app-password'
```

### Mobile Money Integration
Configure mobile money API settings:
```python
MOBILE_MONEY_API_URL = 'https://api.mobilemoney.com'
MOBILE_MONEY_API_KEY = 'your-api-key'
```

## Usage

### For Super Admins
1. **Campus Management**: Create and manage campuses
2. **User Management**: Create users and assign roles/campuses
3. **System Settings**: Configure site name and logo
4. **Audit Monitoring**: View all system activities and logs

### For Campus Admins
1. **User Management**: Create users for their campus
2. **Application Review**: Review and approve/reject applications
3. **Batch Management**: Create admission batches
4. **Document Downloads**: Download applicant profiles and documents

### For Admission Officers
1. **Application Review**: Evaluate applications
2. **Status Updates**: Update application status
3. **Document Verification**: Review uploaded documents

### For Finance Officers
1. **Payment Processing**: Handle payment-related issues
2. **Financial Reports**: View payment statistics

### For Applicants
1. **Account Creation**: Register and create profile
2. **Application Submission**: Complete application forms
3. **Document Upload**: Upload required documents
4. **Payment**: Pay application fees via mobile money
5. **Status Tracking**: Monitor application progress

## API Endpoints

### Authentication
- `POST /accounts/login/` - User login
- `POST /accounts/logout/` - User logout
- `POST /accounts/register/` - User registration

### Applications
- `GET /admissions/applications/` - List applications
- `POST /admissions/applications/create/` - Create application
- `GET /admissions/applications/{id}/` - View application details
- `POST /admissions/applications/{id}/submit/` - Submit application

### Payments
- `POST /payments/initiate/{application_id}/` - Initiate payment
- `GET /payments/status/{payment_id}/` - Check payment status
- `POST /payments/webhook/` - Payment webhook

## Security Features

- **CSRF Protection**: All forms protected against CSRF attacks
- **SQL Injection Prevention**: Django ORM prevents SQL injection
- **XSS Protection**: Template auto-escaping prevents XSS
- **File Upload Security**: File type and size validation
- **Audit Logging**: Complete activity tracking
- **Role-based Access**: Granular permission system

## Deployment

### Production Settings
1. Set `DEBUG = False` in settings
2. Configure proper database credentials
3. Set up static file serving
4. Configure email settings
5. Set up SSL/HTTPS
6. Configure proper logging

### Docker Deployment (Optional)
```dockerfile
FROM python:3.9
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions, please contact the development team or create an issue in the repository.

## Changelog

### Version 1.0.0
- Initial release
- Multi-campus support
- Role-based access control
- Complete application lifecycle
- Mobile money integration
- Audit logging system
- Responsive UI design


















