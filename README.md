# MoneyDesk

One account, many wallets. Built from your `Money_Tracker_Phone.xlsx`.

**Wallets:** Business (Milky Way), Job Salary, Offline Cash, In-Hand Savings. Add more any time.
**Amounts** are in ₹ with Indian digit grouping (₹12,34,567).

## Run it

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then set DJANGO_SECRET_KEY
python manage.py migrate
python manage.py createsuperuser                       # this is your login
python manage.py import_xlsx Money_Tracker_Phone.xlsx --user YOUR_USERNAME
python manage.py runserver
```

Open http://127.0.0.1:8000, log in, then **Security → Turn on two-factor**.
After your account exists, set `ALLOW_SIGNUP=False` in `.env` so nobody else can register.

## What it does

- **Wallets and balances.** Balance = opening balance + income − expenses − money moved out + money moved in.
- **Salary withdrawal.** Dashboard button "Withdraw salary to in-hand" moves money from Job Salary to In-Hand Savings.
  Transfers change balances only; they never count as income or expense, so your savings rate stays honest.
- **Entries.** Income and expenses per wallet, with categories, notes, search, filters (wallet, type, category, month) and CSV export.
- **Dashboard.** Total money, share per wallet, income / expenses / net / savings rate for any month or all time, top spending categories, 6-month trend, budget progress.
- **Budgets.** Monthly limit per expense category, turns amber at 80% and red over 100%.
- **Reports.** Financial year (Apr–Mar, like your sheet): by month, by wallet, by category.
- **Import.** `import_xlsx` reads the *Entries* and *Settings* sheets. Milky Way → wallet "Milky Way" (business), ME → "Offline Cash".
  Change with `--business-wallet "Name"` and `--personal-wallet "Name"`. Rows with amount 0 are skipped.
- **Light and dark theme**, phone layout with a bottom bar.

## Security

- Django login with PBKDF2 hashing, 10+ character passwords, common and numeric-only passwords rejected.
- **Two-factor (TOTP)** with QR setup and single-use recovery codes (stored as keyed hashes).
  The password alone never logs you in when 2FA is on.
- **Lockout:** 5 wrong attempts per username + IP locks login for 15 minutes (also applies to 2FA codes).
- Idle logout after 2 hours (sliding), HttpOnly + SameSite cookies, CSRF on every form, POST-only logout,
  clickjacking and MIME-sniffing protection, open-redirect check on `next`.
- Every query is filtered by the logged-in user, and forms only offer your own wallets and categories.
- CSV export neutralises spreadsheet formulas (`=`, `+`, `-`, `@`).
- Production (`DJANGO_DEBUG=False`): HTTPS redirect, secure cookies, HSTS. Serve behind HTTPS and set
  `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, a long `DJANGO_SECRET_KEY`, and a private `ADMIN_URL`.
  On Vercel the lockout counters use a database table so they are shared between serverless instances (see the Vercel section).

## Deploy to Vercel

Vercel runs the app as a serverless function. Its disk is temporary, so **SQLite will not work there**.
Use Postgres (Neon, free tier, from the Vercel Marketplace). The app switches to Postgres by itself
when `DATABASE_URL` is set, and uses SQLite when it is not.

### 1. Put the code on GitHub
```bash
git init && git add . && git commit -m "MoneyDesk"
# create an empty private repo on GitHub, then:
git remote add origin https://github.com/YOU/moneydesk.git
git push -u origin main
```
`.env`, `.env.local`, `db.sqlite3` and `*.xlsx` are git-ignored, so your data and secrets stay off GitHub.
Use a **private** repo.

### 2. Create the project
Vercel dashboard → **Add New → Project** → import the repo. Vercel finds `manage.py` and detects Django.
Do not press Deploy yet.

### 3. Add the database
Project → **Storage** → **Create / Connect Database** → **Neon (Postgres)** → connect it to this project.
Vercel adds `DATABASE_URL` for you. Tick **Production**.
Use a separate database for Preview, or leave Preview unticked, so test branches never touch real data.

### 4. Set environment variables
Project → **Settings → Environment Variables** (Production):

| Name | Value |
|---|---|
| `DJANGO_SECRET_KEY` | a long random string: `python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"` |
| `ALLOW_SIGNUP` | `False` |
| `ADMIN_URL` | something private, e.g. `panel-7k2x9/` (ends with a slash) |
| `DJANGO_ALLOWED_HOSTS` | only if you use your own domain, e.g. `money.example.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | only if you use your own domain, e.g. `https://money.example.com` |

Leave `DJANGO_DEBUG` unset. On Vercel it is off by default. Your `*.vercel.app` address is allowed automatically.
Never change `DJANGO_SECRET_KEY` later: it would invalidate 2FA recovery codes and log everyone out.

### 5. Deploy
Click **Deploy** (or `npm i -g vercel && vercel --prod`).
The build runs `build.py`, which runs `migrate` and `createcachetable` on the production database.
Vercel collects static files by itself.

### 6. Create your login and import your Excel data (from your computer)
Signup is closed on the live site, so create your user against the production database from your PC.
In the project folder, create a file named `.env.local` with two lines:

```
DATABASE_URL=paste-the-production-postgres-url-here
DJANGO_DEBUG=True
```

Copy the URL from Vercel → Project → Settings → Environment Variables (`DATABASE_URL`, click the eye icon),
or from the Neon dashboard. Then:

```bash
pip install -r requirements.txt
python manage.py createsuperuser
python manage.py import_xlsx Money_Tracker_Phone.xlsx --user YOUR_USERNAME
```

Delete `.env.local` afterwards so a local run cannot touch production by accident.
Run `import_xlsx` only once (it refuses a second run unless you add `--force`).

### 7. First login
Open `https://your-project.vercel.app`, log in, then **Security → Turn on two-factor** and save the recovery codes.

### Updating later
`git push`. Vercel redeploys, and `build.py` applies any new migrations to production.

### Custom domain
Project → **Settings → Domains**. Then add the domain to `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` and redeploy.

### If something fails
- **Build fails with "Set DJANGO_SECRET_KEY"**: add it in step 4, then redeploy.
- **400 Bad Request on the live site**: your domain is missing from `DJANGO_ALLOWED_HOSTS`.
- **403 CSRF error on login**: your `https://` domain is missing from `DJANGO_CSRF_TRUSTED_ORIGINS`.
- **Tables do not exist**: the database was connected only to Preview, or `DATABASE_URL` was missing at build time. Tick Production and redeploy.
- **Styles missing**: check the build log shows `collectstatic` ran, and that `STATIC_ROOT` is still set in `config/settings.py`.

## Tests

`python manage.py test` — 16 tests cover balances, transfers, data isolation, lockout, 2FA, recovery codes and redirects.

## Ideas for later

Recurring entries, Telegram / email reminders, password reset by email, PDF statements, Postgres.
