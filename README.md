# vigil-hypertrace

[Notion](https://www.notion.so/onedollarsummer/Vigil-Hypertrace-300eaf5f4629800b8199d1a9e22cb0a3)

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

in this dataset

| First Fill              | Last Fill               |
| ----------------------- | ----------------------- |
| 2025-07-27 08:50:10 UTC | 2025-12-01 12:59:59 UTC |
| 64 days of data         |                         |

Top 20 new traders by lowest volume (highest capital efficiency):

| Address             | PnL   | Volume | Days | Sharpe |
| ------------------- | ----- | ------ | ---- | ------ |
| 0x26393bcb4446d3... | $112K | $1.2M  | 31   | 5.76   |
| 0x870ce4cbe75814... | $244K | $1.5M  | 19   | 6.33   |
| 0x6581c99e278c12... | $141K | $1.5M  | 18   | 3.94   |
| 0x98d0e60828e17d... | $160K | $1.9M  | 36   | 3.11   |
| 0x0980b34ade9476... | $143K | $1.9M  | 20   | 4.44   |
| 0xdec8eb506264ab... | $103K | $2.3M  | 17   | 11.56  |
| 0xf831a8c0788a44... | $201K | $2.5M  | 65   | 9.98   |
| 0xff35440e44c9db... | $199K | $2.6M  | 19   | 6.03   |
| 0x4a13807147b2a3... | $362K | $3.1M  | 21   | 4.21   |
| 0xced9bd642f2981... | $169K | $3.4M  | 29   | 13.12  |

want to follow wallets like:
0x26393bcb4446d3f40bdc15ca59d7febcb09e7236
