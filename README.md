# vigil contract

### data pipeline

hyperliquid s3 -> paraquet -> tigerdb

### running in ec2

```bash
# 1. create ec2
# 2. copy pem to local

# 3. copy repo from local to ec2
rsync -avz \
 --exclude='.venv' \
 --exclude='data' \
 --exclude='.git' \
 --exclude='**pycache**' \
 --exclude='\*.pyc' \
 --exclude='.ruff_cache' \
 -e "ssh -i ~/.ssh/<pem_file>.pem" \
 </path/to/repo> \
 ec2-user@<ec2_public_ip>.compute-1.amazonaws.com:~/<repo_name>/

# 4. ssh to ec2
ssh -i ~/.ssh/<pem_file>.pem ec2-user@<ec2_public_ip>.compute-1.amazonaws.com

# 5. install uv in ec2
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync

# 6. run in background
nohup uv run python -u scripts/load_to_db.py > load.log 2>&1 &
tail -f load.log

# 7. kill background process
pkill -9 -f python
```
