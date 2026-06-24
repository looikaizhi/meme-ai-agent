"""Dotted JSON paths into gmgn-cli --raw output. Confirmed against
tests/memedogV2/fixtures/{security,info}.json during the Phase 0 spike.
A path that does not exist returns None at read time -> rule degrades open."""

FIELD_MAP = {
    # from `token security --raw`
    "renounced_mint":     "renounced_mint",            # bool
    "renounced_freeze":   "renounced_freeze_account",  # bool
    "honeypot":           "honeypot",                  # int 0/1 (SOL has no is_honeypot)
    "burn_status":        "burn_status",               # "burn" == LP burned
    "lp_locked":          "lock_summary.is_locked",    # bool
    "buy_tax":            "buy_tax",                    # str number
    "sell_tax":           "sell_tax",                  # str number
    # from `token info --raw`
    "top10_rate":         "stat.top_10_holder_rate",        # str 0-1 fraction
    "creator_hold_rate":  "stat.creator_hold_rate",         # str 0-1
    "dev_team_hold_rate": "stat.dev_team_hold_rate",        # str 0-1
    "fresh_wallet_rate":  "stat.fresh_wallet_rate",         # str 0-1
    "sniper_hold_rate":   "stat.top70_sniper_hold_rate",    # str 0-1
    "bundler_rate":       "stat.top_bundler_trader_percentage",  # str 0-1
    "sniper_wallets":     "wallet_tags_stat.sniper_wallets",     # int
    "liquidity_usd":      "liquidity",                 # str number (top-level in info)
    "price_usd":          "price.price",               # str number
    "circulating_supply": "circulating_supply",        # str number
    "volume_5m":          "price.volume_5m",           # str number
    "buys_5m":            "price.buys_5m",             # int
    "sells_5m":           "price.sells_5m",            # int
    # LLM evidence only (NOT hard gates)
    "dev_created_count":  "dev.creator_open_count",          # int
    "dev_ath_mc":         "dev.ath_token_info.ath_mc",       # str (may be "")
    "smart_wallets":      "wallet_tags_stat.smart_wallets",  # int
    "renowned_wallets":   "wallet_tags_stat.renowned_wallets",  # int
}
