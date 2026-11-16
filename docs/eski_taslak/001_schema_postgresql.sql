-- İzmir Pasaport Pier Otel (54 oda) - maliyet muhasebesi başlangıç şeması
-- PostgreSQL 15+. Para birimi TRY; tüm tutarlar KDV hariç tutulur.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE hotels (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  room_count smallint NOT NULL CHECK (room_count > 0),
  currency char(3) NOT NULL DEFAULT 'TRY',
  timezone text NOT NULL DEFAULT 'Europe/Istanbul',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE room_types (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE,
  name text NOT NULL, description text, max_guests smallint NOT NULL CHECK(max_guests > 0),
  base_capacity smallint NOT NULL DEFAULT 2 CHECK(base_capacity > 0),
  standard_cost_factor numeric(8,4) NOT NULL DEFAULT 1 CHECK(standard_cost_factor > 0),
  active boolean NOT NULL DEFAULT true
);
CREATE TABLE rooms (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), hotel_id uuid NOT NULL REFERENCES hotels,
  room_type_id uuid NOT NULL REFERENCES room_types, room_number text NOT NULL,
  floor smallint, status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','maintenance','inactive')),
  opened_on date, UNIQUE(hotel_id, room_number)
);
CREATE TABLE room_packages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE, name text NOT NULL,
  description text, includes_breakfast boolean NOT NULL DEFAULT false,
  includes_other_services boolean NOT NULL DEFAULT false,
  active boolean NOT NULL DEFAULT true
);
CREATE TABLE inventory_categories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL UNIQUE,
  cost_center text NOT NULL CHECK(cost_center IN ('housekeeping','breakfast','restaurant','maintenance','admin','other'))
);
CREATE TABLE units (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE, name text NOT NULL,
  base_unit_id uuid REFERENCES units, to_base_factor numeric(14,6) NOT NULL DEFAULT 1 CHECK(to_base_factor > 0)
);
CREATE TABLE inventory_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), category_id uuid NOT NULL REFERENCES inventory_categories,
  sku text NOT NULL UNIQUE, name text NOT NULL, unit_id uuid NOT NULL REFERENCES units,
  is_perishable boolean NOT NULL DEFAULT false, reorder_level numeric(14,3) NOT NULL DEFAULT 0 CHECK(reorder_level >= 0),
  preferred_supplier text, active boolean NOT NULL DEFAULT true
);
CREATE TABLE suppliers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, tax_number text,
  phone text, email text, active boolean NOT NULL DEFAULT true
);
CREATE TABLE purchase_orders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), supplier_id uuid NOT NULL REFERENCES suppliers,
  order_number text NOT NULL UNIQUE, ordered_at date NOT NULL DEFAULT current_date,
  received_at date, status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','ordered','partial','received','cancelled')),
  notes text
);
CREATE TABLE purchase_order_lines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), purchase_order_id uuid NOT NULL REFERENCES purchase_orders ON DELETE CASCADE,
  item_id uuid NOT NULL REFERENCES inventory_items, quantity numeric(14,3) NOT NULL CHECK(quantity > 0),
  unit_price numeric(14,4) NOT NULL CHECK(unit_price >= 0), tax_rate numeric(6,3) NOT NULL DEFAULT 0 CHECK(tax_rate >= 0),
  received_quantity numeric(14,3) NOT NULL DEFAULT 0 CHECK(received_quantity >= 0 AND received_quantity <= quantity)
);
CREATE TABLE inventory_movements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), item_id uuid NOT NULL REFERENCES inventory_items,
  movement_at timestamptz NOT NULL DEFAULT now(), movement_type text NOT NULL
    CHECK(movement_type IN ('purchase','consumption','waste','count_adjustment','transfer_in','transfer_out')),
  quantity numeric(14,3) NOT NULL CHECK(quantity > 0), unit_cost numeric(14,4) NOT NULL CHECK(unit_cost >= 0),
  source_type text, source_id uuid, notes text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_inventory_movements_item_date ON inventory_movements(item_id, movement_at);

