-- Olist raw-layer schema.
-- Column names are kept identical to the source CSV headers (including the
-- original "lenght" typos) so every column is traceable back to Raw_data.
-- Table creation order follows FK dependencies.

-- customer_id is the per-order customer key (PK, referenced by orders).
-- customer_unique_id identifies the same person across orders; not unique here.
CREATE TABLE customers (
    customer_id              VARCHAR PRIMARY KEY,
    customer_unique_id       VARCHAR NOT NULL,
    customer_zip_code_prefix VARCHAR NOT NULL,
    customer_city            VARCHAR NOT NULL,
    customer_state           VARCHAR NOT NULL
);

CREATE TABLE sellers (
    seller_id              VARCHAR PRIMARY KEY,
    seller_zip_code_prefix VARCHAR NOT NULL,
    seller_city            VARCHAR NOT NULL,
    seller_state           VARCHAR NOT NULL
);

CREATE TABLE product_category_name_translation (
    product_category_name         VARCHAR PRIMARY KEY,
    product_category_name_english VARCHAR NOT NULL
);

-- No FK to product_category_name_translation: 2 source categories
-- (pc_gamer, portateis_cozinha_e_preparadores_de_alimentos) have no translation.
CREATE TABLE products (
    product_id                 VARCHAR PRIMARY KEY,
    product_category_name      VARCHAR,
    product_name_lenght        INTEGER,
    product_description_lenght INTEGER,
    product_photos_qty         INTEGER,
    product_weight_g           INTEGER,
    product_length_cm          INTEGER,
    product_height_cm          INTEGER,
    product_width_cm           INTEGER
);

CREATE TABLE orders (
    order_id                      VARCHAR PRIMARY KEY,
    customer_id                   VARCHAR NOT NULL REFERENCES customers (customer_id),
    order_status                  VARCHAR NOT NULL,
    order_purchase_timestamp      TIMESTAMP NOT NULL,
    order_approved_at             TIMESTAMP,
    order_delivered_carrier_date  TIMESTAMP,
    order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP NOT NULL
);

CREATE TABLE order_items (
    order_id            VARCHAR NOT NULL REFERENCES orders (order_id),
    order_item_id       INTEGER NOT NULL,
    product_id          VARCHAR NOT NULL REFERENCES products (product_id),
    seller_id           VARCHAR NOT NULL REFERENCES sellers (seller_id),
    shipping_limit_date TIMESTAMP NOT NULL,
    price               DECIMAL(12, 2) NOT NULL,
    freight_value       DECIMAL(12, 2) NOT NULL,
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE order_payments (
    order_id             VARCHAR NOT NULL REFERENCES orders (order_id),
    payment_sequential   INTEGER NOT NULL,
    payment_type         VARCHAR NOT NULL,
    payment_installments INTEGER NOT NULL,
    payment_value        DECIMAL(12, 2) NOT NULL,
    PRIMARY KEY (order_id, payment_sequential)
);

-- review_id alone is not unique in the source (same review attached to several orders).
CREATE TABLE order_reviews (
    review_id               VARCHAR NOT NULL,
    order_id                VARCHAR NOT NULL REFERENCES orders (order_id),
    review_score            INTEGER NOT NULL,
    review_comment_title    VARCHAR,
    review_comment_message  VARCHAR,
    review_creation_date    TIMESTAMP NOT NULL,
    review_answer_timestamp TIMESTAMP NOT NULL,
    PRIMARY KEY (review_id, order_id)
);

-- Raw geolocation has no natural key (many points per zip prefix, exact duplicates).
-- Use the derived table geolocation_zip for joins.
CREATE TABLE geolocation (
    geolocation_zip_code_prefix VARCHAR NOT NULL,
    geolocation_lat             DOUBLE NOT NULL,
    geolocation_lng             DOUBLE NOT NULL,
    geolocation_city            VARCHAR NOT NULL,
    geolocation_state           VARCHAR NOT NULL
);
