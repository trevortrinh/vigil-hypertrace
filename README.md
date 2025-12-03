# vigil contract

### setup

1. create s3 bucket
2. create tigerdb instance
3. create ec2 instance

### data pipeline

hyperliquid s3 -> parquet -> tigerdb

```bash
# 1. fetch data from hyperliquid to our s3 parquet
just fetch-data

# 2. reset tigerdb
just db-reset

# 3. load data from s3 to db (run in ec2 for faster processing)
just cloud-load

# 4. create aggregates
just db-aggregates

# 5. refresh aggregates
just db-refresh
```

### running in ec2

```bash
# 1. create ec2 t3.2xlarge (needed cuz 10/10 had hella fills)
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
nohup uv run python -u scripts/cloud_load.py > load.log 2>&1 &
tail -f load.log

# 7. kill background process
pkill -9 -f python
```
