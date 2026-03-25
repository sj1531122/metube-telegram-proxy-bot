# Systemd Deployment Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal `systemd` deployment path for the Telegram bot MVP that matches the validated source-based runtime on the user's server.

**Architecture:** Keep the bot runtime unchanged and add a static `systemd` unit template plus minimal deployment instructions in the repository. The service will run as `root`, read `/opt/metube-telegram-proxy-bot/.env`, and execute `python3 -m bot.main` from the checked-out repo.

**Tech Stack:** Python 3.12 runtime, `systemd`, Markdown, `unittest`

---

### Task 1: Add Systemd Unit Template

**Files:**
- Create: `deploy/systemd/metube-telegram-bot.service`
- Create: `tests/bot/test_deploy_assets.py`

- [ ] **Step 1: Write the failing test**

```python
def test_systemd_unit_exists_with_required_directives():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.bot.test_deploy_assets -v`
Expected: FAIL because the service file does not exist yet

- [ ] **Step 3: Write the minimal implementation**

Create a service file with:
- `User=root`
- `WorkingDirectory=/opt/metube-telegram-proxy-bot`
- `EnvironmentFile=/opt/metube-telegram-proxy-bot/.env`
- `ExecStart=/usr/bin/python3 -m bot.main`
- `Restart=always`
- `RestartSec=5`

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.bot.test_deploy_assets -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add deploy/systemd/metube-telegram-bot.service tests/bot/test_deploy_assets.py
git commit -m "feat: add systemd service template"
```

### Task 2: Document Minimal Systemd Deployment

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README**

Add a short deployment section covering:
- where to copy the service file
- `systemctl daemon-reload`
- `systemctl enable --now metube-telegram-bot`
- `systemctl status` and `journalctl -u metube-telegram-bot -f`
- note that the current MVP runs directly from source without `pip install .`

- [ ] **Step 2: Verify documentation references the new flow**

Run: `rg -n "systemd|systemctl|metube-telegram-bot" README.md deploy/systemd -S`
Expected: matches for the service template and README deployment steps

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add systemd deployment guide"
```

### Task 3: Final Verification

**Files:**
- Verify: `bot/main.py`
- Verify: `tests/bot/test_deploy_assets.py`
- Verify: `README.md`
- Verify: `deploy/systemd/metube-telegram-bot.service`

- [ ] **Step 1: Run focused tests**

Run: `python3 -m unittest tests.bot.test_deploy_assets tests.bot.test_main -v`
Expected: PASS

- [ ] **Step 2: Run full bot tests**

Run: `python3 -m unittest discover -s tests/bot -v`
Expected: PASS

- [ ] **Step 3: Run compile verification**

Run: `python3 -m py_compile bot/*.py tests/bot/*.py`
Expected: PASS

- [ ] **Step 4: Push branch**

```bash
git push origin telegram-bot-mvp
```
