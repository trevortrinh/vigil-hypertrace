# Hyperliquid S3 Data Samples

This directory contains sample data from Hyperliquid's public S3 buckets.
Run `01_hyperliquid_sampler.ipynb` to download samples.

## Directory Structure (mirrors S3)

```
hyperliquid_samples/
├── hyperliquid-archive/
│   ├── market_data/
│   │   └── [YYYYMMDD]/[hour]/l2Book/
│   │       └── [COIN].lz4        # L2 orderbook snapshots
│   └── asset_ctxs/
│       └── [YYYYMMDD].csv.lz4    # Asset context data
│
├── hl-mainnet-node-data/
│   ├── node_fills_by_block/      # Trade fills by block
│   ├── node_fills/               # Legacy fills
│   ├── node_trades/              # Legacy trades
│   └── explorer_blocks/          # Block data
│
└── hl-mainnet-evm-blocks/
    └── blocks/                   # HyperEVM block data (.rmp.lz4)
```

## Data Formats

| Bucket | Format | Compression |
|--------|--------|-------------|
| hyperliquid-archive | JSON/CSV | LZ4 |
| hl-mainnet-node-data | JSON | LZ4 |
| hl-mainnet-evm-blocks | MessagePack | LZ4 |

## AWS Access

All buckets require `--request-payer requester` (you pay transfer costs).

```bash
aws s3 ls s3://hyperliquid-archive/ --request-payer requester
```