-- Ürün/BOM reçeteleri: oda başına konaklama gecesi veya kişi-gece miktarı.
CREATE TABLE room_recipes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), room_type_id uuid NOT NULL REFERENCES room_types,
  item_id uuid NOT NULL REFERENCES inventory_items, usage_basis text NOT NULL
    CHECK(usage_basis IN ('per_room_night','per_guest_night','per_stay')),
  quantity numeric(14,4) NOT NULL CHECK(quantity > 0), valid_from date NOT NULL DEFAULT current_date,
  valid_to date, CHECK(valid_to IS NULL OR valid_to >= valid_from), UNIQUE(room_type_id,item_id,usage_basis,valid_from)
);
CREATE TABLE breakfast_buffet_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), item_id uuid NOT NULL REFERENCES inventory_items,
  servings_per_guest numeric(10,4) NOT NULL CHECK(servings_per_guest >= 0),
  waste_rate numeric(5,4) NOT NULL DEFAULT 0 CHECK(waste_rate >= 0 AND waste_rate < 1),
  valid_from date NOT NULL DEFAULT current_date, valid_to date,
  CHECK(valid_to IS NULL OR valid_to >= valid_from), UNIQUE(item_id,valid_from)
);
CREATE TABLE package_recipe_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), package_id uuid NOT NULL REFERENCES room_packages,
  item_id uuid NOT NULL REFERENCES inventory_items, quantity_per_guest_night numeric(14,4) NOT NULL CHECK(quantity_per_guest_night >= 0),
  UNIQUE(package_id,item_id)
);

CREATE TABLE seasons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL,
  starts_on date NOT NULL, ends_on date NOT NULL, CHECK(ends_on >= starts_on)
);
CREATE TABLE seasonal_price_multipliers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), season_id uuid NOT NULL REFERENCES seasons,
  room_type_id uuid REFERENCES room_types, package_id uuid REFERENCES room_packages,
  multiplier numeric(8,4) NOT NULL CHECK(multiplier > 0), priority smallint NOT NULL DEFAULT 0,
  CHECK(room_type_id IS NOT NULL OR package_id IS NOT NULL)
);
CREATE TABLE occupancy_price_multipliers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), min_occupancy numeric(5,4) NOT NULL CHECK(min_occupancy BETWEEN 0 AND 1),
  max_occupancy numeric(5,4) NOT NULL CHECK(max_occupancy BETWEEN 0 AND 1),
  multiplier numeric(8,4) NOT NULL CHECK(multiplier > 0),
  CHECK(max_occupancy > min_occupancy), UNIQUE(min_occupancy,max_occupancy)
);
CREATE TABLE room_rate_plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), room_type_id uuid NOT NULL REFERENCES room_types,
  package_id uuid NOT NULL REFERENCES room_packages, valid_from date NOT NULL, valid_to date,
  base_rate numeric(14,2) NOT NULL CHECK(base_rate >= 0), min_rate numeric(14,2), max_rate numeric(14,2),
  CHECK(valid_to IS NULL OR valid_to >= valid_from), CHECK(min_rate IS NULL OR min_rate >= 0),
  CHECK(max_rate IS NULL OR max_rate >= 0)
);
CREATE TABLE reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), hotel_id uuid NOT NULL REFERENCES hotels,
  room_id uuid REFERENCES rooms, room_type_id uuid NOT NULL REFERENCES room_types,
  package_id uuid NOT NULL REFERENCES room_packages, confirmation_code text UNIQUE,
  check_in date NOT NULL, check_out date NOT NULL, adults smallint NOT NULL DEFAULT 1 CHECK(adults > 0),
  children smallint NOT NULL DEFAULT 0 CHECK(children >= 0), status text NOT NULL DEFAULT 'booked'
    CHECK(status IN ('booked','checked_in','checked_out','cancelled','no_show')),
  channel text, booked_at timestamptz NOT NULL DEFAULT now(), CHECK(check_out > check_in)
);
CREATE INDEX idx_reservations_dates ON reservations(hotel_id,check_in,check_out,status);
CREATE TABLE reservation_nights (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), reservation_id uuid NOT NULL REFERENCES reservations ON DELETE CASCADE,
  stay_date date NOT NULL, room_rate numeric(14,2) NOT NULL CHECK(room_rate >= 0),
  season_multiplier numeric(8,4) NOT NULL DEFAULT 1, occupancy_multiplier numeric(8,4) NOT NULL DEFAULT 1,
  final_rate numeric(14,2) NOT NULL CHECK(final_rate >= 0), UNIQUE(reservation_id,stay_date)
);

