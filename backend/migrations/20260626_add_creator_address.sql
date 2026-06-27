-- Add creator_address column to strategy_store for per-wallet personal isolation.
-- Each generated strategy can optionally be associated with the wallet address
-- that created it, enabling the "Generated" sub-tab in the Library to show
-- only strategies created by the connected wallet.

ALTER TABLE strategy_store ADD COLUMN creator_address VARCHAR(64);
CREATE INDEX IF NOT EXISTS ix_strategy_creator_address ON strategy_store(creator_address);
