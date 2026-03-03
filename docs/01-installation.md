# Installation Guide

## Prerequisites

| Requirement | Minimum Version | Notes |
|-------------|----------------|-------|
| Python | 3.11+ | 3.12 recommended |
| PostgreSQL | 14+ | 15/16 recommended |
| Git | any | For cloning the repo |

---

## 1. Clone the Repository

```bash
git clone https://github.com/wizzard0s/wizzardchat.git
cd wizzardchat
```

---

## 2. Create a Virtual Environment

```powershell
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux / macOS
python -m venv .venv
source .venv/bin/activate
```

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

> **requirements.txt** installs:
> `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `asyncpg`, `psycopg2-binary`,
> `pydantic`, `pydantic-settings`, `python-dotenv`, `python-jose[cryptography]`,
> `passlib[bcrypt]`, `python-multipart`, `jinja2`

---

## 4. Configure Environment

Copy the example file and edit it:

```powershell
# Windows
Copy-Item .env.example .env
notepad .env
```

```bash
# Linux / macOS
cp .env.example .env
nano .env
```

### Minimum required changes

| Variable | What to set |
|----------|-------------|
| `DATABASE_URL` | Your PostgreSQL connection string (asyncpg driver) |
| `DATABASE_URL_SYNC` | Same but with psycopg2 driver |
| `SECRET_KEY` | A long random string — generate with `python -c "import secrets; print(secrets.token_hex(32))"` |

Full `.env` example:

```env
DATABASE_URL=postgresql+asyncpg://postgres:mypassword@localhost:5432/wizzardchat
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:mypassword@localhost:5432/wizzardchat
SECRET_KEY=your-very-long-random-secret-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
APP_NAME=WizzardChat
APP_PORT=8092
```

---

## 5. Set Up the PostgreSQL Database

```sql
-- Connect to PostgreSQL as superuser and run:
CREATE DATABASE wizzardchat;
```

> WizzardChat creates all tables automatically on first startup — no manual migration needed.

---

## 6. Run the Application

```powershell
# Windows
python main.py
```

```bash
# Linux / macOS
python main.py
```

The app will:
1. Connect to PostgreSQL
2. Create all database tables (if not present)
3. Apply any pending column migrations
4. Seed the default system admin user
5. Seed default roles and global settings
6. Start the HTTP server

Open your browser to: **http://localhost:8092**

Default login credentials:
- **Username:** `admin`
- **Password:** `M@M@5t3r`

> **Security:** Change the admin password immediately after first login via the **Users** page.

---

## 7. Running as a Background Service

### Windows — run hidden

```powershell
Start-Process -FilePath ".\.venv\Scripts\python.exe" `
  -ArgumentList "-B", "-u", "main.py" `
  -WorkingDirectory (Get-Location) `
  -WindowStyle Hidden
```

### Linux — systemd service

Create `/etc/systemd/system/wizzardchat.service`:

```ini
[Unit]
Description=WizzardChat
After=network.target postgresql.service

[Service]
User=www-data
WorkingDirectory=/opt/wizzardchat
ExecStart=/opt/wizzardchat/.venv/bin/python main.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/wizzardchat/.env

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable wizzardchat
systemctl start wizzardchat
systemctl status wizzardchat
```

---

## 8. Verifying the Installation

```bash
# Health check endpoint
curl http://localhost:8092/api/v1/health
# Expected: {"status":"ok","app":"WizzardChat","version":"v1"}
```

```powershell
# PowerShell equivalent
Invoke-RestMethod http://localhost:8092/api/v1/health
```

---

## 9. Updating

```bash
git pull origin main
pip install -r requirements.txt   # pick up any new packages
# Restart the service — new column migrations apply automatically on startup
```

---

## Logs

All application logs are written to `wizzardchat.log` in the project root.

```powershell
# Windows — tail the log
Get-Content wizzardchat.log -Tail 50 -Wait
```

```bash
# Linux
tail -f wizzardchat.log
```

Log levels: `DEBUG` (file) + `INFO` (stdout). Unhandled exceptions are logged as `CRITICAL`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `asyncpg.exceptions.InvalidPasswordError` | Wrong DB credentials | Check `DATABASE_URL` in `.env` |
| `address already in use` on port 8092 | Another process on that port | Change `APP_PORT` in `.env` or kill the other process |
| Page loads but hangs | Old uvicorn reloader zombie | Kill all `python.exe` processes and restart |
| `ModuleNotFoundError` | Missing package | Run `pip install -r requirements.txt` with venv activated |
| Tables not found | DB not created | Create the database in PostgreSQL manually, then restart |