CREATE TABLE cost_centers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL UNIQUE, name text NOT NULL,
  allocation_method text NOT NULL CHECK(allocation_method IN ('occupied_room_nights','available_room_nights','guests','revenue','manual'))
);
CREATE TABLE fixed_expense_categories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL UNIQUE, default_cost_center_id uuid REFERENCES cost_centers
);
CREATE TABLE fixed_expenses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), hotel_id uuid NOT NULL REFERENCES hotels,
  category_id uuid NOT NULL REFERENCES fixed_expense_categories, description text NOT NULL,
  amount numeric(14,2) NOT NULL CHECK(amount >= 0), frequency text NOT NULL CHECK(frequency IN ('monthly','quarterly','annual','one_off')),
  valid_from date NOT NULL, valid_to date, cost_center_id uuid REFERENCES cost_centers,
  CHECK(valid_to IS NULL OR valid_to >= valid_from)
);
CREATE TABLE utility_readings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), hotel_id uuid NOT NULL REFERENCES hotels,
  utility_type text NOT NULL CHECK(utility_type IN ('electricity','water','gas','internet','other')),
  period_start date NOT NULL, period_end date NOT NULL, quantity numeric(14,3) NOT NULL CHECK(quantity >= 0),
  unit text NOT NULL, amount numeric(14,2) NOT NULL CHECK(amount >= 0),
  CHECK(period_end >= period_start)
);
CREATE TABLE labor_costs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), hotel_id uuid NOT NULL REFERENCES hotels,
  cost_center_id uuid REFERENCES cost_centers, period_start date NOT NULL, period_end date NOT NULL,
  employee_count smallint NOT NULL DEFAULT 0 CHECK(employee_count >= 0), gross_pay numeric(14,2) NOT NULL CHECK(gross_pay >= 0),
  employer_cost numeric(14,2) NOT NULL DEFAULT 0 CHECK(employer_cost >= 0), CHECK(period_end >= period_start)
);
CREATE TABLE cost_periods (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), hotel_id uuid NOT NULL REFERENCES hotels,
  period_start date NOT NULL, period_end date NOT NULL, status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
  UNIQUE(hotel_id,period_start,period_end), CHECK(period_end >= period_start)
);
CREATE TABLE expense_allocations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), cost_period_id uuid NOT NULL REFERENCES cost_periods ON DELETE CASCADE,
  cost_center_id uuid NOT NULL REFERENCES cost_centers, source_type text NOT NULL, source_id uuid,
  allocation_basis text NOT NULL, allocated_amount numeric(14,2) NOT NULL CHECK(allocated_amount >= 0),
  allocated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE daily_hotel_metrics (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), hotel_id uuid NOT NULL REFERENCES hotels, metric_date date NOT NULL,
  available_rooms smallint NOT NULL CHECK(available_rooms >= 0), occupied_rooms smallint NOT NULL CHECK(occupied_rooms >= 0),
  out_of_order_rooms smallint NOT NULL DEFAULT 0 CHECK(out_of_order_rooms >= 0), guests smallint NOT NULL DEFAULT 0 CHECK(guests >= 0),
  room_revenue numeric(14,2) NOT NULL DEFAULT 0 CHECK(room_revenue >= 0), UNIQUE(hotel_id,metric_date),
  CHECK(occupied_rooms + out_of_order_rooms <= available_rooms)
);
CREATE TABLE audit_log (
  id bigserial PRIMARY KEY, table_name text NOT NULL, record_id uuid, action text NOT NULL,
  changed_at timestamptz NOT NULL DEFAULT now(), changed_by text DEFAULT current_user, old_values jsonb, new_values jsonb
);

CREATE VIEW v_inventory_on_hand AS
SELECT i.id item_id, i.sku, i.name, u.code unit_code, i.reorder_level,
  COALESCE(SUM(CASE WHEN m.movement_type IN ('purchase','transfer_in') THEN m.quantity
                    WHEN m.movement_type IN ('consumption','waste','transfer_out') THEN -m.quantity
                    WHEN m.movement_type='count_adjustment' THEN m.quantity ELSE 0 END),0) quantity_on_hand
FROM inventory_items i JOIN units u ON u.id=i.unit_id LEFT JOIN inventory_movements m ON m.item_id=i.id
GROUP BY i.id,i.sku,i.name,u.code,i.reorder_level;

CREATE VIEW v_daily_occupancy AS
SELECT hotel_id, metric_date, available_rooms, occupied_rooms,
       CASE WHEN available_rooms=0 THEN 0 ELSE occupied_rooms::numeric/available_rooms END occupancy_rate,
       guests, room_revenue,
       CASE WHEN occupied_rooms=0 THEN 0 ELSE room_revenue/occupied_rooms END revpar_occupied
FROM daily_hotel_metrics;
