# Render Flask Starter

Minimal Flask API project for deployment to Render.

## Local run

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Windows Git Bash:

```bash
python -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt
python app.py
```

Open:

- http://localhost:5000/
- http://localhost:5000/health
- http://localhost:5000/api/test

## Render

Connect the GitHub repository to Render.

Render settings:

- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Health Check Path: `/health`

`render.yaml` is also included for Blueprint deployment.
"# render_server" 
