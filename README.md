# FastAPI Backend - Queue RX

A production-ready FastAPI backend with SQLAlchemy ORM, Alembic migrations, and PostgreSQL database support.

## Clone this repo :-
```
git clone ...repo.git
```
asks for username:
password:
For password visit https://gist.github.com/kavangajera/ed0a632c27f6076e9854c6231ebe2b8a

## Table of Contents

- [Project Structure](#project-structure)
- [Setup & Installation](#setup--installation)
- [Database & Migrations](#database--migrations)
- [Running the Application](#running-the-application)
- [Project Architecture](#project-architecture)
- [API Documentation](#api-documentation)
- [Best Practices](#best-practices)
- [Deployment](#deployment)

---

## Project Structure

```
fastapi-backend/
├── alembic/                    # Database migration files
│   ├── versions/              # Migration version files
│   └── env.py                 # Alembic environment configuration
├── core/                      # Core application configuration
│   ├── config.py             # Environment settings using Pydantic
│   └── database.py           # Database connection and session management
├── models/                    # SQLAlchemy ORM models
│   ├── __init__.py           # Model imports (IMPORTANT for Alembic)
│   ├── user.py
│   ├── doctor.py
│   ├── patient.py
│   └── ...
├── routes/                    # API route handlers
│   ├── auth_routes.py
│   ├── user_routes.py
│   └── ...
├── schemas/                   # Pydantic schemas for request/response validation / DTOs
│   ├── user_schema.py
│   └── ...
├── services/                  # Business logic layer
│   ├── auth_service.py
│   └── ...
├── middlewares/              # Custom middleware
│   ├── auth_middleware.py
│   └── ...
├── public/                   # Static files
├── main.py                   # Application entry point
├── alembic.ini              # Alembic configuration
├── pyproject.toml           # Project dependencies (uv format)
├── requirements.txt         # Compiled dependencies (pip format)
└── .env                     # Environment variables
```

---

## Setup & Installation

### Option 1: Using `uv` (Recommended)

[uv](https://docs.astral.sh/uv/) is a fast Python package manager that automatically manages virtual environments.

#### Install uv

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or using pip
pip install uv
```

#### Install Dependencies

```bash
# uv automatically creates .venv and installs dependencies
uv sync
```

#### Activate Virtual Environment

```bash
# macOS/Linux
    source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

#### Add New Dependencies

```bash
# Add a new package (automatically updates pyproject.toml and installs)
uv add package-name

# Example
uv add pyjwt
```

#### Compile pyproject.toml to requirements.txt

```bash
# Generate requirements.txt from pyproject.toml
uv pip compile pyproject.toml -o requirements.txt

# Or use pip-tools
pip install pip-tools
pip-compile pyproject.toml -o requirements.txt
```

### Option 2: Using `pip`

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

---

## Database & Migrations

### Database Configuration

Configure your database connection in `.env`:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
FRONTEND_URL=http://localhost:3000
ENV=development
```

### Core Database Setup

**`core/database.py`** - Database connection and session management:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from core.config import settings

# Create database engine
engine = create_engine(settings.DATABASE_URL)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Dependency for route handlers
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**`core/config.py`** - Environment configuration using Pydantic:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    FRONTEND_URL: str
    ENV: str = "development"
    DATABASE_URL: str

    class Config:
        env_file = ".env"

settings = Settings()
```

### Alembic Setup & Commands

#### 1. Initialize Alembic (Already Done)

```bash
alembic init alembic
```

#### 2. Configure Alembic Environment

**IMPORTANT**: `alembic/env.py` must import all models for autogenerate to work:

```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from core.database import Base
from alembic import context

# ⚠️ CRITICAL: Import all models here
from models import *  # This imports all models from models/__init__.py

config = context.config
target_metadata = Base.metadata  # Alembic uses this for autogenerate
```

**Why this matters**: Alembic's `--autogenerate` feature compares `Base.metadata` with the database schema. If models aren't imported, they won't be detected, and migrations won't be generated.

#### 3. Create Migration

```bash
# Generate migration automatically by detecting model changes
alembic revision --autogenerate -m "initial migration"

# Or create empty migration manually
alembic revision -m "add custom index"
```

#### 4. Apply Migrations

```bash
# Upgrade to latest version
alembic upgrade head

# Upgrade to specific version
alembic upgrade +1  # Next version
alembic upgrade ae1027a6acf  # Specific revision

# Downgrade
alembic downgrade -1  # Previous version
alembic downgrade base  # Rollback all
```

#### 5. View Migration History

```bash
# Show current version
alembic current

# Show migration history
alembic history

# Show pending migrations
alembic history --verbose
```

### Models Organization

**`models/__init__.py`** - Centralized model imports:

```python
from .user import User
from .doctor import Doctor
from .patient import Patient
from .device import Device
from .refresh_token import RefreshToken
from .appointment import Appointment
from .doctor_slot import DoctorSlot
from .payment import Payment
from .doctor_availability import DoctorAvailability
from .password_reset_token import PasswordResetToken
```

**Why this matters**: 
- Alembic imports `from models import *` to detect all models
- Provides clean imports: `from models import User, Doctor`
- Single source of truth for all models

---

## Running the Application

### Development Server

```bash
# Using uvicorn directly
uvicorn main:app --host 0.0.0.0 --port 8443

# With auto-reload (watches for file changes)
uvicorn main:app --host 0.0.0.0 --port 8443 --reload

# Using uv
uv run main.py

# Using Python directly (if main.py has uvicorn.run)
python main.py
```

### Important Notes on `--reload`

⚠️ **Issue with `--reload` flag**: When using `--reload`, the server creates a subprocess that can be difficult to kill. You may need to:

```bash
# Find and kill the process
lsof -i :8000
kill -9 <PID>

# Or use pkill
pkill -f "uvicorn main:app"
```

**Recommendation**: Use `--reload` only during active development. For production or when you don't need hot-reloading, omit the flag.

### Access Points

- **API Root**: http://127.0.0.1:8000/
- **Swagger Docs**: http://127.0.0.1:8000/docs
- **ReDoc**: http://127.0.0.1:8000/redoc

---

## Project Architecture

### 1. Routes (API Endpoints)

Routes define your API endpoints and handle HTTP requests.

**Example: `routes/user_routes.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.database import get_db
from schemas.user_schema import UserCreate, UserResponse
from services.user_service import create_user, get_user_by_id

router = APIRouter(
    prefix="/users",
    tags=["Users"]  # Groups endpoints in Swagger UI
)

@router.post("/", response_model=UserResponse, status_code=201)
async def register_user(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new user account.
    
    - **email**: Valid email address
    - **password**: Minimum 8 characters
    - **name**: Full name
    """
    return create_user(db, user_data)

@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: Session = Depends(get_db)
):
    """Retrieve user by ID"""
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
```

**Include routes in `main.py`:**

```python
from fastapi import FastAPI
from routes import user_routes, auth_routes, appointment_routes

app = FastAPI()

# Include routers
app.include_router(user_routes.router)
app.include_router(auth_routes.router)
app.include_router(appointment_routes.router)
```

### 2. Schemas (Pydantic Models)

Schemas validate request/response data and provide automatic documentation.

**Example: `schemas/user_schema.py`**

```python
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100)

class UserResponse(UserBase):
    id: int
    created_at: datetime
    is_active: bool
    
    class Config:
        from_attributes = True  # Enables ORM mode (formerly orm_mode)

class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
```

**Best Practices for Schemas:**

- Use `EmailStr` for email validation
- Use `Field()` for constraints and documentation
- Separate schemas: `Create`, `Update`, `Response`, `Base`
- Use `from_attributes = True` for ORM models
- Add docstrings for Swagger documentation
- Use `Optional` for nullable fields

### 3. Services (Business Logic)

Services contain business logic, keeping routes clean and testable.

**Example: `services/user_service.py`**

```python
from sqlalchemy.orm import Session
from models import User
from schemas.user_schema import UserCreate
from argon2 import PasswordHasher

ph = PasswordHasher()

def create_user(db: Session, user_data: UserCreate):
    hashed_password = ph.hash(user_data.password)
    db_user = User(
        email=user_data.email,
        name=user_data.name,
        hashed_password=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()
```

### 4. Middlewares

Middlewares process requests/responses globally.

**Example: `middlewares/auth_middleware.py`**

```python
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Process request
        token = request.headers.get("Authorization")
        
        # Add custom logic
        if not token and request.url.path.startswith("/api/protected"):
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        response = await call_next(request)
        return response
```

**Add middleware in `main.py`:**

```python
from middlewares.auth_middleware import AuthMiddleware

app.add_middleware(AuthMiddleware)
```

### 5. Dependency Injection

FastAPI's dependency injection system provides clean, reusable code.

#### Database Session Dependency

```python
from core.database import get_db

@router.get("/users")
async def list_users(db: Session = Depends(get_db)):
    return db.query(User).all()
```

#### Authentication Dependency

```python
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer_scheme = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
    db: Session = Depends(get_db)
):
    token = credentials.credentials
    # Verify token and return user
    user = verify_token(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

@router.get("/profile")
async def get_profile(current_user: User = Depends(get_current_user)):
    return current_user
```

#### Role-Based Access Control

```python
from enum import Enum

class UserRole(str, Enum):
    ADMIN = "admin"
    DOCTOR = "doctor"
    PATIENT = "patient"

def roles_required(*allowed_roles: UserRole):
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return role_checker

@router.post("/appointments")
async def create_appointment(
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    # Only patients can create appointments
    pass
```

---

## API Documentation

### Swagger UI Customization

This project uses `fastapi-swagger-dark` for a dark-themed Swagger UI.

**Setup in `main.py`:**

```python
from fastapi import FastAPI, APIRouter
import fastapi_swagger_dark as fsd

app = FastAPI(docs_url=None)  # Disable default docs

router = APIRouter()
fsd.install(router)  # Install dark theme
app.include_router(router)
```

### Making the Authorize Button Visible

To enable the "Authorize" button in Swagger UI, use `Security` dependency:

```python
from fastapi import Security
from fastapi.security import HTTPBearer

bearer_scheme = HTTPBearer()

@router.get(
    "/protected",
    dependencies=[Security(bearer_scheme)]  # Shows lock icon in Swagger
)
async def protected_route():
    return {"message": "Protected data"}
```

**Alternative: Global security**

```python
app = FastAPI(
    docs_url=None,
    dependencies=[Security(bearer_scheme)]  # All routes require auth
)
```

### Documentation Best Practices

#### 1. Use Tags for Organization

```python
router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"]  # Groups in Swagger sidebar
)
```

#### 2. Add Endpoint Descriptions

```python
@router.post(
    "/",
    response_model=AppointmentResponse,
    status_code=201,
    summary="Create Appointment",
    description="Book a new appointment with a doctor",
    response_description="Created appointment details"
)
async def create_appointment(...):
    """
    Create a new appointment:
    
    - **doctor_id**: ID of the doctor
    - **slot_id**: Available time slot
    - **notes**: Optional appointment notes
    """
    pass
```

#### 3. Document Response Models

```python
from typing import List

@router.get(
    "/",
    response_model=List[AppointmentResponse],
    responses={
        200: {"description": "List of appointments"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"}
    }
)
async def list_appointments(...):
    pass
```

#### 4. Use Examples in Schemas

```python
class AppointmentCreate(BaseModel):
    doctor_id: int = Field(..., example=1)
    slot_id: int = Field(..., example=5)
    notes: Optional[str] = Field(None, example="First consultation")
    
    class Config:
        json_schema_extra = {
            "example": {
                "doctor_id": 1,
                "slot_id": 5,
                "notes": "First consultation for back pain"
            }
        }
```

---

## Best Practices

### 1. Project Organization

- **Separation of Concerns**: Routes → Services → Models
- **Single Responsibility**: Each file has one clear purpose
- **Dependency Injection**: Use FastAPI's `Depends()` for clean code

### 2. Database Best Practices

- Always use `db.commit()` after modifications
- Use `db.refresh(obj)` to get updated data after commit
- Close sessions properly (handled by `get_db()` dependency)
- Use transactions for multiple operations

### 3. Schema Design

- Create separate schemas for Create, Update, and Response
- Use Pydantic validators for complex validation
- Enable `from_attributes = True` for ORM compatibility
- Add field constraints using `Field()`

### 4. Security

- Never commit `.env` files (add to `.gitignore`)
- Hash passwords using `argon2-cffi`
- Use JWT tokens for authentication
- Implement rate limiting for public endpoints
- Validate all user inputs

### 5. Error Handling

```python
from fastapi import HTTPException

@router.get("/users/{user_id}")
async def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"User with id {user_id} not found"
        )
    return user
```

### 6. Environment-Specific Configuration

```python
# core/config.py
class Settings(BaseSettings):
    ENV: str = "development"
    DEBUG: bool = False
    
    @property
    def is_production(self) -> bool:
        return self.ENV == "production"
```

---

## Deployment

### Deploy to Vercel

```bash
# Install Vercel CLI
npm install -g vercel

# Deploy
vercel --prod
```

### Configuration Files

**`vercel.json`** - Vercel deployment configuration:

```json
{
  "builds": [
    {
      "src": "main.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "dest": "main.py"
    }
  ]
}
```

### Environment Variables

Set environment variables in Vercel dashboard or using CLI:

```bash
vercel env add DATABASE_URL
vercel env add FRONTEND_URL
```

---

## Common Commands Cheat Sheet

```bash
# Virtual Environment
source .venv/bin/activate          # Activate venv
deactivate                         # Deactivate venv

# Dependencies (uv)
uv sync                           # Install all dependencies
uv add package-name               # Add new package
uv remove package-name            # Remove package
uv pip compile pyproject.toml -o requirements.txt  # Generate requirements.txt

# Dependencies (pip)
pip install -r requirements.txt   # Install dependencies
pip freeze > requirements.txt     # Update requirements.txt

# Database Migrations
alembic revision --autogenerate -m "message"  # Create migration
alembic upgrade head              # Apply migrations
alembic downgrade -1              # Rollback one migration
alembic current                   # Show current version
alembic history                   # Show migration history

# Run Server
uvicorn main:app --port 8000                    # Production
uvicorn main:app --port 8000 --reload           # Development
python main.py                                   # If configured in main.py
uv run main.py                                   # Using uv

# Kill Server (if stuck)
lsof -i :8000                     # Find process
kill -9 <PID>                     # Kill process
pkill -f "uvicorn main:app"       # Kill by name
```

---

## Troubleshooting

### Alembic Not Detecting Models

**Problem**: `alembic revision --autogenerate` creates empty migration.

**Solution**: Ensure all models are imported in `alembic/env.py`:

```python
from models import *  # Must import all models
```

### Database Connection Issues

**Problem**: `sqlalchemy.exc.OperationalError`

**Solution**: 
- Check `DATABASE_URL` in `.env`
- Ensure PostgreSQL is running
- Verify database exists

### Port Already in Use

**Problem**: `Address already in use`

**Solution**:
```bash
lsof -i :8000
kill -9 <PID>
```

---

## Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [uv Documentation](https://docs.astral.sh/uv/)

---

## License

[Your License Here]

## Contributors
-kavangajera
-Devarshi2285
