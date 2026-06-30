CREATE TABLE IF NOT EXISTS marketplace_containers (
    id SERIAL PRIMARY KEY,
    container_id   VARCHAR(72)  NOT NULL UNIQUE,
    container_name VARCHAR(128) NOT NULL UNIQUE,
    role           VARCHAR(16)  NOT NULL,
    strategy_id    VARCHAR(128) NOT NULL,
    creator_wallet VARCHAR(42)  NOT NULL DEFAULT '',
    subscriber_wallet VARCHAR(42) NOT NULL DEFAULT '',
    sub_id         VARCHAR(68)  NOT NULL DEFAULT '',
    pool_id        VARCHAR(66)  NOT NULL DEFAULT '',
    vault_address  VARCHAR(42)  NOT NULL DEFAULT '',
    publisher_endpoint VARCHAR(256) NOT NULL DEFAULT '',
    status         VARCHAR(16)  NOT NULL DEFAULT 'running',
    created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    stopped_at     TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mc_strategy_role
    ON marketplace_containers (strategy_id, role);
CREATE INDEX IF NOT EXISTS idx_mc_creator
    ON marketplace_containers (creator_wallet);
CREATE INDEX IF NOT EXISTS idx_mc_subscriber
    ON marketplace_containers (subscriber_wallet);
