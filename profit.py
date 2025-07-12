import psycopg2, textwrap
import os 
DATABASE_URL = os.environ["DATABASE_URL"]
sql = textwrap.dedent("""
CREATE OR REPLACE FUNCTION f_insert_profit()
RETURNS trigger AS $$
DECLARE
    unit_cost      NUMERIC(10,2);
    v_gas_name     TEXT;
    total_refill   INTEGER;
    total_sold     INTEGER;
BEGIN
    -- 1) Get gas brand name
    SELECT gas_name INTO v_gas_name
      FROM gas_table
     WHERE gas_id = NEW.gas_id;

    -- ---------- PATH A - COMPLETE SALE ----------
    IF NEW.complete_sale IS TRUE THEN
        -- Prefer full price from any company except POWER GAS
        SELECT MIN(cgp.full_price)
          INTO unit_cost
          FROM company_gas_price cgp
          JOIN buying_company bc ON bc.company_id = cgp.company_id
         WHERE cgp.gas_id = NEW.gas_id
           AND cgp.full_price > 0
           AND (
               v_gas_name IN ('Power','Power 13kg') OR
               bc.company_name <> 'POWER GAS'
           );

        -- Fallback to KAFUSH AND JAY (if not Power brand)
        IF unit_cost IS NULL AND v_gas_name NOT IN ('Power','Power 13kg') THEN
            SELECT cg.full_price INTO unit_cost
              FROM company_gas_price cg
              JOIN buying_company bc ON bc.company_id = cg.company_id
             WHERE bc.company_name = 'KAFUSH AND JAY'
               AND cg.gas_id = NEW.gas_id
             LIMIT 1;
        END IF;

    -- ---------- PATH B - Normal Refill Sale ----------
    ELSE
        -- a) Get recent refill and sale totals
        SELECT COALESCE(SUM(quantity), 0) INTO total_refill
          FROM refill_table
         WHERE gas_id = NEW.gas_id
           AND refill_time >= (CURRENT_TIMESTAMP - INTERVAL '5 days');

        SELECT COUNT(*) INTO total_sold
          FROM sales_table
         WHERE gas_id = NEW.gas_id
           AND complete_sale = FALSE
           AND time_sold >= (CURRENT_TIMESTAMP - INTERVAL '5 days');

        -- b) If more refill than sold, find latest refill cost
        IF total_sold < total_refill THEN
            SELECT MIN(r.unit_price) INTO unit_cost
              FROM refill_table r
              JOIN buying_company bc ON bc.company_id = r.company_id
             WHERE r.gas_id = NEW.gas_id
               AND r.refill_time >= (CURRENT_TIMESTAMP - INTERVAL '5 days')
               AND (
                   v_gas_name IN ('Power','Power 13kg') OR
                   bc.company_name <> 'POWER GAS'
               );
        END IF;

        -- c) Fallback to KAFUSH AND JAY refill price
        IF unit_cost IS NULL AND v_gas_name NOT IN ('Power','Power 13kg') THEN
            SELECT cg.refill_price INTO unit_cost
              FROM company_gas_price cg
              JOIN buying_company bc ON bc.company_id = cg.company_id
             WHERE bc.company_name = 'KAFUSH AND JAY'
               AND cg.gas_id = NEW.gas_id
             LIMIT 1;
        END IF;
    END IF;

    -- 3) Ultimate safety fallback
    IF unit_cost IS NULL THEN
        unit_cost := 0;
    END IF;

    -- 4) Insert profit row
    INSERT INTO profit_table (
        sale_id, gas_id, company_id,
        qty, revenue, cost
    )
    VALUES (
        NEW.sale_id,
        NEW.gas_id,
        NULL,
        1,
        NEW.amount_paid_cash + NEW.amount_paid_till,
        unit_cost
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_sales_profit ON sales_table;

CREATE TRIGGER trg_sales_profit
AFTER INSERT ON sales_table
FOR EACH ROW
EXECUTE FUNCTION f_insert_profit();

""")

with psycopg2.connect(DATABASE_URL, sslmode="require") as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
print("✅ Profit trigger (v4) installed.")
