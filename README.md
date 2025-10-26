````markdown
# QR-Jacker

**QR-Jacker** — Local QR session manager & visual recon dashboard (lab use only).

> A compact, lab-focused tool for generating QR sessions and visualizing consenting client telemetry in a slick dark-themed admin UI. Intended for controlled red-team / Hack The Box style labs and defensive training only.

---

## ⚠️ IMPORTANT (Read first)

**This project is for EDUCATIONAL and AUTHORIZED TESTING ONLY.**  
Do **not** use against systems, networks or people without explicit permission. By using this tool you confirm you are authorized to test the target systems and accept all responsibility for your actions. See `ABOUT.txt` for full disclaimer and credits.

---

## Features

- Generate QR codes bound to unique session IDs (PNG saved to `./qrcodes/`)
- Public-facing landing page (visitor) that collects consenting telemetry and optionally geolocation (if allowed by client)
- Local admin dashboard (admin-only) showing live device tiles, OS icons, session info, and context menu actions (specs, location, download JSON, delete)
- Local SQLite logs (`./logs/events.db`)
- Designed for lab/HTB usage — Cloudflare Tunnel friendly

---

## Quick tutorial

Follow these steps to get QR-Jacker running locally and expose it via Cloudflare Tunnel.

### 1. Clone the repo
```bash
git clone <your-repo-url>
cd QR-Jacker
````

### 2. Give permissions (optional)

Make scripts executable (if you want to run the packaged binary or helper scripts):

```bash
chmod +x ./script.py     # or ./qrjacker (if you built a binary)
```

### 3. Python virtual environment (must)

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Install dependencies

You need Python and these packages:

* `Flask==3.0.0`
* `qrcode==7.4.2`
* `Pillow==10.1.0`

Install using requirements or pip:

```bash
# Option A (if requirements.txt is provided)
pip install -r requirements.txt

# Option B (manual)
pip install Flask qrcode Pillow
```

### 5. Run the script

If you built a binary (release) run:

```bash
./qrjacker
```

Otherwise run the Python script:

```bash
python3 script.py
# or
./script.py
```

### 6. Open the admin panel in your browser

The admin UI runs locally (default):

```
http://127.0.0.1:5001
```

(If your config uses different ports, check console output when the server starts.)

---

## How to expose the victim-facing page (Cloudflare Tunnel)

To make the visitor landing accessible from the internet (for lab testing using a safe tunnel):

1. Install and log into cloudflared (see Cloudflare docs).
2. Run:

```bash
cloudflared tunnel --url http://127.0.0.1:5000
```

3. Cloudflared will provide you with a public URL like:

```
https://random-name.trycloudflare.com
```

4. Copy that link.

---

## Generate QR & use flow

1. In the Admin panel click **Generate QR**.
2. When prompted, **paste the Cloudflare link** you copied (or leave blank to use the default `CLOUDFLARE_URL` env var / localhost).
3. The dashboard will generate and show a QR (and save PNG to `./qrcodes/`).
4. Give this QR to a **test device you own** and ask the tester to scan and click the consent button on the landing page.
5. When the device interacts, a new device tile will appear in the admin dashboard (refresh or wait for auto-refresh).

---

## Files & folders

* `script.py` — main server script (admin + public apps)
* `qrcodes/` — saved QR PNGs
* `logs/events.db` — SQLite database with logs
* `static/` — static assets (icons, logo)
* `ABOUT.txt` — credits + legal disclaimer
* `release/` — (optional) compiled binary if you build with PyInstaller

---

## Tips & troubleshooting

* If the admin UI doesn’t show images, ensure `static/img/` contains `android.png`, `iphone.png`, `mac.png`, `win.png`, `linux.png`, and `unknown.png`.
* If running the PyInstaller onefile binary, make sure you start it from the project root so it can read/write `qrcodes/` and `logs/`.
* If your QR binary > 100 MB, upload it to **GitHub Releases** rather than committing the binary into the repo (GitHub blocks files >100 MB in repo).
* If geolocation isn’t captured it’s because the client denied the browser permission — that’s expected.

---

## Packaging & distribution (quick note)

To produce a single executable (Linux) that hides the source:

1. Create a venv and install `pyinstaller` (and `pyarmor` if you want obfuscation).
2. Run the obfuscate + build workflow (example in `build_release.sh` if provided).
3. Upload the resulting `dist/qrjacker` binary to **GitHub Releases** (preferred) or track it with Git LFS (not recommended unless you know quotas).

---

## Legal / Responsible Use (IMPORTANT)

This tool is provided for **authorized testing and educational purposes only**. You must have explicit permission to test any target. The author is not responsible for misuse. See `ABOUT.txt` for a full disclaimer.

---

## Credits

* **Tool / UI**: QR-Jacker (originally QRRecon admin UI)
* **Developer**: Phoenix

  * Instagram: [@ethicalphoenix](https://instagram.com/ethicalphoenix)
  * Telegram: [t.me/MrRabbit_008](https://t.me/MrRabbit_008)

---

## Need help?

If you run into issues, contact:

* Instagram: `@ethicalphoenix`
* Telegram: `t.me/MrRabbit_008`

Or open an issue in the repository with logs, error messages, and a description of the problem.

---

## LICENSE

Add your license here (MIT / GPL / etc.). If you don’t want the code reused publicly, do **not** choose permissive licenses. Consider keeping the source in a **private repo** if you plan to distribute only compiled binaries.

---

Thank you — and remember: **use it ethically.**

```

---

Want me to:
- Save that into a `README.md` file for you (I can provide the exact file content), and
- Add a `requirements.txt` and `ABOUT.txt` files too?
::contentReference[oaicite:0]{index=0}
```
