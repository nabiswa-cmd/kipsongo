import psycopg2
import os

DATABASE_URL = os.environ["DATABASE_URL"]

try:
    # ✅ Connect securely using SSL
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()

    # 🔧 gas_table with CHECK constraints for non-negative values
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gas_table (
            gas_id SERIAL PRIMARY KEY,
            gas_name TEXT NOT NULL,
            empty_cylinders INTEGER DEFAULT 0 CHECK (empty_cylinders >= 0),
            filled_cylinders INTEGER DEFAULT 0 CHECK (filled_cylinders >= 0),
            total_cylinders NUMERIC(10,2) GENERATED ALWAYS AS (empty_cylinders + filled_cylinders) STORED
        );
    """)

    # 🔧 prepaid_sales
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prepaid_sales (
            id SERIAL PRIMARY KEY,
            gas_id INTEGER REFERENCES gas_table(gas_id) ON DELETE CASCADE,
            customer_name TEXT NOT NULL,
            customer_phone TEXT,
            customer_address TEXT,
            empty_given BOOLEAN DEFAULT FALSE,
            customer_picture TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 🔧 sales_table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sales_table (
            sale_id SERIAL PRIMARY KEY,
            gas_id INTEGER REFERENCES gas_table(gas_id),
            sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            amount_paid_cash NUMERIC(10,2) DEFAULT 0,
            amount_paid_till NUMERIC(10,2) DEFAULT 0,
            total NUMERIC(10,2) GENERATED ALWAYS AS (amount_paid_cash + amount_paid_till) STORED,
            time_sold TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            source_kipsongo_pioneer BOOLEAN DEFAULT FALSE,
            source_mama_pam BOOLEAN DEFAULT FALSE,
            source_external BOOLEAN DEFAULT FALSE,
            complete_sale BOOLEAN DEFAULT FALSE,
            empty_not_given BOOLEAN DEFAULT FALSE,
            exchange_cylinder BOOLEAN DEFAULT FALSE
        );
    """)

    # 🔧 gas_debts
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gas_debts (
            id SERIAL PRIMARY KEY,
            gas_id INTEGER REFERENCES gas_table(gas_id),
            amount_paid NUMERIC(10,2) DEFAULT 0.00,
            amount_to_be_paid NUMERIC(10,2),
            date_to_be_paid DATE,
            authorized_by TEXT CHECK (authorized_by IN ('Mama Dan', 'Baba Dan')),
            empty_cylinder_given BOOLEAN DEFAULT FALSE,
            customer_name TEXT,
            customer_phone TEXT,
            customer_address TEXT,
            time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            customer_picture TEXT
        );
    """)

    # 🔧 gas_debt_payments
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gas_debt_payments (
            id SERIAL PRIMARY KEY,
            debt_id INTEGER REFERENCES gas_debts(id) ON DELETE CASCADE,
            amount NUMERIC(10,2),
            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 🔧 stock_out
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_out (
            id SERIAL PRIMARY KEY,
            gas_id INTEGER REFERENCES gas_table(gas_id) ON DELETE CASCADE,
            cylinder_state TEXT CHECK (cylinder_state IN ('empty','filled')),
            destination_type TEXT CHECK (destination_type IN ('station','delivery','customer')),
            destination_value TEXT NOT NULL,
            time_out TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 🔧 stock_change
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_change (
            id SERIAL PRIMARY KEY,
            gas_id INTEGER REFERENCES gas_table(gas_id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            quantity_change INTEGER NOT NULL,
            notes TEXT,
            changed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 🔧 users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
    """)

    # 🔧 Insert admin user
    cur.execute("""
        INSERT INTO users (username, password)
        VALUES (%s, %s)
        ON CONFLICT (username) DO NOTHING;
    """, ('admin', 'admin123'))

    # 🔧 buying_company
    cur.execute("""
        CREATE TABLE IF NOT EXISTS buying_company (
            company_id SERIAL PRIMARY KEY,
            company_name TEXT UNIQUE NOT NULL
        );
    """)

    # 🔧 Seed suppliers
    SEED_COMPANIES = ['KAFUSH AND JAY', 'DAN SUPPLY', 'NEW SUPPLIER']
    for name in SEED_COMPANIES:
        cur.execute("""
            INSERT INTO buying_company (company_name)
            VALUES (%s)
            ON CONFLICT (company_name) DO NOTHING;
        """, (name,))

    # 🔧 company_gas_price
    cur.execute("""
        CREATE TABLE IF NOT EXISTS company_gas_price (
            company_id INTEGER NOT NULL REFERENCES buying_company(company_id) ON DELETE CASCADE,
            gas_id     INTEGER NOT NULL REFERENCES gas_table(gas_id) ON DELETE CASCADE,
            refill_price NUMERIC(10,2) DEFAULT 0,
            full_price   NUMERIC(10,2) DEFAULT 0,
            last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (company_id, gas_id)
        );
    """)

    # Auto‑populate company gas price matrix
    cur.execute("""
        INSERT INTO company_gas_price (company_id, gas_id)
        SELECT c.company_id, g.gas_id
        FROM   buying_company c
        CROSS  JOIN gas_table g
        ON CONFLICT DO NOTHING;
    """)

    # 🔧 refill_table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS refill_table (
            refill_id SERIAL PRIMARY KEY,
            company_id INTEGER REFERENCES buying_company(company_id) ON DELETE CASCADE,
            gas_id INTEGER REFERENCES gas_table(gas_id) ON DELETE CASCADE,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            unit_price NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0),
            total_cost NUMERIC(12,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
            refill_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 🔧 stock_in
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_in (
            id SERIAL PRIMARY KEY,
            gas_id INTEGER REFERENCES gas_table(gas_id) ON DELETE CASCADE,
            cylinder_state TEXT CHECK (cylinder_state IN ('empty','filled')),
            source_type TEXT CHECK (source_type IN ('supplier','Work Station','customer')),
            source_value TEXT NOT NULL,
            time_in TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 🔧 profit_table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS profit_table (
            profit_id SERIAL PRIMARY KEY,
            sale_id INTEGER REFERENCES sales_table(sale_id) ON DELETE SET NULL,
            gas_id INTEGER REFERENCES gas_table(gas_id) ON DELETE CASCADE,
            company_id INTEGER REFERENCES buying_company(company_id) ON DELETE SET NULL,
            qty INTEGER NOT NULL DEFAULT 1,
            revenue NUMERIC(10,2) NOT NULL,
            cost NUMERIC(10,2) NOT NULL,
            time_recorded TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    print("✅ All tables created successfully.")

except Exception as e:
    print("❌ Error creating tables:", e)

finally:
    if 'conn' in locals():
        conn.close()
