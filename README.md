# AI-Job-Hunter
This will help us to hunt the jobs without manual effort

## What it does

This project schedules a daily job-application cycle at 10:00 AM IST and uses Playwright to open portals and inspect application flows.

- Starts a Python scheduler using `APScheduler`
- Runs a `JobAgent` once per day at 10:00 AM IST
- Opens configured portals, searches for keyword-based jobs, and tries to trigger an application flow
- Uses a fallback list if a portal cannot be scraped during the run

## Run locally

1. Create a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in your values.
4. Run the scheduler:

   ```bash
   python app.py
   ```

5. To verify the automation flow without waiting for the scheduled time:

   ```bash
   python app.py --test
   ```

## Dashboard UI

A simple Streamlit dashboard is included so you can view the job matching and apply summary in a user-friendly screen.

Run it with:

```powershell
streamlit run dashboard.py
```

Or use the bundled launcher:

```powershell
dashboard.bat
```

The dashboard shows:
- how many jobs matched your resume
- how many were attempted/applied
- recent portal results and match scores

## Windows Task Scheduler

If you want the agent to keep running on a Windows machine, create a scheduled task that starts:

```powershell
python C:\Tools\AI-Job-Hunter\app.py
```

Set the task to run daily at `10:00 AM` using the `Asia/Kolkata` timezone.

## Important note

The Playwright browser flow is a practical automation scaffold. You will likely need to refine the portal selectors for LinkedIn or Indeed, because those sites frequently change their DOM structure and may require login or CAPTCHA handling for real applications.
