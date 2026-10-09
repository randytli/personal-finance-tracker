"""PostgreSQL label invariants, installed on fresh schemas and explicit upgrades.

Ownership follows the existing immutable transaction -> raw -> Item provenance.
No financial columns or classification rules are changed.
"""

LABEL_SCHEMA_SQL = [
    """INSERT INTO transaction_label_definitions
        (label_id, name, normalized_name, is_system, created_by, updated_by)
        VALUES ('CHINA', 'China', 'china', true, 'system', 'system'),
               ('MEMBERSHIP', 'Membership', 'membership', true, 'system', 'system')
        ON CONFLICT (label_id) DO NOTHING""",
    """CREATE OR REPLACE FUNCTION pft_label_definition_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path FROM CURRENT AS $body$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Labels must be archived, not deleted' USING ERRCODE = '23514';
          END IF;
          IF NEW.label_id IS DISTINCT FROM OLD.label_id
             OR NEW.user_id IS DISTINCT FROM OLD.user_id
             OR NEW.is_system IS DISTINCT FROM OLD.is_system THEN
            RAISE EXCEPTION 'Label identity and owner are immutable' USING ERRCODE = '23514';
          END IF;
          IF OLD.is_system AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'System labels are immutable' USING ERRCODE = '23514';
          END IF;
          IF OLD.archived_at IS NOT NULL AND NEW.archived_at IS DISTINCT FROM OLD.archived_at THEN
            RAISE EXCEPTION 'Archived labels cannot be reactivated' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $body$""",
    """CREATE OR REPLACE FUNCTION pft_label_association_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path FROM CURRENT AS $body$
        DECLARE definition transaction_label_definitions%ROWTYPE; owner_id varchar;
        BEGIN
          SELECT * INTO definition FROM transaction_label_definitions
            WHERE label_id = NEW.label FOR SHARE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'Unknown label' USING ERRCODE = '23503';
          END IF;
          IF NOT definition.is_system THEN
            SELECT i.user_id INTO owner_id FROM items i
              JOIN raw_transactions r ON r.item_id = i.item_id
              WHERE r.transaction_id = NEW.transaction_id FOR SHARE OF i, r;
            IF owner_id IS DISTINCT FROM definition.user_id THEN
              RAISE EXCEPTION 'Transaction and label owners differ' USING ERRCODE = '23514';
            END IF;
            IF definition.archived_at IS NOT NULL
               AND NEW.decision = 'include' AND NEW.cleared_at IS NULL THEN
              IF TG_OP = 'INSERT' THEN
                RAISE EXCEPTION 'Archived labels cannot be added' USING ERRCODE = '23514';
              ELSIF OLD.transaction_id IS DISTINCT FROM NEW.transaction_id
                 OR OLD.label IS DISTINCT FROM NEW.label
                 OR OLD.decision IS DISTINCT FROM 'include' OR OLD.cleared_at IS NOT NULL THEN
                RAISE EXCEPTION 'Archived labels cannot be added' USING ERRCODE = '23514';
              END IF;
            END IF;
          END IF;
          RETURN NEW;
        END $body$""",
    """CREATE OR REPLACE FUNCTION pft_label_owner_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path FROM CURRENT AS $body$
        DECLARE owner_id varchar;
        BEGIN
          IF TG_TABLE_NAME = 'items' THEN
            IF NEW.user_id IS DISTINCT FROM OLD.user_id AND EXISTS (
              SELECT 1 FROM raw_transactions r
              JOIN manual_transaction_label_overrides o ON o.transaction_id = r.transaction_id
              JOIN transaction_label_definitions d ON d.label_id = o.label
              WHERE r.item_id = OLD.item_id AND NOT d.is_system) THEN
              RAISE EXCEPTION 'Cannot change owner of custom-labeled transactions' USING ERRCODE = '23514';
            END IF;
          ELSE
            IF NEW.item_id IS DISTINCT FROM OLD.item_id THEN
              SELECT user_id INTO owner_id FROM items WHERE item_id = NEW.item_id FOR SHARE;
              IF EXISTS (
                SELECT 1 FROM manual_transaction_label_overrides o
                JOIN transaction_label_definitions d ON d.label_id = o.label
                WHERE o.transaction_id = OLD.transaction_id AND NOT d.is_system
                  AND d.user_id IS DISTINCT FROM owner_id) THEN
                RAISE EXCEPTION 'Cannot reparent custom-labeled transactions across owners' USING ERRCODE = '23514';
              END IF;
            END IF;
          END IF;
          RETURN NEW;
        END $body$""",
]

for table, name, events, function in (
    ('transaction_label_definitions', 'pft_label_definition_guard', 'UPDATE OR DELETE', 'pft_label_definition_guard'),
    ('manual_transaction_label_overrides', 'pft_label_association_guard', 'INSERT OR UPDATE', 'pft_label_association_guard'),
    ('items', 'pft_label_item_owner_guard', 'UPDATE OF user_id', 'pft_label_owner_guard'),
    ('raw_transactions', 'pft_label_raw_owner_guard', 'UPDATE OF item_id', 'pft_label_owner_guard'),
):
    LABEL_SCHEMA_SQL.extend([
        f'DROP TRIGGER IF EXISTS {name} ON {table}',
        f'CREATE TRIGGER {name} BEFORE {events} ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()',
    ])


def install_label_schema(target, connection, **kwargs):
    if connection.dialect.name == 'postgresql':
        for statement in LABEL_SCHEMA_SQL:
            connection.exec_driver_sql(statement)
