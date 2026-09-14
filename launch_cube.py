#!/usr/bin/env python3
"""CubeMini auto-launcher — login once, scrape repeatedly until district done."""
from sync_state_to_cubemini import ssh_exec, ssh_sftp_put
import sys, time

district = sys.argv[1] if len(sys.argv) > 1 else 'miyun'
region_id = f'beijing_{district}'

# Step 1: Login + save clean state backup
print(f'Logging into {region_id}...')
ssh_exec('pkill -f scrape_anjuke 2>/dev/null; sleep 1', timeout=8)

cmd = (f'cd /home/frank/district-content-engine && '
       f'DISPLAY=:99 PYTHONPATH=/home/frank/district-content-engine '
       f'nohup /home/frank/crawler-venv/bin/python3 data/scrape_anjuke.py '
       f'--login --manual --xvfb --region {region_id} '
       f'>> /tmp/cube_login.log 2>&1 &')
try: ssh_exec(cmd, timeout=8)
except: pass

print('⏳ Waiting for captcha (VNC or auto-clear)...')
# Wait up to 3 min for login to complete
for i in range(18):
    time.sleep(10)
    out, _ = ssh_exec('tail -2 /tmp/cube_login.log', timeout=5)
    if 'Storage state saved' in out:
        print('✅ Login complete!')
        break
else:
    print('⚠️  Login timeout, proceeding anyway...')

# Backup the clean state
ssh_exec('cp /home/frank/district-content-engine/anjuke_state.json /home/frank/district-content-engine/anjuke_state_clean.json; echo backed_up', timeout=5)
ssh_exec('pkill -f scrape_anjuke 2>/dev/null; sleep 2', timeout=8)

# Step 2: Scrape loop — restore clean state before each launch
max_rounds = 10
for round_num in range(1, max_rounds + 1):
    print(f'\n🔄 Round {round_num}/{max_rounds}: launching {region_id}...')

    # Restore clean state
    ssh_exec('cp /home/frank/district-content-engine/anjuke_state_clean.json /home/frank/district-content-engine/anjuke_state.json', timeout=5)

    # Launch
    cmd = (f'cd /home/frank/district-content-engine && '
           f'DISPLAY=:99 PYTHONPATH=/home/frank/district-content-engine '
           f'nohup /home/frank/crawler-venv/bin/python3 data/scrape_anjuke.py '
           f'--region {region_id} --shangquan all --xvfb '
           f'>> /tmp/cube_{district}.log 2>&1 &')
    try: ssh_exec(cmd, timeout=8)
    except: pass

    # Wait for completion or captcha wall
    time.sleep(15)
    last_line = ''
    stall_count = 0
    while stall_count < 6:  # 3 min max wait
        time.sleep(30)
        out, _ = ssh_exec(f'tail -3 /tmp/cube_{district}.log', timeout=5)
        new_last = out.strip().split('\n')[-1] if out.strip() else ''
        if 'Batch complete' in out:
            print(f'  ✅ District complete!')
            sys.exit(0)
        if new_last == last_line:
            stall_count += 1
        else:
            stall_count = 0
            last_line = new_last
        # Check progress
        if 'Saved' in out:
            print(f'  {out.strip()[-80:]}')
        if 'scraped' in out:
            print(f'  📊 {out.strip()[-100:]}')

    # Stalled — scraper probably exited from captcha
    ssh_exec('pkill -f scrape_anjuke 2>/dev/null', timeout=5)
    print(f'  ⚠️  Captcha wall — restarting with clean state...')

print(f'\n❌ Max rounds ({max_rounds}) reached. District partially complete.')
